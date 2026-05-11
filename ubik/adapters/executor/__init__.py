"""Executor adapters — how Ubik turns proposals into code changes."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .aider import AiderConfig, AiderExecutor
from .base import Executor, ExecutionResult, ExecutorOutcome, ExecutorTask
from .claude_agent import ClaudeAgentConfig, ClaudeAgentExecutor

if TYPE_CHECKING:
    from ubik.core.config import UbikConfig

__all__ = [
    "Executor",
    "ExecutionResult",
    "ExecutorOutcome",
    "ExecutorTask",
    "AiderConfig",
    "AiderExecutor",
    "ClaudeAgentConfig",
    "ClaudeAgentExecutor",
    "executor_from_config",
]


def executor_from_config(cfg: "UbikConfig") -> Executor:
    """Resolve an Executor from ``UbikConfig.executor.type``.

    Both adapters create their own git worktrees under
    ``executor.sandbox.worktree_dir`` and respect the cost / time caps
    plumbed through ``ExecutorTask``.
    """
    etype = cfg.executor.type
    worktree_root = cfg.executor.sandbox.worktree_dir

    if etype == "aider":
        return AiderExecutor(
            AiderConfig(
                base_url=cfg.llm.base_url or "https://api.z.ai/api/coding/paas/v4",
                api_key_env=cfg.llm.api_key_env,
                model=f"openai/{cfg.llm.model}",
                worktree_root=worktree_root,
            )
        )

    if etype == "claude_agent_sdk":
        # The SDK speaks Anthropic's API directly. Honor the user's
        # llm.model when the loader infers an Anthropic id; otherwise
        # default to the latest Sonnet so config oversights still work.
        model = cfg.llm.model
        if not model.startswith(("claude-", "anthropic.")):
            model = "claude-sonnet-4-6"
        return ClaudeAgentExecutor(
            ClaudeAgentConfig(
                model=model,
                api_key_env=cfg.llm.api_key_env or "ANTHROPIC_API_KEY",
                worktree_root=worktree_root,
            )
        )

    raise RuntimeError(
        f"executor.type={etype!r} reached the factory but is not in the "
        "supported set. Loader bug — see SUPPORTED_EXECUTOR_TYPES."
    )
