# Ubik

> *Pssst — wanna solve some entropy?*
>
> An AI resident engineer for your codebase. Whispers findings. Proposes fixes. Waits for your tap.

🤫 [psssst.dev](https://psssst.dev) · `pip install psssst`

[![PyPI](https://img.shields.io/pypi/v/psssst.svg?label=pip%20install%20psssst)](https://pypi.org/project/psssst/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Status: alpha](https://img.shields.io/badge/status-alpha-yellow.svg)](#)
[![CI](https://github.com/getubik/ubik/actions/workflows/ci.yml/badge.svg)](https://github.com/getubik/ubik/actions/workflows/ci.yml)

> **Ubik is the product. "Pssst!" is the noise it makes when it's about to tell you something.**

---

## What is Ubik?

Ubik lives next to your repository. While you sleep, it:

1. **Reads** the codebase, the recent commits, the production logs.
2. **Watches** competitors, tech trends, papers, security advisories.
3. **Proposes** specific improvements — with evidence, plan, and risk.
4. **Whispers** to you on Telegram: *"Pssst — Ubik found something."*
5. **Ships** the fix when you tap ✅ — through Aider, Claude Code, or any
   agentic executor — onto a feature branch, with tests, as a PR.

You stay in approval mode. Ubik does the digging.

---

## Quickstart

```bash
pip install psssst      # the PyPI name; `ubik` was squatted in 2014

# In any repo:
cd my-repo
ubik init               # interactive wizard → ubik.yaml + .env.example
cp .env.example .env    # fill in API keys + Telegram bot token

ubik run --dry-run      # smoke test: audits + persists, no notifications
ubik run                # autonomous daemon for real
# or
ubik mcp                # MCP server (stdio) — for Claude Desktop / Cursor
# or
ubik audit              # one-shot codebase audit, dump report
```

That's it. Ubik is now resident.

The `ubik init` wizard ships with provider presets for **Z.AI / GLM-5.1**
(default — free with the annual plan), **Anthropic**, **OpenAI**, and
**Ollama** (local). Every field in the generated `ubik.yaml` is honored
by the loader — no config knob is decorative. Roadmap-only fields (web
search, Slack bridge, GitLab verifier, Postgres notebook) are documented
in [`docs/roadmap.md`](docs/roadmap.md) and intentionally absent from
the example.

---

## Why "Pssst"?

Most AI tooling shouts. Ubik whispers. The slogan comes from Philip K. Dick's
1969 novel *Ubik*, where a mysterious product cures reality through cryptic
chapter-opening ads. Our product cures codebases the same way: by leaning over
and going *psst*.

> *"Where's a code reviewer that actually reads the diff?*
>  *Safe to deploy. Won't push to main without approval.*
>  *It's UBIK!"*

---

## Architecture

Ubik is **vendor-agnostic** and **executor-agnostic** by design. Pluggable
adapters at four seams:

```
       ┌──────────────────────────┐
       │     Ubik Orchestrator     │
       │                          │
       │  Researcher → Bridge →    │
       │  Executor   → Verifier   │
       └──────────────────────────┘
              │       │       │       │
              ▼       ▼       ▼       ▼
         LLM      Comms   Coding   Git/PR
       ─────────────────────────────────
        GLM-5.1   Telegram  Claude  GitHub
        Claude    Slack     Agent   GitLab
        GPT       Discord    SDK    ...
        Local     Webhook   Aider
        ...       ...       OpenHands
```

Pick one of each. Swap whenever. Notebook of past findings is shared across
projects so what Ubik learns once, it remembers everywhere.

See [`docs/architecture.md`](docs/architecture.md) for the full picture.

### 2026 stack

Ubik is built on the best-of-breed of mid-2026:

| Layer | Choice | Why |
|---|---|---|
| **Build / dep mgmt** | `uv` + `uv_build` ([Astral](https://astral.sh)) | 100× pip, OpenAI-acquired, the new default |
| **Lint + format** | `ruff` (Astral) | Replaces black + isort + flake8, single binary |
| **Type check** | `ty` (Astral) | mypy alternative, Rust-fast |
| **LLM dispatch** | `litellm` | 100+ providers, vendor-agnostic |
| **Agent loop** | `pydantic-ai` | Type-safe + first-class OpenTelemetry |
| **Coding executor** | `claude-agent-sdk` (Python) | [Multi-agent orchestration](https://www.anthropic.com/), advisor tool, sandbox |
| **Default LLM** | [GLM-5.1](https://docs.z.ai/guides/llm/glm-5.1) (#1 SWE-Bench Pro) | SOTA + free with Z.AI annual plan |
| **MCP server** | `mcp` SDK + Server Cards + MCP Apps | Linux Foundation governed (AAIF), OAuth 2.1 |
| **Observability** | OpenTelemetry GenAI + Langfuse | Industry standard, OSS, multi-project insights |
| **License** | Apache 2.0 | Patent grant + contributor-friendly |

See [`docs/stack.md`](docs/stack.md) for the full reasoning.

---

## Use cases

- **Solo founders** running multiple repos — one Ubik, many `ubik.yaml`s.
- **Open source maintainers** — proactive PR triage, stale-issue digestion.
- **Researchers** — bibliometric scans, citation tracking, paper outline review.
- **Consultancies** — codebase health audit on a new client engagement.
- **Yourself, in your IDE** — install as MCP server, ask in Claude Desktop:
  *"Ubik, what's gone stale in this repo?"*

---

## License

[Apache 2.0](LICENSE). Free for any use, commercial or otherwise. Patent
grant included.

---

## Status

Alpha — `pip install psssst` (v0.1.5 live on PyPI · CI matrix green on
py3.10–3.13 × ubuntu / macOS / Windows). The autonomous daemon, the
MCP server, the wizard, and the Telegram bridge all ship in the
package today. Streamable-HTTP transport for `ubik mcp`, MCP registry
submission, and a richer notebook backend are the next milestones —
see the [Roadmap](docs/roadmap.md).

Built by [ANOTS](https://anots.com). Inspired by Philip K. Dick.
