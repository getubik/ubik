"""
Tiny helpers to extract a Telegram-sized digest from a long markdown
audit report. No LLM, just structural parsing — keeps the notify path
deterministic, fast, and free.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(slots=True)
class AuditDigest:
    """A small slice of an audit suitable for a phone notification."""

    title: str
    """First H1 heading of the report, or a fallback."""

    tldr: str
    """The TL;DR section if present, else the first paragraph."""

    finding_count: int
    """How many `### N.` numbered findings the report contains."""

    severities: dict[str, int]
    """Severity histogram across findings: low / medium / high / critical."""

    top_findings: list[str]
    """Up to 3 finding titles, in document order."""


_H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_TLDR_RE = re.compile(
    r"^##\s*TL;DR\s*\n(?P<body>.+?)(?=^##\s|\Z)",
    re.MULTILINE | re.DOTALL | re.IGNORECASE,
)
_FINDING_HEADING_RE = re.compile(
    r"^###\s+(\d+)\.\s+(?P<title>.+?)(?:\s+·\s+(?P<sev>low|medium|high|critical))?\s*$",
    re.MULTILINE | re.IGNORECASE,
)


def digest_audit(markdown: str, *, fallback_title: str = "Audit") -> AuditDigest:
    """Extract a Telegram-friendly digest from an audit report."""
    title_match = _H1_RE.search(markdown)
    title = title_match.group(1).strip() if title_match else fallback_title

    tldr_match = _TLDR_RE.search(markdown)
    if tldr_match:
        tldr = tldr_match.group("body").strip()
    else:
        # First non-empty paragraph after the H1.
        body = markdown.split("\n", 1)[-1] if title_match else markdown
        paras = [p.strip() for p in body.split("\n\n") if p.strip()]
        # Skip trailing-frontmatter / meta-only paragraphs.
        tldr = next((p for p in paras if not p.startswith("#")), "")

    findings: list[str] = []
    severities = {"low": 0, "medium": 0, "high": 0, "critical": 0}
    for m in _FINDING_HEADING_RE.finditer(markdown):
        findings.append(m.group("title").strip())
        sev = (m.group("sev") or "").lower()
        if sev in severities:
            severities[sev] += 1

    return AuditDigest(
        title=title,
        tldr=tldr,
        finding_count=len(findings),
        severities=severities,
        top_findings=findings[:3],
    )


def render_telegram_body(digest: AuditDigest, *, body_url: str | None = None) -> str:
    """Format an AuditDigest as Telegram MarkdownV2-safe body text."""
    lines: list[str] = []

    # TL;DR
    if digest.tldr:
        # Trim TL;DR to ~12 lines max so the message fits a phone screen.
        tldr_lines = digest.tldr.splitlines()
        if len(tldr_lines) > 12:
            tldr_lines = tldr_lines[:12] + ["…"]
        lines.append("\n".join(tldr_lines))

    # Finding count + severity summary
    if digest.finding_count > 0:
        sev_parts = [
            f"{n} {label}"
            for label, n in (
                ("critical", digest.severities["critical"]),
                ("high", digest.severities["high"]),
                ("medium", digest.severities["medium"]),
                ("low", digest.severities["low"]),
            )
            if n > 0
        ]
        sev_str = " · ".join(sev_parts) if sev_parts else "no severity tagged"
        lines.append("")
        lines.append(f"*{digest.finding_count} findings* — {sev_str}")

    # Top findings, plain text bullets
    if digest.top_findings:
        lines.append("")
        for t in digest.top_findings:
            # Use • not '-' so MarkdownV2's '-' escaping rule doesn't fight us
            lines.append(f"• {t}")

    if body_url:
        lines.append("")
        lines.append(f"[full report]({body_url})")

    return "\n".join(lines).strip()
