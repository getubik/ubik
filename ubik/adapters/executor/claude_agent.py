"""
Claude Agent SDK executor.

Uses the official ``claude-agent-sdk`` (Python) to drive file edits in
an isolated git worktree — the same sandboxing pattern AiderExecutor
uses. The SDK's tool harness (Read/Write/Edit/Bash with pre-approved
permission mode) does the actual work; Ubik handles the
worktree/branch/commit/test scaffolding.

Provider compatibility note
---------------------------
As of mid-2026, ``claude-agent-sdk`` does NOT expose an OpenAI-
compatible ``base_url`` knob. It speaks to Anthropic's Messages API
directly via the official client, so this executor requires a real
``ANTHROPIC_API_KEY`` and Anthropic-served models. If you want
GLM-5.1 / Z.AI for the executor, use ``executor.type: "aider"`` —
Aider's ``--openai-api-base`` flag handles that case.

Failure modes handled here:
  • SDK not installed → outcome=FAILED, descriptive note
  • ANTHROPIC_API_KEY missing → outcome=FAILED
  • SDK raises → outcome=FAILED with traceback tail
  • Session finishes with no commits → outcome=FAILED (matches Aider's
    empty-diff guard so the verifier never pushes a 0-commit branch)
  • Session exceeds time_cap_seconds → outcome=TIMED_OUT
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

from ubik.tools.git import (
    Worktree,
    commit_all,
    commits_ahead,
    create_worktree,
    diff_shortstat,
    files_changed,
    has_uncommitted_changes,
    head_sha,
)

from .base import Executor, ExecutionResult, ExecutorOutcome, ExecutorTask

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ClaudeAgentConfig:
    """Configuration for the Claude Agent SDK executor."""

    model: str = "claude-sonnet-4-6"
    """Anthropic model id. Pass anything the SDK accepts — including
    the GLM / Kimi names exposed by Anthropic-compatible proxies."""

    api_key_env: str = "ANTHROPIC_API_KEY"
    """SDK reads ANTHROPIC_API_KEY from os.environ; we only check it
    exists ahead of time to fail loud."""

    base_url: str | None = None
    """Optional Anthropic-API-compatible endpoint override (e.g. Z.AI's
    ``/api/anthropic`` surface that powers Claude Code routing to GLM).
    When set, the run() method temporarily exports ``ANTHROPIC_BASE_URL``
    + ``ANTHROPIC_API_KEY`` so the SDK's underlying ``anthropic`` client
    picks them up at construction time. Restored after each task to
    avoid polluting the daemon's env."""

    allowed_tools: list[str] = field(
        default_factory=lambda: ["Read", "Write", "Edit", "Bash", "Glob", "Grep"]
    )
    """Tool allowlist passed straight to ClaudeAgentOptions. Bash is
    needed for installs/test runs from inside the agent loop."""

    permission_mode: str = "acceptEdits"
    """Pre-approve file edits — the worktree sandbox is the safety net."""

    max_turns: int = 30
    """SDK's per-session turn cap — orthogonal to our wall-clock cap."""

    worktree_root: str = ".ubik-worktrees"

    extra_options: dict[str, Any] = field(default_factory=dict)
    """Power-user knobs forwarded into ClaudeAgentOptions(**extra_options)."""


_SYSTEM_PROMPT = (
    "You are Ubik, an AI resident engineer working in an isolated git "
    "worktree. The user's proposal describes the change. Make the "
    "smallest edit that satisfies the plan. Do not invent dependencies. "
    "Do not modify CI / Dockerfile / pipeline config unless the plan "
    "explicitly requires it. Keep the existing code style — no drive-by "
    "reformats. If the plan is wrong, output a single sentence "
    "explaining why instead of editing files."
)


