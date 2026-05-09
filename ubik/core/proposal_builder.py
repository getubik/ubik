"""
Turn a Researcher audit + finding extracts into Proposals.

The audit gives us a markdown report; ``extract_findings`` (in
``summarize.py``) pulls the ``### N. <title> · <severity>`` blocks
out of it. This module is the bridge from those blocks to
``Proposal`` objects the orchestrator can publish.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from ubik.core.proposal import Proposal
from ubik.core.summarize import FindingExtract


_SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4, "unknown": 0}


def findings_to_proposals(
    findings: Iterable[FindingExtract],
    *,
    project: str,
    repo_path: Path | str,
    base_branch: str = "main",
    min_severity: str = "medium",
) -> list[Proposal]:
    """Lift each in-scope finding into a fresh Proposal.

    ``min_severity`` filters out the long tail. Default 'medium' means
    we don't ping the user about every nit — only the things actually
    worth a tap.
    """
    floor = _SEVERITY_RANK.get(min_severity.lower(), 2)
    out: list[Proposal] = []

    for f in findings:
        if _SEVERITY_RANK.get(f.severity.lower(), 0) < floor:
            continue

        # Body that the user sees on Telegram — keep it short, the
        # full block is preserved on the proposal for the executor.
        summary_parts = []
        if f.why_it_matters:
            summary_parts.append(f.why_it_matters)
        elif f.title:
            summary_parts.append(f.title)
        summary = "\n\n".join(summary_parts).strip()

        proposal = Proposal.new(
            project=project,
            title=f.title,
            severity=f.severity,
            summary=summary,
            plan=f.proposed_fix,
            evidence=f.evidence,
            risk=f.risk,
            eta=f.eta,
            repo_path=str(Path(repo_path).resolve()),
            base_branch=base_branch,
            notes=f.raw_block,
        )
        out.append(proposal)

    return out
