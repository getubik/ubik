# Architecture, explained

Or: *what's actually under the hood, and how the pieces talk.*

> Ubik runs on Forge (residential VPS, hostname `Hermes`) with a
> minute-grained `git fetch + reinstall` cron — same pattern GYIBB's
> scraper uses. Push to `main` and within 60s the Forge instance
> reflects the new code, no human touch.

This document walks the reader through Ubik's internals one layer at a time.
If you read [`architecture.md`](architecture.md) first you've got the
diagrams; this is the version that answers questions like "wait, when I run
Claude Code with Z.AI shim, whose LLM does what?"

---

## The two-direction question

Ubik shows up on both sides of an LLM conversation:

1. **You → Ubik** (someone calls Ubik as a tool)
2. **Ubik → its own LLM** (Ubik does work using a model)

These run on different agent loops, with different libraries, often with
different providers — even when you're using "the same model."

```
                 ┌──────────────────────────────────────┐
                 │   You — typing in a CLI              │
                 │   (Claude Code / Cursor / Continue)  │
                 │                                      │
                 │   Your client's LLM does:            │
                 │     - read your message              │
                 │     - decide which tool to call      │
                 │     - format the response            │
                 │                                      │
                 │   ↓ MCP protocol (tool call)         │
                 ├──────────────────────────────────────┤
                 │   Ubik MCP server                    │
                 │   `ubik mcp`                          │
                 │                                      │
                 │   Receives tool call, dispatches to: │
                 │                                      │
                 │   ┌────────────────────────────────┐ │
                 │   │  Researcher (audit / propose)  │ │
                 │   │  pydantic-ai loop              │ │
                 │   │  Ubik's LLM (litellm-routed)  │ │
                 │   └────────────────────────────────┘ │
                 │                                      │
                 │   ┌────────────────────────────────┐ │
                 │   │  Executor (write code)         │ │
                 │   │  claude-agent-sdk loop         │ │
                 │   │  Ubik's LLM (litellm-routed)  │ │
                 │   └────────────────────────────────┘ │
                 └──────────────────────────────────────┘
```

Both your client and Ubik are running their own agent loops. They
**don't share state**; they communicate only via the MCP wire.

---

## Five libraries, one product

Ubik orchestrates five third-party libraries, each chosen because they're
the best of their category in May 2026. Replacing any one of them is a
config change, not a refactor.

### 1. MCP server — `mcp` (Anthropic Python SDK)

The protocol that lets your IDE / agent CLI call Ubik. `ubik mcp` starts a
server that speaks the [Model Context Protocol](https://modelcontextprotocol.io)
over stdio (default) or Streamable HTTP.

**What it owns**: tool registry, prompt templates, resource URIs, the
`.well-known/mcp-server-card.json` metadata for auto-discovery.

**What it does NOT do**: the actual work. It dispatches tool calls into
the researcher / executor / notebook layers below it.

### 2. Researcher loop — `pydantic-ai`

The library that runs Ubik's audit / research / propose loops. Type-safe
agent definitions, async by default, first-class OpenTelemetry GenAI
semantic-convention emission.

**What it owns**: the per-call agent loop, retry semantics, tool calls
within Ubik's own brain (when researcher calls codebase_read, web_search,
notebook_query as internal helpers).

**What it does NOT do**: code modification. That's the executor's job.

### 3. Executor — `claude-agent-sdk` (Anthropic Python SDK)

When Ubik needs to *write code* — apply a fix, refactor a file, draft a
PR — it spawns a Claude Agent SDK session in an isolated git worktree.
Why this and not Aider directly:

- Multi-agent orchestration native (lead → specialist sub-agents)
- Sandbox network allowlists (`allowedDomains` / `deniedDomains`)
- Effort levels (low / medium / high / xhigh) with budget controls
- Eager session-store streaming for live UI feedback
- Advisor-tool escalation pattern for high-stakes decisions

The SDK is configurable via `base_url` — point it at Z.AI's endpoint and
Claude Agent SDK happily talks to GLM-5.1 instead of Claude. Same SDK,
different brain.

**Aider stays as a fallback adapter.** Some users prefer its commit-per-edit
discipline; the executor adapter pattern lets us run either.

### 4. LLM client — `litellm`

The universal wire format. 100+ providers behind one async chat() call.

**What it owns**: provider routing (Anthropic / OpenAI / Z.AI / Bedrock /
Gemini / Groq / Ollama / vLLM), retry policy, timeout, parameter
sanitization.

**What it does NOT do**: agent loops or tool calling. It's just the
HTTP/streaming layer. Researcher and executor sit above it.

### 5. Notebook — filesystem markdown + manifest

Plain markdown files with YAML frontmatter, indexed in a single
`research/manifest.json`. Self-describing, grep-friendly, git-friendly.

When multi-project mode lands (Sprint 4), this becomes optional Postgres
+ pgvector for semantic search across hundreds of projects. The interface
stays the same — adapter pattern again.

---

## Walkthrough: a typical session

Imagine: you're in Claude Code (configured with Z.AI shim, so its LLM is
GLM-5.1). You type:

```
> audit my repo
```

What happens:

1. **Your Claude Code reads the message.** Its own GLM-5.1 (via Z.AI)
   sees the message. Tool descriptions for the registered MCP servers
   include `ubik.audit_repo(path)` from Ubik. The model picks that tool.
