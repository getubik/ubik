"""
Ubik CLI — entry points for the autonomous daemon and the MCP server.

Three commands, one binary:

    ubik run           # autonomous mode: schedule + bridge + executor
    ubik mcp           # MCP server: stdio (default) or HTTP
    ubik audit         # one-shot: scan a repo, dump a markdown report

The MCP server can also be invoked directly via:
    python -m ubik.mcp.server
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

app = typer.Typer(
    name="ubik",
    help="Ubik — an AI resident engineer for your codebase. (Pssst!)",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


@app.command()
def run(
    config: Path = typer.Option(
        Path("ubik.yaml"),
        "--config",
        "-c",
        help="Path to ubik.yaml (default: ./ubik.yaml)",
    ),
    repo: Optional[Path] = typer.Option(
        None,
        "--repo",
        help="Override the repo path the daemon watches (default: from config).",
    ),
    daily_at: str = typer.Option(
        "09:00",
        "--daily-at",
        help="Local time HH:MM for the daily audit cycle.",
    ),
    pulse_minutes: int = typer.Option(
        0,
        "--pulse-minutes",
        help="If > 0, fire a quick pulse cycle every N minutes (Sprint 5).",
    ),
    notebook_path: Optional[Path] = typer.Option(
        None,
        "--notebook",
        help="Override notebook root (default: <repo>/research).",
    ),
    poll_offset_file: Path = typer.Option(
        Path("/var/lib/ubik/poll-offset"),
        "--poll-offset-file",
        help="Where to persist the Telegram update_id between restarts.",
    ),
    min_severity: str = typer.Option(
        "medium",
        "--min-severity",
        help="Floor severity for proposals (low/medium/high/critical).",
    ),
) -> None:
    """Start the autonomous Ubik daemon.

    Wires adapters, runs a daily Researcher cycle, and concurrently
    long-polls the bridge for approval taps. Produces Proposals from
    audit findings, publishes them to Telegram, and on ✅ ships fixes
    via the Executor + Verifier pipeline.

    Stop with Ctrl-C (sends a "going quiet" notification, drains
    in-flight tasks).
    """
    import asyncio
    import logging

    from ubik.core.config import load as load_config
    from ubik.core.daemon import Daemon, DaemonConfig

    cfg = load_config(config if config.exists() else None, repo_path=repo)
    if not cfg.project.repo_path:
        console.print(
            "[red]No repo path. Pass --repo or set project.repo_path in ubik.yaml.[/red]"
        )
        raise typer.Exit(1)

    nb_root = notebook_path or (Path(cfg.project.repo_path) / cfg.notebook.path).resolve()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s · %(name)s · %(levelname)s · %(message)s",
    )

    daemon_cfg = DaemonConfig(
        daily_at=daily_at,
        pulse_minutes=pulse_minutes,
        approval_poll_offset=str(poll_offset_file),
        min_proposal_severity=min_severity,
    )

    console.print(
        f"[dim]🤫 Ubik · daemon waking up · "
        f"watching [bold]{cfg.project.repo_path}[/bold] · "
        f"daily audit @ [cyan]{daily_at}[/cyan][/dim]"
    )

    try:
        daemon = Daemon(
            config=cfg,
            notebook_root=nb_root,
            daemon_config=daemon_cfg,
        )
    except RuntimeError as e:
        console.print(f"[red]Daemon setup failed: {e}[/red]")
        raise typer.Exit(2) from e

    try:
        asyncio.run(daemon.run())
    except KeyboardInterrupt:
        console.print("\n[dim]Ubik · received Ctrl-C, shutting down…[/dim]")


@app.command()
def mcp(
    transport: str = typer.Option(
        "stdio",
        "--transport",
        "-t",
        help="MCP transport: stdio (default) or http",
    ),
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(3000, "--port"),
    config: Optional[Path] = typer.Option(
        None,
        "--config",
        help="Optional ubik.yaml — without it, MCP runs read-only",
    ),
) -> None:
    """Run as an MCP server.

    Exposed tools:
        ubik.research(topic)
        ubik.audit_repo(scope)
        ubik.propose_fix(issue)
        ubik.notebook.search(query)
        ubik.notebook.recent(n)

    Plug into Claude Desktop / Cursor / Continue.dev via the standard
    `mcpServers` config.
    """
    if transport != "stdio":
        console.print(
            f"[yellow]transport={transport!r} not yet implemented "
            f"(stdio only in Sprint 2.2; HTTP lands in Sprint 2.4)[/yellow]"
        )
        raise typer.Exit(2)

    import asyncio
    import logging

    from ubik.mcp.server import run_stdio

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s · %(name)s · %(levelname)s · %(message)s",
    )

    # stderr banner — stdout MUST stay clean for the JSON-RPC protocol.
    import sys
    print("🤫 Ubik · MCP server (stdio) ready", file=sys.stderr)

    try:
        asyncio.run(run_stdio(config_path=config))
    except KeyboardInterrupt:
        print("Ubik MCP server stopped.", file=sys.stderr)
    except RuntimeError as e:
        console.print(f"[red]MCP server failed: {e}[/red]")
        raise typer.Exit(3) from e


@app.command()
def audit(
    repo: Path = typer.Argument(
        Path("."),
        help="Path to the repository (default: current directory)",
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Write report to this path in addition to the notebook",
    ),
    config: Optional[Path] = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to ubik.yaml (default: ./ubik.yaml in repo, or env-only)",
    ),
    project_name: Optional[str] = typer.Option(
        None, "--project", help="Override project name in the report"
    ),
    notebook_path: Optional[Path] = typer.Option(
        None, "--notebook", help="Override notebook root (default: ./research in repo)"
    ),
    max_tokens: int = typer.Option(
        8000, "--max-tokens", help="Cap on the model's reply length"
    ),
    notify: Optional[str] = typer.Option(
        None,
        "--notify",
        help="After audit, push a digest to a bridge: 'telegram' (uses TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID env vars).",
    ),
) -> None:
    """One-shot codebase audit.

    Reads the repo, runs the researcher loop once, persists a markdown
    report into the notebook. Useful for trying Ubik without committing
    to a daemon.
    """
    if not repo.exists():
        console.print(f"[red]repo not found: {repo}[/red]")
        raise typer.Exit(1)

    import asyncio
    import logging

    from ubik.adapters.llm import llm_from_config
    from ubik.core.config import load as load_config
    from ubik.core.notebook import Notebook
    from ubik.core.researcher import run_audit

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s · %(name)s · %(levelname)s · %(message)s",
    )

    cfg = load_config(config, repo_path=repo)
    nb_root = notebook_path or (Path(cfg.project.repo_path) / cfg.notebook.path).resolve()
    notebook = Notebook(nb_root)

    llm = llm_from_config(cfg.llm.to_litellm_dict())

    console.print(
        f"[dim]🤫 Ubik · auditing [bold]{repo.resolve()}[/bold] "
        f"with [cyan]{cfg.llm.model}[/cyan]…[/dim]"
    )

    try:
        result = asyncio.run(
            run_audit(
                llm=llm,
                notebook=notebook,
                repo_path=repo,
                project_name=project_name,
                max_tokens=max_tokens,
            )
        )
    except RuntimeError as e:
        console.print(f"[red]audit failed: {e}[/red]")
        raise typer.Exit(2) from e

    body_path = nb_root / result.entry.body_path
    console.print()
    console.print(f"[green]✅ Audit saved → [bold]{body_path}[/bold][/green]")
    console.print(
        f"   tokens: in={result.input_tokens} out={result.output_tokens} "
        f"thinking={result.thinking_tokens}"
    )

    if output:
        Path(output).write_text(result.markdown, encoding="utf-8")
        console.print(f"   also written → {output}")

    head = "\n".join(result.markdown.splitlines()[:30])
    console.print()
    console.print("[dim]── preview (first 30 lines) ──[/dim]")
    console.print(head)
    console.print("[dim]── /preview ──[/dim]")

    # ── optional bridge notify ──────────────────────────────────────────
    if notify:
        from ubik.adapters.bridge import NotifyMessage, Severity
        from ubik.core.summarize import digest_audit, render_telegram_body

        digest = digest_audit(result.markdown, fallback_title=result.entry.title)

        # Severity = highest individual finding severity, else low.
        sev = Severity.LOW
        for level in (Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM):
            if digest.severities.get(level.value, 0) > 0:
                sev = level
                break

        body = render_telegram_body(digest)
        msg = NotifyMessage(
            title=digest.title,
            body_markdown=body,
            footer=f"ubik audit · {result.entry.project} · "
                   f"in={result.input_tokens} out={result.output_tokens} "
                   f"thinking={result.thinking_tokens}",
            severity=sev,
            tags=["audit"],
        )

        if notify == "telegram":
            from ubik.adapters.bridge.telegram import telegram_from_env
            try:
                bridge = telegram_from_env()
            except RuntimeError as e:
                console.print(f"[red]notify=telegram failed: {e}[/red]")
                raise typer.Exit(3) from e
            asyncio.run(bridge.notify(msg))
            console.print(f"[green]→ Telegram notified[/green] (chat id from env)")
        else:
            console.print(f"[red]unknown --notify target: {notify}[/red]")
            raise typer.Exit(4)


@app.command()
def init() -> None:
    """Scaffold a `ubik.yaml` in the current directory.

    Copies the example config from the package and walks you through the
    adapter choices interactively.
    """
    target = Path("ubik.yaml")
    if target.exists():
        console.print(f"[yellow]{target} already exists — refusing to overwrite[/yellow]")
        raise typer.Exit(1)

    # TODO(sprint-1): copy ubik.example.yaml from package data, ask
    # interactive questions to fill in.
    console.print("[yellow]init not implemented yet — sprint 1[/yellow]")


def main() -> None:
    """Entry point referenced by pyproject.toml's [project.scripts]."""
    app()


if __name__ == "__main__":
    main()
