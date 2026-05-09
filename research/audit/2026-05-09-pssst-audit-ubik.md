---
slug: 2026-05-09-pssst-audit-ubik
kind: audit
project: Ubik
title: "Pssst! Audit · Ubik"
tags: ["audit", "single-shot"]
created_at: 2026-05-09T17:08:07.030445+00:00
---
# Pssst! Audit · Ubik

## TL;DR
- **`cli.py` is cut off mid-expression** in the `--notify` path — the only non-stub command has a broken tail.
- **Two of three CLI commands are stubs** (`run`, `mcp` print "not implemented"). The project's own `audit` command is the only functional surface.
- **Missing `CHANGELOG.md`** produces a documented 404 from `pyproject.toml` project URLs.
- **No CLI integration tests, no config-loading tests, no LLM adapter tests** — 4 test files cover leaf utilities only.

## What I read
9 files verbatim out of 39 total: 24 Python, 7 Markdown, 4 config/misc, across 5 commits on `main`.

## Findings

### 1. Finish the truncated `--notify` block in `cli.py` · critical
**Evidence**: `ubik/cli.py` line 251 — the file ends mid-expression:
```python
        digest = digest_audit(result.markdown,
```
The `if notify:` branch is unreachable code; any user passing `--notify telegram` will never get a notification and will not see an error either — the function simply doesn't complete.

**Why it matters**: The only documented end-to-end flow (`ubik audit --notify telegram`) is broken at the exact point where value is delivered. Users will assume the audit succeeded silently.

**Proposed fix**: Complete the `digest_audit` call, wire `render_telegram_body`, instantiate `TelegramBridge` from env vars, call `bridge.notify()`. Wrap in try/except with a clear error if `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` are missing.

**Risk**: low — the supporting functions (`digest_audit`, `render_telegram_body`, `TelegramBridge`) all exist and are tested.

**ETA**: ~1 hour.

---

