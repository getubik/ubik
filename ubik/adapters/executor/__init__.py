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
        # Claude Agent SDK wraps the official `anthropic` Python client,
        # which respects ANTHROPIC_BASE_URL at construction time. So if
        # the user has llm.base_url set to an Anthropic-compatible proxy
        # (Z.AI's /api/anthropic surface for Claude Code routing,
        # OpenRouter, LiteLLM gateway, etc.), we pass it through and
        # trust their model name — the proxy decides what to do with it.
        #
        # ONLY fall back to claude-sonnet-4-6 when both conditions hit:
        #   1. No base_url override (so we're talking to real Anthropic)
        #   2. Model name isn't Anthropic-shaped
        # In that case we shout, because silently billing two providers
        # is the kind of surprise users hate.
        base_url = cfg.llm.base_url
        model = cfg.llm.model
        api_key_env = cfg.llm.api_key_env or "ANTHROPIC_API_KEY"
        anthropic_shaped = model.startswith(("claude-", "anthropic."))

        if not base_url and not anthropic_shaped:
            logger.warning(
                "executor.type=claude_agent_sdk with llm.model=%r and no "
                "base_url override — the SDK speaks Anthropic's official "
                "API which won't recognize that model. Falling back to "
                "'claude-sonnet-4-6' on ANTHROPIC_API_KEY. If your "
                "provider exposes an Anthropic-compatible endpoint "
                "(like Z.AI's /api/anthropic surface for Claude Code "
                "routing), set llm.base_url to that URL and we'll pass "
                "it through via ANTHROPIC_BASE_URL.",
                model,
            )
            model = "claude-sonnet-4-6"
            api_key_env = "ANTHROPIC_API_KEY"
            base_url = None

        return ClaudeAgentExecutor(
            ClaudeAgentConfig(
                model=model,
                api_key_env=api_key_env,
                base_url=base_url,
                worktree_root=worktree_root,
            )
        )

    raise RuntimeError(
        f"executor.type={etype!r} reached the factory but is not in the "
        "supported set. Loader bug — see SUPPORTED_EXECUTOR_TYPES."
    )
