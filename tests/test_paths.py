"""Cross-platform user state paths."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from ubik.core.paths import default_poll_offset_path, user_state_dir


def test_ubik_home_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("UBIK_HOME", str(tmp_path / "custom"))
    assert user_state_dir() == (tmp_path / "custom").resolve()


@pytest.mark.skipif(sys.platform != "win32", reason="windows-only path rule")
def test_windows_uses_localappdata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UBIK_HOME", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", "C:/fake/AppData/Local")
    assert "ubik" in str(user_state_dir()).lower()


@pytest.mark.skipif(sys.platform != "linux", reason="linux-only path rule")
def test_linux_xdg_state_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("UBIK_HOME", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert user_state_dir() == tmp_path / "ubik"


def test_default_poll_offset_lives_under_state_dir() -> None:
    p = default_poll_offset_path()
    assert p.parent == user_state_dir()
    assert p.name == "poll-offset"
