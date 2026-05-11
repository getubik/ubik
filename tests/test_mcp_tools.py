"""Tests for the MCP tool handlers (notebook side — no LLM mocking yet)."""

from __future__ import annotations

from pathlib import Path

from ubik.core.notebook import Notebook
from ubik.mcp.server import (
    tool_notebook_read,
    tool_notebook_recent,
    tool_notebook_search,
)


def _seed_notebook(tmp_path: Path) -> Notebook:
    nb = Notebook(tmp_path)
    nb.write(kind="audit", project="alpha", title="First audit", body_markdown="x")
    nb.write(kind="audit", project="beta", title="Second audit", body_markdown="y")
    nb.write(
        kind="proposal",
        project="alpha",
        title="Trendhunter hallucination guard",
        body_markdown="Compound prefix issue.",
        tags=["trendhunter", "regex"],
        severity="medium",
    )
    return nb


def test_recent_returns_envelope(tmp_path: Path) -> None:
    nb = _seed_notebook(tmp_path)
    out = tool_notebook_recent(nb, n=10)
    assert out["status"] == "ok"
    assert out["count"] == 3
    assert {e["title"] for e in out["entries"]} == {
        "First audit",
        "Second audit",
        "Trendhunter hallucination guard",
    }


def test_recent_filters_by_project(tmp_path: Path) -> None:
    nb = _seed_notebook(tmp_path)
    out = tool_notebook_recent(nb, n=10, project="alpha")
    assert out["count"] == 2
    assert all(e["project"] == "alpha" for e in out["entries"])


def test_search_finds_by_tag(tmp_path: Path) -> None:
    nb = _seed_notebook(tmp_path)
    out = tool_notebook_search(nb, query="trendhunter")
    assert out["count"] == 1
    assert out["entries"][0]["title"] == "Trendhunter hallucination guard"


def test_search_filters_by_kind(tmp_path: Path) -> None:
    nb = _seed_notebook(tmp_path)
    out = tool_notebook_search(nb, query="audit", kind="proposal")
    assert out["count"] == 0  # title says "audit" but kind=proposal mismatch
    out_audit = tool_notebook_search(nb, query="audit", kind="audit")
    assert out_audit["count"] == 2


def test_read_returns_body(tmp_path: Path) -> None:
    nb = _seed_notebook(tmp_path)
    recent = tool_notebook_recent(nb, n=1)
    slug = recent["entries"][0]["slug"]

    out = tool_notebook_read(nb, slug=slug)
    assert out["status"] == "ok"
    assert "kind:" in out["markdown"]  # YAML frontmatter present


def test_read_unknown_slug_returns_error(tmp_path: Path) -> None:
    nb = _seed_notebook(tmp_path)
    out = tool_notebook_read(nb, slug="does-not-exist")
    assert out["status"] == "error"
    assert "does-not-exist" in out["error"]
