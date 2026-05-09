# Strategy

A condensed record of the strategic decisions made on 2026-05-09 about
licensing, pricing, hosted tier, and provider relationships. Written so a
future contributor (or future-us) can rebuild the reasoning from scratch.

---

## TL;DR

- **Ubik is OSS, BYOM, forever.** Apache 2.0. Bring your own LLM key.
- **No hosted tier today.** The math doesn't justify it before traction.
- **GLM-5.1 is the recommended brain** — but Ubik works with any model
  via the litellm adapter (Anthropic, OpenAI, Bedrock, Gemini, local).
- **Z.AI Coding Plan reselling is forbidden.** Confirmed in their ToS.
  Hosted SaaS on top of our personal Coding Plan is not viable.
- **Self-hosted GLM-5.1 is feasible (MIT license) but expensive.**
  ~$7-15K/mo GPU bills for production. Phase 2, after 500+ paying users.
- **The product's value is the harness, not the model.** Models depreciate
  every 3-6 months as new open weights ship. Harness compounds across
  releases. Build the harness; let users pick the brain.

---

## Decisions and their reasoning

### 1. License: Apache 2.0

Apache 2.0 over MIT for the patent grant — it's worth nothing today, but
it's the difference between "anyone can fork" and "anyone can fork without
fear of patent reprisal" if Ubik becomes commercially significant.

Decided: 2026-05-09. Locked in `pyproject.toml` and `LICENSE`.

### 2. BYOM is the default — not because we want it, because the math forces it

The original idea: charge $10/mo membership, serve users from our personal
Z.AI GLM Coding Plan ($250/year locked in at the old price).

Why this doesn't work:

> *"You may not resell, sub-resell, repackage, aggregate, proxy or otherwise
> provide the GLM Coding Plan to any third party, whether on a paid or free
> basis, nor may you use the GLM Coding Plan to provide model capabilities
> as a service to third parties."*
> — [Z.AI Subscription Terms](https://docs.z.ai/legal-agreement/subscription-terms)

Plus the GLM Coding Plan caps concurrency at 1 in-flight request — undocumented
but real. Multi-tenant SaaS would degrade to a single user at a time anyway.

So: BYOM is the default for the foreseeable future. Users connect their own
Anthropic / OpenAI / Z.AI direct-API / Bedrock / local key. Ubik is the
orchestrator on top.

### 3. Self-hosting GLM-5.1 is a Phase 2 option, not Phase 0

GLM-5.1 is MIT-licensed open weights — fully permissive for SaaS. Hardware
reality:

| Config | VRAM | Feasible for FP8? |
|---|---|---|
| 4× H100 (320 GB) | weights alone need 754 GB | No |
| 8× H100 (640 GB) | tight but workable | Yes |
| 8× H200 (1128 GB) | recommended production | Yes |

Cloud rental: **~$9.52/hr on Spheron H200 spot ≈ $6900/mo** for one cluster.
AWS p5.48xlarge: $60-100/hr, $43-70K/mo on-demand.

Break-even at $10/mo membership: ~500-1000 active users. Unrealistic before
traction. Phase 2 milestone, when MRR justifies it.

Even then, the better play is **autoscale on a managed inference provider**
(OpenRouter, Together, Fireworks) rather than buy GPUs. Models depreciate
every 3-6 months; capital tied up in GPUs depreciates faster than the model.

### 4. The harness, not the brain, is the moat

Insight from the May 2026 tech radar: harness gap > model gap. Claude Opus
4.7 scores 91.1% on Cursor's harness vs 87.2% on Claude Code's harness —
same model, 4-point spread. The orchestrator design matters more than which
LLM is current SOTA.

Strategic implication: don't try to compete with the model layer (Anthropic,
OpenAI, Z.AI). Compete on:

