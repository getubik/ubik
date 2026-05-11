"""
Codebase context collection — what the Researcher sees on a `ubik audit`.

Single-shot mode (Sprint 1) gathers a bounded snapshot of the repo so
that even a large codebase fits in a single LLM context window:

  1. Repo metadata        — name, default branch, languages by extension
  2. Tree skeleton        — first N files matching the project's likely
                            entry points (limited by depth + globs)
  3. README + docs/       — content of the obvious roots
  4. Recent git history   — last K commits with subject + diffstat
  5. Representative files — the top-level files most likely to define
                            architecture (configs, entry modules)

Output is a single flat dict that the Researcher renders into the
prompt. Future sprints will add streaming / iterative tool-call mode.
"""

from __future__ import annotations

import logging
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Files / dirs we never want to include in the snapshot — too large,
# too noisy, or already known to the LLM (e.g. lockfiles).
_SKIP_DIRS = frozenset(
    {
        ".git",
        ".github",
        ".venv",
        "venv",
        "env",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".tox",
        "build",
        "dist",
        "target",
        "bin",
        "obj",
        ".idea",
        ".vscode",
        ".next",
        ".nuxt",
        ".cache",
        "coverage",
        "htmlcov",
        ".coverage",
    }
)

_SKIP_EXTS = frozenset(
    {
        ".pyc",
        ".pyo",
        ".so",
        ".dll",
        ".exe",
        ".bin",
        ".o",
        ".a",
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".webp",
        ".ico",
        ".svg",
        ".pdf",
        ".zip",
        ".tar",
        ".gz",
        ".bz2",
        ".xz",
        ".7z",
        ".mp3",
        ".mp4",
        ".mov",
        ".avi",
        ".webm",
        ".lock",  # uv.lock, package-lock.json, etc. — large, low signal
        ".min.js",
        ".min.css",
    }
)

# Extensions Ubik treats as primary code (architecture-revealing).
_CODE_EXTS = frozenset(
    {
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".go",
        ".rs",
        ".java",
        ".kt",
        ".swift",
        ".rb",
        ".php",
        ".cs",
        ".cpp",
        ".c",
        ".h",
        ".vue",
        ".svelte",
        ".astro",
    }
)

# Files that almost always reveal architecture intent. Order matters
# (we try them top-down and stop at total budget).
_HIGH_VALUE_BASENAMES = (
    "README.md",
    "README.rst",
    "README.txt",
    "README",
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "docker-compose.yml",
    "docker-compose.yaml",
    "Dockerfile",
    "Makefile",
    "justfile",
    "requirements.txt",
    "tsconfig.json",
    "tsconfig.base.json",
    ".env.example",
    "env.example",
    "ARCHITECTURE.md",
    "CONTRIBUTING.md",
    "ROADMAP.md",
)


@dataclass(slots=True)
class FileSnippet:
    path: str
    """Repo-relative POSIX path."""
    content: str
    """Body — may be truncated."""
    truncated: bool = False
    line_count: int = 0


@dataclass(slots=True)
class GitCommit:
    sha: str
    subject: str
    author: str
    date: str
    diff_stat: str = ""


@dataclass(slots=True)
class RepoSnapshot:
    """The bounded view of a repo that an audit prompt will consume."""

    repo_path: str
    repo_name: str
    default_branch: str

    # Roughly: language by file count, sorted desc.
    languages: dict[str, int] = field(default_factory=dict)

    # Tree skeleton: list of repo-relative paths.
    file_tree: list[str] = field(default_factory=list)

    # The actual file bodies (bounded set).
    high_value_files: list[FileSnippet] = field(default_factory=list)

    # Last K commits.
    recent_commits: list[GitCommit] = field(default_factory=list)

    # File counts seen vs. files actually included.
    total_files_scanned: int = 0
    total_files_included: int = 0


# ── public entry point ───────────────────────────────────────────────────


def read_repo(
    repo_path: Path | str,
    *,
    max_files_in_tree: int = 200,
    max_high_value_files: int = 20,
    max_file_chars: int = 6000,
    max_commits: int = 20,
) -> RepoSnapshot:
    """Collect a bounded snapshot suitable for one LLM context window."""
    root = Path(repo_path).resolve()
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"not a directory: {root}")

    snapshot = RepoSnapshot(
        repo_path=str(root),
        repo_name=root.name,
        default_branch=_detect_default_branch(root),
    )

    files = list(_walk(root, max_files_in_tree=max_files_in_tree))
    snapshot.total_files_scanned = len(files)
    snapshot.languages = _language_breakdown(files)
    snapshot.file_tree = [_rel(f, root) for f in files][:max_files_in_tree]

    snapshot.high_value_files = _gather_high_value_files(
        root, files, max_high_value_files, max_file_chars
    )
    snapshot.total_files_included = len(snapshot.high_value_files)

    snapshot.recent_commits = _git_log(root, max_commits)
    return snapshot


