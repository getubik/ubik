"""Tests for the audit-markdown → FindingExtract parser."""

from __future__ import annotations

from ubik.core.summarize import extract_findings

SAMPLE = """\
# Ubik Audit · gyibb

## TL;DR
- Three things matter.

## What I read
720 files.

## Findings

### 1. Drop the docker socket mount · critical
**Evidence**: docker-compose.yml line 116 mounts /var/run/docker.sock:ro
**Why it matters**: read-only doesn't stop env-var inspection or container listing.
**Proposed fix**: remove the mount. Use Gateway's /api/v1/nodes for status instead.
**Risk**: low
**ETA**: 1 hour

### 2. Stop tracking runtime data in git · high
**Evidence**:
- logs/gyibb.log
- data/circuit_breaker_cache/ (50+ files)
- data/raw_ugc_data.json
**Why it matters**: repo bloats forever, clones slow down.
**Proposed fix**: add to .gitignore + git rm --cached.
**Risk**: low
**ETA**: 30 minutes

### 3. Trim Dockerfile bloat · medium
**Evidence**: gyibb-web/Dockerfile copies entire node_modules.
**Why it matters**: ~100MB of devDependencies in production image.
**Proposed fix**: npm prune --production before copy.
**Risk**: low
**ETA**: 1 hour

## What looks healthy
- Streams refactor mature.

## Open questions
1. Is Forge actually serving traffic?
"""


def test_extract_three_findings() -> None:
    findings = extract_findings(SAMPLE)
    assert len(findings) == 3


def test_extract_severity_and_title() -> None:
    findings = extract_findings(SAMPLE)
    assert findings[0].number == 1
    assert findings[0].severity == "critical"
    assert findings[0].title.startswith("Drop the docker socket mount")
    assert findings[1].severity == "high"
    assert findings[2].severity == "medium"


def test_extract_evidence_multiline() -> None:
    findings = extract_findings(SAMPLE)
    f2 = findings[1]
    assert any("logs/gyibb.log" in e for e in f2.evidence)
    assert any("circuit_breaker_cache" in e for e in f2.evidence)


def test_extract_proposed_fix_and_risk_eta() -> None:
    findings = extract_findings(SAMPLE)
    f1 = findings[0]
    assert "remove the mount" in f1.proposed_fix.lower()
    assert f1.risk.startswith("low")
    assert "1 hour" in f1.eta


def test_extract_stops_at_what_looks_healthy() -> None:
    """Findings must not bleed into the 'What looks healthy' or 'Open questions' sections."""
    findings = extract_findings(SAMPLE)
    last = findings[-1]
    assert "Streams refactor" not in last.raw_block
    assert "Open questions" not in last.raw_block


def test_extract_severity_unknown_when_missing() -> None:
    md = "## Findings\n\n### 1. No severity tag here\n**Evidence**: x.\n"
    findings = extract_findings(md)
    assert len(findings) == 1
    assert findings[0].severity == "unknown"


def test_extract_zero_findings_on_empty() -> None:
    assert extract_findings("# nothing here") == []
