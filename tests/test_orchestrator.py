"""Tests for the orchestrator state machine.

Uses fakes for Bridge + Executor — no Telegram round-trip, no LLM.
Validates state transitions, double-tap idempotency, and the
execute → READY_FOR_PR / EXECUTION_FAILED branches.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from ubik.adapters.bridge import (
    ApprovalEvent,
    Decision,
    NotifyMessage,
    ProposalMessage,
)
from ubik.adapters.executor import (
    ExecutionResult,
    ExecutorOutcome,
    ExecutorTask,
)
from ubik.adapters.verifier import VerifyOutcome, VerifyResult, VerifyTask
from ubik.core.notebook import Notebook
from ubik.core.orchestrator import Orchestrator
from ubik.core.proposal import Proposal, ProposalState, ProposalStore

# ── Fakes ───────────────────────────────────────────────────────────────


@dataclass
class FakeBridge:
    name: str = "fake"
    proposals: list[ProposalMessage] = field(default_factory=list)
    notifies: list[NotifyMessage] = field(default_factory=list)
    edits: list[dict] = field(default_factory=list)

    async def notify(self, message: NotifyMessage) -> None:
        self.notifies.append(message)

    async def propose(self, message: ProposalMessage) -> dict[str, str]:
        self.proposals.append(message)
        return {"chat_id": "fake-chat", "message_id": str(len(self.proposals))}

    async def edit_message(self, chat_id, message_id, new_text, *, keep_keyboard=False):
        self.edits.append(
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": new_text,
            }
        )
        return True


@dataclass
class FakeVerifier:
    name: str = "fake-github"
    outcome: VerifyOutcome = VerifyOutcome.OPENED
    last_task: VerifyTask | None = None

    async def verify(self, task: VerifyTask) -> VerifyResult:
        self.last_task = task
        if self.outcome == VerifyOutcome.OPENED:
            return VerifyResult(
                outcome=VerifyOutcome.OPENED,
                proposal_id=task.proposal_id,
                branch=task.branch,
                pr_url="https://github.com/getubik/ubik/pull/42",
                pr_number=42,
                notes="ok",
            )
        return VerifyResult(
            outcome=self.outcome,
            proposal_id=task.proposal_id,
            branch=task.branch,
            notes="simulated failure",
        )


@dataclass
class FakeExecutor:
    name: str = "fake-aider"
    outcome: ExecutorOutcome = ExecutorOutcome.SUCCESS
    last_task: ExecutorTask | None = None

    async def run(self, task: ExecutorTask) -> ExecutionResult:
        self.last_task = task
        return ExecutionResult(
            outcome=self.outcome,
            proposal_id=task.proposal_id,
            branch=task.target_branch or f"auto/{task.proposal_id[:8]}",
            head_sha="deadbeef",
            files_changed=["docker-compose.yml"],
            diff_summary=" 1 file changed, 1 deletion(-)",
            test_passed=(self.outcome == ExecutorOutcome.SUCCESS),
            notes="ran",
            duration_seconds=12.3,
        )


# ── Helpers ─────────────────────────────────────────────────────────────


def _make_setup(
    tmp_path: Path,
    executor_outcome=ExecutorOutcome.SUCCESS,
    verifier: FakeVerifier | None = None,
):
    notebook = Notebook(tmp_path)
    store = ProposalStore(tmp_path)
    bridge = FakeBridge()
    executor = FakeExecutor(outcome=executor_outcome)
    orch = Orchestrator(
        store=store,
        notebook=notebook,
        bridge=bridge,
        executor=executor,
        verifier=verifier,
    )

    proposal = Proposal.new(
        project="gyibb",
        title="Drop docker socket mount",
        severity="critical",
        summary="Ambassador shouldn't see /var/run/docker.sock",
        plan="Remove the mount from docker-compose.yml.",
        evidence=["line 116"],
        risk="low",
        eta="1h",
        repo_path=str(tmp_path / "host"),  # path doesn't need to exist for fake executor
    )
    store.save(proposal)
    return orch, store, bridge, executor, proposal


# ── Tests ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_publish_moves_draft_to_pending(tmp_path: Path) -> None:
    orch, store, bridge, _, proposal = _make_setup(tmp_path)

    await orch.publish(proposal.id)

    after = store.load(proposal.id)
    assert after.state == ProposalState.PENDING
    assert after.bridge_refs == {"chat_id": "fake-chat", "message_id": "1"}
    assert len(bridge.proposals) == 1
    assert bridge.proposals[0].proposal_id == proposal.id


@pytest.mark.asyncio
async def test_publish_refuses_nonpending_states(tmp_path: Path) -> None:
    orch, store, _, _, proposal = _make_setup(tmp_path)

    proposal.state = ProposalState.APPROVED
    store.save(proposal)

    with pytest.raises(RuntimeError, match="refusing to publish"):
        await orch.publish(proposal.id)


@pytest.mark.asyncio
async def test_approve_runs_executor_and_marks_ready_for_pr(tmp_path: Path) -> None:
    orch, store, bridge, executor, proposal = _make_setup(tmp_path)
    await orch.publish(proposal.id)

    event = ApprovalEvent(
        proposal_id=proposal.id,
        decision=Decision.APPROVED,
        by="ismail",
        at="2026-05-09T22:00:00",
    )
    await orch.on_approval(event)

    after = store.load(proposal.id)
    assert after.state == ProposalState.READY_FOR_PR
    assert after.branch == f"auto/{proposal.id[:8]}"
    assert after.head_sha == "deadbeef"
    assert "docker-compose.yml" in after.files_changed
    # Bridge edit (lock) + post-execution notify both fired.
    assert len(bridge.edits) == 1
    assert "Approved" in bridge.edits[0]["text"]
    assert any("branch ready" in n.title for n in bridge.notifies)


@pytest.mark.asyncio
async def test_approve_executor_failure_marks_execution_failed(tmp_path: Path) -> None:
    orch, store, bridge, _, proposal = _make_setup(
        tmp_path, executor_outcome=ExecutorOutcome.FAILED
    )
    await orch.publish(proposal.id)

    await orch.on_approval(
        ApprovalEvent(
            proposal_id=proposal.id,
            decision=Decision.APPROVED,
            by="i",
            at="t",
        )
    )

    after = store.load(proposal.id)
    assert after.state == ProposalState.EXECUTION_FAILED
    assert any("execution failed" in n.title for n in bridge.notifies)


@pytest.mark.asyncio
async def test_reject_marks_rejected_and_locks_message(tmp_path: Path) -> None:
    orch, store, bridge, _, proposal = _make_setup(tmp_path)
    await orch.publish(proposal.id)

    await orch.on_approval(
        ApprovalEvent(
            proposal_id=proposal.id,
            decision=Decision.REJECTED,
            by="i",
            at="t",
        )
    )

    after = store.load(proposal.id)
    assert after.state == ProposalState.REJECTED
    assert "Rejected" in bridge.edits[0]["text"]


@pytest.mark.asyncio
async def test_double_tap_is_idempotent(tmp_path: Path) -> None:
    orch, store, bridge, executor, proposal = _make_setup(tmp_path)
    await orch.publish(proposal.id)

    ev = ApprovalEvent(proposal_id=proposal.id, decision=Decision.APPROVED, by="i", at="t")
    await orch.on_approval(ev)
    # Second tap on the same proposal must NOT re-execute.
    executor.outcome = ExecutorOutcome.FAILED  # if it runs again, would mark FAILED
    await orch.on_approval(ev)

    after = store.load(proposal.id)
    assert after.state == ProposalState.READY_FOR_PR  # didn't get bumped to FAILED


@pytest.mark.asyncio
async def test_diff_tap_does_not_change_state(tmp_path: Path) -> None:
    orch, store, bridge, _, proposal = _make_setup(tmp_path)
    await orch.publish(proposal.id)

    await orch.on_approval(
        ApprovalEvent(
            proposal_id=proposal.id,
            decision=Decision.PENDING,  # 'diff' tap
            by="i",
            at="t",
        )
    )

    after = store.load(proposal.id)
    assert after.state == ProposalState.PENDING  # unchanged
    # Bridge got a notify with the full body.
    assert any("diff" in n.title.lower() for n in bridge.notifies)


@pytest.mark.asyncio
async def test_unknown_proposal_id_is_ignored(tmp_path: Path) -> None:
    orch, store, bridge, _, _ = _make_setup(tmp_path)

    await orch.on_approval(
        ApprovalEvent(
            proposal_id="does-not-exist",
            decision=Decision.APPROVED,
            by="i",
            at="t",
        )
    )
    # No exceptions, no side effects.
    assert bridge.notifies == []
    assert bridge.edits == []


# ── Verifier integration ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_approve_with_verifier_opens_pr(tmp_path: Path) -> None:
    verifier = FakeVerifier()
    orch, store, bridge, _, proposal = _make_setup(tmp_path, verifier=verifier)
    await orch.publish(proposal.id)

    await orch.on_approval(
        ApprovalEvent(
            proposal_id=proposal.id,
            decision=Decision.APPROVED,
            by="i",
            at="t",
        )
    )

    after = store.load(proposal.id)
    assert after.state == ProposalState.PR_OPENED
    assert after.pr_url == "https://github.com/getubik/ubik/pull/42"
    # Two notifies: post-execution summary + post-verify summary.
    assert any("PR ready" in n.title for n in bridge.notifies)


@pytest.mark.asyncio
async def test_approve_with_verifier_failure_keeps_ready_state(tmp_path: Path) -> None:
    verifier = FakeVerifier(outcome=VerifyOutcome.PUSH_FAILED)
    orch, store, bridge, _, proposal = _make_setup(tmp_path, verifier=verifier)
    await orch.publish(proposal.id)

    await orch.on_approval(
        ApprovalEvent(
            proposal_id=proposal.id,
            decision=Decision.APPROVED,
            by="i",
            at="t",
        )
    )

    after = store.load(proposal.id)
    # Stays at READY_FOR_PR (executor done) but no PR URL.
    assert after.state == ProposalState.READY_FOR_PR
    assert after.pr_url is None
    assert any("PR failed" in n.title for n in bridge.notifies)


@pytest.mark.asyncio
async def test_executor_failure_skips_verifier(tmp_path: Path) -> None:
    verifier = FakeVerifier()
    orch, store, _, _, proposal = _make_setup(
        tmp_path,
        executor_outcome=ExecutorOutcome.FAILED,
        verifier=verifier,
    )
    await orch.publish(proposal.id)

    await orch.on_approval(
        ApprovalEvent(
            proposal_id=proposal.id,
            decision=Decision.APPROVED,
            by="i",
            at="t",
        )
    )

    after = store.load(proposal.id)
    assert after.state == ProposalState.EXECUTION_FAILED
    # Verifier should not have been called.
    assert verifier.last_task is None
