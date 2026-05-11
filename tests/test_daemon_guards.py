"""
Daemon audit-cycle guards: --dry-run path + max_proposals_per_day cap.

These exercise the new code paths added in 0.1.0. Real I/O is patched
out — telegram_from_env, run_audit, and the LLM adapter are all
replaced with fakes. The point is the branching logic in
_daily_audit_cycle, not the underlying adapters.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest

from ubik.adapters.bridge import NotifyMessage, ProposalMessage
from ubik.core.config import UbikConfig

# ── Fakes ────────────────────────────────────────────────────────────────


@dataclass
class FakeBridge:
    name: str = "fake-tg"
    proposals: list[ProposalMessage] = field(default_factory=list)
    notifies: list[NotifyMessage] = field(default_factory=list)

    async def notify(self, message):
        self.notifies.append(message)

    async def propose(self, message):
        self.proposals.append(message)
        return {"chat_id": "x", "message_id": str(len(self.proposals))}

    async def edit_message(self, chat_id, message_id, new_text, *, keep_keyboard=False):
        return True

    async def poll_approvals(self, *, on_event, offset_state_path):
        # Never yields events; the daemon's run() awaits us indefinitely.
        await asyncio.Event().wait()


class FakeLLM:
    name = "fake-llm"

    async def complete(self, *args, **kwargs):
        return {"content": "", "input_tokens": 0, "output_tokens": 0}


@dataclass
class FakeAuditResult:
    """Mimics ResearcherResult shape: .markdown + token counts + .entry."""

    markdown: str
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0

    @property
    def entry(self) -> Any:
        @dataclass
        class _E:
            project: str = "demo"
            title: str = "audit"
            body_path: str = "audit.md"

        return _E()


# ── Helpers ──────────────────────────────────────────────────────────────


def _findings_markdown(n: int) -> str:
    """Return audit markdown with N high-severity findings the extractor
    picks up. Format mirrors tests/test_findings_extract.py SAMPLE."""
    parts = ["# Audit · demo\n\n## Findings\n"]
    for i in range(1, n + 1):
        parts.append(
            f"\n### {i}. Synthetic finding {i} · high\n"
            f"**Evidence**: line {i} of fake.py\n"
            f"**Why it matters**: deterministic test fixture.\n"
            f"**Proposed fix**: do thing number {i}.\n"
            f"**Risk**: low\n"
            f"**ETA**: 5 minutes\n"
        )
    return "\n".join(parts)


@pytest.fixture
def patched_daemon(monkeypatch, tmp_path):
    """Build a Daemon with all external I/O replaced by fakes."""
    from ubik.core import daemon as daemon_mod

    fake_bridge = FakeBridge()
    fake_llm = FakeLLM()

    monkeypatch.setattr(daemon_mod, "bridge_from_config", lambda _cfg: fake_bridge)
    monkeypatch.setattr(daemon_mod, "executor_from_config", lambda _cfg: object())
    monkeypatch.setattr(daemon_mod, "verifier_from_config", lambda _cfg: object())
    monkeypatch.setattr(daemon_mod, "llm_from_config", lambda *_a, **_k: fake_llm)

    cfg = UbikConfig()
    cfg.project.name = "demo"
    cfg.project.repo_path = str(tmp_path)
    cfg.cost.max_proposals_per_day = 3  # tight cap for test

    notebook_root = tmp_path / "research"
    notebook_root.mkdir()

    daemon = daemon_mod.Daemon(
        config=cfg,
        notebook_root=notebook_root,
        daemon_config=daemon_mod.DaemonConfig(dry_run=False),
    )
    # Don't actually run executor / orchestrator-via-bridge during cycle.
    return daemon, fake_bridge, notebook_root


# ── Tests ────────────────────────────────────────────────────────────────


def test_dry_run_persists_but_does_not_publish(patched_daemon, monkeypatch):
    daemon, fake_bridge, notebook_root = patched_daemon
    daemon.daemon_cfg.dry_run = True

    async def fake_audit(**_kwargs):
        return FakeAuditResult(markdown=_findings_markdown(2))

    monkeypatch.setattr("ubik.core.daemon.run_audit", fake_audit)

    asyncio.run(daemon.run_audit_cycle())

    # Proposals were saved to disk.
    saved_ids = daemon.store.all_ids()
    assert len(saved_ids) >= 1, "dry-run must still persist proposals"

    # But the bridge was never asked to publish them.
    assert fake_bridge.proposals == [], (
        f"dry-run leaked {len(fake_bridge.proposals)} proposals to the bridge"
    )

    # And the daily counter was NOT incremented (publish path is the only
    # one that increments).
    assert daemon.proposal_counter.count_today() == 0


def test_cap_reached_drops_overflow_proposals(patched_daemon, monkeypatch):
    daemon, fake_bridge, notebook_root = patched_daemon

    # Pre-load the counter with 2 — cap is 3 so only 1 of the 5 new
    # proposals should slip through.
    daemon.proposal_counter.increment()
    daemon.proposal_counter.increment()

    async def fake_audit(**_kwargs):
        return FakeAuditResult(markdown=_findings_markdown(5))

    # Stub out orchestrator.publish so we don't actually drive the bridge
    # for each accepted proposal — we only care about the gate logic.
    publish_calls: list[str] = []

    async def fake_publish(pid: str) -> None:
        publish_calls.append(pid)

    monkeypatch.setattr("ubik.core.daemon.run_audit", fake_audit)
    monkeypatch.setattr(daemon.orchestrator, "publish", fake_publish)

    asyncio.run(daemon.run_audit_cycle())

    # Exactly one proposal (3 cap - 2 already used) should have hit publish.
    assert len(publish_calls) == 1, (
        f"expected 1 publish call (cap 3, used 2, 5 candidates), got {len(publish_calls)}"
    )

    # The cap-warning notification must have been sent.
    cap_msgs = [n for n in fake_bridge.notifies if "cap" in (n.title or "").lower()]
    assert cap_msgs, "no cap-reached warning was sent to the bridge"


def test_dry_run_skips_cap_warning_notification(patched_daemon, monkeypatch):
    """Even when over cap, dry-run must not spam the bridge with warnings."""
    daemon, fake_bridge, _ = patched_daemon
    daemon.daemon_cfg.dry_run = True
    daemon.proposal_counter.increment()
    daemon.proposal_counter.increment()
    daemon.proposal_counter.increment()  # at cap

    async def fake_audit(**_kwargs):
        return FakeAuditResult(markdown=_findings_markdown(5))

    monkeypatch.setattr("ubik.core.daemon.run_audit", fake_audit)

    asyncio.run(daemon.run_audit_cycle())

    cap_msgs = [n for n in fake_bridge.notifies if "cap" in (n.title or "").lower()]
    assert cap_msgs == [], "dry-run must not push cap warnings to bridge"
