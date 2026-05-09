---
slug: 2026-05-09-pssst-audit-ubik
kind: audit
project: Ubik
title: "Pssst! Audit · Ubik"
tags: ["audit", "single-shot"]
created_at: 2026-05-09T16:50:49.737791+00:00
---
# Pssst! Audit · Ubik

## TL;DR

- The `audit` command is the only live surface; `run`, `mcp`, and `init` are stubs with `TODO` comments. Anyone installing from `main` gets three dead subcommands.
- `asyncio.run()` inside a sync Typer handler will hang or throw on Windows when interrupted — and the repo path (`D:\Projects`) says the author is on Windows.
- `pyproject.toml` links to a `CHANGELOG.md` that doesn't exist in the tree. Ship it or remove the URL; a 404 on a fresh install erodes trust.

## What I read

32 files across 7 languages (19 Python, 6 Markdown, 4 config/static). 4 commits on 2026-05-09, all scaffolding. 7 files provided verbatim — CLI, pyproject, tests, and package root.

## Findings

### 1. Ship the missing CHANGELOG.md · low
**Evidence**: `pyproject.toml` line — `Changelog = "https://github.com/getubik/ubik/blob/main/CHANGELOG.md"`. No `CHANGELOG.md` appears in the file tree.
**Why it matters**: Anyone clicking the PyPI/classifier link hits a 404. For a pre-alpha it's low stakes, but it's also a one-line fix.
**Proposed fix**: Create `CHANGELOG.md` with a single `## 0.0.1 — Unreleased` heading, or remove the `[project.urls] Changelog` entry until there's something to link to.
**Risk**: low.
**ETA**: 2 minutes.

### 2. Replace bare `asyncio.run()` in `audit` with a Windows-safe runner · medium
**Evidence**: `ubik/cli.py` lines 130–138 — `result = asyncio.run(run_audit(...))`. Project path is `D:\Projects\Ubik` (Windows). No event loop policy set.
**Why it matters**: On Windows, `asyncio.run()` uses `ProactorEventLoop`, which mishandles `KeyboardInterrupt` in some Python ≤3.12 builds — the process hangs instead of shutting down. Also, if anyone calls `audit` from inside an already-running loop (e.g. an IDE extension), it raises `RuntimeError("This event loop is already running")`.
**Proposed fix**: Extract a small helper:
```python
def _run_coroutine(coro):
    """Windows-compatible, reentrant-safe coroutine runner."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        import nest_asyncio  # or queue on the existing loop
        nest_asyncio.apply()
        return loop.run_until_complete(coro)
    return asyncio.run(coro)
```
At minimum, wrap the `asyncio.run()` call in a `try/except KeyboardInterrupt` that calls `sys.exit(130)`.
**Risk**: low — additive change, no API break.
**ETA**: 30 minutes.

### 3. No CLI integration tests · medium
**Evidence**: `tests/` contains `test_codebase_read.py` (62 lines) and `test_notebook.py` (92 lines). No `test_cli.py`. The `audit` command wires config loading, LLM construction, and notebook writes — all untested at the integration level.
**Why it matters**: `cli.py` is the only surface a user actually touches. The import chain (`llm_from_config` → `load_config` → `run_audit`) can break silently since each piece is tested in isolation (if at all — we can't see `researcher` tests).
**Proposed fix**: Add `tests/test_cli.py` with at minimum:
- `test_audit_missing_repo_exits_1` — passes a nonexistent path, asserts exit code.
- `test_audit_missing_config_defaults Gracefully` — runs against the fixture repo in `tests/` with no `ubik.yaml`, checks it doesn't crash before the LLM call.
- `test_run_and_mcp_show_not_implemented` — asserts the stub messages appear on stdout.
Use `typer.testing.CliRunner` for isolation.
**Risk**: low.
**ETA**: 1 hour.

### 4. `init` command is truncated — the file ends mid-comment · low
**Evidence**: `ubik/cli.py` (truncated) — the `init()` function body ends at `# TODO(sprint-1): copy ubik.example.yaml from package data, ask\n    # interactive questions to`. The closing paren/quote is missing.
**Why it matters**: If the truncation reflects the actual file, `import ubik.cli` will raise a `SyntaxError` and the entire CLI becomes unusable — including `audit`. If it's only the audit data that was truncated, no issue.
**Proposed fix**: Verify the real file. If it's incomplete, either finish `init()` or add a `raise NotImplementedError` placeholder and `# noqa` so the module at least imports.
**Risk**: low — unless the file is actually truncated, in which case *critical*.
**ETA**: 5 minutes to verify, 1 hour to implement.

### 5. `ty` type checker pinned to a pre-release alpha · low
**Evidence**: `pyproject.toml` dev extra — `"ty>=0.0.1a3 ; python_version >= '3.10'"`. The comment says "Still pre-1.0 in mid-2026."
**Why it matters**: Alpha pins can yank from PyPI without notice, breaking CI from one day to the next. The `>=` range means any future breaking alpha is automatically pulled in.
**Proposed fix**: Pin to a known-good alpha (`ty==0.0.1a3`) with an upper bound (`<0.1.0`), or gate it behind a `make typecheck` that's allowed to fail in CI until `ty` hits stable. Add a comment with the expected graduation timeline.
**Risk**: low — dev-only dependency, but CI flakiness wastes time.
**ETA**: 10 minutes.

## What looks Healthy

- **Adapter architecture is clean.** Four seams (LLM, Bridge, Executor, Verifier) with `__init__.py` gateways. Swapping Claude for GLM is a config change, not a refactor.
- **Test quality is good where it exists.** `test_codebase_read.py` and `test_notebook.py` cover edge cases (binary exclusion, truncation, ordering, search miss) — not just happy paths.
- **`pyproject.toml` is unusually well-documented.** Every dependency block has inline rationale. Future maintainers can make informed swap decisions.
- **`ruff` config is strict and sane.** Bugbear, comprehensions, simplify, pyupgrade all enabled. Line-length handled by formatter, not lint. This is the right default.
- **Notebook persistence with YAML frontmatter.** Human-readable, grep-friendly, no database required for the single-project case.

## Open questions

1. Is `ubik/cli.py` actually truncated at line 208 in the repo, or was it truncated only in the audit data? If the former, the package won't import at all.
2. Does `load_config(config=None, repo_path=repo)` degrade gracefully when no `ubik.yaml` exists — i.e., does `audit` work with environment-only credentials, or does it raise?
3. Are `ubik/adapters/bridge/__init__.py`, `executor/__init__.py`, and `verifier/__init__.py` empty re-exports or do they contain base classes? The tree shows them but no contents were provided.
4. Is `researcher.py`'s `run_audit` tested anywhere? It's the core orchestration function but no test file is visible.
5. The test title `"Trendhunter halucination guard"` — is the one-L spelling intentional test data, or does the same misspelling appear in production code?
