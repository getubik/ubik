"""
Ubik daemon — the long-running entry point.

Wires every component together and runs two concurrent tasks:

  • Scheduler — fires periodic Researcher passes. Each pass produces an
    audit, the audit's findings become Proposals, the orchestrator
    publishes Proposals via the Bridge.

  • Approval poll — long-polls the Bridge for callback events. Each
    event is dispatched to Orchestrator.on_approval, which moves the
    Proposal through APPROVED → EXECUTION → READY_FOR_PR → PR_OPENED.

The daemon owns no business logic — just orchestration of components
that already exist. `ubik run` calls `Daemon(...).run()`.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

from ubik.adapters.bridge import (
    ApprovalEvent,
    Bridge,
    NotifyMessage,
    Severity,
    bridge_from_config,
)
from ubik.adapters.executor import Executor, executor_from_config
from ubik.adapters.llm import LLMAdapter, llm_from_config
from ubik.adapters.verifier import Verifier, verifier_from_config
from ubik.core.config import UbikConfig
from ubik.core.notebook import Notebook
from ubik.core.orchestrator import Orchestrator, OrchestratorConfig
from ubik.core.proposal import ProposalStore
from ubik.core.proposal_builder import findings_to_proposals
from ubik.core.proposal_counter import DailyProposalCounter
from ubik.core.researcher import run_audit
from ubik.core.scheduler import Scheduler
from ubik.core.summarize import extract_findings

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DaemonConfig:
    """Runtime parameters above and beyond the base UbikConfig."""

    daily_at: str = "09:00"
    """Local-time HH:MM for the daily audit."""

    pulse_minutes: int = 0
    """If > 0, fire a quick pulse audit every N minutes too."""

    audit_max_tokens: int = 8000
    min_proposal_severity: str = "medium"
    """Floor for what makes it to a proposal — 'low' = noisy, 'high' = quiet."""

    approval_poll_offset: str = ""
    """File where we stash the last Telegram update_id between restarts.
    Empty = use platform user-state dir (resolved in __post_init__-style at use site)."""

    dry_run: bool = False
    """If True, the daemon runs the audit + persists proposals + extracts
    findings, but does NOT publish them to the bridge or hand them to the
    executor. Useful for first-time setup ('show me what you'd do')."""


class Daemon:
    """The orchestrator-of-orchestrators. Owns startup, scheduling, and shutdown."""

    def __init__(
        self,
        *,
        config: UbikConfig,
        notebook_root: Path,
        daemon_config: DaemonConfig | None = None,
    ) -> None:
        self.cfg = config
        self.daemon_cfg = daemon_config or DaemonConfig()
        self.notebook_root = notebook_root

        self.notebook = Notebook(notebook_root)
        self.store = ProposalStore(notebook_root)

        # Build LLM (BYOM via litellm_adapter)
        self.llm: LLMAdapter = llm_from_config(self.cfg.llm.to_litellm_dict())

        # Bridge — resolved from cfg.bridge.type via the factory.
        # bridge_from_config falls back to env vars for chat ids when
        # approver_chat_ids is empty in YAML, so the wizard's "fill in
        # later" flow works.
        try:
            self.bridge: Bridge = bridge_from_config(self.cfg)
        except RuntimeError as e:
            raise RuntimeError(
                f"Daemon needs a bridge configured. {e}. "
                "Check ubik.yaml's `bridge` block and the env vars it "
                "names (token_env / chat_id_env)."
            ) from e

        # Executor + Verifier — resolved from config too. Sandbox knobs
        # (worktree dir) come from the executor block; cost/time caps
        # live on ExecutorTask and are wired via OrchestratorConfig below.
        self.executor: Executor = executor_from_config(self.cfg)
        self.verifier: Verifier = verifier_from_config(self.cfg)

        self.orchestrator = Orchestrator(
            store=self.store,
            notebook=self.notebook,
            bridge=self.bridge,
            executor=self.executor,
            verifier=self.verifier,
            config=OrchestratorConfig(
                notebook_root=notebook_root,
                default_test_command=self.cfg.verifier.test_command,
                default_cost_cap_usd=self.cfg.executor.sandbox.cost_cap_usd,
                default_time_cap_seconds=self.cfg.executor.sandbox.time_cap_minutes * 60,
            ),
        )

        # Proposal-per-day counter — file-backed, lives next to proposals.
        self.proposal_counter = DailyProposalCounter(notebook_root)

        self.scheduler = Scheduler()
        self._stop = asyncio.Event()

    # ── public API ──────────────────────────────────────────────────────

    async def run(self) -> None:
        """Block forever — until SIGINT or scheduler stop."""
        await self._announce_start()

        # Schedule the daily audit
        self.scheduler.daily_at(
            self.daemon_cfg.daily_at,
            self._daily_audit_cycle,
            name=f"daily-audit@{self.daemon_cfg.daily_at}",
        )

        if self.daemon_cfg.pulse_minutes > 0:
            self.scheduler.every_minutes(
                self.daemon_cfg.pulse_minutes,
                self._pulse_cycle,
                name=f"pulse-{self.daemon_cfg.pulse_minutes}m",
            )

        approval_offset_path = Path(self.daemon_cfg.approval_poll_offset)
        approval_offset_path.parent.mkdir(parents=True, exist_ok=True)

        scheduler_task = asyncio.create_task(self.scheduler.run(), name="scheduler")
        approval_task = asyncio.create_task(
            self.bridge.poll_approvals(  # type: ignore[attr-defined]
                on_event=self._on_approval_event,
                offset_state_path=approval_offset_path,
            ),
            name="approval-poll",
        )

        try:
            await asyncio.wait(
                {scheduler_task, approval_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            self.scheduler.stop()
            for t in (scheduler_task, approval_task):
                if not t.done():
                    t.cancel()
                    try:
                        await t
                    except (asyncio.CancelledError, Exception):
                        pass
            await self._announce_stop()

    def stop(self) -> None:
        self._stop.set()
        self.scheduler.stop()

    # ── scheduled jobs ──────────────────────────────────────────────────

    async def run_audit_cycle(self) -> None:
        """Public entry point for a single audit cycle."""
        return await self._daily_audit_cycle()

    async def _daily_audit_cycle(self) -> None:
        """One audit pass: snapshot → audit → extract findings → proposals → publish."""
        repo_path = Path(self.cfg.project.repo_path)
        project = self.cfg.project.name or repo_path.name
        logger.info("Daily audit cycle starting · project=%s · path=%s", project, repo_path)

        try:
            result = await run_audit(
                llm=self.llm,
                notebook=self.notebook,
                repo_path=repo_path,
                project_name=project,
                max_tokens=self.daemon_cfg.audit_max_tokens,
            )
        except Exception as e:
            logger.error("Audit run failed: %s", e, exc_info=True)
            await self._post_error("daily-audit", str(e))
            return

        findings = extract_findings(result.markdown)
        proposals = findings_to_proposals(
            findings,
            project=project,
            repo_path=repo_path,
            base_branch=self.cfg.project.default_branch,
            min_severity=self.daemon_cfg.min_proposal_severity,
        )

        logger.info(
            "Audit produced %d findings (%d above %s threshold)",
            len(findings),
            len(proposals),
            self.daemon_cfg.min_proposal_severity,
        )

        # Daily proposal cap — prevent a runaway audit from blasting the
        # operator's Telegram with 50 proposals at once. The counter is
        # filesystem-backed so it survives restarts.
        cap = self.cfg.cost.max_proposals_per_day
        used_today = self.proposal_counter.count_today()
        budget = max(0, cap - used_today)
        if len(proposals) > budget:
            logger.warning(
                "Daily proposal cap reached: %d already published today, "
                "cap=%d, dropping %d of %d new proposals",
                used_today,
                cap,
                len(proposals) - budget,
                len(proposals),
            )
            await self._post_cap_warning(used_today, cap, dropped=len(proposals) - budget)
            proposals = proposals[:budget]

        for p in proposals:
            self.store.save(p)

            if self.daemon_cfg.dry_run:
                logger.info(
                    "[dry-run] Proposal %s saved to disk; bridge.notify and "
                    "orchestrator.publish skipped.",
                    p.id[:8],
                )
                continue

            try:
                await self.orchestrator.publish(p.id)
                self.proposal_counter.increment()
            except Exception as e:
                logger.error("Publish failed for proposal %s: %s", p.id[:8], e, exc_info=True)

    async def _pulse_cycle(self) -> None:
        """Cheap interval check — for now, a no-op placeholder. Sprint 5
        wires anomaly detection here (stream tail, log spike, etc.)."""
        logger.debug("Pulse cycle (no-op for now)")

    async def _on_approval_event(self, event: ApprovalEvent) -> None:
        """Bridge calls this on every callback. Forward to Orchestrator."""
        try:
            await self.orchestrator.on_approval(event)
        except Exception as e:
            logger.error(
                "Orchestrator.on_approval crashed for proposal %s: %s",
                event.proposal_id[:8],
                e,
                exc_info=True,
            )

    # ── lifecycle pings ─────────────────────────────────────────────────

    async def _announce_start(self) -> None:
        """Tell the user the daemon woke up — short, decorative."""
        try:
            await self.bridge.notify(
                NotifyMessage(
                    title=f"Ubik · daemon awake · {self.cfg.project.name or 'unknown'}",
                    body_markdown=(
                        f"Daily audit at **{self.daemon_cfg.daily_at}** local time.\n"
                        f"Pulse: **{self.daemon_cfg.pulse_minutes} min**"
                        if self.daemon_cfg.pulse_minutes
                        else f"Daily audit at **{self.daemon_cfg.daily_at}** local time."
                    ),
                    footer=f"watching {self.cfg.project.repo_path}",
                    severity=Severity.LOW,
                    tags=["daemon", "lifecycle"],
                )
            )
        except Exception:
            pass  # bridge errors must not stop the daemon

    async def _announce_stop(self) -> None:
        try:
            await self.bridge.notify(
                NotifyMessage(
                    title=f"Ubik · daemon stopped · {self.cfg.project.name or 'unknown'}",
                    body_markdown="Pssst. I'm going quiet for now.",
                    severity=Severity.LOW,
                    tags=["daemon", "lifecycle"],
                )
            )
        except Exception:
            pass

    async def _post_cap_warning(self, used: int, cap: int, *, dropped: int) -> None:
        """One-line nudge when the daily proposal cap kicks in."""
        if self.daemon_cfg.dry_run:
            return
        try:
            await self.bridge.notify(
                NotifyMessage(
                    title=f"Ubik · daily proposal cap reached · {self.cfg.project.name or 'unknown'}",
                    body_markdown=(
                        f"Already published **{used}** today (cap **{cap}**). "
                        f"Dropped **{dropped}** new proposals from this cycle. "
                        "Raise `cost.max_proposals_per_day` in `ubik.yaml` to lift."
                    ),
                    severity=Severity.MEDIUM,
                    tags=["daemon", "cost-cap"],
                )
            )
        except Exception:
            pass

    async def _post_error(self, where: str, msg: str) -> None:
        try:
            await self.bridge.notify(
                NotifyMessage(
                    title=f"Ubik · {where} crashed",
                    body_markdown=f"```\n{msg[:1500]}\n```",
                    severity=Severity.HIGH,
                    tags=["daemon", "error"],
                )
            )
        except Exception:
            pass