- Notebook (cross-project memory)
- Multi-agent loop (researcher → critic → executor → verifier)
- MCP tool surface (anyone's IDE talks to Ubik)
- Approval flow (human-in-the-loop, telegram-driven)
- Adapter library (every executor: Aider, Claude Code, OpenHands)
- Domain knowledge (per industry: SaaS, kitchen products, fintech)

Cursor doesn't host a model. Aider doesn't. Claude Code does (Anthropic's),
but their value is the harness, not the model. Same for Ubik.

### 5. "Pssst!" is the slogan; "Ubik" is the product

Brand mistake we almost made: spreading "Pssst!" across slash commands,
tool namespaces, MCP server names. Users would not know whether they're
talking to "Pssst" or "Ubik".

Decision: **identifier is always Ubik. "Pssst!" is decoration only.**

| Surface | Name |
|---|---|
| Slash command | `/ubik audit` |
| Tool namespace | `ubik.audit`, `ubik.research` |
| MCP server | `ubik` |
| Binary / package | `ubik` |
| Conversation | "Ubik found a bug" |
| Hero slogan (homepage, once) | "Pssst — wanna solve some entropy?" |
| Notification opener (decoration) | "🤫 Ubik · ..." |

> Ubik is the product. "Pssst!" is the noise it makes when it's about to
> tell you something.

### 6. Pricing today: free OSS + enterprise inquiry footer

Two-column pricing page, no middle:

```
SELF-HOST                       ENTERPRISE
$0 — OSS forever                custom — call us
─────────────                   ──────────────
✓ Apache 2.0                    ✓ On-prem deployment
✓ Bring your own LLM key        ✓ Self-hosted any model
✓ All adapters, all features    ✓ SSO + audit logs
✓ Self-host on your infra       ✓ Dedicated support

`pip install ubik`              `Schedule a call`
```

No hosted tier yet. No member ranks. No artificial limits on the OSS path.
The only paid offering is enterprise — which itself is a "call us" form
until we have real demand.

When usage shows traction (50+ active OSS users using `ubik run` daily),
Phase 1 hosted tier becomes worth building — most likely on a managed
inference provider (OpenRouter, Together) rather than self-hosted GPUs.

---

## Provider relationships

### Z.AI (GLM)

- **Today**: GLM-5.1 is the recommended default. Users connect their own
  Z.AI API key (direct API, not the Coding Plan — the Coding Plan is
  personal-use-only per their ToS).
- **Recommended in our docs**: Coding Plan ($30-90/quarter) for individual
  users who want the unlimited annual feel. They use it with Claude Code
  via the Z.AI base_url shim, then plug Ubik in via MCP.
- **Future**: Pursue partnership when Ubik has metrics. Pitch is "we drive
  Coding Plan signups, give us a SaaS-eligible enterprise tier."

### Anthropic (Claude)

- **Today**: First-class Ubik executor adapter is `claude-agent-sdk`
  (Anthropic's Python library, formerly Claude Code SDK). It powers our
  code-modification path. Configurable `base_url` lets it run against
  GLM-5.1 via Z.AI shim too — same SDK, different brain.
- **Future**: Showcase listing on Anthropic's customer page, MCP
  reference-implementation positioning.

### Open weights (DeepSeek, Qwen, GLM, Kimi)

- **Today**: All accessible via litellm. Users with strong opinions on
  privacy can run local Ollama / vLLM. Adapter pattern handles this with
  one config change.
- **Future**: When/if we build hosted, model rotates — the harness doesn't.
  Open weights leapfrog every 3-6 months; we ride the wave, don't anchor
  to one model.

---

## What we are NOT building

- **Free tier with weak LLMs.** Llama 3.3 70B, Qwen 3 Coder 32B, Gemini
  Flash all score ~50% lower than GLM-5.1 on SWE-Bench Pro. A free trial
  on those models would damage Ubik's reputation more than help adoption.
- **Hosted SaaS on top of our personal GLM Coding Plan.** Forbidden by ToS.
- **Our own LLM.** Models depreciate too fast to justify the capex.
- **A web UI before the CLI is solid.** CLI / MCP first, web later.
- **An IDE extension.** MCP makes this redundant — the IDE is whatever the
  user wants. We don't ship per-IDE plugins.

---

## When to revisit

- **Quarterly.** Stack landscape shifts (new SOTA model, new MCP spec, new
  agentic framework). Re-read this doc, update assumptions.
- **At 100 active users.** Phase 1 hosted decision becomes real.
- **At 1000 active users.** Phase 2 self-hosted GLM-5.1 (or whatever
  open-weight is current SOTA) becomes worth costing out.
- **Whenever Z.AI publishes an enterprise SaaS license tier.** Could
  unlock a hosted path that's cheaper than provider markup.