### 2. Validate the `--notify` flag against known bridges · high
**Evidence**: `ubik/cli.py` line ~228:
```python
notify: Optional[str] = typer.Option(
    None,
    "--notify",
    help="After audit, push a digest to a bridge: 'telegram' (uses TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID env vars).",
)
```
Any string is accepted. Passing `--notify slack` silently does nothing once the block is completed (Slack bridge isn't wired). Passing `--notify foobar` also silently does nothing.

**Why it matters**: Silent no-ops erode trust. The user explicitly asked for a side effect and got no feedback.

**Proposed fix**: Use `typer.Option` with a `click.Choice` or a Literal enum. Fail fast with a clear message if the chosen bridge's env vars are missing. Print `"notification sent to {n} chat(s)"` on success.

**Risk**: low.

**ETA**: ~30 minutes.

---

### 3. Ship the missing `CHANGELOG.md` · medium
**Evidence**: `pyproject.toml` declares:
```toml
Changelog = "https://github.com/getubik/ubik/blob/main/CHANGELOG.md"
```
No `CHANGELOG.md` appears in the file tree. The link 404s.

**Why it matters**: PyPI renders this URL on the project page once published. A 404 on the first click damages credibility before the user reads a single line of code.

**Proposed fix**: Create `CHANGELOG.md` with a single `## 0.0.1 — Unreleased` header and the Sprint 1 summary from commit `fa3d35c`. Wire it into the build if desired, or remove the URL from `pyproject.toml` until there's something to show.

**Risk**: low.

**ETA**: ~15 minutes.

---

### 4. Add CLI integration tests and config-loading tests · medium
**Evidence**: `tests/` contains 4 files — all test pure functions or isolated classes (`read_repo`, `Notebook`, `digest_audit`, `_markdown_lite_to_html`). Zero tests invoke `ubik audit`, `ubik run`, or `load_config`. The `typer.testing.CliRunner` pattern is not used anywhere.

**Why it matters**: The CLI is the only user-facing surface. `run_audit` (in `researcher.py`) and `load_config` are called directly without any test confirming they compose correctly. The next refactor could break the only working command with no CI signal.

**Proposed fix**: Add `tests/test_cli.py` using `typer.testing.CliRunner`. At minimum: (1) `ubik audit` on a fixture repo with a mock LLM, asserting exit code and notebook file creation; (2) `ubik run` with missing config asserts exit 1; (3) `ubik` with no args prints help. Add `tests/test_config.py` for `load_config` with a minimal YAML fixture.

**Risk**: medium — may surface hidden coupling in `load_config` or `run_audit` that requires design changes.

**ETA**: ~3–4 hours for meaningful coverage.

---

### 5. Guard `asyncio.run()` against nested-event-loop environments · medium
**Evidence**: `ubik/cli.py` line ~183:
```python
result = asyncio.run(
    run_audit(llm=llm, notebook=notebook, repo_path=repo, ...)
)
```
`asyncio.run()` creates a new event loop and fails with `RuntimeError` if called inside an existing loop (e.g., Jupyter, some test runners, or a future `run` command that itself is async).

**Why it matters**: The `except RuntimeError` handler on line ~190 will swallow this with a generic "audit failed" message, hiding the real cause. As `ubik run` and `ubik mcp` come online, the chance of nested-loop calls increases.

**Proposed fix**: Extract a small helper (`_run_coroutine`) that detects an existing loop and uses `anyio.from_thread.run_sync` or a fallback. Alternatively, make the `audit` command `async def` and use `typer`'s async support (via `anyio`). At minimum, catch the specific nested-loop error and print a helpful message.

**Risk**: low.

**ETA**: ~1 hour.

---

### 6. Surface missing LLM credentials early · low
**Evidence**: `llm_from_config(cfg.llm.to_litellm_dict())` is called without any pre-check. If the model requires an API key (e.g., `OPENAI_API_KEY`, `Z_API_KEY`) and it's absent, the failure occurs deep inside `litellm.completion()` with a generic auth error.

**Why it matters**: The user sees a stack trace from inside a library they didn't choose, with no pointer to which env var to set.

**Proposed fix**: After `load_config`, inspect `cfg.llm.model` and check for the corresponding env var convention (litellm maps models to env vars deterministically). Print `"Set {VAR} — get one at {url}"` before calling the LLM. Optionally add a `ubik doctor` command that validates the full adapter chain.

**Risk**: low.

**ETA**: ~1 hour.

---

### 7. Default `max_tokens=8000` may silently truncate large-audit outputs · low
**Evidence**: `ubik/cli.py` line ~220: `max_tokens: int = typer.Option(8000, ...)`. A full audit of a non-trivial repo (the target use case) with findings, evidence, and proposed fixes can easily exceed 8K tokens.

**Why it matters**: The report will be cut off. The "preview (first 30 lines)" will look fine, but the persisted notebook entry will be incomplete — missing findings, or missing the "What looks healthy" / "Open questions" sections. There's no truncation warning to the user.

**Proposed fix**: Either raise the default (12000–16000 for modern models), or detect truncation from the LLM response (`finish_reason == "length"`) and print a warning suggesting `--max-tokens` override.

**Risk**: low — higher token counts cost more but are user-controlled.

**ETA**: ~30 minutes.

## What looks Healthy

- **Adapter architecture is genuinely clean.** `base.py` → `telegram.py` with `NotifyMessage` / `Severity` dataclasses, and `_markdown_lite_to_html` with proper XSS escaping. Swappable by design.
- **Test quality on implemented modules is strong.** The notebook, summarize, and telegram rendering tests cover edge cases (empty input, long strings, XSS, truncation) — not just happy paths.
- **`pyproject.toml` is exemplary.** Optional dependency groups, meta-extras (`all`, `all-plus`, `dev`), ruff config, clear comments. Other projects could copy this structure.
- **`read_repo` correctly handles adversarial inputs.** Tests confirm `.git`, `node_modules`, and binary files are excluded. Truncation is tested and signaled.
- **The notebook system is well-designed** — YAML frontmatter, slug generation with word-boundary truncation, search across title/tags/body, project filtering. Simple filesystem backend, extensible to `pgvector` later.

## Open questions

1. **Is `cli.py` actually truncated on disk, or was it just truncated in the data provided to me?** The file ends at line 251 mid-expression — if this is the real state of `main`, finding 1 is the top priority.
2. **What does `run_audit` in `ubik/core/researcher.py` look like?** It's the core of the product and I couldn't read it. Does it handle LLM retries, rate limits, or partial responses?
3. **What does `cfg.llm.to_litellm_dict()` emit?** The config model in `ubik/core/config.py` wasn't provided. Does it validate the model name, or pass garbage through to litellm?
4. **Is the `research/audit/2026-05-09-pssst-audit-ubik.md` file a previous self-audit?** If so, it's an interesting precedent — but it should be `.gitignore`d or generated fresh, not committed as source truth.
5. **What's the intended auth model for the MCP server (`ubik mcp`)?** The help text mentions OAuth 2.1 in the README, but the stub accepts no credentials. Is this deferred to sprint 2, or is there a design doc?
