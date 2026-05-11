"""
Claude Agent SDK executor — orchestration around a mocked SDK boundary.

We don't import claude_agent_sdk for real; the executor lazy-imports it,
so we install a fake module into sys.modules before the executor runs.
This validates: missing-SDK error path, missing-API-key error path,
worktree creation, no-commits guard, success path.
"""
from __future__ import annotations

import asyncio
import subprocess
import sys
import types
from pathlib import Path

import pytest

from ubik.adapters.executor import (
    ClaudeAgentConfig,
    ClaudeAgentExecutor,
    ExecutorOutcome,
    ExecutorTask,
)


# ── Fake SDK plumbing ────────────────────────────────────────────────────


def _install_fake_sdk(*, on_query=None) -> types.ModuleType:
    """Install a fake claude_agent_sdk module. Returns the module."""
    mod = types.ModuleType("claude_agent_sdk")

    class ClaudeAgentOptions:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    async def query(*, prompt, options, transport=None):
        if on_query is not None:
            async for m in on_query(prompt=prompt, options=options):
                yield m
        else:
            yield {"type": "text", "content": "ok"}

    mod.ClaudeAgentOptions = ClaudeAgentOptions
    mod.query = query
    sys.modules["claude_agent_sdk"] = mod
    return mod


def _uninstall_fake_sdk() -> None:
    sys.modules.pop("claude_agent_sdk", None)


@pytest.fixture
def fake_sdk():
    mod = _install_fake_sdk()
    try:
        yield mod
    finally:
        _uninstall_fake_sdk()


# ── Helper: minimal git repo so worktree creation works ─────────────────


def _git_repo(tmp_path: Path) -> Path:
    """Init a git repo with a self-pointing origin so create_worktree can
    resolve ``origin/main``. Mirrors tests/test_executor_aider.py."""
    repo = tmp_path / "repo"
    repo.mkdir()
    for cmd in (
        ["git", "init", "-q", "-b", "main"],
        ["git", "config", "user.email", "t@t"],
        ["git", "config", "user.name", "t"],
        ["git", "config", "commit.gpgsign", "false"],
    ):
        subprocess.run(cmd, cwd=repo, check=True, capture_output=True)
    (repo / "README.md").write_text("hello")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "remote", "add", "origin", str(repo)],
        cwd=repo, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "fetch", "origin", "main", "--quiet"],
        cwd=repo, check=False, capture_output=True,
    )
    return repo


# ── Tests ────────────────────────────────────────────────────────────────


def test_missing_sdk_returns_failed():
    """No fake_sdk fixture — the import inside run() should miss."""
    _uninstall_fake_sdk()
    ex = ClaudeAgentExecutor(ClaudeAgentConfig())
    task = ExecutorTask(proposal_id="x", repo_path=Path("."))
    result = asyncio.run(ex.run(task))
    assert result.outcome == ExecutorOutcome.FAILED
    assert "claude-agent-sdk" in result.notes


def test_missing_api_key_returns_failed(fake_sdk, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    ex = ClaudeAgentExecutor(ClaudeAgentConfig())
    task = ExecutorTask(proposal_id="x", repo_path=Path("."))
    result = asyncio.run(ex.run(task))
    assert result.outcome == ExecutorOutcome.FAILED
    assert "ANTHROPIC_API_KEY" in result.notes


def test_no_commits_after_session_marks_failed(fake_sdk, monkeypatch, tmp_path):
    """SDK runs cleanly but model never edited anything → executor must
    refuse to mark success (mirrors Aider's empty-diff guard)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    repo = _git_repo(tmp_path)

    ex = ClaudeAgentExecutor(ClaudeAgentConfig(worktree_root=str(tmp_path / "wt")))
    task = ExecutorTask(
        proposal_id="abc12345",
        repo_path=repo,
        base_branch="main",
        title="no-op task",
        plan="describe but do not edit",
    )
    result = asyncio.run(ex.run(task))
    assert result.outcome == ExecutorOutcome.FAILED
    assert "No new commits" in result.notes
    assert result.files_changed == []


def test_successful_session_with_real_edit(fake_sdk, monkeypatch, tmp_path):
    """SDK 'edits' a file via the fake — executor inspects git, sees a
    new commit, and reports SUCCESS."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    repo = _git_repo(tmp_path)

    async def edit_during_query(*, prompt, options):
        # Write a file in the worktree (cwd from options) and yield a msg.
        Path(options.cwd, "new.txt").write_text("hi")
        yield {"type": "text", "content": "edited new.txt"}

    _install_fake_sdk(on_query=edit_during_query)

    ex = ClaudeAgentExecutor(ClaudeAgentConfig(worktree_root=str(tmp_path / "wt")))
    task = ExecutorTask(
        proposal_id="abc12345",
        repo_path=repo,
        base_branch="main",
        title="add new.txt",
        plan="create file",
    )
    result = asyncio.run(ex.run(task))
    assert result.outcome == ExecutorOutcome.SUCCESS, result.notes
    assert "new.txt" in result.files_changed
    assert result.head_sha
    assert result.branch and result.branch.startswith("auto/")


def test_session_timeout_returns_timed_out(monkeypatch, tmp_path):
    """A query() that yields slowly past time_cap_seconds is killed."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    repo = _git_repo(tmp_path)

    async def slow_query(*, prompt, options):
        await asyncio.sleep(5)  # task.time_cap_seconds=1 below
        yield {"type": "text", "content": "too late"}

    _install_fake_sdk(on_query=slow_query)

    ex = ClaudeAgentExecutor(ClaudeAgentConfig(worktree_root=str(tmp_path / "wt")))
    task = ExecutorTask(
        proposal_id="abc12345",
        repo_path=repo,
        base_branch="main",
        title="slow",
        plan="",
        time_cap_seconds=1,
    )
    result = asyncio.run(ex.run(task))
    assert result.outcome == ExecutorOutcome.TIMED_OUT
    assert "wall-clock cap" in result.notes
    _uninstall_fake_sdk()
