"""
Ubik MCP server — Model Context Protocol surface.

Lets any MCP-compatible client (Claude Desktop, Claude Code, Cursor,
Cline, Continue.dev, …) call Ubik as a tool. Tools dispatched here:

  - ubik.audit         single-shot codebase audit
  - ubik.research      free-form research session
  - ubik.notebook.recent   list recent notebook entries
  - ubik.notebook.search   substring search across past entries
  - ubik.notebook.read     fetch a single entry by slug

Prompts (slash commands in clients that surface them):

  - ubik-audit         "audit ./<path>"
  - ubik-research      "research <topic>"
  - ubik-recent        "what did Ubik find recently?"

Transports:

  • stdio (default)            — local Claude Desktop / Claude Code / Cursor
  • streamable-http (planned)  — remote / hosted, OAuth 2.1 (Sprint 3)

Sprint 2.2 ships stdio only. HTTP wires up in 2.4.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from ubik.adapters.llm import llm_from_config
from ubik.core.config import UbikConfig, load as load_config
from ubik.core.notebook import Notebook
from ubik.core.researcher import run_audit

logger = logging.getLogger(__name__)


# ── Tool implementations (the actual handlers) ───────────────────────────


async def tool_audit(
    cfg: UbikConfig,
    notebook: Notebook,
    *,
    path: str,
    project_name: str | None = None,
    max_tokens: int = 8000,
) -> dict[str, Any]:
    """Run a single-shot audit and return the markdown report inline."""
    repo_path = Path(path).resolve()
    if not repo_path.exists() or not repo_path.is_dir():
        return {
            "status": "error",
            "error": f"path does not exist or is not a directory: {repo_path}",
        }

    llm = llm_from_config(cfg.llm.to_litellm_dict())
    result = await run_audit(
        llm=llm,
        notebook=notebook,
        repo_path=repo_path,
        project_name=project_name,
        max_tokens=max_tokens,
    )

    return {
        "status": "ok",
        "markdown": result.markdown,
        "notebook_entry": {
            "slug": result.entry.slug,
            "path": str((notebook.root / result.entry.body_path).as_posix()),
            "title": result.entry.title,
        },
        "tokens": {
            "input": result.input_tokens,
            "output": result.output_tokens,
            "thinking": result.thinking_tokens,
        },
        "snapshot": {
            "files_scanned": result.snapshot.total_files_scanned,
            "files_included": result.snapshot.total_files_included,
            "commits_read": len(result.snapshot.recent_commits),
            "languages": result.snapshot.languages,
        },
    }


def tool_notebook_recent(
    notebook: Notebook,
    *,
    n: int = 10,
    project: str | None = None,
) -> dict[str, Any]:
    entries = notebook.recent(n=n, project=project)
    return {
        "status": "ok",
        "count": len(entries),
        "entries": [
            {
                "slug": e.slug,
                "kind": e.kind,
                "project": e.project,
                "title": e.title,
                "summary": e.summary,
                "created_at": e.created_at,
                "severity": e.severity,
                "tags": e.tags,
            }
            for e in entries
        ],
    }


def tool_notebook_search(
    notebook: Notebook,
    *,
    query: str,
    kind: str | None = None,
) -> dict[str, Any]:
    entries = notebook.search(query, kind=kind)  # type: ignore[arg-type]
    return {
        "status": "ok",
        "count": len(entries),
        "query": query,
        "entries": [
            {
                "slug": e.slug,
                "kind": e.kind,
                "project": e.project,
                "title": e.title,
                "summary": e.summary,
                "created_at": e.created_at,
            }
            for e in entries
        ],
    }


def tool_notebook_read(
    notebook: Notebook,
    *,
    slug: str,
) -> dict[str, Any]:
    try:
        body = notebook.read(slug)
    except KeyError as e:
        return {"status": "error", "error": str(e)}
    return {"status": "ok", "slug": slug, "markdown": body}


# ── Server wiring ─────────────────────────────────────────────────────────


def _build_server(cfg: UbikConfig, notebook: Notebook):
    """Assemble the MCP Server with all tools + prompts registered.

    Imported lazily so `import ubik` doesn't pull in `mcp` for users who
    only run `ubik audit` from the CLI.
    """
    try:
        from mcp.server import Server
        from mcp.types import (
            GetPromptResult,
            Prompt,
            PromptArgument,
            PromptMessage,
            TextContent,
            Tool,
        )
    except ImportError as e:
        raise RuntimeError(
            "MCP server requires the 'mcp' extra: pip install ubik[mcp]"
        ) from e

    server: Server = Server("ubik")

    # ── Tool catalog (advertised to clients) ────────────────────────────

    @server.list_tools()
    async def _list_tools() -> list[Tool]:
        return [
            Tool(
                name="ubik.audit",
                description=(
                    "Run a single-shot Ubik audit on a local repository. "
                    "Reads the codebase, runs the researcher loop with extended thinking, "
                    "writes a structured markdown report (TL;DR · findings with severity / "
                    "evidence / fix / risk / ETA · open questions) into Ubik's notebook, "
                    "and returns the report inline."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Absolute or relative path to the repository.",
                        },
                        "project_name": {
                            "type": "string",
                            "description": "Override project name on the report (default: directory name).",
                        },
                        "max_tokens": {
                            "type": "integer",
                            "description": "Cap on the model's reply length. Default 8000.",
                            "default": 8000,
                        },
                    },
                    "required": ["path"],
                },
            ),
            Tool(
                name="ubik.notebook.recent",
                description=(
                    "Return the N most recent notebook entries, newest first. "
                    "Each entry carries title, summary, kind (audit/proposal/research), "
                    "severity, tags, and a stable slug to fetch the full body."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "n": {"type": "integer", "default": 10, "minimum": 1, "maximum": 100},
                        "project": {
                            "type": "string",
                            "description": "Optional filter — only entries from this project.",
                        },
                    },
                },
            ),
            Tool(
                name="ubik.notebook.search",
                description=(
                    "Substring search across past notebook entries' titles, summaries, "
                    "and tags. Returns matches newest-first."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query (substring)."},
                        "kind": {
                            "type": "string",
                            "enum": ["audit", "daily", "weekly", "monthly", "proposal", "research"],
                            "description": "Optional kind filter.",
                        },
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="ubik.notebook.read",
                description=(
                    "Fetch the full markdown body of a single notebook entry by slug. "
                    "Use after `ubik.notebook.recent` or `ubik.notebook.search` to read details."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "slug": {"type": "string", "description": "Stable notebook entry slug."},
                    },
                    "required": ["slug"],
                },
            ),
        ]

    # ── Tool dispatcher ─────────────────────────────────────────────────

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        import json

        if name == "ubik.audit":
            result = await tool_audit(cfg, notebook, **arguments)
        elif name == "ubik.notebook.recent":
            result = tool_notebook_recent(notebook, **arguments)
        elif name == "ubik.notebook.search":
            result = tool_notebook_search(notebook, **arguments)
        elif name == "ubik.notebook.read":
            result = tool_notebook_read(notebook, **arguments)
        else:
            result = {"status": "error", "error": f"unknown tool: {name}"}

        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

    # ── Prompt catalog (slash commands in supporting clients) ──────────

    @server.list_prompts()
    async def _list_prompts() -> list[Prompt]:
        return [
            Prompt(
                name="ubik-audit",
                description="Run an Ubik audit on a repo path.",
                arguments=[
                    PromptArgument(
                        name="path",
                        description="Path to the repository (default: current directory).",
                        required=False,
                    ),
                ],
            ),
            Prompt(
                name="ubik-recent",
                description="Show recent Ubik notebook entries.",
                arguments=[
                    PromptArgument(
                        name="n",
                        description="How many recent entries (default: 5).",
                        required=False,
                    ),
                ],
            ),
            Prompt(
                name="ubik-research",
                description="Ask Ubik to research a topic against the current repo.",
                arguments=[
                    PromptArgument(
                        name="topic",
                        description="What Ubik should research.",
                        required=True,
                    ),
                ],
            ),
        ]

    @server.get_prompt()
    async def _get_prompt(name: str, arguments: dict[str, str] | None) -> GetPromptResult:
        args = arguments or {}
        if name == "ubik-audit":
            path = args.get("path", ".")
            text = (
                f"Use the `ubik.audit` tool with path={path!r}. "
                f"After it returns, summarise the TL;DR + the highest-severity finding."
            )
        elif name == "ubik-recent":
            n = args.get("n", "5")
            text = (
                f"Use the `ubik.notebook.recent` tool with n={n}. "
                f"List the entries grouped by project, newest first."
            )
        elif name == "ubik-research":
            topic = args.get("topic", "")
            text = (
                f"Use the `ubik.audit` tool on the current repository, focusing the analysis on "
                f"the following topic: {topic!r}. After the audit returns, narrow the findings to "
                f"those most relevant to {topic!r}."
            )
        else:
            text = f"Unknown prompt: {name}"

        return GetPromptResult(
            description=f"Ubik prompt: {name}",
            messages=[
                PromptMessage(
                    role="user",
                    content=TextContent(type="text", text=text),
                )
            ],
        )

    return server


async def run_stdio(config_path: Path | None = None, repo_path: Path | None = None) -> None:
    """Run the Ubik MCP server over stdio. Blocks until stdin closes."""
    try:
        from mcp.server.stdio import stdio_server
    except ImportError as e:
        raise RuntimeError(
            "MCP server requires the 'mcp' extra: pip install ubik[mcp]"
        ) from e

    cfg = load_config(config_path, repo_path=repo_path)
    nb_root = (Path(cfg.project.repo_path) / cfg.notebook.path).resolve()
    notebook = Notebook(nb_root)

    server = _build_server(cfg, notebook)

    logger.info("Ubik MCP server starting (stdio) · notebook=%s · llm=%s",
                nb_root, cfg.llm.model)

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())
