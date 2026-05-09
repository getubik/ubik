# Stack — why these tools, mid-2026

> *"The tools are the slogan."* — anonymous

Ubik is built on a deliberately curated stack chosen in May 2026, with an
explicit bias toward tools that have **won their category** rather than the
flashy newcomers. Each pick is reversible (every layer is a pluggable adapter),
but the defaults reflect what production teams converge on right now.

## Build & dependency management — `uv` + `uv_build`

[Astral's uv](https://astral.sh/blog/uv) is the new Python project foundation.
As of mid-2026:

- **126M monthly PyPI downloads** — surpassed Poetry (~75M) some time in early 2026.
- **OpenAI Codex** (2M weekly active devs) migrated from `pip` to `uv`,
  saving ≈1M minutes of CI compute every week.
- **OpenAI acquired Astral** in March 2026; uv and ruff stay open source but
  get tighter integration with Codex going forward.
- 10–100× faster than Poetry on resolution and install.
- Replaces `pip`, `virtualenv`, `pyenv`, `pip-tools`, `pipx`, and Poetry —
  one binary.

We use `uv_build` as the build backend (PEP 621-clean, zero config) instead of
hatchling. For pure-Python projects like Ubik, hatchling's extra surface buys
nothing.

## Lint, format, type-check — `ruff` + `ty`

Both from Astral, both Rust-fast.

- `ruff` replaces black + isort + flake8. 99.9% Black-compatible formatter,
  built-in import sorting, hundreds of lint rules.
- `ty` is Astral's mypy alternative, still pre-1.0 but already useful in CI.
  We use it in `dev` extras only — pin loose so it can iterate.

If you're on a team that absolutely needs Black-bit-identical output, swap
ruff's formatter for Black via config. Everything else stays.

## LLM dispatch — `litellm` + `pydantic-ai`

Two layers, each with a clear job:

- **litellm** is the universal client. 100+ providers (Z.AI, OpenAI,
  Anthropic, Google, Bedrock, Groq, Ollama, vLLM, …). One `chat()` call,
  swap providers via config.
- **pydantic-ai** sits on top for the agent loop itself. Type-safe tool
  calls, streaming, retry semantics, and **first-class OpenTelemetry
  GenAI semantic convention** support — which became the industry default
  for agent observability in 2026.

Why both: litellm gives us a vendor-neutral wire layer; pydantic-ai gives us a
typed, observable agent loop on top. Either alone leaves a hole.

## Default LLM — GLM-5.1 (and why it's free here)

[Z.AI's GLM-5.1](https://docs.z.ai/guides/llm/glm-5.1) (released 7 April 2026):

- **#1 on SWE-Bench Pro** (58.4) — beats Claude Opus 4.6 (57.3) and GPT-5.4 (57.7).
- Open weights, 754B-param MoE, 40B active.
- Up to **8 hours of continuous coherent execution** on a single agentic task.
- Available through the Z.AI **GLM Coding Plan annual subscription** with
  unlimited tokens, which makes Ubik effectively zero marginal cost when
  configured this way.

Concretely: Anthropic's Claude Code Max tier is $200/month for similar
capability. Running Ubik on GLM-5.1 with the annual plan delivers comparable
agentic coding at a flat yearly fee. Adapter pattern preserves the option to
swap if a better model appears — which it will.

For decisions Ubik flags as high-stakes, the optional **advisor** path can
escalate to a stronger model (Anthropic's pattern from `advisor-tool-2026-03-01`)
without leaving the loop. Off by default.

## Coding executor — `claude-agent-sdk` (Python)

Anthropic renamed the Claude Code SDK to **Claude Agent SDK** in early 2026
and shipped the Python package as a first-class citizen. We use it directly
(not via subprocess) because it gives us:

- **Multi-agent orchestration** — a lead agent breaks work into pieces and
  delegates to specialist sub-agents in parallel on a shared filesystem.
  Ubik's Researcher → Critic → Planner chain becomes a native pattern.
- **Sandbox network allowlist** (`allowedDomains` / `deniedDomains`) without
  having to bolt on iptables ourselves.
- **Eager session-store streaming** for live UI updates (Telegram inline
  keyboard refresh, cross-process resume).
- **Effort levels** (`low`/`medium`/`high`/`xhigh`) with budget knobs.
- Z.AI shim works out of the box: set `base_url` to the Z.AI coding paaS
  endpoint and the SDK happily talks to GLM-5.1.

Aider stays as a secondary executor for repos where the user already
relies on its git-commit-per-edit discipline. OpenHands is wired for
heavy autonomous workloads but spawned as an external service.

## MCP — `mcp` SDK + Server Cards + MCP Apps

The Model Context Protocol moved out of pure Anthropic governance into the
**Linux Foundation's Agentic AI Foundation (AAIF)** in December 2025. By
mid-2026 it has 97M monthly SDK downloads, OAuth 2.1 + PKCE for remote
servers, and the Streamable HTTP transport.

We adopt three relatively new primitives:

- **Server Cards** (`.well-known/mcp-server-card`) — Smithery, MCP registry,
  Cursor, Claude Desktop all read this for auto-discovery. Set it once and
  every MCP-aware client finds Ubik.
- **MCP Apps** (SEP-1865) — interactive UIs from MCP servers. Approvers can
  tap "✅" inside their IDE without leaving the chat thread.
- **Tasks primitive** (SEP-1686) — long-running operations with retry
  semantics. Multi-hour audit / research workflows survive crashes.

OAuth 2.1 stays optional in the example config — turn it on the moment you
expose Ubik over a public URL.

## Bridge — Telegram first, Slack/Discord/webhook adapters available

Telegram won the asynchronous-approval-bot race. python-telegram-bot v21+ has
inline keyboards, file attachments, and a stable async API. Slack, Discord,
and a generic webhook adapter ship in the same release for teams already
living elsewhere.

## Notebook — filesystem + optional pgvector

Daily / weekly / ad-hoc reports live in `research/` as markdown + a
`manifest.json` index. Plain text, git-friendly, auditable. This is enough for
single-project use.

Multi-project mode flips on a Postgres backend with **pgvector** for semantic
search. A finding from one repo can be cited when researching another —
"this pub/sub event-loss pattern showed up in GYIBB; the same fix applies
here." pgvector + a small sentence-transformers encoder gives sub-100ms
similarity queries across 100k+ entries.

## Observability — OpenTelemetry GenAI + Langfuse

OpenTelemetry's **GenAI semantic conventions** standardized in 2026 — every
serious agent framework (Pydantic AI, Strands, smolagents, CrewAI) emits
traces against them. We instrument once and the telemetry portable.

Langfuse is the default backend because it's:

- **Open source** (self-hostable, MIT) and YC-backed (W23) — operational
  longevity is a real concern for this category.
- **OTel-native** ingestion at `/api/public/otel`.
- Multi-tenant by design — one Langfuse instance for all your Ubik-managed
  projects, scoped queries via attributes.
- Cost-tracking dashboards rolled up from tagged root spans, which is how
  modern multi-agent cost attribution works.

LangSmith and Braintrust are valid alternatives via the same OTel layer —
swap the exporter endpoint, nothing else changes.

## What we *didn't* pick (and why)

| Skipped | Reason |
|---|---|
| **Hatchling** | Fine, but uv_build is faster and zero-config for pure Python. |
| **Poetry** | Still solid, but uv has eaten its lunch on every metric in 2026. |
| **mypy** | Slow. ty is Rust-fast and improving every week. |
| **LangChain / LangGraph** | Overkill for our orchestration shape; we use pydantic-ai instead. |
| **Auto-GPT / BabyAGI heritage** | Abandoned. The space moved on. |
| **Subprocess `claude` CLI** | Strictly worse than the Python SDK now that the SDK exists. |
| **PostgreSQL by default** | Extra ops burden until you actually have multi-project insight needs. |

## Trade-offs you should know about

- **GLM-5.1 lags Opus 4.7 on the very hardest reasoning benchmarks.** For
  most coding work this gap is ≤8% (per BenchLM April 2026); for some
  long-tail edge cases it's larger. The advisor escalation path exists
  for exactly this.
- **uv is young.** Two years old. Some Poetry plugins have no equivalent.
  If you depend on those, stay on Poetry — the adapter pattern doesn't
  help here.
- **Astral's OpenAI acquisition is recent.** The tools remain OSS today;
  we're betting that stays true. If it doesn't, hatchling + ruff fork +
  mypy is a tolerable fallback.
- **MCP is rapidly evolving.** Spec changes have been backwards-compatible
  so far, but pin the SDK loosely and watch the changelog.

## When to revisit

Re-evaluate this stack:

- Every six months on a calendar trigger.
- Whenever a new SOTA coding model appears with a noticeable benchmark gap.
- Whenever the MCP spec ships a major (e.g. 3.0) revision.
- If Astral's licensing or governance changes.

Adapter pattern means a stack swap costs hours, not weeks. Don't let
inertia carry you past a clear improvement.
