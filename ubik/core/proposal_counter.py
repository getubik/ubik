"""
Daily proposal counter — file-backed cap state for ``cost.max_proposals_per_day``.

State lives at ``<notebook_root>/proposals/.daily-counter.json``. The
counter is keyed by local-date string (YYYY-MM-DD) so a midnight rollover
naturally resets it without any cron job.

Single-writer assumption: only the daemon increments. Tests construct
their own counter against a tmp dir.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path


class DailyProposalCounter:
    def __init__(self, notebook_root: Path) -> None:
        self._path = Path(notebook_root) / "proposals" / ".daily-counter.json"
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def count_today(self) -> int:
        data = self._load()
        return int(data.get(self._today(), 0))

    def increment(self) -> int:
        data = self._load()
        today = self._today()
        data[today] = int(data.get(today, 0)) + 1
        self._save(data)
        return data[today]

    @staticmethod
    def _today() -> str:
        return date.today().isoformat()

    def _load(self) -> dict[str, int]:
        if not self._path.exists():
            return {}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            return {k: int(v) for k, v in raw.items() if isinstance(v, (int, str))}
        except (json.JSONDecodeError, OSError, ValueError):
            return {}

    def _save(self, data: dict[str, int]) -> None:
        # Trim to last 30 days to keep the file tiny.
        if len(data) > 30:
            keep = sorted(data.keys())[-30:]
            data = {k: data[k] for k in keep}
        self._path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
