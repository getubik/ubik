# Recommendations

What we recommend for first-time Ubik users — and what we use ourselves.

> **Short version:** GLM Coding Plan + Claude Code + Ubik MCP server.
> $30/quarter for the brain, free for the harness, agentic everywhere.

---

## The stack we use ourselves

| Layer | Choice | Cost |
|---|---|---|
| **LLM** | [GLM-5.1](https://docs.z.ai/guides/llm/glm-5.1) via [Z.AI Coding Plan](https://z.ai/subscribe) | ~$30-90/quarter |
| **Agent CLI** | [Claude Code](https://www.anthropic.com/product/claude-code) with Z.AI base_url shim | $0 (uses your Coding Plan quota) |
| **Tool surface** | Ubik MCP server | Free, OSS |
| **Repo** | Whatever you're working on | Yours |
| **Bridge** | Telegram (optional, for autonomous mode) | Free |

This combination produces:

- **Top-of-leaderboard reasoning** (GLM-5.1 is #1 on SWE-Bench Pro, Apr 2026)
- **The Claude Code UX** you already know — chat in your terminal, it edits files, runs commands
- **Ubik as a tool** — `/ubik-audit ./repo`, `/ubik-research <topic>`, `/ubik-propose <issue>`
- **Approval-driven autonomy** — when you want it, Ubik runs nightly research and pings you on Telegram with proposals; tap ✅ and it ships a PR

---

## Setup (15 minutes total)

### 1. GLM Coding Plan

- Go to [z.ai/subscribe](https://z.ai/subscribe).
- Pick **Pro ($30/quarter)** or **Max ($80/quarter)** depending on usage.
- After payment, copy your API key from the dashboard.

> Quota is in prompts (not tokens). Pro = 600 prompts / 5h window.
> For Ubik audit usage, Pro is plenty. Max only matters if you run
> multiple agents in parallel (Claude Code + Ubik daemon + side projects).

### 2. Claude Code with Z.AI shim

```bash
# install Claude Code (npm) — see Anthropic's docs for the latest URL
npm install -g @anthropic-ai/claude-code

# point it at Z.AI's OpenAI-compatible endpoint
export ANTHROPIC_BASE_URL="https://api.z.ai/api/coding/paas/v4"
export ANTHROPIC_API_KEY="<your Z.AI Coding Plan key>"

# verify
claude --version
```

That's the official Z.AI shim — see [docs.z.ai/devpack/tool/claude](https://docs.z.ai/devpack/tool/claude).
Claude Code will route every request to GLM-5.1 instead of Anthropic's models.

### 3. Ubik

```bash
# install
pip install ubik   # or: uv tool install ubik

# point Ubik's own internal LLM calls at the same Z.AI endpoint
export Z_AI_API_KEY="<same key>"

# (optional) Telegram for autonomous mode
export TELEGRAM_BOT_TOKEN="..."
export TELEGRAM_CHAT_ID="..."

# try it
ubik audit ./your-repo
```

### 4. Wire Ubik into Claude Code (MCP)

Edit `~/.config/claude/code/mcp.json` (or whatever your Claude Code MCP
config path is — see Anthropic docs):

```json
{
  "mcpServers": {
    "ubik": {
      "command": "ubik",
      "args": ["mcp"]
    }
  }
}
```

Restart Claude Code. Now in your Claude Code chat:

```
> /ubik-audit ./this-repo
```

…and Claude Code calls Ubik as a tool. Ubik runs the audit on its own
internal loop (also using GLM-5.1 via the same Z.AI key), returns a
structured markdown report, and Claude Code presents it in your chat.

---

## Alternatives — bring your own brain

Ubik is LLM-agnostic via litellm. Any of these work as a substitute for
GLM-5.1:

| Brain | When to pick it |
|---|---|
| **Anthropic Claude Opus 4.7** | You already have an Anthropic API budget; want best multi-file reasoning. |
| **OpenAI GPT-5.5 / 5.4** | Same — you already pay OpenAI. Strong terminal-task performance. |
| **AWS Bedrock (Claude / Llama)** | Enterprise compliance binds you to Bedrock. |
| **Gemini 2.5 / 3.1 Pro** | Long context (1M+) matters for your repo. |
| **DeepSeek V4-Pro** (open) | You want open weights but don't want to manage Z.AI. MIT licensed. |
| **Local Ollama / vLLM** | Privacy-first; willing to accept a quality hit. |

Drop the `base_url` and `model` in `ubik.yaml` to swap. Everything else
in Ubik works identically.

---

## What if I'm new to all of this?

Cheapest viable starting setup:

1. Pay $30 for one Z.AI Coding Plan quarter (Pro tier).
2. Install Ubik (`pip install ubik`).
3. Set `Z_AI_API_KEY` in your env.
4. Run `ubik audit ./your-repo`.

Total: $30 + 5 minutes. You get a senior-engineer-grade audit of your
codebase. If you don't think it was worth $30, your quarter's not over —
keep using it for daily Claude Code sessions until it is.

---

## What we don't recommend

- **Free-tier LLMs (Groq, Cerebras, Gemini Flash) for Ubik audits.**
  These models score ~50% lower on SWE-Bench Pro than GLM-5.1. The audit
  output will be vague and occasionally fabricated. Ubik can do better
  than that, but only with a strong brain underneath.
- **Auto-approval of Ubik's proposals without reading them.** Even with
  GLM-5.1, the executor occasionally produces fixes that pass tests but
  introduce subtle behavior changes. The approval loop exists for a
  reason — read the diff before you tap ✅.
- **Running Ubik against repos you don't own.** Self-evident, but worth
  saying. Ubik writes commits and opens PRs. Don't aim it at someone
  else's project without permission.

---

## Migration paths

- **Coming from Cursor:** Keep Cursor for inline edits; add Ubik as a
  background research/audit assistant via MCP. They complement, not
  compete.
- **Coming from Aider:** Ubik can use Aider as its executor adapter
  (Sprint 2 work). Your existing Aider workflow becomes the "execute"
  step in Ubik's loop.
- **Coming from Claude Code (Anthropic-billed):** Just add Z.AI base_url
  and you're paying Z.AI prices instead of Anthropic prices. Quality is
  comparable on most tasks.

The point is: nothing in your current workflow needs to change to add
Ubik. It sits next to whatever you already use.
