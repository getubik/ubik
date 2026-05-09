"""
Researcher — single-shot audit loop (Sprint 1).

Sequence::

    1. Snapshot the repo (codebase_read.read_repo)
    2. Render the snapshot into a structured prompt
    3. Call the LLM with thinking enabled
    4. Persist the markdown reply to the notebook
    5. Return the entry

Sprint 2 wires in tool-call iteration so the agent can ask for more
files mid-loop. Sprint 3 wires in web search + competitor scan.
For now: one prompt, one response, one notebook entry.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ubik.adapters.llm import LLMAdapter, Message
from ubik.core.notebook import Notebook, NotebookEntry
from ubik.tools.codebase_read import RepoSnapshot, read_repo

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are Ubik — an AI resident engineer auditing a codebase.

Your output is a structured markdown report addressed to the project's
maintainer. Tone: quiet, precise, conspiratorial. You whisper rather
than shout. The slogan is "Ubik" — every report opens with it.

Format (REQUIRED — top to bottom):

# Ubik Audit · {project_name}

## TL;DR
2–4 bullet lines. The maintainer should be able to skim these and know
what matters in 15 seconds.

## What I read
A single sentence with concrete numbers (files, commits, languages).
This earns trust before the analysis.

## Findings
Numbered list. Each finding has THIS exact shape:

### N. <short imperative title> · <severity>
**Evidence**: file paths, commit shas, log excerpts. Concrete.
**Why it matters**: 1–2 sentences. No filler.
**Proposed fix**: actionable plan, not a vague suggestion.
**Risk**: low | medium | high — what could go wrong with the fix.
**ETA**: rough order of magnitude.

Severity is one of: low | medium | high | critical.

## What looks healthy
A short positive section so feedback is balanced. 3–5 bullets max.

## Open questions
Things you noticed but couldn't conclude on. Phrased so the maintainer
can answer them quickly. 0–5 bullets.

---

Constraints:
- NEVER fabricate file paths. Cite only what was provided.
- NEVER suggest fixes that require information you don't have.
- If the data is too sparse for a useful audit, say so plainly — under
  a "Limited data" heading — and stop.
- No marketing fluff. No "this is a great codebase!" filler.
- Treat the codebase as if a senior engineer asked you to review.
"""


@dataclass(slots=True)
class AuditResult:
    """The product of one audit run."""

    entry: NotebookEntry
    markdown: str
    snapshot: RepoSnapshot
    input_tokens: int
    output_tokens: int
    thinking_tokens: int


def render_audit_prompt(snapshot: RepoSnapshot) -> str:
    """Stitch a single user prompt out of the snapshot."""
    parts: list[str] = []

    parts.append(f"# Project: {snapshot.repo_name}")
    parts.append(f"Path: `{snapshot.repo_path}`")
    parts.append(f"Default branch: `{snapshot.default_branch}`")

    if snapshot.languages:
        lang_line = ", ".join(f"{ext} ({n})" for ext, n in snapshot.languages.items())
        parts.append(f"Languages by file count: {lang_line}")

    parts.append(
        f"\nFiles scanned: {snapshot.total_files_scanned} · "
        f"included verbatim below: {snapshot.total_files_included}"
    )

    # File tree
    if snapshot.file_tree:
        parts.append("\n## File tree (truncated)")
        parts.append("```")
        parts.extend(snapshot.file_tree[:200])
        parts.append("```")

    # Recent commits
    if snapshot.recent_commits:
        parts.append("\n## Recent commits")
        for c in snapshot.recent_commits:
            parts.append(f"- `{c.sha}` ({c.date}) {c.subject} — {c.author}")
            if c.diff_stat:
                parts.append(f"  · _{c.diff_stat}_")

    # Files
    if snapshot.high_value_files:
        parts.append("\n## High-value file contents")
        for f in snapshot.high_value_files:
            tail = " (truncated)" if f.truncated else ""
            parts.append(f"\n### `{f.path}`{tail} · {f.line_count} lines")
            parts.append("```")
            parts.append(f.content)
            parts.append("```")

    parts.append(
        "\n---\n\nNow produce the audit report in the exact format "
        "specified in the system prompt. Begin with `# Ubik Audit · "
        f"{snapshot.repo_name}`."
    )

    return "\n".join(parts)


async def run_audit(
    llm: LLMAdapter,
    notebook: Notebook,
    repo_path: Path | str,
    *,
    project_name: str | None = None,
    max_tokens: int = 8000,
) -> AuditResult:
    """Run a single-shot audit. Returns the persisted entry + raw markdown."""
    started = datetime.now(timezone.utc)
    logger.info("Ubik Audit starting at %s", repo_path)

    snapshot = read_repo(repo_path)
    project = project_name or snapshot.repo_name

    user_prompt = render_audit_prompt(snapshot)

    logger.info(
        "Snapshot ready: %d files scanned, %d included, %d commits",
        snapshot.total_files_scanned,
        snapshot.total_files_included,
        len(snapshot.recent_commits),
    )

    response = await llm.chat(
        [
            Message(role="system", content=SYSTEM_PROMPT),
            Message(role="user", content=user_prompt),
        ],
        temperature=0.4,
        max_tokens=max_tokens,
        thinking=True,
    )

    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    logger.info(
        "Audit complete in %.1fs · in=%d out=%d thinking=%d",
        elapsed,
        response.input_tokens,
        response.output_tokens,
        response.thinking_tokens,
    )

    # Title pulled from first H1, fallback to project name.
    title = _title_from_markdown(response.text) or f"Audit · {project}"

    entry = notebook.write(
        kind="audit",
        project=project,
        title=title,
        body_markdown=response.text,
        tags=["audit", "single-shot"],
    )

    return AuditResult(
        entry=entry,
        markdown=response.text,
        snapshot=snapshot,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        thinking_tokens=response.thinking_tokens,
    )


def _title_from_markdown(md: str) -> str | None:
    """Pull the first `# heading` out of the LLM's reply."""
    for line in md.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return None
