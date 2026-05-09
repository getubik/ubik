"""Tests for the filesystem notebook."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from ubik.core.notebook import Notebook, slugify


def test_slugify_basic() -> None:
    assert slugify("Pssst! Audit") == "pssst-audit"
    assert slugify("Hello, World — 2026") == "hello-world-2026"
    assert slugify("") == "entry"
    # Long string truncates at word boundary.
    long = "a" * 100
    assert len(slugify(long)) <= 60


def test_write_creates_markdown_with_frontmatter(tmp_path: Path) -> None:
    nb = Notebook(tmp_path)
    when = datetime(2026, 5, 9, 12, 0, tzinfo=timezone.utc)
    entry = nb.write(
        kind="audit",
        project="ubik",
        title="Pssst! Audit · ubik",
        body_markdown="## TL;DR\nIt's fine.",
        tags=["audit", "single-shot"],
        when=when,
    )

    body_path = tmp_path / entry.body_path
    assert body_path.exists()
    text = body_path.read_text(encoding="utf-8")
    assert text.startswith("---")
    assert "kind: audit" in text
    assert "project: ubik" in text
    assert "## TL;DR" in text
    assert "It's fine." in text


def test_recent_orders_newest_first(tmp_path: Path) -> None:
    nb = Notebook(tmp_path)
    nb.write(
        kind="audit", project="p", title="first",
        body_markdown="x", when=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    nb.write(
        kind="audit", project="p", title="second",
        body_markdown="x", when=datetime(2026, 5, 1, tzinfo=timezone.utc),
    )
    items = nb.recent(2)
    assert [e.title for e in items] == ["second", "first"]


def test_search_matches_title_summary_tags(tmp_path: Path) -> None:
    nb = Notebook(tmp_path)
    nb.write(
        kind="proposal", project="p", title="Trendhunter hallucination guard",
        body_markdown="Compound prefix issue.\n",
        tags=["trendhunter", "regex"],
    )
    nb.write(
        kind="audit", project="p", title="Unrelated review",
        body_markdown="Other content",
    )

    assert len(nb.search("hallucination")) == 1
    assert len(nb.search("trendhunter")) == 1   # matches tag
    assert len(nb.search("nothing-here")) == 0


def test_recent_filter_by_project(tmp_path: Path) -> None:
    nb = Notebook(tmp_path)
    nb.write(kind="audit", project="alpha", title="A", body_markdown="x")
    nb.write(kind="audit", project="beta",  title="B", body_markdown="x")
    assert {e.project for e in nb.recent(5, project="alpha")} == {"alpha"}


def test_read_returns_persisted_body(tmp_path: Path) -> None:
    nb = Notebook(tmp_path)
    entry = nb.write(
        kind="audit", project="p", title="t",
        body_markdown="line one\nline two",
    )
    body = nb.read(entry.slug)
    assert "line one" in body
    assert "line two" in body
    with pytest.raises(KeyError):
        nb.read("does-not-exist")
