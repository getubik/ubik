"""Adapter factories: type field in config dispatches to the right class."""
from __future__ import annotations

import pytest

from ubik.adapters.bridge import bridge_from_config
from ubik.adapters.executor import (
    AiderExecutor,
    ClaudeAgentExecutor,
    executor_from_config,
)
from ubik.adapters.verifier import (
    GitHubVerifier,
    GitLabVerifier,
    verifier_from_config,
)
from ubik.core.config import UbikConfig


# ── Executor factory ────────────────────────────────────────────────────


def test_executor_factory_aider_default():
    cfg = UbikConfig()
    assert cfg.executor.type == "aider"
    ex = executor_from_config(cfg)
    assert isinstance(ex, AiderExecutor)
    assert ex.config.worktree_root == cfg.executor.sandbox.worktree_dir
    # litellm-style "openai/<model>" prefix is required for Aider.
    assert ex.config.model.startswith("openai/")


def test_executor_factory_claude_agent():
    cfg = UbikConfig()
    cfg.executor.type = "claude_agent_sdk"
    cfg.llm.model = "claude-sonnet-4-6"
    cfg.llm.api_key_env = "ANTHROPIC_API_KEY"
    ex = executor_from_config(cfg)
    assert isinstance(ex, ClaudeAgentExecutor)
    assert ex.config.model == "claude-sonnet-4-6"
    assert ex.config.api_key_env == "ANTHROPIC_API_KEY"
    assert ex.config.worktree_root == cfg.executor.sandbox.worktree_dir


def test_executor_factory_claude_agent_corrects_non_anthropic_model():
    """If the user pointed llm.model at GLM (default), don't blindly send
    it to the Anthropic-only SDK — fall back to the latest Sonnet."""
    cfg = UbikConfig()
    cfg.executor.type = "claude_agent_sdk"
    # Default cfg.llm.model is "glm-5.1" — not an Anthropic id.
    ex = executor_from_config(cfg)
    assert isinstance(ex, ClaudeAgentExecutor)
    assert ex.config.model.startswith("claude-")


def test_executor_factory_unknown_type_raises():
    cfg = UbikConfig()
    cfg.executor.type = "openhands"  # bypass loader validation
    with pytest.raises(RuntimeError, match="not in the supported set"):
        executor_from_config(cfg)


# ── Verifier factory ────────────────────────────────────────────────────


def test_verifier_factory_github_default():
    cfg = UbikConfig()
    assert cfg.verifier.pr.provider == "github"
    v = verifier_from_config(cfg)
    assert isinstance(v, GitHubVerifier)


def test_verifier_factory_gitlab():
    cfg = UbikConfig()
    cfg.verifier.pr.provider = "gitlab"
    v = verifier_from_config(cfg)
    assert isinstance(v, GitLabVerifier)


def test_verifier_factory_unknown_raises():
    cfg = UbikConfig()
    cfg.verifier.pr.provider = "bitbucket"
    with pytest.raises(RuntimeError, match="not in the supported set"):
        verifier_from_config(cfg)


# ── Bridge factory ──────────────────────────────────────────────────────


def test_bridge_factory_telegram_with_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345,67890")
    cfg = UbikConfig()
    cfg.bridge.approver_chat_ids = []  # force env fallback
    br = bridge_from_config(cfg)
    assert br.config.bot_token == "test-token"
    assert br.config.chat_ids == [12345, 67890]


def test_bridge_factory_telegram_yaml_chat_ids_win(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")
    cfg = UbikConfig()
    cfg.bridge.approver_chat_ids = [111, 222]
    br = bridge_from_config(cfg)
    assert br.config.chat_ids == [111, 222]


def test_bridge_factory_telegram_no_chat_ids_anywhere(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    cfg = UbikConfig()
    cfg.bridge.approver_chat_ids = []
    with pytest.raises(RuntimeError, match="nobody to whisper"):
        bridge_from_config(cfg)


def test_bridge_factory_unknown_raises():
    cfg = UbikConfig()
    cfg.bridge.type = "discord"
    with pytest.raises(RuntimeError, match="not in the supported set"):
        bridge_from_config(cfg)
