"""
Proposal — the unit Ubik whispers to the human.

Lifecycle:

    [DRAFT]  researcher emits proposal (severity, plan, evidence)
        │
        ▼
    [PENDING]  bridge has pushed the message; waiting for callback
        │
        ├─→ user taps ❌  → [REJECTED]
        ├─→ user taps 📝  → [REFINING]  → researcher iterates → [PENDING]
        └─→ user taps ✅  → [APPROVED]
                              │
                              ▼
                       executor runs
                              │
                              ├─ outcome=SUCCESS → [READY_FOR_PR]
                              └─ otherwise       → [EXECUTION_FAILED]
                                                     │
                                                     └─→ [REJECTED] (final)

Persistence is keyed by `proposal_id` (UUID4). Filesystem-backed today;
Postgres later when multi-tenant kicks in.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path


class ProposalState(str, Enum):
    DRAFT = "draft"
    PENDING = "pending"  # Telegram message sent, awaiting tap
    APPROVED = "approved"  # User said yes, executor not started yet
    REFINING = "refining"  # User asked for revision
    EXECUTION_RUNNING = "execution_running"
    READY_FOR_PR = "ready_for_pr"  # Executor green, awaiting verifier
    PR_OPENED = "pr_opened"  # Verifier created the PR; awaiting merge
    DONE = "done"  # Merged, deployed, smoke-checked
    REJECTED = "rejected"  # User declined or executor failed
    EXECUTION_FAILED = "execution_failed"


@dataclass(slots=True)
class Proposal:
    """A single improvement Ubik wants to make."""

    id: str
    project: str
    title: str
    severity: str  # low | medium | high | critical
    summary: str
    plan: str
    evidence: list[str] = field(default_factory=list)
    risk: str = ""
    eta: str = ""
    repo_path: str = ""
    base_branch: str = "main"

    state: ProposalState = ProposalState.DRAFT
    created_at: str = ""
    updated_at: str = ""

    # Bridge-side pointers (e.g. Telegram message_id) — adapter-specific.
    bridge_refs: dict[str, str] = field(default_factory=dict)

    # Set once executor produces a branch.
    branch: str | None = None
    head_sha: str | None = None
    files_changed: list[str] = field(default_factory=list)

    # Set once verifier opens a PR.
    pr_url: str | None = None

    notes: str = ""

    @classmethod
    def new(cls, **kwargs) -> Proposal:
        """Create a draft proposal with a fresh UUID + timestamp."""
        now = datetime.now(timezone.utc).isoformat()
        return cls(
            id=str(uuid.uuid4()),
            created_at=now,
            updated_at=now,
            **kwargs,
        )

    def touch(self) -> None:
        """Bump updated_at."""
        self.updated_at = datetime.now(timezone.utc).isoformat()


# ── Persistence ──────────────────────────────────────────────────────────


class ProposalStore:
    """Filesystem-backed proposal store.

    Layout:
        <root>/proposals/<id>.json     ← per-proposal state
        <root>/proposals/index.json    ← flat list of all IDs + states

    Atomic enough for single-writer use (the Ubik daemon). Postgres
    backend slots in behind the same interface in Sprint 4.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root) / "proposals"
        self.root.mkdir(parents=True, exist_ok=True)

    # ── public API ──────────────────────────────────────────────────────

    def save(self, proposal: Proposal) -> None:
        proposal.touch()
        path = self.root / f"{proposal.id}.json"
        path.write_text(
            json.dumps(asdict_proposal(proposal), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._update_index(proposal)

    def load(self, proposal_id: str) -> Proposal:
        path = self.root / f"{proposal_id}.json"
        if not path.exists():
            raise KeyError(f"no proposal with id {proposal_id!r}")
        data = json.loads(path.read_text(encoding="utf-8"))
        return _proposal_from_dict(data)

    def by_state(self, state: ProposalState) -> list[Proposal]:
        index = self._load_index()
        ids = [item["id"] for item in index if item.get("state") == state.value]
        return [self.load(pid) for pid in ids]

    def all_ids(self) -> list[str]:
        return [item["id"] for item in self._load_index()]

    # ── internals ───────────────────────────────────────────────────────

    @property
    def _index_path(self) -> Path:
        return self.root / "index.json"

    def _load_index(self) -> list[dict]:
        if not self._index_path.exists():
            return []
        try:
            return json.loads(self._index_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

    def _update_index(self, proposal: Proposal) -> None:
        index = self._load_index()
        for item in index:
            if item.get("id") == proposal.id:
                item["state"] = proposal.state.value
                item["title"] = proposal.title
                item["severity"] = proposal.severity
                item["updated_at"] = proposal.updated_at
                break
        else:
            index.append(
                {
                    "id": proposal.id,
                    "title": proposal.title,
                    "severity": proposal.severity,
                    "state": proposal.state.value,
                    "created_at": proposal.created_at,
                    "updated_at": proposal.updated_at,
                }
            )
        self._index_path.write_text(
            json.dumps(index, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def asdict_proposal(p: Proposal) -> dict:
    """asdict() with the enum unwrapped to its value (for JSON)."""
    d = asdict(p)
    d["state"] = p.state.value
    return d


def _proposal_from_dict(data: dict) -> Proposal:
    """Inverse of asdict_proposal — restores the enum."""
    state_val = data.get("state", ProposalState.DRAFT.value)
    return Proposal(
        id=data["id"],
        project=data["project"],
        title=data["title"],
        severity=data["severity"],
        summary=data.get("summary", ""),
        plan=data.get("plan", ""),
        evidence=data.get("evidence", []),
        risk=data.get("risk", ""),
        eta=data.get("eta", ""),
        repo_path=data.get("repo_path", ""),
        base_branch=data.get("base_branch", "main"),
        state=ProposalState(state_val),
        created_at=data.get("created_at", ""),
        updated_at=data.get("updated_at", ""),
        bridge_refs=data.get("bridge_refs", {}),
        branch=data.get("branch"),
        head_sha=data.get("head_sha"),
        files_changed=data.get("files_changed", []),
        pr_url=data.get("pr_url"),
        notes=data.get("notes", ""),
    )
