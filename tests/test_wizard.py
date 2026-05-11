"""Wizard rendering: answers must round-trip through the config loader."""
from __future__ import annotations

from pathlib import Path

import pytest

from ubik.core.config import load
from ubik.core.wizard import (
    PRESETS,
    WizardAnswers,
    preset_by_key,
    render_env_example,
    render_yaml,
)


def _answers(**overrides) -> WizardAnswers:
    base = dict(
        project_name="demo",
        repo_path="/tmp/demo",
        default_branch="main",
        preset=preset_by_key("zai"),
        approver_chat_ids=[],
        github_repo="acme/demo",
        test_command="pytest -q",
        max_proposals_per_day=20,
        daily_usd_cap=15.0,
        notebook_path="./research",
        daily_at="09:00",
    )
    base.update(overrides)
    return WizardAnswers(**base)


def test_round_trip_zai_default(tmp_path: Path) -> None:
    a = _answers(approver_chat_ids=[123, 456])
    p = tmp_path / "ubik.yaml"
    p.write_text(render_yaml(a), encoding="utf-8")

    cfg = load(p)
    assert cfg.project.name == "demo"
    assert cfg.llm.api_key_env == "Z_AI_API_KEY"
    assert cfg.llm.model == "glm-5.1"
    assert cfg.bridge.approver_chat_ids == [123, 456]
    assert cfg.verifier.pr.repo == "acme/demo"
    assert cfg.verifier.test_command == "pytest -q"
    assert cfg.cost.max_proposals_per_day == 20
    assert cfg.schedule.daily_at == "09:00"


@pytest.mark.parametrize("preset_key", [p.key for p in PRESETS])
def test_every_preset_renders_a_loadable_yaml(tmp_path: Path, preset_key: str) -> None:
    a = _answers(preset=preset_by_key(preset_key))
    p = tmp_path / f"ubik-{preset_key}.yaml"
    p.write_text(render_yaml(a), encoding="utf-8")

    cfg = load(p)
    assert cfg.llm.api_key_env == a.preset.api_key_env
    assert cfg.llm.model == a.preset.model
    assert cfg.llm.provider == a.preset.provider
    assert cfg.llm.base_url == a.preset.base_url


def test_no_test_command_is_emitted_as_null(tmp_path: Path) -> None:
    a = _answers(test_command=None)
    p = tmp_path / "ubik.yaml"
    p.write_text(render_yaml(a), encoding="utf-8")

    cfg = load(p)
    assert cfg.verifier.test_command is None


def test_env_example_lists_all_referenced_env_vars() -> None:
    a = _answers(approver_chat_ids=[1])
    env = render_env_example(a)
    for key in (a.preset.api_key_env, a.bridge_token_env, a.bridge_chat_id_env, "GITHUB_TOKEN"):
        assert f"{key}=" in env, f"{key} missing from rendered .env.example"
