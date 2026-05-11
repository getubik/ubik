"""Executor adapters — how Ubik turns proposals into code changes."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .aider import AiderConfig, AiderExecutor
from .base import Executor, ExecutionResult, ExecutorOutcome, ExecutorTask
from .claude_agent import ClaudeAgentConfig, ClaudeAgentExecutor

if TYPE_CHECKING:
    from ubik.core.config import UbikConfig

logger = logging.getLogger(__name__)

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
        # The Claude Agent SDK speaks Anthropic's Messages API directly —
        # no OpenAI-compatible base_url knob. So this executor is locked
        # to Anthropic-served models regardless of what the researcher
        # LLM block points at. If the user's llm.model is non-Anthropic
        # (e.g. they picked Z.AI / Kimi / MiniMax in `ubik init`), we
        # FALL BACK to Claude Sonnet 4.6 and shout about it — silently
        # billing two providers is the kind of surprise users hate.
        model = cfg.llm.model
        api_key_env = cfg.llm.api_key_env or "ANTHROPIC_API_KEY"
        if not model.startswith(("claude-", "anthropic.")):
            logger.warning(
                "executor.type=claude_agent_sdk but llm.model=%r is not an "
                "Anthropic id. The SDK only speaks Anthropic's API, so the "
                "executor will use 'claude-sonnet-4-6' on ANTHROPIC_API_KEY "
                "regardless of your researcher LLM choice. "
                "Switch executor.type to 'aider' if you want %r to do the "
                "code edits too.",
                model, model,
            )
            model = "claude-sonnet-4-6"
            api_key_env = "ANTHROPIC_API_KEY"
        return ClaudeAgentExecutor(
            ClaudeAgentConfig(
                model=model,
                api_key_env=api_key_env,
                worktree_root=worktree_root,
            )
        )

    raise RuntimeError(
        f"executor.type={etype!r} reached the factory but is not in the "
        "supported set. Loader bug — see SUPPORTED_EXECUTOR_TYPES."
    )
