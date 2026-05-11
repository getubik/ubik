"""
Git helpers for the executor — worktrees, branches, diff inspection.

Every executor task runs in its own *git worktree* (a sibling working
directory sharing the same `.git` repository). That gives us:

  • Filesystem isolation — the host repo stays clean while the executor
    edits files.
  • Branch semantics — the worktree starts on a fresh branch off
    `base_branch`. Even if the executor tries to push, branch protection
    on `main` stops it.
  • Cheap teardown — `git worktree remove` deletes the directory plus
    metadata. No leftover state.

Used by `ubik/adapters/executor/*` so all executors get the same
sandbox primitives.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


class GitError(RuntimeError):
    """Raised when a git invocation fails."""


@dataclass(slots=True)
class Worktree:
    """A live git worktree owned by an executor task."""

    path: Path
    """Filesystem path to the worktree root."""

    branch: str
    """Branch the worktree is checked out on."""

    base_branch: str
    """The branch this worktree was forked from."""

    repo_path: Path
    """The host repository (where `.git` lives)."""


def _git(args: list[str], cwd: Path | None = None, check: bool = True) -> str:
    """Run a git command, return stdout. Raises GitError on non-zero exit."""
    cmd = ["git", *args]
    logger.debug("git %s (cwd=%s)", " ".join(args), cwd)
    out = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if check and out.returncode != 0:
        raise GitError(
            f"git {' '.join(args)} failed (exit {out.returncode}): "
            f"{out.stderr.strip() or out.stdout.strip()}"
        )
    return out.stdout.strip()


def create_worktree(
    repo_path: Path | str,
    *,
    branch: str,
    base_branch: str = "main",
    worktree_root: Path | str = ".ubik-worktrees",
) -> Worktree:
    """Create a fresh worktree off `base_branch` on a new branch.

    The worktree is placed at::

        {worktree_root}/{branch_slug}/

    relative to the *parent* of the host repo (we don't put the worktree
    inside the repo because some tools fight with that).
    """
    repo = Path(repo_path).resolve()
    if not (repo / ".git").exists():
        raise GitError(f"not a git repo: {repo}")

    branch_slug = branch.replace("/", "-").replace(" ", "-")
    root = Path(worktree_root)
    if not root.is_absolute():
        root = (repo.parent / root).resolve()
    root.mkdir(parents=True, exist_ok=True)

    wt_path = root / branch_slug
    if wt_path.exists():
        # Stale worktree from a previous run — clean it up first.
        logger.info("Removing stale worktree at %s", wt_path)
        remove_worktree(repo, wt_path)

    # Make sure base_branch is up to date in the host repo (cheap
    # `git fetch` keeps the worktree fresh too).
    _git(["fetch", "origin", base_branch, "--quiet"], cwd=repo, check=False)

    # `git worktree add -B` creates the worktree AND the new branch off
    # base_branch in one shot, force-resetting the branch if a previous
    # run left it behind. Plain `-b` would error out on stale branches
    # even after we cleaned the worktree directory.
    _git(
        ["worktree", "add", "-B", branch, str(wt_path), f"origin/{base_branch}"],
        cwd=repo,
    )

    logger.info("Worktree created: %s on branch %s (off %s)", wt_path, branch, base_branch)
    return Worktree(path=wt_path, branch=branch, base_branch=base_branch, repo_path=repo)


def remove_worktree(repo_path: Path | str, worktree_path: Path | str) -> None:
    """Drop a worktree and its on-disk directory."""
    repo = Path(repo_path).resolve()
    wt = Path(worktree_path).resolve()

    # First ask git to forget it — even if the path is already gone.
    _git(["worktree", "remove", "--force", str(wt)], cwd=repo, check=False)

    # Belt and suspenders: also nuke the directory if anything's left.
    if wt.exists():
        shutil.rmtree(wt, ignore_errors=True)


def head_sha(worktree: Worktree) -> str:
    """Return the tip commit SHA on the worktree's current branch."""
    return _git(["rev-parse", "HEAD"], cwd=worktree.path)


def _refresh_base_ref(worktree: Worktree) -> None:
    """Pull `origin/<base_branch>` so diffs see the same SHA the worktree
    was actually forked from. Without this, the *local* `<base_branch>`
    ref can lag behind the remote — happens whenever a co-worker (or
    Ubik itself, on a previous cycle) merges a PR while the daemon is
    asleep. The next cycle's worktree forks from `origin/main` (latest)
    but `git diff main...HEAD` compares against an older local SHA, so
    every commit between old-local-main and origin-main shows up as
    "changes" on the new branch — including merges that landed
    upstream long ago. Falsely-positive `files_changed` then leaks past
    the empty-commit guard in the orchestrator and the verifier
    happily pushes an empty branch, GitHub returns 422, and the user
    sees a stuck "branch ready" notification with no PR.
    """
    _git(
        ["fetch", "origin", worktree.base_branch],
        cwd=worktree.path,
        check=False,
    )


def diff_shortstat(worktree: Worktree) -> str:
    """Return `git diff --shortstat` against the *remote* base_branch."""
    _refresh_base_ref(worktree)
    return _git(
        ["diff", "--shortstat", f"origin/{worktree.base_branch}...HEAD"],
        cwd=worktree.path,
        check=False,
    )


def files_changed(worktree: Worktree) -> list[str]:
    """List repo-relative paths changed on this worktree's branch.

    Compares against `origin/<base_branch>` rather than the local ref —
    see `_refresh_base_ref` for why.
    """
    _refresh_base_ref(worktree)
    out = _git(
        ["diff", "--name-only", f"origin/{worktree.base_branch}...HEAD"],
        cwd=worktree.path,
        check=False,
    )
    return [line.strip() for line in out.splitlines() if line.strip()]


def commits_ahead(worktree: Worktree) -> int:
    """How many commits this branch has that `origin/<base_branch>` doesn't.

    The orchestrator's empty-execution guard uses this as the canonical
    signal — if it returns 0, the executor session produced nothing
    pushable and we should mark the proposal failed instead of letting
    the verifier push an empty branch.
    """
    _refresh_base_ref(worktree)
    out = _git(
        ["rev-list", "--count", f"origin/{worktree.base_branch}..HEAD"],
        cwd=worktree.path,
        check=False,
    )
    try:
        return int(out.strip())
    except ValueError:
        return 0


def has_uncommitted_changes(worktree: Worktree) -> bool:
    """True if the worktree has staged or unstaged edits not yet committed."""
    out = _git(["status", "--porcelain"], cwd=worktree.path)
    return bool(out)


def commit_all(worktree: Worktree, message: str) -> str:
    """Stage all and commit. Returns the new commit SHA. Raises if nothing to commit."""
    _git(["add", "-A"], cwd=worktree.path)
    if not has_uncommitted_changes(worktree):
        # Nothing to commit — return current HEAD anyway, executor can decide.
        return head_sha(worktree)
    _git(["commit", "-m", message], cwd=worktree.path)
    return head_sha(worktree)