2. **MCP call lands at Ubik.** Ubik's MCP server (`ubik mcp`) receives:
   `{tool: "ubik.audit_repo", args: {"path": "."}}`.
3. **Ubik runs the researcher loop.** This is a *separate* agent loop —
   Claude Code's loop is paused, waiting on Ubik's response. Inside Ubik,
   pydantic-ai issues an LLM call (also routed to GLM-5.1 via litellm
   with the same Z.AI base_url), passes the system prompt + the
   codebase_read snapshot, gets a markdown audit back.
4. **Ubik writes to notebook.** The audit lands as a new markdown file
   under `research/audit/` with YAML frontmatter, manifest updated.
5. **Ubik returns.** The MCP response carries the audit markdown back to
   Claude Code.
6. **Your Claude Code formats and shows you the result.** Its own LLM
   summarizes / prettifies and shows it in your terminal.

Two separate LLM calls happened during this exchange — one in your
Claude Code, one in Ubik. Both used GLM-5.1, but neither knew about the
other's call. They communicated only via the MCP tool wire.

If you'd run `ubik audit .` directly from your shell instead, step 1 is
skipped (no client agent loop) — Ubik just runs its own loop and prints
the result. Same researcher, same LLM, no MCP layer.

---

## Walkthrough: an autonomous proposal

Now imagine: Ubik is running as `ubik run` on a server, with Telegram
configured. Some hours later:

1. **Scheduler fires** (e.g. daily 09:00). Ubik's researcher runs against
   the configured repo.
2. **A finding comes back** with severity ≥ medium.
3. **Ubik composes a proposal** — concrete fix plan, evidence, risk, ETA.
4. **Bridge pushes it to Telegram.** You see "🤫 Ubik · {project} · 1
   high-severity proposal" with inline buttons: ✅ Approve · 👁 Show diff
   · 📝 Refine · ❌ Reject.
5. **You tap ✅.** Telegram callback fires back to Ubik.
6. **Ubik spawns the executor.** Claude Agent SDK starts in a fresh git
   worktree on a new branch (e.g. `auto/2026-05-09-001`). Sandbox
   enforced: cost cap, time cap, domain allowlist. The executor's LLM is
   GLM-5.1 (or whatever you've configured), routed through `base_url`.
7. **The executor writes code.** Multi-step: read files, edit, run tests
   in the sandbox, fix failures, commit.
8. **Verifier runs.** Tests must pass; build must succeed; smoke check OK.
9. **PR is opened** against `main`. Bridge sends a second Telegram ping:
   "PR #42 ready — review and merge."
10. **You read the diff in GitHub.** Tap merge. Auto-deploy fires (Coolify
    / Vercel / whatever your CI is). Bridge sends the third ping: "Live
    in 4m 12s, smoke check green."

You tapped twice. Ubik did everything in between. The harness is the
product.

---

## Why this layering matters

A common question: "why not just put everything in Claude Agent SDK and
skip pydantic-ai?"

Two reasons:

1. **Different jobs need different shapes.** Researcher is read-heavy,
   exploratory, type-safe (the output schema is structured: a list of
   findings with severity tags). Pydantic-AI fits this perfectly. Executor
   is write-heavy, sequential, sandboxed. Claude Agent SDK fits this.
2. **Failure isolation.** If Anthropic deprecates Claude Agent SDK or
   tightens its license, only the executor adapter breaks. The researcher
   keeps running on pydantic-ai. We swap the executor without rewriting
   the audit pipeline.

The five-library split is the result. Each piece replaceable, none of
them load-bearing on a single vendor's continued goodwill.

---

## What lives in each Python file (as of Sprint 1)

```
ubik/
├── adapters/
│   ├── llm/
│   │   ├── base.py              ← Message / LLMAdapter Protocol
│   │   └── litellm_adapter.py   ← #4 in the layer list above
│   ├── bridge/
│   │   ├── base.py              ← Bridge / NotifyMessage / Severity
│   │   └── telegram.py          ← Telegram Bot API client
│   ├── executor/                ← (Sprint 2.3) claude-agent-sdk wrapper
│   └── verifier/                ← (Sprint 2.4) GitHub PR creator
│
├── core/
│   ├── researcher.py            ← #2 in the layer list (pydantic-ai later)
│   ├── notebook.py              ← #5 (filesystem markdown + manifest)
│   ├── summarize.py             ← Markdown digest extractor for bridges
│   ├── config.py                ← ubik.yaml loader
│   └── orchestrator.py          ← (Sprint 2.3) the proposal lifecycle
│
├── mcp/
│   └── server.py                ← #1 in the layer list (mcp Python SDK)
│
├── tools/
│   ├── codebase_read.py         ← bounded repo snapshot
│   ├── git.py                   ← (Sprint 2) commit / branch / worktree
│   ├── web_search.py            ← (Sprint 3) Serper / SearxNG
│   └── shell.py                 ← (Sprint 2.3) sandboxed subprocess runner
│
└── cli.py                        ← `ubik audit / run / mcp / init`
```

Each layer's contract is a Protocol in `base.py`. New providers / new
agent libraries / new transports plug in by satisfying that Protocol.
We don't fork; we adapt.
