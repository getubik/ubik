"""Config loader contract: every field in ubik.example.yaml must round-trip."""

from __future__ import annotations

from pathlib import Path

import pytest

from ubik.core.config import (
    SUPPORTED_BRIDGE_TYPES,
    SUPPORTED_EXECUTOR_TYPES,
    ConfigError,
    UbikConfig,
    load,
)


def test_load_with_no_file_returns_defaults() -> None:
    cfg = load()
    assert isinstance(cfg, UbikConfig)
    assert cfg.cost.max_proposals_per_day == 20
    assert cfg.executor.type == "aider"
    assert cfg.bridge.type == "telegram"
    assert cfg.executor.sandbox.time_cap_minutes == 15


def test_load_repo_path_override(tmp_path: Path) -> None:
    cfg = load(repo_path=tmp_path)
    assert cfg.project.repo_path == str(tmp_path.resolve())
    assert cfg.project.name == tmp_path.name


def _write(p: Path, body: str) -> Path:
    p.write_text(body, encoding="utf-8")
    return p


def test_load_full_config(tmp_path: Path) -> None:
    yml = _write(
        tmp_path / "ubik.yaml",
        """
project:
  name: "demo"
  repo_path: "."
  default_branch: "trunk"

researcher:
  llm:
    provider: "openai"
    base_url: null
    api_key_env: "OPENAI_API_KEY"
    model: "gpt-4o"
    thinking: false
    max_tokens: 4096
  schedule:
    daily_at: "07:30"
    pulse_every_minutes: 30

executor:
  type: "aider"
  sandbox:
    worktree_dir: "./.wt"
    cost_cap_usd: 9.5
    time_cap_minutes: 30
  guardrails:
    cannot_push_to: ["release"]
    require_tests: false
    require_pr_review: false

bridge:
  type: "telegram"
  token_env: "TG_TOKEN"
  chat_id_env: "TG_CHAT"
  approver_chat_ids: [11, 22]
  rate_limit:
    max_pushes_per_hour: 9
    cooldown_minutes_per_proposal: 90

verifier:
  test_command: "make test"
  build_command: "make build"
  smoke_command: "curl -f localhost:8000/health"
  pr:
    provider: "github"
    repo: "acme/widget"
    base_branch: "trunk"
    auto_create: false

notebook:
  storage: "filesystem"
  path: "./notes"

cost:
  daily_usd_cap: 33.0
  alert_at_percent: 70
  track_only: true
  max_proposals_per_day: 7
""",
    )
    cfg = load(yml)
    assert cfg.project.default_branch == "trunk"
    assert cfg.llm.model == "gpt-4o"
    assert cfg.llm.thinking is False
    assert cfg.schedule.daily_at == "07:30"
    assert cfg.schedule.pulse_every_minutes == 30
    assert cfg.executor.sandbox.cost_cap_usd == 9.5
    assert cfg.executor.sandbox.time_cap_minutes == 30
    assert cfg.executor.guardrails.cannot_push_to == ["release"]
    assert cfg.executor.guardrails.require_tests is False
    assert cfg.bridge.approver_chat_ids == [11, 22]
    assert cfg.bridge.rate_limit.max_pushes_per_hour == 9
    assert cfg.verifier.test_command == "make test"
    assert cfg.verifier.pr.repo == "acme/widget"
    assert cfg.verifier.pr.auto_create is False
    assert cfg.notebook.path == "./notes"
    assert cfg.cost.max_proposals_per_day == 7
    assert cfg.cost.track_only is True


def test_unknown_executor_type_raises(tmp_path: Path) -> None:
    yml = _write(
        tmp_path / "ubik.yaml",
        """
executor:
  type: "openhands"
""",
    )
    with pytest.raises(ConfigError) as exc_info:
        load(yml)
    assert "executor.type" in str(exc_info.value)
    assert "openhands" in str(exc_info.value)


def test_unknown_bridge_type_raises(tmp_path: Path) -> None:
    yml = _write(
        tmp_path / "ubik.yaml",
        """
bridge:
  type: "slack"
""",
    )
    with pytest.raises(ConfigError) as exc_info:
        load(yml)
    assert "bridge.type" in str(exc_info.value)


def test_supported_sets_match_implementation() -> None:
    """Sanity: don't accidentally let a roadmap value into the supported set.
    Update this list deliberately when an adapter actually ships."""
    assert {"aider", "claude_agent_sdk"} == SUPPORTED_EXECUTOR_TYPES
    assert {"telegram"} == SUPPORTED_BRIDGE_TYPES


def test_partial_block_keeps_defaults_for_missing_keys(tmp_path: Path) -> None:
    """Loader must not require every key in a block to be present."""
    yml = _write(
        tmp_path / "ubik.yaml",
        """
cost:
  daily_usd_cap: 1.0
""",
    )
    cfg = load(yml)
    assert cfg.cost.daily_usd_cap == 1.0
    assert cfg.cost.max_proposals_per_day == 20  # default preserved
    assert cfg.cost.alert_at_percent == 80