class ClaudeAgentExecutor(Executor):
    """Worktree-isolated Claude Agent SDK runner."""

    name = "claude_agent_sdk"

    def __init__(self, config: ClaudeAgentConfig) -> None:
        self.config = config

    async def run(self, task: ExecutorTask) -> ExecutionResult:
        started = time.monotonic()

        # Lazy import — keep base ubik install free of the SDK dep.
        try:
            from claude_agent_sdk import (  # type: ignore[import-not-found]
                ClaudeAgentOptions,
                query,
            )
        except ImportError:
            return ExecutionResult(
                outcome=ExecutorOutcome.FAILED,
                proposal_id=task.proposal_id,
                notes=(
                    "claude-agent-sdk not installed. "
                    "Install with: pip install psssst[claude-agent]"
                ),
                duration_seconds=time.monotonic() - started,
            )

        if not os.environ.get(self.config.api_key_env):
            return ExecutionResult(
                outcome=ExecutorOutcome.FAILED,
                proposal_id=task.proposal_id,
                notes=(
                    f"Missing env var {self.config.api_key_env}. "
                    "The Claude Agent SDK speaks the Anthropic API directly — "
                    "Z.AI / GLM is not supported here. Use "
                    "executor.type: \"aider\" for OpenAI-compatible providers."
                ),
                duration_seconds=time.monotonic() - started,
            )

        branch = task.target_branch or f"auto/{task.proposal_id}"

        try:
            wt = create_worktree(
                task.repo_path,
                branch=branch,
                base_branch=task.base_branch,
                worktree_root=self.config.worktree_root,
            )
        except Exception as e:
            return ExecutionResult(
                outcome=ExecutorOutcome.FAILED,
                proposal_id=task.proposal_id,
                notes=f"Worktree setup failed: {e}",
                duration_seconds=time.monotonic() - started,
            )

        # Custom-endpoint support — the SDK reads ANTHROPIC_BASE_URL +
        # ANTHROPIC_API_KEY at construction time. When the user pointed
        # us at an Anthropic-compatible proxy (Z.AI's /api/anthropic,
        # OpenRouter, LiteLLM gateway, etc.), forward the credentials
        # through env vars and restore them on the way out so other
        # tasks in the same process don't inherit the override.
        saved_env: dict[str, str | None] = {}
        if self.config.base_url:
            saved_env["ANTHROPIC_BASE_URL"] = os.environ.get("ANTHROPIC_BASE_URL")
            os.environ["ANTHROPIC_BASE_URL"] = self.config.base_url
        if self.config.api_key_env != "ANTHROPIC_API_KEY":
            saved_env["ANTHROPIC_API_KEY"] = os.environ.get("ANTHROPIC_API_KEY")
            os.environ["ANTHROPIC_API_KEY"] = api_key

        try:
            outcome, exec_notes = await self._drive(query, ClaudeAgentOptions, wt, task)
        finally:
            for key, prev in saved_env.items():
                if prev is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = prev

        # Auto-commit any straggling uncommitted edits — the SDK's tools
        # write files but don't make commits on their own.
        if has_uncommitted_changes(wt):
            try:
                commit_all(wt, f"ubik: {task.title or task.proposal_id}".strip())
            except Exception as e:
                logger.warning("Manual commit_all failed: %s", e)

        # Inspect what landed.
        head: str | None = None
        files: list[str] = []
        diff_stat = ""
        ahead = 0
        try:
            head = head_sha(wt)
            files = files_changed(wt)
            diff_stat = diff_shortstat(wt)
            ahead = commits_ahead(wt)
        except Exception as e:
            logger.warning("Post-SDK inspection failed: %s", e)

        if outcome == ExecutorOutcome.SUCCESS and ahead == 0:
            outcome = ExecutorOutcome.FAILED
            exec_notes = (
                (exec_notes or "")
                + "\n\nNo new commits on the worktree branch — the SDK "
                "session exited cleanly but produced no committable "
                "changes. Likely the model described the plan without "
                "running its Edit/Write tools."
            ).strip()
            files = []

        # Optional test run.
        test_passed: bool | None = None
        test_notes = ""
        if outcome == ExecutorOutcome.SUCCESS and task.test_command:
            test_passed, test_notes = await self._run_tests(wt, task)
            if not test_passed:
                outcome = ExecutorOutcome.FAILED

        return ExecutionResult(
            outcome=outcome,
            proposal_id=task.proposal_id,
            branch=wt.branch,
            head_sha=head,
            files_changed=files,
            diff_summary=diff_stat,
            test_passed=test_passed,
            notes="\n\n".join(filter(None, [exec_notes, test_notes])),
            duration_seconds=time.monotonic() - started,
        )

    # ── internals ───────────────────────────────────────────────────────

    async def _drive(
        self,
        query_fn: Any,
        options_cls: Any,
        wt: Worktree,
        task: ExecutorTask,
    ) -> tuple[ExecutorOutcome, str]:
        """Run one ``query()`` session inside ``wt.path``."""
        options = options_cls(
            model=self.config.model,
            system_prompt=_SYSTEM_PROMPT,
            allowed_tools=list(self.config.allowed_tools),
            cwd=str(wt.path),
            max_turns=self.config.max_turns,
            permission_mode=self.config.permission_mode,
            **self.config.extra_options,
        )

        prompt = self._build_prompt(task)

        async def _consume() -> str:
            chunks: list[str] = []
            async for message in query_fn(prompt=prompt, options=options):
                # Messages are SDK-typed; we don't introspect them deeply,
                # we just collect a stringified tail for the PR body.
                chunks.append(repr(message)[:400])
            return "\n".join(chunks[-20:])  # keep last 20 for context

        try:
            output = await asyncio.wait_for(_consume(), timeout=task.time_cap_seconds)
        except asyncio.TimeoutError:
            return (
                ExecutorOutcome.TIMED_OUT,
                f"Claude Agent SDK session hit the {task.time_cap_seconds}s "
                "wall-clock cap and was cancelled.",
            )
        except Exception as e:
            logger.error("Claude Agent SDK raised: %s", e, exc_info=True)
            return (ExecutorOutcome.FAILED, f"SDK session raised: {type(e).__name__}: {e}")

        return (
            ExecutorOutcome.SUCCESS,
            f"Claude Agent SDK session finished.\n\nLast messages:\n```\n{output[-3500:]}\n```",
        )

    def _build_prompt(self, task: ExecutorTask) -> str:
        parts: list[str] = []
        if task.title:
            parts.append(f"# Task: {task.title}")
        if task.description:
            parts.append("\n## Context\n\n" + task.description.strip())
        if task.plan:
            parts.append("\n## Plan\n\n" + task.plan.strip())
        parts.append(
            "\nWork inside the current directory. Use Read/Edit/Write to "
            "make the changes; commit nothing yourself — Ubik will commit "
            "any uncommitted changes after you finish."
        )
        return "\n".join(parts)

    async def _run_tests(
        self,
        wt: Worktree,
        task: ExecutorTask,
    ) -> tuple[bool, str]:
        assert task.test_command
        try:
            proc = await asyncio.create_subprocess_shell(
                task.test_command,
                cwd=str(wt.path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except OSError as e:
            return (False, f"Could not start test command: {e}")

        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=600)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return (False, "Tests hit 10-minute cap and were killed.")

        ok = proc.returncode == 0
        tail = (stdout or b"").decode("utf-8", errors="replace")[-2000:]
        prefix = "Tests passed." if ok else f"Tests failed (rc={proc.returncode})."
        return (ok, f"{prefix}\n\n```\n{tail}\n```")
