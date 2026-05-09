"""
Bridge adapter base — how Ubik whispers and waits.

A Bridge is the channel between Ubik and the human approver:
Telegram, Slack, Discord, email, webhook, MCP-Apps, or anything
custom. Each bridge implements the same minimal contract so the
orchestrator never knows where the user actually is.

Sprint 2 ships only the **notify** half of the contract — fire-and-
forget message delivery for `ubik audit --notify`. The **propose**
half (inline-keyboard approval, callbacks, decision capture) lands
when the executor wires up.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol


class Severity(str, Enum):
    """Proposal urgency. Mirrors the audit severities."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Decision(str, Enum):
    """The approver's reply on a proposal."""
    APPROVED = "approved"
    REJECTED = "rejected"
    REFINE = "refine"          # send back with comment
    PENDING = "pending"        # not yet answered


@dataclass(slots=True)
class NotifyMessage:
    """A one-shot notification — no reply expected."""

    title: str
    """Bold header line on the message."""

    body_markdown: str
    """Body. Bridges may downgrade if the channel doesn't render markdown."""

    footer: str | None = None
    """Optional small-print line (e.g. "from `ubik audit ./repo`")."""

    severity: Severity = Severity.LOW
    """Drives icon / color choice in bridges that support it."""

    tags: list[str] = field(default_factory=list)


class Bridge(Protocol):
    """The minimal contract a bridge implementation must satisfy."""

    name: str
    """Short identifier, e.g. 'telegram', 'slack'."""

    async def notify(self, message: NotifyMessage) -> None:
        """Push a one-shot message. No reply path needed."""
        ...
