"""Tests for the audit digest extractor."""

from __future__ import annotations

from ubik.core.summarize import digest_audit, render_telegram_body

SAMPLE_AUDIT = """\
# Pssst! Audit · ubik

## TL;DR
- The audit command is the only live surface.
- Missing CHANGELOG.md leaves a 404 from PyPI.
- Pre-release `ty` pin lacks an upper bound.

## What I read
32 files across 7 languages.

## Findings

### 1. Ship the missing CHANGELOG.md · low
Body 1.

### 2. Replace bare asyncio.run() · medium
Body 2.

### 3. Add CLI integration tests · medium
Body 3.

### 4. Verify init() is not truncated · critical
Body 4.

## What looks healthy
- Adapter architecture is clean.
"""


def test_digest_extracts_title_and_tldr() -> None:
    d = digest_audit(SAMPLE_AUDIT)
    assert d.title == "Pssst! Audit · ubik"
    assert "audit command is the only live surface" in d.tldr
    assert d.finding_count == 4


def test_digest_severity_histogram() -> None:
    d = digest_audit(SAMPLE_AUDIT)
    assert d.severities == {"low": 1, "medium": 2, "high": 0, "critical": 1}


def test_digest_top_findings_capped_at_3() -> None:
    d = digest_audit(SAMPLE_AUDIT)
    assert len(d.top_findings) == 3
    assert d.top_findings[0].startswith("Ship the missing CHANGELOG")
    assert d.top_findings[2].startswith("Add CLI integration tests")


def test_digest_handles_no_tldr() -> None:
    md = "# Quick Audit\n\nFirst paragraph here.\n\n### 1. Foo · low\nBody."
    d = digest_audit(md)
    assert d.tldr == "First paragraph here."
    assert d.finding_count == 1


def test_digest_fallback_title() -> None:
    d = digest_audit("no heading here", fallback_title="Default")
    assert d.title == "Default"
    assert d.finding_count == 0


def test_render_telegram_body_includes_severity_summary() -> None:
    d = digest_audit(SAMPLE_AUDIT)
    body = render_telegram_body(d)
    assert "4 findings" in body
    assert "1 critical" in body
    assert "2 medium" in body
    assert "1 low" in body
    # Top findings rendered as bullets
    assert "• Ship the missing CHANGELOG" in body


def test_render_telegram_body_with_url() -> None:
    d = digest_audit(SAMPLE_AUDIT)
    body = render_telegram_body(d, body_url="https://psssst.dev/notebook/1")
    assert "[full report](https://psssst.dev/notebook/1)" in body
