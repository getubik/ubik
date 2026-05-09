"""Tests for the proposal lifecycle + persistence layer."""
from __future__ import annotations

from pathlib import Path

import pytest

from ubik.core.proposal import Proposal, ProposalState, ProposalStore


def _make_proposal(**overrides) -> Proposal:
    defaults = dict(
        project="gyibb",
        title="Remove docker socket mount",
        severity="critical",
        summary="Ambassador shouldn't see /var/run/docker.sock",
        plan="Drop the volume mount; use a status endpoint instead.",
        evidence=["docker-compose.yml line 116"],
        risk="low",
        eta="1 hour",
        repo_path="/opt/gyibb-v2",
    )
    defaults.update(overrides)
    return Proposal.new(**defaults)


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    store = ProposalStore(tmp_path)
    p = _make_proposal()
    store.save(p)

    loaded = store.load(p.id)
    assert loaded.id == p.id
    assert loaded.title == p.title
    assert loaded.severity == "critical"
    assert loaded.state == ProposalState.DRAFT
    assert loaded.evidence == ["docker-compose.yml line 116"]


def test_state_transitions_persist(tmp_path: Path) -> None:
    store = ProposalStore(tmp_path)
    p = _make_proposal()
    store.save(p)

    p.state = ProposalState.PENDING
    p.bridge_refs = {"chat_id": "215587838", "message_id": "42"}
    store.save(p)

    after = store.load(p.id)
    assert after.state == ProposalState.PENDING
    assert after.bridge_refs == {"chat_id": "215587838", "message_id": "42"}


def test_by_state_filters(tmp_path: Path) -> None:
    store = ProposalStore(tmp_path)

    p1 = _make_proposal(title="one")
    p2 = _make_proposal(title="two")
    p3 = _make_proposal(title="three")
    p2.state = ProposalState.PENDING
    p3.state = ProposalState.APPROVED

    for p in (p1, p2, p3):
        store.save(p)

    drafts = store.by_state(ProposalState.DRAFT)
    pending = store.by_state(ProposalState.PENDING)
    approved = store.by_state(ProposalState.APPROVED)

    assert {p.title for p in drafts} == {"one"}
    assert {p.title for p in pending} == {"two"}
    assert {p.title for p in approved} == {"three"}


def test_load_missing_raises(tmp_path: Path) -> None:
    store = ProposalStore(tmp_path)
    with pytest.raises(KeyError):
        store.load("does-not-exist")


def test_index_survives_corruption(tmp_path: Path) -> None:
    store = ProposalStore(tmp_path)
    p = _make_proposal()
    store.save(p)

    # Corrupt the manifest JSON.
    (tmp_path / "proposals" / "index.json").write_text("not-json", encoding="utf-8")

    # by_state must not crash; it just falls back to empty.
    assert store.by_state(ProposalState.DRAFT) == []

    # A fresh save rebuilds the index.
    store.save(p)
    assert len(store.by_state(ProposalState.DRAFT)) == 1
