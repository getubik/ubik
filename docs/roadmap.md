# Roadmap

## Sprint 1 — Skeleton + Core (week 1)

- [x] Repo skeleton (commit 71b8069)
- [x] 2026 stack lock-in: uv + ruff + ty + claude-agent-sdk + pydantic-ai + OTel
- [ ] LLM adapter (litellm wrapper, GLM/Z.AI default; pydantic-ai agent loop on top)
- [ ] Notebook (markdown writer + JSON manifest)
- [ ] Researcher single-shot mode (`ubik audit`)
- [ ] First end-to-end test: audit a small repo, dump report
- [ ] OpenTelemetry GenAI instrumentation baseline (no backend yet, just spans)

## Sprint 2 — Adapters + MCP (week 2)

- [ ] Executor adapter: Claude Agent SDK (Python, Z.AI shim) primary
- [ ] Executor adapter: Aider (subprocess) secondary
- [ ] Bridge adapter: Telegram with inline keyboard
- [ ] Verifier adapter: GitHub PR + status checks
- [ ] MCP server (stdio + Streamable HTTP transports)
- [ ] MCP Server Card (`.well-known/mcp-server-card`) for registry discovery
- [ ] Worktree isolation, sandbox network allowlist (claude-agent-sdk native)

## Sprint 3 — GYIBB integration + Public release (week 3)

- [ ] GYIBB-flavored config in `examples/gyibb-config.yaml`
- [ ] Hetzner deployment (autonomous mode)
- [ ] First real proposal-to-merge loop running on production
- [ ] PyPI release (`pip install ubik`)
- [ ] npm release (`@getubik/mcp` thin wrapper)
- [ ] README polish, demo GIF, quickstart video

## Sprint 4 — Multi-project (week 4)

- [ ] Project manifest (one daemon, many repos)
- [ ] Cross-project notebook search
- [ ] Per-project Telegram tagging

## Sprint 5+ — Community polish

- [ ] Smithery / MCP registry submission
- [ ] Web search adapter (Serper, SearxNG, DuckDuckGo)
- [ ] Slack bridge
- [ ] GitLab verifier
- [ ] Hosted version (`ubik.dev`)

## Long-term ideas

- Self-improvement loop — Ubik proposes changes to itself
- Cross-project insight: pattern detected in one repo flagged in another
- Cost analytics + budget enforcement
- Plugin marketplace for niche analyzers
- Training-free fine-tuning of researcher prompts via notebook history

---

## Config schema — supported in 0.1.0 vs roadmap

The `ubik/core/config.py` loader is the canonical contract; only fields
listed in [the honest example](../ubik.example.yaml) round-trip. The
following blocks were advertised in pre-0.1.0 example configs but are
**not wired** today and live here as roadmap pointers:

| Roadmap block | Supersedes which sprint | Notes |
|---|---|---|
| `project.shared_namespace` | Sprint 4 (multi-project notebook search) | Postgres + pgvector backend required |
| `researcher.llm.advisor` | Future | Anthropic-style escalation for high-stakes calls |
| `researcher.scope` (web_search / arxiv / hackernews / github_issues / competitor_urls) | Sprint 5+ | Each subscope ships with its own adapter |
| `executor.sandbox.network.{allowed_domains,denied_domains,allow_managed_only}` | After Slice 3 | Native to claude-agent-sdk; Aider needs a wrapper |
| `bridge.mcp_apps` | After Slice 3 | MCP Apps SEP-1865 inline approval surface |
| `verifier.pr.provider`: `"bitbucket"` / `"gitea"` | Sprint 5+ | (`"github"` and `"gitlab"` ship in 0.1.0) |
| `notebook.storage: "postgres"` + `notebook.postgres_url_env` | Sprint 4 | Cross-project semantic search |
| `notebook.retention_days` | Sprint 5+ | Currently the notebook grows forever |
| `mcp.*` | Partial — `ubik mcp` server runs stdio only; HTTP/OAuth/server-card are not honored from YAML | |
| `observability.*` | Sprint 5+ | OTel spans emitted unconditionally; backend selection via env for now |

If you need one of these, open an issue describing the use case — the
priorities above can shift based on demand.
