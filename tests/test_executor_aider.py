"""Tests for the Aider executor adapter — protocol shape + failure paths.

We don't actually invoke `aider` here (would need network + an LLM key);
those are covered by smoke tests on Forge. These tests verify the
adapter's failure-mode handling and ExecutorTask/Result wiring.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ubik.adapters.executor import (
    AiderConfig,
    AiderExecutor,
    ExecutionResult,
    ExecutorOutcome,
    ExecutorTask,
)


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for cmd in (
        ["git", "init", "-q", "-b", "main"],
        ["git", "config", "user.email", "t@t"],
        ["git", "config", "user.name", "t"],
        ["git", "config", "commit.gpgsign", "false"],
    ):
        subprocess.run(cmd, cwd=path, check=True, capture_output=True)
    (path / "README.md").write_text("# repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "initial"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "remote", "add", "origin", str(path)],
        cwd=path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "fetch", "origin", "main", "--quiet"],
        cwd=path,
        check=False,
        capture_output=True,
    )


@pytest.mark.asyncio
async def test_aider_missing_returns_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If aider is not on PATH, the adapter returns FAILED with a friendly note."""
    repo = tmp_path / "host"
    _init_repo(repo)

    cfg = AiderConfig(
        aider_binary="totally-not-installed-aider",
        api_key_env="FAKE_KEY",
    )
    executor = AiderExecutor(cfg)
    monkeypatch.setenv("FAKE_KEY", "x")

    task = ExecutorTask(
        proposal_id="p1",
        repo_path=repo,
        title="something",
        plan="don't do anything",
    )

    result = await executor.run(task)
    assert result.outcome == ExecutorOutcome.FAILED
    assert "totally-not-installed-aider" in result.notes
    assert result.proposal_id == "p1"


@pytest.mark.asyncio
async def test_missing_api_key_env_returns_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No API key in env → FAILED with the env var name in the note."""
    repo = tmp_path / "host"
    _init_repo(repo)

    monkeypatch.delenv("UBIK_TEST_KEY", raising=False)
    cfg = AiderConfig(api_key_env="UBIK_TEST_KEY", aider_binary="echo")  # echo is on PATH
    executor = AiderExecutor(cfg)

    task = ExecutorTask(proposal_id="p2", repo_path=repo)
    result = await executor.run(task)
    assert result.outcome == ExecutorOutcome.FAILED
    assert "UBIK_TEST_KEY" in result.notes


def test_executor_task_default_target_branch() -> None:
    """target_branch defaults computed by the executor, not the dataclass."""
    task = ExecutorTask(proposal_id="p1", repo_path=Path("."))
    assert task.target_branch is None  # adapter fills it later


def test_execution_result_carries_diagnostics() -> None:
    """ExecutionResult is a flat dataclass — sanity check the shape."""
    r = ExecutionResult(
        outcome=ExecutorOutcome.SUCCESS,
        proposal_id="p3",
        branch="auto/p3",
        head_sha="abc123",
        files_changed=["foo.py"],
        diff_summary=" 1 file changed",
        test_passed=True,
        notes="ok",
        cost_estimate_usd=0.0,
        duration_seconds=10.5,
    )
    assert r.outcome == ExecutorOutcome.SUCCESS
    assert r.test_passed is True
    assert r.duration_seconds == pytest.approx(10.5)
