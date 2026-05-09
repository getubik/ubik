"""
Tiny helpers to extract a Telegram-sized digest from a long markdown
audit report. No LLM, just structural parsing — keeps the notify path
deterministic, fast, and free.

Two extractors live here:

  • ``digest_audit``      — squeeze the audit into a phone-sized blurb
                             (TL;DR + finding count + top 3 titles)
  • ``extract_findings``  — pull each ``### N. <title> · <severity>``
                             block out as a FindingExtract for the
                             daemon to turn into Proposals
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


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


@dataclass(slots=True)
class FindingExtract:
    """One numbered finding pulled out of an audit report."""

    number: int
    title: str
    severity: str
    """low | medium | high | critical | unknown"""

    evidence: list[str] = field(default_factory=list)
    why_it_matters: str = ""
    proposed_fix: str = ""
    risk: str = ""
    eta: str = ""

    raw_block: str = ""
    """The full markdown block, preserved for debugging / proposal body."""


# Section labels we recognize inside a finding block. All optional —
# missing fields just stay empty.
_FINDING_BLOCK_RE = re.compile(
    r"^###\s+(?P<num>\d+)\.\s+(?P<title>.+?)"
    r"(?:\s+·\s+(?P<sev>low|medium|high|critical))?\s*$",
    re.MULTILINE | re.IGNORECASE,
)
_LABEL_RE = re.compile(
    r"\*\*(?P<label>Evidence|Why it matters|Proposed fix|Risk|ETA)\*\*:?\s*"
    r"(?P<body>.*?)(?=\*\*(?:Evidence|Why it matters|Proposed fix|Risk|ETA)\*\*|$)",
    re.IGNORECASE | re.DOTALL,
)


def extract_findings(markdown: str) -> list[FindingExtract]:
    """Pull every ``### N. <title> · <sev>`` block out of an audit report.

    Robust to the optional fields being missing or rearranged. Stops the
    block at the next H3 (next finding) or H2 (section change). Returns
    findings in document order.
    """
    findings: list[FindingExtract] = []

    # Collect all match positions so we can slice the block bodies.
    matches = list(_FINDING_BLOCK_RE.finditer(markdown))
    for i, m in enumerate(matches):
        block_start = m.end()
        # Stop at the next finding heading OR the next H2 section.
        block_end = len(markdown)
        if i + 1 < len(matches):
            block_end = matches[i + 1].start()
        # Or the next H2 (## ...) — for the "What looks healthy" section.
        h2_match = re.search(r"^##\s+", markdown[block_start:block_end], re.MULTILINE)
        if h2_match:
            block_end = block_start + h2_match.start()

        body = markdown[block_start:block_end].strip()

        finding = FindingExtract(
            number=int(m.group("num")),
            title=m.group("title").strip(),
            severity=(m.group("sev") or "unknown").lower(),
            raw_block=body,
        )

        # Walk the labels inside the block.
        for lm in _LABEL_RE.finditer(body):
            label = lm.group("label").lower()
            text = lm.group("body").strip().rstrip("*").rstrip()
            if label == "evidence":
                # Evidence often spans multiple lines / bullets — split on newlines.
                finding.evidence = [
                    line.lstrip("•- ").strip()
                    for line in text.splitlines()
                    if line.strip() and not line.strip().startswith("**")
                ]
            elif label == "why it matters":
                finding.why_it_matters = text
            elif label == "proposed fix":
                finding.proposed_fix = text
            elif label == "risk":
                # Strip trailing "(.|—|...) ETA stuff" if author crammed onto one line.
                finding.risk = text.split("\n", 1)[0].strip().rstrip(".")
            elif label == "eta":
                finding.eta = text.split("\n", 1)[0].strip().rstrip(".")

        findings.append(finding)

    return findings


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
