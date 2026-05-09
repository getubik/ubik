"""
Notebook — where Ubik remembers.

Every research session, every audit, every proposal becomes a markdown
file under `research/` with YAML frontmatter for indexing. A small
`manifest.json` keeps a flat list of entries so future Researcher loops
can cite past work without re-scanning the whole tree.

Filesystem layout::

    research/
    ├── manifest.json
    ├── audit/
    │   └── 2026-05-09-getubik-ubik.md
    ├── daily/
    │   └── 2026-05-09-pulse.md
    ├── weekly/
    │   └── 2026-W19.md
    ├── monthly/
    └── proposals/
        └── 2026-05-09-trendhunter-halucination.md
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

EntryKind = Literal["audit", "daily", "weekly", "monthly", "proposal", "research"]


@dataclass(slots=True)
class NotebookEntry:
    """A single archived note."""

    slug: str
    kind: EntryKind
    project: str
    title: str
    summary: str
    created_at: str
    body_path: str
    """Path relative to the notebook root."""

    severity: str | None = None
    """For proposals: low | medium | high | critical."""

    tags: list[str] = field(default_factory=list)


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str, max_len: int = 60) -> str:
    """ASCII-only, lowercase, hyphenated. Cuts at word boundary."""
    text = text.lower().strip()
    slug = _SLUG_RE.sub("-", text).strip("-")
    if len(slug) > max_len:
        slug = slug[:max_len].rsplit("-", 1)[0]
    return slug or "entry"


class Notebook:
    """Filesystem-backed notebook.

    Plain markdown + a small JSON manifest. Easy to grep, easy to
    diff, easy to back up. Postgres+pgvector backend lives behind
    the same interface but is wired in a separate module.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._manifest_path = self.root / "manifest.json"

    # ── public API ───────────────────────────────────────────────────────

    def write(
        self,
        kind: EntryKind,
        project: str,
        title: str,
        body_markdown: str,
        *,
        summary: str | None = None,
        severity: str | None = None,
        tags: list[str] | None = None,
        when: datetime | None = None,
    ) -> NotebookEntry:
        """Persist a new entry. Returns the metadata record."""
        when = when or datetime.now(timezone.utc)
        date_part = when.strftime("%Y-%m-%d")
        slug = f"{date_part}-{slugify(title)}"

        sub = self.root / kind
        sub.mkdir(parents=True, exist_ok=True)
        body_path = sub / f"{slug}.md"

        entry = NotebookEntry(
            slug=slug,
            kind=kind,
            project=project,
            title=title,
            summary=(summary or _excerpt(body_markdown)),
            created_at=when.isoformat(),
            body_path=str(body_path.relative_to(self.root).as_posix()),
            severity=severity,
            tags=list(tags or []),
        )

        # Write the markdown with YAML frontmatter so the file is
        # self-describing even without the manifest.
        body_path.write_text(_render_with_frontmatter(entry, body_markdown), encoding="utf-8")

        # Append to manifest. Tiny single-process write — no locking.
        manifest = self._load_manifest()
        manifest.append(asdict(entry))
        self._manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        return entry

    def recent(self, n: int = 10, project: str | None = None) -> list[NotebookEntry]:
        """Return the n most recent entries, newest first."""
        manifest = self._load_manifest()
        if project:
            manifest = [e for e in manifest if e.get("project") == project]
        manifest.sort(key=lambda e: e["created_at"], reverse=True)
        return [NotebookEntry(**e) for e in manifest[:n]]

    def search(self, query: str, *, kind: EntryKind | None = None) -> list[NotebookEntry]:
        """Substring search over title + summary + tags. Returns newest-first."""
        q = query.lower()
        manifest = self._load_manifest()
        if kind:
            manifest = [e for e in manifest if e.get("kind") == kind]
        hits = [
            e
            for e in manifest
            if q in e["title"].lower()
            or q in e["summary"].lower()
            or any(q in t.lower() for t in e.get("tags", []))
        ]
        hits.sort(key=lambda e: e["created_at"], reverse=True)
        return [NotebookEntry(**e) for e in hits]

    def read(self, slug: str) -> str:
        """Return the markdown body of an entry by slug."""
        for entry in self._load_manifest():
            if entry["slug"] == slug:
                return (self.root / entry["body_path"]).read_text(encoding="utf-8")
        raise KeyError(f"no notebook entry with slug {slug!r}")

    # ── internals ────────────────────────────────────────────────────────

    def _load_manifest(self) -> list[dict[str, Any]]:
        if not self._manifest_path.exists():
            return []
        try:
            return json.loads(self._manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # Manifest is recoverable from filenames if it's ever corrupted —
            # but for now, fail soft (empty list) so the rest of the system
            # keeps running.
            return []


# ── helpers ──────────────────────────────────────────────────────────────


def _excerpt(markdown: str, max_chars: int = 240) -> str:
    """Pull a short summary out of the first paragraph of body markdown."""
    # Strip frontmatter / headings / code fences for a usable lead.
    stripped = re.sub(r"^---.*?---\s*", "", markdown, flags=re.DOTALL)
    stripped = re.sub(r"^#+\s.*$", "", stripped, flags=re.MULTILINE)
    stripped = re.sub(r"```.*?```", "", stripped, flags=re.DOTALL)
    paras = [p.strip() for p in stripped.split("\n\n") if p.strip()]
    lead = paras[0] if paras else stripped.strip()
    lead = re.sub(r"\s+", " ", lead)
    return lead[:max_chars] + ("…" if len(lead) > max_chars else "")


def _render_with_frontmatter(entry: NotebookEntry, body: str) -> str:
    """Prepend YAML frontmatter so the .md file is standalone."""
    fm_lines = ["---"]
    fm_lines.append(f"slug: {entry.slug}")
    fm_lines.append(f"kind: {entry.kind}")
    fm_lines.append(f"project: {entry.project}")
    fm_lines.append(f"title: {json.dumps(entry.title, ensure_ascii=False)}")
    if entry.severity:
        fm_lines.append(f"severity: {entry.severity}")
    if entry.tags:
        fm_lines.append("tags: " + json.dumps(entry.tags, ensure_ascii=False))
    fm_lines.append(f"created_at: {entry.created_at}")
    fm_lines.append("---")
    fm_lines.append("")
    return "\n".join(fm_lines) + body.strip() + "\n"
