"""
Executor adapter base — how Ubik turns a proposal into a code change.

A Proposal becomes an ExecutorTask. The configured executor (Aider /
Claude Agent SDK / OpenHands / custom) runs against an isolated git
worktree, makes edits, runs tests, and reports back an ExecutionResult.

The orchestrator then asks the verifier to open a PR, never letting
the executor near `main`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Protocol


class ExecutorOutcome(str, Enum):
    """Final state of an executor run."""
    SUCCESS = "success"
    """Edits applied, tests pass, branch ready to PR."""

    FAILED = "failed"
    """Executor refused or errored — branch rolled back."""

    TIMED_OUT = "timed_out"
    """Hit the time cap. Whatever was committed stays on the branch."""

    COST_CAPPED = "cost_capped"
    """Hit the cost cap. Same disposition as timed_out."""


@dataclass(slots=True)
class ExecutorTask:
    """A code-modification task derived from a Proposal."""

    proposal_id: str
    """Stable ID matching the proposal in the notebook."""

    repo_path: Path
    """Path to the host repo (the executor will create a worktree off it)."""

    base_branch: str = "main"
    """Branch to fork from."""

    target_branch: str | None = None
    """Branch name for the executor's work. Defaults to `auto/<proposal_id>`."""

    title: str = ""
    """One-line summary, used as the commit subject."""

    description: str = ""
    """Full proposal markdown — context for the executor's prompt."""

    plan: str = ""
    """The 'Proposed fix' section of the proposal — concrete instructions."""

    test_command: str | None = None
    """Optional `pytest -q` (or equivalent). If set, the executor must pass."""

    cost_cap_usd: float = 5.0
    """Hard kill switch. Adapter aborts if the LLM bill projection exceeds this."""

    time_cap_seconds: int = 900
    """Hard kill switch. 15 min default."""

    allowed_domains: list[str] = field(default_factory=list)
    """Network egress allowlist. Empty = adapter default."""


@dataclass(slots=True)
class ExecutionResult:
    """The product of one executor run."""

    outcome: ExecutorOutcome
    proposal_id: str

    branch: str | None = None
    """Branch the executor committed to. None on early failure."""

    head_sha: str | None = None
    """Tip commit SHA on `branch`. None on early failure."""

    files_changed: list[str] = field(default_factory=list)
    """Repo-relative paths the executor touched."""

    diff_summary: str = ""
    """Short text — `git diff --shortstat` or equivalent."""

    test_passed: bool | None = None
    """None if no test command; True/False otherwise."""

    notes: str = ""
    """Free-form executor commentary — went into the PR body."""

    cost_estimate_usd: float = 0.0
    """Best-effort token cost estimate."""

    duration_seconds: float = 0.0


class Executor(Protocol):
    """The minimal contract every executor implementation must satisfy."""

    name: str
    """Short identifier, e.g. 'aider', 'claude_agent_sdk', 'openhands'."""

    async def run(self, task: ExecutorTask) -> ExecutionResult:
        """Run the task. Must NEVER push to `task.base_branch`.

        Implementations:
          1. Create a git worktree at `<worktree_root>/<task.proposal_id>/`
             on a new branch derived from `task.base_branch`.
          2. Drive their underlying agent (Aider / Claude Agent SDK / …)
             with the proposal as context.
          3. Enforce cost_cap_usd, time_cap_seconds.
          4. Optionally run `task.test_command`.
          5. Return an ExecutionResult — even on failure (set outcome).
          6. Leave the branch in place; orchestrator decides whether to
             open a PR or discard the worktree.
        """
        ...
