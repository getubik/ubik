# Architecture

> *Psssst! Ubik whispers because it has earned the right to be heard.*

## Loop

```
┌─────────────────────────────────────────────────────────────┐
│ 1. Researcher                                                │
│    Scheduled (hourly/daily/weekly) or on-demand (MCP).      │
│    Reads: codebase + git history + redis/logs + web         │
│    + competitors + arxiv + past notebook entries.           │
│    Emits: structured Proposal { severity, plan, evidence }. │
└──────────────┬──────────────────────────────────────────────┘
               ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. Bridge (Telegram / Slack / webhook)                       │
│    Pushes the Proposal to the configured approver(s).       │
│    Inline keyboard: ✅ Approve · 👁 Show diff · 📝 Refine.  │
│    Cooldown + rate limit prevent noise.                     │
└──────────────┬──────────────────────────────────────────────┘
               ▼ (only on ✅)
┌─────────────────────────────────────────────────────────────┐
│ 3. Executor (Aider / Claude Code / OpenHands)               │
│    Spawned in an isolated git worktree on a fresh branch.   │
│    Sandboxed: cost cap, time cap, network allowlist.        │
│    CANNOT push to main — branch protection enforces.        │
└──────────────┬──────────────────────────────────────────────┘
               ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. Verifier                                                  │
│    Runs tests, build, smoke check.                          │
│    Opens a PR (GitHub / GitLab) → Bridge pings approver.    │
│    Final merge requires the second human tap.               │
└──────────────┬──────────────────────────────────────────────┘
               ▼
┌─────────────────────────────────────────────────────────────┐
│ 5. Notebook                                                  │
│    Every step archived as markdown + manifest.              │
│    Future Researcher loops cite past entries (memory).      │
└─────────────────────────────────────────────────────────────┘
```

## Adapter seams

Four pluggable interfaces. Implement the protocol, register, swap in `ubik.yaml`.

| Adapter   | Protocol                | Reference impls                         |
|-----------|-------------------------|-----------------------------------------|
| LLM       | `chat(messages) → str`  | `litellm` (universal), `claude_code_zai`|
| Executor  | `run(task) → Result`    | `aider`, `claude_code`, `openhands`     |
| Bridge    | `propose(p) → Decision` | `telegram`, `slack`, `webhook`          |
| Verifier  | `verify(branch) → PR`   | `github`, `gitlab`                      |

See [`adapters.md`](adapters.md) for writing your own.

## Modes

- **`ubik run`** — long-lived autonomous daemon
- **`ubik mcp`** — Model Context Protocol server (stdio + HTTP)
- **`ubik audit`** — one-shot single report

The same orchestrator core powers all three.

## Multi-project

A single Ubik daemon can manage many repos via a project manifest. Each repo
keeps its own `ubik.yaml`; the daemon reads them all, runs separate scheduler
contexts, and tags every Telegram message with its project.

Cross-project knowledge transfer is automatic: notebook entries are searchable
across all projects, so a pattern Ubik learns in one repo can be referenced
when researching another.
