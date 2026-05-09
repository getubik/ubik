# Roadmap

## Sprint 1 — Skeleton + Core (week 1)

- [x] Repo skeleton (this commit)
- [ ] LLM adapter (litellm wrapper, GLM/Z.AI default)
- [ ] Notebook (markdown writer + JSON manifest)
- [ ] Researcher single-shot mode (`ubik audit`)
- [ ] First end-to-end test: audit a small repo, dump report

## Sprint 2 — Adapters + MCP (week 2)

- [ ] Executor adapter: Aider + Claude Code (Z.AI shim)
- [ ] Bridge adapter: Telegram with inline keyboard
- [ ] Verifier adapter: GitHub PR + status checks
- [ ] MCP server (stdio transport)
- [ ] Worktree isolation, sandbox enforcement

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
