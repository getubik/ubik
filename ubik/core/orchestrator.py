"""
Orchestrator — wires Researcher, Bridge, Executor, and Verifier together.

This is the glue that makes Ubik *autonomous*. The flow:

    1. (Externally) Researcher emits Proposal → ProposalStore.save(state=DRAFT)
    2. orchestrator.publish(proposal_id) → bridge.propose() → state=PENDING
    3. orchestrator.run_approval_loop() — long-poll bridge for taps
    4. on_event(approval) →
         - APPROVED  → state=APPROVED → execute(proposal_id)
         - REJECTED  → state=REJECTED → bridge.edit_message("rejected")
         - PENDING   → 'diff' tap, no state change, send full diff
    5. execute() → executor.run() →
         - SUCCESS   → state=READY_FOR_PR → (verifier picks up next sprint)
         - else      → state=EXECUTION_FAILED

State machine is intentionally rigid; bad transitions raise. The
orchestrator owns no LLM calls — everything LLM-side lives in
researcher / executor.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from ubik.adapters.bridge import (
    ApprovalEvent,
    Bridge,
    Decision,
    ProposalMessage,
    Severity,
)
from ubik.adapters.executor import ExecutionResult, Executor, ExecutorOutcome, ExecutorTask
from ubik.adapters.verifier import Verifier, VerifyOutcome, VerifyTask
from ubik.core.notebook import Notebook
from ubik.core.proposal import Proposal, ProposalState, ProposalStore

logger = logging.getLogger(__name__)


# ── Severity wiring ──────────────────────────────────────────────────────


_SEV_MAP = {
    "low": Severity.LOW,
    "medium": Severity.MEDIUM,
    "high": Severity.HIGH,
    "critical": Severity.CRITICAL,
}


def _to_severity(s: str) -> Severity:
    return _SEV_MAP.get((s or "").lower(), Severity.MEDIUM)


# ── Orchestrator ─────────────────────────────────────────────────────────


@dataclass(slots=True)
class OrchestratorConfig:
    """Knobs that change orchestrator behavior at runtime."""

    notebook_root: Path
    """Where ProposalStore + Notebook live (already initialized)."""

    # State machine guards
    auto_publish_drafts: bool = True
    """When True, publish() will accept DRAFT proposals (typical).
    Set False if a separate process emits & a different one publishes."""

    # Per-task executor defaults (cherry-picked from ExecutorTask). Daemon
    # fills these from ubik.yaml (executor.sandbox + verifier.test_command).
    # Without this hook the orchestrator handed the executor a hard-coded
    # 5USD/15min budget and no test command — regardless of config.
    default_test_command: str | None = None
    default_cost_cap_usd: float = 5.0
    default_time_cap_seconds: int = 900


class Orchestrator:
    """The conductor. Owns no LLM, owns the proposal lifecycle."""

    def __init__(
        self,
        *,
        store: ProposalStore,
        notebook: Notebook,
        bridge: Bridge,
        executor: Executor,
        verifier: Verifier | None = None,
        config: OrchestratorConfig | None = None,
    ) -> None:
        self.store = store
        self.notebook = notebook
        self.bridge = bridge
        self.executor = executor
        self.verifier = verifier
        self.config = config or OrchestratorConfig(notebook_root=notebook.root)

    # ── publish: proposal → bridge ──────────────────────────────────────

    async def publish(self, proposal_id: str) -> None:
        """Push a proposal to the human for approval."""
        proposal = self.store.load(proposal_id)

        if proposal.state == ProposalState.DRAFT and not self.config.auto_publish_drafts:
            raise RuntimeError(
                "auto_publish_drafts=False but proposal is still DRAFT — "
                "promote it first or flip the flag"
            )

        if proposal.state not in (ProposalState.DRAFT, ProposalState.PENDING):
            raise RuntimeError(
                f"refusing to publish from state {proposal.state.value} "
                f"(only DRAFT or PENDING are valid)"
            )

        body = self._render_proposal_body(proposal)
        msg = ProposalMessage(
            proposal_id=proposal.id,
            title=f"Ubik · {proposal.project} · {proposal.title}",
            body_markdown=body,
            footer=f"id: {proposal.id[:8]}",
            severity=_to_severity(proposal.severity),
            tags=["proposal", proposal.severity],
        )

        refs = await self.bridge.propose(msg)
        proposal.bridge_refs = refs
        proposal.state = ProposalState.PENDING
        self.store.save(proposal)
        logger.info("Proposal %s published → bridge refs %s", proposal.id[:8], refs)

    # ── inbound: human approval ─────────────────────────────────────────

    async def on_approval(self, event: ApprovalEvent) -> None:
        """Receive a tap from the bridge. Dispatch by decision."""
        try:
            proposal = self.store.load(event.proposal_id)
        except KeyError:
            logger.warning("Approval for unknown proposal %s — ignored", event.proposal_id)
            return

        # Idempotency — if the user double-taps, refuse the second.
        if proposal.state not in (ProposalState.PENDING, ProposalState.REFINING):
            logger.info(
                "Approval for proposal %s ignored (state=%s)",
                proposal.id[:8],
                proposal.state.value,
            )
            return

        if event.decision == Decision.APPROVED:
            await self._handle_approved(proposal, event)
        elif event.decision == Decision.REJECTED:
            await self._handle_rejected(proposal, event)
        elif event.decision == Decision.REFINE:
            # Stub for now — researcher needs to be re-invoked with the
            # user's note. Sprint 3.
            proposal.state = ProposalState.REFINING
            proposal.notes = (proposal.notes + "\n\n" + event.note).strip()
            self.store.save(proposal)
            logger.info("Proposal %s marked REFINING (refine flow not wired yet)", proposal.id[:8])
        elif event.decision == Decision.PENDING:
            # 'diff' tap — show more, don't change state.
            await self._handle_diff_request(proposal, event)
        else:
            logger.warning("Unknown decision %s on proposal %s", event.decision, proposal.id[:8])

    # ── execute: approved proposal → branch ──────────────────────────────

    async def execute(self, proposal_id: str) -> ExecutionResult:
        """Run the executor against an APPROVED proposal."""
        proposal = self.store.load(proposal_id)
        if proposal.state != ProposalState.APPROVED:
            raise RuntimeError(
                f"refusing to execute from state {proposal.state.value} (must be APPROVED first)"
            )

        proposal.state = ProposalState.EXECUTION_RUNNING
        self.store.save(proposal)

        task = ExecutorTask(
            proposal_id=proposal.id,
            repo_path=Path(proposal.repo_path),
            base_branch=proposal.base_branch,
            target_branch=f"auto/{proposal.id[:8]}",
            title=proposal.title,
            description=proposal.summary,
            plan=proposal.plan,
            test_command=self.config.default_test_command,
            cost_cap_usd=self.config.default_cost_cap_usd,
            time_cap_seconds=self.config.default_time_cap_seconds,
        )

        logger.info("Executing proposal %s via %s", proposal.id[:8], self.executor.name)
        result = await self.executor.run(task)

        # Mirror executor result back onto the proposal.
        proposal.branch = result.branch
        proposal.head_sha = result.head_sha
        proposal.files_changed = result.files_changed
        proposal.notes = (proposal.notes + "\n\n" + (result.notes or "")).strip()

        if result.outcome == ExecutorOutcome.SUCCESS:
            # Empty-diff guard: Aider sometimes describes a change in its
            # output ("here's what I'd add") without committing it (seen
            # on proposal 2d06e19e — pyproject.toml ceiling pin). Without
            # this check the state machine moves to READY_FOR_PR, the
            # verifier pushes the empty branch, GitHub returns 422 with
            # "No commits between main and auto/<id>" and the PR never
            # opens. Treat zero file changes as a failed execution so
            # the operator gets a real error instead of a silently-stuck
            # proposal.
            if not result.files_changed:
                proposal.state = ProposalState.EXECUTION_FAILED
                proposal.notes = (
                    (proposal.notes or "") + "\n\nDetected zero file changes after Aider session. "
                    "Most likely the model described the change without "
                    "committing it. Re-run after tightening the prompt or "
                    "re-pinning Aider's --auto-commits behaviour."
                ).strip()
            else:
                proposal.state = ProposalState.READY_FOR_PR
        else:
            proposal.state = ProposalState.EXECUTION_FAILED

        self.store.save(proposal)

        # Decide whether the verifier will run next. When it will, the
        # "branch ready" intermediate notify is redundant — the user
        # gets a single "PR ready" (or "PR failed") message instead.
        # Eliminates the double-ping double-vibration UX problem.
        will_open_pr = (
            result.outcome == ExecutorOutcome.SUCCESS
            and result.files_changed
            and self.verifier is not None
            and result.branch
        )

        if not will_open_pr:
            # Only ping the bridge directly when no PR-open step is coming.
            try:
                await self._post_execution_summary(proposal, result)
            except Exception as e:  # never block on bridge errors
                logger.warning("Post-execution bridge update failed: %s", e)
        else:
            try:
                await self._open_pr(proposal, result)
            except Exception as e:
                logger.error("Verifier crashed: %s", e, exc_info=True)
                proposal.notes = (proposal.notes + f"\n\nVerifier crashed: {e}").strip()
                self.store.save(proposal)
                # Verifier blew up — fall back to a regular execution
                # summary so the user still hears about the success.
                try:
                    await self._post_execution_summary(proposal, result)
                except Exception:
                    pass

        return result

    async def _open_pr(self, proposal: Proposal, result: ExecutionResult) -> None:
        """Push the executor's branch and open a PR."""
        from pathlib import Path

        # Worktree path is determined by the executor adapter's convention.
        # AiderExecutor uses <worktree_root>/<branch-slug>/ relative to the
        # repo's parent. Fall back to a best-guess if the executor didn't
        # surface the path.
        repo_path = Path(proposal.repo_path)
        branch_slug = (result.branch or "").replace("/", "-")
        worktree_path = (repo_path.parent / ".ubik-worktrees" / branch_slug).resolve()

        verify_task = VerifyTask(
            proposal_id=proposal.id,
            repo_path=repo_path,
            worktree_path=worktree_path,
            branch=result.branch or "",
            base_branch=proposal.base_branch,
            title=f"Ubik · {proposal.title}",
            body=self._render_pr_body(proposal, result),
        )

        verify_result = await self.verifier.verify(verify_task)

        if verify_result.outcome == VerifyOutcome.OPENED:
            proposal.state = ProposalState.PR_OPENED
            proposal.pr_url = verify_result.pr_url
            proposal.notes = (
                proposal.notes + f"\n\nPR opened: {verify_result.pr_url} ({verify_result.notes})"
            ).strip()
        else:
            proposal.notes = (
                proposal.notes
                + f"\n\nVerifier {verify_result.outcome.value}: {verify_result.notes}"
            ).strip()

        self.store.save(proposal)

        # Bridge ping with the PR link.
        try:
            await self._post_verify_summary(proposal, verify_result)
        except Exception as e:
            logger.warning("Post-verify bridge update failed: %s", e)

    def _render_pr_body(self, p: Proposal, r: ExecutionResult) -> str:
        """Markdown for the PR description."""
        parts = [
            f"## Proposal\n\n{p.summary}\n",
            f"## Plan\n\n{p.plan}\n",
        ]
        if p.evidence:
            parts.append("## Evidence\n\n" + "\n".join(f"- {e}" for e in p.evidence))
        parts.append("\n---\n")
        parts.append(
            f"_Auto-generated by [Ubik](https://psssst.dev) · proposal "
            f"`{p.id[:8]}` · severity `{p.severity}` · executor `{self.executor.name}`_"
        )
        if r.diff_summary:
            parts.append(f"_Diff_: `{r.diff_summary.strip()}`")
        if r.test_passed is not None:
            parts.append(f"_Tests_: {'✅ passed' if r.test_passed else '⚠️ skipped/failed'}")
        return "\n".join(parts)

    async def _post_verify_summary(self, proposal: Proposal, result) -> None:
        """Tell the user the PR is up (or why it wasn't)."""
        from ubik.adapters.bridge import NotifyMessage

        if result.outcome == VerifyOutcome.OPENED:
            body = (
                f"**PR opened** for proposal `{proposal.id[:8]}`\n\n"
                f"Branch: `{result.branch}` → `{proposal.base_branch}`\n"
                f"Link: {result.pr_url}\n\n"
                "Review the diff. Tap merge in GitHub when ready."
            )
            sev = Severity.MEDIUM
            title = f"Ubik · PR ready · {proposal.title}"
        else:
            body = f"**{result.outcome.value}**\n\n" + (result.notes[:1500] or "no verifier output")
            sev = Severity.HIGH
            title = f"Ubik · PR failed · {proposal.title}"

        await self.bridge.notify(
            NotifyMessage(
                title=title,
                body_markdown=body,
                footer=f"id: {proposal.id[:8]}",
                severity=sev,
                tags=["verify", proposal.severity],
            )
        )

    # ── helpers ─────────────────────────────────────────────────────────

    def _render_proposal_body(self, p: Proposal) -> str:
        """Format a Proposal for the bridge's body slot."""
        lines: list[str] = []
        if p.summary:
            lines.append(p.summary.strip())
        if p.evidence:
            lines.append("")
            lines.append("**Evidence**")
            lines.extend(f"• {e}" for e in p.evidence[:5])
            extra = len(p.evidence) - 5
            if extra > 0:
                lines.append(f"_…and {extra} more — tap 👁 Diff for the full list_")
        if p.plan:
            lines.append("")
            lines.append("**Plan**")
            lines.append(p.plan.strip())
        if p.risk:
            lines.append("")
            lines.append(f"**Risk** {p.risk}    **ETA** {p.eta or '—'}")
        return "\n".join(lines)

    async def _handle_approved(self, proposal: Proposal, event: ApprovalEvent) -> None:
        proposal.state = ProposalState.APPROVED
        proposal.notes = (proposal.notes + f"\n\nApproved by {event.by} at {event.at}").strip()
        self.store.save(proposal)
        await self._lock_bridge_message(proposal, suffix="\n\n✅ <i>Approved — Ubik is on it.</i>")

        # Fire-and-forget execute. Caller (the daemon loop) will await
        # this via asyncio.create_task; here we just hand off.
        try:
            await self.execute(proposal.id)
        except Exception as e:
            logger.error("Execute failed for proposal %s: %s", proposal.id[:8], e, exc_info=True)
            proposal.state = ProposalState.EXECUTION_FAILED
            proposal.notes = (proposal.notes + f"\n\nExecutor crashed: {e}").strip()
            self.store.save(proposal)

    async def _handle_rejected(self, proposal: Proposal, event: ApprovalEvent) -> None:
        proposal.state = ProposalState.REJECTED
        proposal.notes = (proposal.notes + f"\n\nRejected by {event.by} at {event.at}").strip()
        self.store.save(proposal)
        await self._lock_bridge_message(proposal, suffix="\n\n❌ <i>Rejected.</i>")

    async def _handle_diff_request(self, proposal: Proposal, event: ApprovalEvent) -> None:
        # Today the proposal body already carries the plan + evidence;
        # we just re-send it as a notify (no buttons) so the user sees
        # the full text expanded. Real diff viewing comes after the
        # executor runs, in Sprint 2.3b/p6.
        from ubik.adapters.bridge import NotifyMessage

        nm = NotifyMessage(
            title=f"Ubik · {proposal.project} · diff (pre-execution)",
            body_markdown=self._render_proposal_body(proposal),
            footer=f"id: {proposal.id[:8]}",
            severity=_to_severity(proposal.severity),
        )
        try:
            await self.bridge.notify(nm)
        except Exception as e:
            logger.warning("Diff notify failed: %s", e)

    async def _lock_bridge_message(self, proposal: Proposal, *, suffix: str) -> None:
        """Edit the original proposal message to remove buttons + add status."""
        refs = proposal.bridge_refs or {}
        chat_id = refs.get("chat_id")
        message_id = refs.get("message_id")
        if not (chat_id and message_id):
            return

        body = self._render_proposal_body(proposal) + suffix
        if hasattr(self.bridge, "edit_message"):
            try:
                await self.bridge.edit_message(chat_id, message_id, body)
            except Exception as e:
                logger.warning("edit_message failed: %s", e)

    async def _post_execution_summary(self, proposal: Proposal, result: ExecutionResult) -> None:
        """Tell the user how the executor went."""
        from ubik.adapters.bridge import NotifyMessage

        if result.outcome == ExecutorOutcome.SUCCESS:
            title = f"Ubik · branch ready · {proposal.title}"
            body = (
                f"**{result.outcome.value}** in {result.duration_seconds:.0f}s\n"
                f"Branch: `{result.branch}`\n"
                f"Files: {len(result.files_changed)} touched\n"
                f"`{result.diff_summary}`\n\n"
                f"Tests: {'✅ passed' if result.test_passed else '— skipped/failed'}"
            )
            sev = Severity.MEDIUM
        else:
            title = f"Ubik · execution failed · {proposal.title}"
            body = f"**{result.outcome.value}** after {result.duration_seconds:.0f}s\n\n" + (
                result.notes[:1500] or "no executor output"
            )
            sev = Severity.HIGH

        await self.bridge.notify(
            NotifyMessage(
                title=title,
                body_markdown=body,
                footer=f"id: {proposal.id[:8]}",
                severity=sev,
                tags=["execution", proposal.severity],
            )
        )
