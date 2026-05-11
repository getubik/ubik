"""Cost-cap counter: file-backed, date-keyed, survives import."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from ubik.core.proposal_counter import DailyProposalCounter


def test_count_today_starts_at_zero(tmp_path: Path) -> None:
    c = DailyProposalCounter(tmp_path)
    assert c.count_today() == 0


def test_increment_persists_across_instances(tmp_path: Path) -> None:
    c1 = DailyProposalCounter(tmp_path)
    c1.increment()
    c1.increment()
    c1.increment()

    c2 = DailyProposalCounter(tmp_path)
    assert c2.count_today() == 3


def test_state_file_lives_under_proposals_dir(tmp_path: Path) -> None:
    c = DailyProposalCounter(tmp_path)
    c.increment()
    assert (tmp_path / "proposals" / ".daily-counter.json").exists()


def test_other_dates_do_not_count_toward_today(tmp_path: Path) -> None:
    state = tmp_path / "proposals"
    state.mkdir(parents=True)
    (state / ".daily-counter.json").write_text(
        json.dumps({"1999-01-01": 999, date.today().isoformat(): 4}),
        encoding="utf-8",
    )
    c = DailyProposalCounter(tmp_path)
    assert c.count_today() == 4


def test_corrupt_state_file_is_treated_as_empty(tmp_path: Path) -> None:
    state = tmp_path / "proposals"
    state.mkdir(parents=True)
    (state / ".daily-counter.json").write_text("not json {{{", encoding="utf-8")

    c = DailyProposalCounter(tmp_path)
    assert c.count_today() == 0
    c.increment()
    assert c.count_today() == 1


def test_old_dates_are_pruned_above_30_entries(tmp_path: Path) -> None:
    state = tmp_path / "proposals"
    state.mkdir(parents=True)
    fake = {f"2000-{m:02d}-01": 1 for m in range(1, 13)}
    fake.update({f"2001-{m:02d}-01": 1 for m in range(1, 13)})
    fake.update({f"2002-{m:02d}-01": 1 for m in range(1, 13)})
    (state / ".daily-counter.json").write_text(json.dumps(fake), encoding="utf-8")

    c = DailyProposalCounter(tmp_path)
    c.increment()
    saved = json.loads((state / ".daily-counter.json").read_text(encoding="utf-8"))
    assert len(saved) <= 30
