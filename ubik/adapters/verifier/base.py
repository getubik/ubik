"""
Verifier adapter base — what happens after the executor commits.

The verifier's job:

  1. (Optional) Re-run the test suite on the worktree branch to confirm
     the executor's local pass holds up.
  2. Push the branch to the remote.
  3. Open a Pull Request from `branch` into `base_branch`.
  4. Return the PR URL so the orchestrator can ping the user with
     "PR ready, here's the link, tap merge when you've reviewed."

We DO NOT auto-merge. Final gate is always the human eyeball.

Sprint 2.3b/p6 ships only the GitHub adapter (gh CLI subprocess).
GitLab / Bitbucket adapters slot in via the same Protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol


class VerifyOutcome(str, Enum):
    OPENED = "opened"
    """PR created cleanly. Proposal moves to PR_OPENED state."""

    PUSH_FAILED = "push_failed"
    """git push to origin failed (network / auth / branch protection)."""

    PR_FAILED = "pr_failed"
    """gh CLI / API rejected the PR creation request."""


@dataclass(slots=True)
class VerifyTask:
    """Inputs for a verifier run — produced by the orchestrator after
    the executor lands a SUCCESS."""

    proposal_id: str
    repo_path: Path
    """Path to the host repo (where `.git` lives)."""

    worktree_path: Path
    """Path to the executor's worktree (branch is checked out here)."""

    branch: str
    """Branch name the executor committed to."""

    base_branch: str = "main"

    title: str = ""
    """PR title — typically the proposal title with an Ubik prefix."""

    body: str = ""
    """PR body — typically the full proposal markdown."""

    repo_slug: str | None = None
    """e.g. 'getubik/ubik'. None means: detect from `git remote get-url origin`."""

    draft: bool = False
    """If True, open as draft PR (won't trigger CI on PR creation)."""


@dataclass(slots=True)
class VerifyResult:
    """The product of a verifier run."""

    outcome: VerifyOutcome
    proposal_id: str
    branch: str

    pr_url: str | None = None
    pr_number: int | None = None
    notes: str = ""


class Verifier(Protocol):
    """Minimal contract every verifier implementation must satisfy."""

    name: str
    """Short identifier, e.g. 'github', 'gitlab'."""

    async def verify(self, task: VerifyTask) -> VerifyResult:
        """Push branch + open PR. Must NEVER merge."""
        ...
