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
    help="Pssssst! An AI resident engineer for your codebase.",
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
    once: bool = typer.Option(False, "--once", help="Run one cycle and exit (debug)"),
) -> None:
    """Start the autonomous Ubik daemon.

    Reads `ubik.yaml`, wires the adapters, schedules research loops, and
    listens to the configured bridge for approval taps.
    """
    if not config.exists():
        console.print(f"[red]config not found: {config}[/red]")
        console.print("Run [bold]ubik init[/bold] to scaffold one, or pass --config.")
        raise typer.Exit(1)

    console.print(f"[dim]Pssssst! Ubik is reading [bold]{config}[/bold]...[/dim]")
    # TODO(sprint-1): load config, wire adapters, start scheduler.
    console.print("[yellow]daemon not implemented yet — sprint 1[/yellow]")


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
    console.print(f"[dim]Pssssst! MCP server starting ({transport})...[/dim]")
    # TODO(sprint-2): start MCP server.
    console.print("[yellow]MCP server not implemented yet — sprint 2[/yellow]")


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
        help="Write report to this path (default: stdout)",
    ),
) -> None:
    """One-shot codebase audit.

    Reads the repo, runs the researcher loop once, dumps a markdown
    report. Useful for trying Ubik without committing to a daemon.
    """
    if not repo.exists():
        console.print(f"[red]repo not found: {repo}[/red]")
        raise typer.Exit(1)

    console.print(f"[dim]Pssssst! Auditing [bold]{repo.resolve()}[/bold]...[/dim]")
    # TODO(sprint-1): run researcher in single-shot mode.
    console.print("[yellow]audit not implemented yet — sprint 1[/yellow]")


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
