# Changelog

## 0.1.3 — Z.AI Claude Code routing matches the official recipe

Followed [docs.z.ai/devpack/tool/claude](https://docs.z.ai/devpack/tool/claude)
exactly so the `claude_agent_sdk` executor talks to Z.AI's
`/api/anthropic` proxy the same way Claude Code does.

### Changed
- `ClaudeAgentExecutor.run()` now sets **both** `ANTHROPIC_API_KEY`
  (x-api-key header) **and** `ANTHROPIC_AUTH_TOKEN` (Bearer header)
  when a custom `base_url` is configured. Z.AI's proxy reads the
  Bearer; original Anthropic reads x-api-key; setting both keeps every
  proxy happy without needing per-provider branching.
- Also exports `API_TIMEOUT_MS=3000000` (50 minutes) per Z.AI's
  recipe — the agent loop chews through that on large refactors.
- All overrides are restored after each task so they don't leak into
  other code in the same process.

### Added
- New wizard preset: **Z.AI · GLM via Claude Agent SDK** (key
  `zai-claude`). Points at `https://api.z.ai/api/anthropic` with
  `GLM-4.7` as the default model. Pair with
  `executor.type: "claude_agent_sdk"` in `ubik.yaml` for end-to-end
  GLM coding via the Anthropic-compatible surface.

### How to use it

```bash
ubik init                    # pick "Z.AI · GLM via Claude Agent SDK"
# then edit ubik.yaml:
#   executor:
#     type: claude_agent_sdk
ubik run
```

You stay on the Z.AI Coding Plan (3× usage at a fraction of the cost
per Z.AI's pitch); the SDK speaks Anthropic protocol; Z.AI translates.

## 0.1.2 — Claude Agent SDK now follows `llm.base_url`

The Claude Agent SDK wraps the official `anthropic` Python client,
which respects `ANTHROPIC_BASE_URL` at construction time. This release
threads `llm.base_url` through into that env var so the SDK can target
**Anthropic-compatible proxies** the same way Claude Code does — e.g.
Z.AI's `/api/anthropic` surface that routes through GLM, OpenRouter,
or a LiteLLM gateway.

### Behavior change in `executor_from_config` (claude_agent_sdk branch)
- **With `llm.base_url` set**: pass the model name and base URL
  through untouched. The proxy decides what the model id maps to.
- **Without `llm.base_url`**: same as before — if the model isn't an
  Anthropic id, fall back to `claude-sonnet-4-6` on `ANTHROPIC_API_KEY`
  and log a warning explaining the swap.

### How to use Claude Code's GLM trick from Ubik

Edit `ubik.yaml`:

```yaml
researcher:
  llm:
    provider: "anthropic"
    base_url: "https://api.z.ai/api/anthropic"   # Anthropic-compat
    api_key_env: "Z_AI_API_KEY"
    model: "claude-sonnet-4-5"   # whatever name the proxy expects
executor:
  type: "claude_agent_sdk"
```

Result: the SDK speaks Anthropic protocol, Z.AI translates to GLM under
the hood, you stay on the Z.AI Coding Plan billing.

### Test
118 passed (was 117) — split the silent-swap test into two: one for the
new pass-through-with-base_url path, one for the legacy swap-when-pure-
Anthropic path.

## 0.1.1 — Expanded wizard provider presets

### Added
- `ubik init` wizard now ships **8 provider presets** (was 4):
  - **Z.AI · GLM Coding Plan** ★ recommended — free with annual sub, SOTA SWE-Bench Pro (default)
  - **Z.AI · GLM** — standard API, pay-per-token (`api/paas/v4` instead of `api/coding/paas/v4`)
  - **Anthropic · Claude Sonnet 4.6**
  - **Anthropic · Claude Opus 4.7** (1M context)
  - **Moonshot · Kimi K2.6** — long-context reasoning
  - **MiniMax · M2.7**
  - **OpenAI · GPT-4o**
  - **Ollama · local** (llama3.1, no API key)

All eight round-trip through the loader (parametrized wizard test).
Model IDs and endpoints are starting points — users can edit
`ubik.yaml` after the wizard if a provider has renamed since release.

## 0.1.0 — First public release

> **PyPI distribution name is `psssst`** (not `ubik`). The `ubik` name
> was squatted by an abandoned Python 2.6-era package; rather than wait
> on a PEP 541 transfer we ship under `psssst` to align with the
> [psssst.dev](https://psssst.dev) brand. The CLI command is still
> `ubik` and `import ubik` still works — only the install line changes:
> `pip install psssst`.


The "honest config + first-run wizard + real factory" milestone. Closes
the gap between the README's vendor-agnostic story and what the loader,
daemon, and adapter registry actually honored.

### Added
- `ubik init` — real interactive wizard with provider presets (Z.AI,
  Anthropic, OpenAI, Ollama). Generates `ubik.yaml` + `.env.example`.
- **Adapter factories** — `bridge_from_config` / `executor_from_config` /
  `verifier_from_config` resolve from `cfg.*.type`. Daemon no longer
  hard-codes Telegram + Aider + GitHub.
- **Claude Agent SDK executor** — `executor.type: "claude_agent_sdk"`.
  Worktree-isolated, same lifecycle guards as the Aider adapter (empty-
  diff guard, time cap). Requires `ANTHROPIC_API_KEY` (the SDK speaks
  Anthropic's API directly — Z.AI / GLM users keep `executor.type:
  "aider"`).
- **GitLab verifier** — `verifier.pr.provider: "gitlab"`. Mirrors the
  GitHub adapter; uses `glab` CLI if present, REST fallback otherwise.
  Self-hosted instances supported via `GitLabVerifierConfig.api_base`.
- GitHub Actions CI: ruff lint + format check, pytest matrix
  py3.10-3.13 on ubuntu + py3.12 on macOS / Windows, build + twine
  check on every PR.
- `ubik run --dry-run` — runs the audit cycle, persists proposals to
  disk, but skips bridge notification and executor invocation. The
  recommended first-run smoke test.
- `cost.max_proposals_per_day` — actually enforced. File-backed daily
  counter at `<notebook>/proposals/.daily-counter.json`. Cap-reached
  notifications go to the bridge.
- `executor.sandbox.{cost_cap_usd, time_cap_minutes}` and
  `verifier.test_command` — wired through the orchestrator into
  `ExecutorTask` (previously every task ran with the hard-coded
  defaults regardless of YAML).
- Cross-platform default state path: `<user-state-dir>/ubik/poll-offset`
  (XDG on Linux, `~/Library/Application Support/ubik` on macOS,
  `%LOCALAPPDATA%/ubik` on Windows). Override with `UBIK_HOME` or
  `--poll-offset-file`.
- `executor.type` and `bridge.type` validated against the supported
  set on load (currently `aider` and `telegram`); roadmap values raise
  with a pointer to `docs/roadmap.md`.

### Changed
- `ubik.example.yaml` rewritten to only include fields the loader
  honors. Roadmap-only fields removed; pointers in `docs/roadmap.md`.
- README quickstart now points at `ubik init` instead of the
  copy-an-example-and-edit dance.
- Author metadata, version, and dev-status classifier updated for the
  first PyPI release.

### Removed
- The Linux-only `/var/lib/ubik/poll-offset` default (replaced by the
  cross-platform helper above).

## 0.0.1

- Initial scaffold.
