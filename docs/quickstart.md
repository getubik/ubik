# Quickstart

## Install

```bash
pip install psssst              # core (PyPI name; `ubik` was squatted in 2014)
pip install psssst[mcp]         # + MCP server
pip install psssst[telegram]    # + Telegram bridge
pip install psssst[all]         # everything
```

The CLI command is still `ubik` and `import ubik` still works — only the
PyPI distribution name is `psssst`.

## Initialize a project

```bash
cd my-repo
ubik init               # scaffolds ubik.yaml
$EDITOR ubik.yaml       # set LLM endpoint, Telegram token, etc.
```

## Three ways to run

### 1. Autonomous daemon

```bash
ubik run
```

Background process, scheduled research, Telegram approval flow. Best for
long-running projects you actively maintain.

### 2. MCP server (Claude Desktop / Cursor)

```bash
ubik mcp
```

Add to your Claude Desktop config:

```json
{
  "mcpServers": {
    "ubik": {
      "command": "ubik",
      "args": ["mcp"],
      "env": {
        "Z_AI_API_KEY": "..."
      }
    }
  }
}
```

Then in Claude Desktop:

> *"Ubik, audit the repo I'm in and propose three improvements."*

### 3. One-shot audit

```bash
ubik audit ./my-repo --output report.md
```

No daemon, no Telegram — just run, read the report, exit.

## Minimum viable config

```yaml
# ubik.yaml
project:
  name: "my-repo"
  repo_path: "."

researcher:
  llm:
    base_url: "https://api.z.ai/api/coding/paas/v4"
    api_key_env: "Z_AI_API_KEY"
    model: "glm-5.1"

bridge:
  type: "telegram"
  token_env: "TELEGRAM_BOT_TOKEN"
  approver_chat_ids: [YOUR_TELEGRAM_USER_ID]
```

That's it. `ubik run` does the rest.
