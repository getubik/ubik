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
from typing import Any

from ubik.adapters.bridge import (
    ApprovalEvent,
    Bridge,
    NotifyMessage,
    Severity,
    telegram_from_env,
)
from ubik.adapters.executor import AiderConfig, AiderExecutor, Executor
from ubik.adapters.llm import LLMAdapter, llm_from_config
from ubik.adapters.verifier import GitHubVerifier, Verifier
from ubik.core.config import UbikConfig
from ubik.core.notebook import Notebook
from ubik.core.orchestrator import Orchestrator
from ubik.core.proposal import ProposalStore
from ubik.core.proposal_builder import findings_to_proposals
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

    approval_poll_offset: str = "/var/lib/ubik/poll-offset"
    """File where we stash the last Telegram update_id between restarts."""


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

        # Bridge — Telegram from env (Slack/Discord adapters land later)
        try:
            self.bridge: Bridge = telegram_from_env()
        except RuntimeError as e:
            raise RuntimeError(
                f"Daemon needs a bridge configured. {e}. "
                "Set TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID, or extend the daemon "
                "to a different adapter."
            ) from e

        # Executor — Aider by default
        self.executor: Executor = AiderExecutor(
            AiderConfig(
                base_url=self.cfg.llm.base_url or "https://api.z.ai/api/coding/paas/v4",
                api_key_env=self.cfg.llm.api_key_env,
                model=f"openai/{self.cfg.llm.model}",
            )
        )

        # Verifier — GitHub. Optional; missing token just means PRs won't open
        # automatically and the daemon stops at READY_FOR_PR (you push manually).
        self.verifier: Verifier = GitHubVerifier()

        self.orchestrator = Orchestrator(
            store=self.store,
            notebook=self.notebook,
            bridge=self.bridge,
            executor=self.executor,
            verifier=self.verifier,
        )

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
            len(findings), len(proposals), self.daemon_cfg.min_proposal_severity,
        )

        for p in proposals:
            self.store.save(p)
            try:
                await self.orchestrator.publish(p.id)
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
                event.proposal_id[:8], e, exc_info=True,
            )

    # ── lifecycle pings ─────────────────────────────────────────────────

    async def _announce_start(self) -> None:
        """Tell the user the daemon woke up — short, decorative."""
        try:
            await self.bridge.notify(NotifyMessage(
                title=f"Ubik · daemon awake · {self.cfg.project.name or 'unknown'}",
                body_markdown=(
                    f"Daily audit at **{self.daemon_cfg.daily_at}** local time.\n"
                    f"Pulse: **{self.daemon_cfg.pulse_minutes} min**" if self.daemon_cfg.pulse_minutes
                    else f"Daily audit at **{self.daemon_cfg.daily_at}** local time."
                ),
                footer=f"watching {self.cfg.project.repo_path}",
                severity=Severity.LOW,
                tags=["daemon", "lifecycle"],
            ))
        except Exception:
            pass  # bridge errors must not stop the daemon

    async def _announce_stop(self) -> None:
        try:
            await self.bridge.notify(NotifyMessage(
                title=f"Ubik · daemon stopped · {self.cfg.project.name or 'unknown'}",
                body_markdown="Pssst. I'm going quiet for now.",
                severity=Severity.LOW,
                tags=["daemon", "lifecycle"],
            ))
        except Exception:
            pass

    async def _post_error(self, where: str, msg: str) -> None:
        try:
            await self.bridge.notify(NotifyMessage(
                title=f"Ubik · {where} crashed",
                body_markdown=f"```\n{msg[:1500]}\n```",
                severity=Severity.HIGH,
                tags=["daemon", "error"],
            ))
        except Exception:
            pass