# ── internals ────────────────────────────────────────────────────────────


def _walk(root: Path, *, max_files_in_tree: int) -> list[Path]:
    """Yield all candidate files (already filtered by skip lists). Stops at cap."""
    out: list[Path] = []
    for p in root.rglob("*"):
        if len(out) >= max_files_in_tree * 4:  # over-collect, we'll trim later
            break
        if not p.is_file():
            continue
        if any(part in _SKIP_DIRS for part in p.relative_to(root).parts):
            continue
        if p.suffix.lower() in _SKIP_EXTS:
            continue
        if p.name.startswith(".") and p.name not in {".gitignore", ".env.example"}:
            continue
        out.append(p)
    return out


def _rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _language_breakdown(files: list[Path]) -> dict[str, int]:
    """File count by extension, top 10."""
    counts: Counter[str] = Counter()
    for f in files:
        ext = f.suffix.lower() or "(no-ext)"
        counts[ext] += 1
    return dict(counts.most_common(10))


def _detect_default_branch(root: Path) -> str:
    """Try `git symbolic-ref` first; fall back to 'main'."""
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "symbolic-ref", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=4,
            check=False,
        )
        if out.returncode == 0:
            return out.stdout.strip() or "main"
    except (FileNotFoundError, subprocess.SubprocessError):
        pass
    return "main"


def _git_log(root: Path, max_commits: int) -> list[GitCommit]:
    """`git log` shallow, bounded — empty list on any error."""
    fmt = "%H%x1f%s%x1f%an%x1f%ad"
    try:
        out = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "log",
                f"-{max_commits}",
                f"--pretty=format:{fmt}",
                "--date=short",
                "--shortstat",
            ],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return []
    if out.returncode != 0:
        return []

    commits: list[GitCommit] = []
    # `--shortstat` separates each commit with a blank line; pretty
    # format prints first, then a stat line. Easiest robust parse:
    # iterate, when we see a line with %x1f-separated data, start a
    # new commit; the next non-empty line that looks like " N files
    # changed, …" is the stat for the previous commit.
    pending: GitCommit | None = None
    for line in out.stdout.splitlines():
        if "\x1f" in line:
            if pending is not None:
                commits.append(pending)
            sha, subject, author, date = line.split("\x1f", 3)
            pending = GitCommit(sha=sha[:7], subject=subject, author=author, date=date)
        elif (
            (
                pending
                and line.strip().startswith(
                    (
                        "1 file",
                        "2 file",
                        "3 file",
                        "4 file",
                        "5 file",
                        "6 file",
                        "7 file",
                        "8 file",
                        "9 file",
                    )
                )
            )
            or "file changed" in line
            or "files changed" in line
        ):
            pending.diff_stat = line.strip()
    if pending is not None:
        commits.append(pending)
    return commits[:max_commits]


def _gather_high_value_files(
    root: Path,
    candidates: list[Path],
    max_files: int,
    max_file_chars: int,
) -> list[FileSnippet]:
    """Collect file bodies, prioritizing high-signal basenames."""
    selected: list[Path] = []
    seen: set[Path] = set()

    # 1) Always-include basenames first.
    for basename in _HIGH_VALUE_BASENAMES:
        for p in candidates:
            if p.name == basename and p not in seen:
                selected.append(p)
                seen.add(p)
                if len(selected) >= max_files:
                    break

    # 2) Top-level code files next.
    if len(selected) < max_files:
        for p in candidates:
            if p in seen:
                continue
            if p.suffix.lower() in _CODE_EXTS and len(p.relative_to(root).parts) <= 2:
                selected.append(p)
                seen.add(p)
                if len(selected) >= max_files:
                    break

    out: list[FileSnippet] = []
    for path in selected:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            logger.debug("could not read %s: %s", path, e)
            continue
        truncated = len(text) > max_file_chars
        body = text[:max_file_chars]
        out.append(
            FileSnippet(
                path=_rel(path, root),
                content=body,
                truncated=truncated,
                line_count=text.count("\n") + 1,
            )
        )
    return out
