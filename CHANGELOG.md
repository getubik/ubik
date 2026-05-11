# Changelog

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
