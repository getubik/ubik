"""
Aider executor adapter.

Why Aider as the first executor:

  • Already battle-tested at scale (~41k stars, 4.1M installs, weekly
    15B tokens, 13K commits as of mid-2026).
  • Git-native: every edit becomes a commit with a sensible message.
  • Subprocess-driven: simple control flow, no Python session lifecycle
    to manage. Survives crashes cleanly.
  • Litellm-compatible: same `--openai-api-base` / `--model` flags
    accept Z.AI, Anthropic, OpenAI, local Ollama, etc.

Claude Agent SDK and OpenHands adapters live in sibling files and
satisfy the same `Executor` Protocol — pick via config.

Failure modes we handle:
  • aider not on PATH                      → outcome=FAILED, descriptive note
  • aider exits non-zero                   → outcome=FAILED
  • test command fails after aider succeeds → outcome=FAILED
  • subprocess hangs past time_cap_seconds  → outcome=TIMED_OUT, kill -9
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from ubik.tools.git import (
    Worktree,
    commit_all,
    create_worktree,
    diff_shortstat,
    files_changed,
    has_uncommitted_changes,
    head_sha,
    remove_worktree,
)

from .base import Executor, ExecutionResult, ExecutorOutcome, ExecutorTask

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AiderConfig:
    """Configuration for the Aider executor.

    Mirrors the subset of `aider --help` flags we need. Bring-your-own-LLM
    via `base_url` + `api_key_env` + `model` so the executor talks to
    whatever brain Ubik is configured for (default: GLM-5.1 via Z.AI).
    """

    base_url: str = "https://api.z.ai/api/coding/paas/v4"
    api_key_env: str = "Z_AI_API_KEY"
    model: str = "openai/glm-5.1"
    """litellm-style identifier. The 'openai/' prefix tells aider to use
    the OpenAI-compatible client, which Z.AI implements."""

    aider_binary: str = "aider"
    """Override if aider isn't on PATH or you've installed via uv tool."""

    extra_flags: list[str] | None = None
    """Power-user knobs: e.g. ['--no-auto-commits', '--map-tokens', '4096']"""

    worktree_root: str = ".ubik-worktrees"


class AiderExecutor(Executor):
    """Subprocess-based Aider runner with sandboxed worktrees."""

    name = "aider"

    def __init__(self, config: AiderConfig) -> None:
        self.config = config

    # ── public API ──────────────────────────────────────────────────────

    async def run(self, task: ExecutorTask) -> ExecutionResult:
        started = time.monotonic()

        if not shutil.which(self.config.aider_binary):
            return ExecutionResult(
                outcome=ExecutorOutcome.FAILED,
                proposal_id=task.proposal_id,
                notes=(
                    f"Aider is not on PATH (looked for {self.config.aider_binary!r}). "
                    "Install with: pip install aider-chat"
                ),
                duration_seconds=time.monotonic() - started,
            )

        api_key = os.environ.get(self.config.api_key_env)
        if not api_key:
            return ExecutionResult(
                outcome=ExecutorOutcome.FAILED,
                proposal_id=task.proposal_id,
                notes=f"Missing env var {self.config.api_key_env}",
                duration_seconds=time.monotonic() - started,
            )

        branch = task.target_branch or f"auto/{task.proposal_id}"

        # 1. Spin up worktree
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

        # 2. Drive Aider with the proposal as the message
        try:
            outcome, exec_notes = await self._drive_aider(wt, task, api_key)
        except Exception as e:
            logger.error("Aider drove off the road: %s", e, exc_info=True)
            outcome = ExecutorOutcome.FAILED
            exec_notes = f"Aider session raised: {e}"

        # 3. Inspect what landed
        head = None
        files: list[str] = []
        diff_stat = ""
        try:
            head = head_sha(wt)
            files = files_changed(wt)
            diff_stat = diff_shortstat(wt)
        except Exception as e:
            logger.warning("Post-aider inspection failed: %s", e)

        # 4. Optional test run on the worktree
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

    async def _drive_aider(
        self,
        wt: Worktree,
        task: ExecutorTask,
        api_key: str,
    ) -> tuple[ExecutorOutcome, str]:
        """Invoke `aider` as a subprocess. Returns (outcome, notes)."""
        message = self._build_message(task)

        cmd = [
            self.config.aider_binary,
            "--yes-always",
            "--no-stream",
            "--no-pretty",
            "--no-show-model-warnings",
            "--openai-api-base", self.config.base_url,
            "--openai-api-key", api_key,
            "--model", self.config.model,
            "--message", message,
        ]
        if self.config.extra_flags:
            cmd.extend(self.config.extra_flags)

        logger.info("Aider starting · branch=%s · cap=%ds", wt.branch, task.time_cap_seconds)

        try:
            proc = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    *cmd,
                    cwd=str(wt.path),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                ),
                timeout=10,  # process-spawn timeout, separate from run cap
            )
        except asyncio.TimeoutError:
            return (ExecutorOutcome.FAILED, "Aider failed to launch in 10s")

        try:
            stdout, _ = await asyncio.wait_for(
                proc.communicate(), timeout=task.time_cap_seconds
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return (
                ExecutorOutcome.TIMED_OUT,
                f"Aider hit time cap ({task.time_cap_seconds}s) and was killed.",
            )

        rc = proc.returncode
        output = (stdout or b"").decode("utf-8", errors="replace")[-4000:]

        # Aider auto-commits by default, but if we told it `--no-auto-commits`
        # we'd need to commit here ourselves. Either way, capture the state.
        if has_uncommitted_changes(wt):
            try:
                commit_all(wt, f"ubik: {task.title or task.proposal_id}".strip())
            except Exception as e:
                logger.warning("Manual commit_all failed: %s", e)

        if rc == 0:
            return (
                ExecutorOutcome.SUCCESS,
                f"Aider exited 0.\n\nLast output:\n```\n{output}\n```",
            )
        return (
            ExecutorOutcome.FAILED,
            f"Aider exited {rc}.\n\nLast output:\n```\n{output}\n```",
        )

    def _build_message(self, task: ExecutorTask) -> str:
        """Compose the prompt Aider sees on stdin."""
        parts: list[str] = []
        if task.title:
            parts.append(f"# Task: {task.title}")
        if task.description:
            parts.append("\n## Context\n\n" + task.description.strip())
        if task.plan:
            parts.append("\n## Plan\n\n" + task.plan.strip())
        parts.append(
            "\n## Constraints\n\n"
            "- Make the smallest change that satisfies the plan.\n"
            "- Do not invent dependencies. If a library is missing, say so.\n"
            "- Do not modify CI / Dockerfile / pipeline config unless explicitly required.\n"
            "- Keep the existing code style. No drive-by reformats.\n"
            "- If the plan is wrong, output a single sentence explaining why "
            "instead of editing files."
        )
        return "\n".join(parts)

    async def _run_tests(
        self,
        wt: Worktree,
        task: ExecutorTask,
    ) -> tuple[bool, str]:
        """Run task.test_command in the worktree, return (ok, notes)."""
        assert task.test_command  # narrows type
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
