"""
Cross-platform path helpers — replaces the old hard-coded ``/var/lib/ubik``.

Resolution rules (in order):

  1. ``UBIK_HOME`` env var, if set, wins for everything.
  2. Otherwise: standard XDG / OS convention:
       - Linux:   ~/.local/state/ubik
       - macOS:   ~/Library/Application Support/ubik
       - Windows: %LOCALAPPDATA%\\ubik (e.g. C:/Users/foo/AppData/Local/ubik)
       - fallback: ~/.ubik

We avoid pulling in the ``platformdirs`` dependency for one helper —
the rules above are stable enough to inline.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def user_state_dir() -> Path:
    """Per-user mutable state — counters, poll offsets, caches."""
    override = os.environ.get("UBIK_HOME")
    if override:
        return Path(override).expanduser().resolve()

    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "ubik"

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "ubik"

    # Linux / BSD / everything else: XDG_STATE_HOME, then ~/.local/state.
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        return Path(xdg) / "ubik"
    return Path.home() / ".local" / "state" / "ubik"


def default_poll_offset_path() -> Path:
    return user_state_dir() / "poll-offset"
