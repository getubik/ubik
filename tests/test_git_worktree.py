"""Tests for the git worktree helpers used by every executor."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ubik.tools.git import (
    GitError,
    commit_all,
    create_worktree,
    diff_shortstat,
    files_changed,
    has_uncommitted_changes,
    head_sha,
    remove_worktree,
)


def _init_repo(path: Path) -> None:
    """Create a tiny throwaway repo with one commit on `main`."""
    path.mkdir(parents=True, exist_ok=True)
    runs = [
        ["git", "init", "-q", "-b", "main"],
        ["git", "config", "user.email", "t@t"],
        ["git", "config", "user.name", "t"],
        ["git", "config", "commit.gpgsign", "false"],
    ]
    for cmd in runs:
        subprocess.run(cmd, cwd=path, check=True, capture_output=True)
    (path / "README.md").write_text("# repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "initial"], cwd=path, check=True, capture_output=True
    )
    # Pretend we have an `origin` so `fetch origin main` doesn't hard-fail.
    subprocess.run(
        ["git", "remote", "add", "origin", str(path)],
        cwd=path, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "fetch", "origin", "main", "--quiet"],
        cwd=path, check=False, capture_output=True,
    )


def test_create_worktree_off_main(tmp_path: Path) -> None:
    repo = tmp_path / "host"
    _init_repo(repo)

    wt = create_worktree(
        repo,
        branch="auto/test-1",
        base_branch="main",
        worktree_root=tmp_path / "trees",
    )

    assert wt.path.exists()
    assert wt.branch == "auto/test-1"
    assert (wt.path / "README.md").read_text(encoding="utf-8").startswith("# repo")


def test_create_worktree_replaces_stale(tmp_path: Path) -> None:
    repo = tmp_path / "host"
    _init_repo(repo)
    root = tmp_path / "trees"

    create_worktree(repo, branch="auto/x", base_branch="main", worktree_root=root)
    # Second create with same branch must clean the first.
    wt2 = create_worktree(
        repo, branch="auto/x", base_branch="main", worktree_root=root
    )
    assert wt2.path.exists()


def test_diff_and_commit_flow(tmp_path: Path) -> None:
    repo = tmp_path / "host"
    _init_repo(repo)
    wt = create_worktree(
        repo, branch="auto/diff-test", base_branch="main",
        worktree_root=tmp_path / "trees",
    )

    # No uncommitted changes initially.
    assert not has_uncommitted_changes(wt)

    (wt.path / "new.txt").write_text("hello\n", encoding="utf-8")
    assert has_uncommitted_changes(wt)

    new_sha = commit_all(wt, "ubik: add new.txt")
    assert new_sha
    assert not has_uncommitted_changes(wt)

    changed = files_changed(wt)
    assert "new.txt" in changed

    stat = diff_shortstat(wt)
    assert "new.txt" in stat or "1 file changed" in stat


def test_remove_worktree_idempotent(tmp_path: Path) -> None:
    repo = tmp_path / "host"
    _init_repo(repo)
    wt = create_worktree(
        repo, branch="auto/rm", base_branch="main",
        worktree_root=tmp_path / "trees",
    )
    path = wt.path
    assert path.exists()

    remove_worktree(repo, path)
    assert not path.exists()

    # Calling remove again on a nonexistent path is OK.
    remove_worktree(repo, path)


def test_create_worktree_rejects_non_repo(tmp_path: Path) -> None:
    not_a_repo = tmp_path / "plain"
    not_a_repo.mkdir()
    with pytest.raises(GitError):
        create_worktree(
            not_a_repo, branch="auto/x", base_branch="main",
            worktree_root=tmp_path / "trees",
        )
