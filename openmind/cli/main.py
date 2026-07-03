from __future__ import annotations

import sqlite3
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from openmind.core.engine import OpenMindEngine

app = typer.Typer(help="OpenMind local AI memory engine.")
source_app = typer.Typer(help="Manage user-approved folders.")
app.add_typer(source_app, name="source")
console = Console()


def engine() -> OpenMindEngine:
    return OpenMindEngine()


@app.command("init")
def init_command() -> None:
    paths = engine().init()
    console.print("[green]OpenMind initialized[/green]")
    console.print(f"Home: {paths.home}")
    console.print(f"SQLite: {paths.sqlite_path}")
    console.print(f"LanceDB: {paths.lancedb_path}")


@source_app.command("add")
def source_add(path: str) -> None:
    try:
        source = engine().add_source(path)
    except (FileNotFoundError, NotADirectoryError, sqlite3.IntegrityError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    console.print(f"[green]Added source[/green] {source.id}: {source.path}")


@source_app.command("list")
def source_list() -> None:
    sources = engine().list_sources()
    table = Table(title="Sources")
    table.add_column("ID")
    table.add_column("Path")
    table.add_column("Recursive")
    table.add_column("Enabled")
    for source in sources:
        table.add_row(source.id, source.path, str(source.recursive), str(source.enabled))
    console.print(table)


@source_app.command("remove")
def source_remove(source_id: str) -> None:
    removed = engine().remove_source(source_id)
    if not removed:
        raise typer.BadParameter(f"Unknown source id: {source_id}")
    console.print(f"[green]Removed source[/green] {source_id}")


@app.command("index")
def index_command() -> None:
    summary = engine().index()
    console.print("[green]Index complete[/green]")
    console.print(f"Files seen: {summary.files_seen}")
    console.print(f"Files indexed: {summary.files_indexed}")
    console.print(f"Files skipped: {summary.files_skipped}")
    console.print(f"Errors: {summary.errors}")


@app.command("search")
def search_command(query: str, limit: int = typer.Option(5, min=1, max=50)) -> None:
    results = engine().search(query, limit=limit)
    if not results:
        console.print("[yellow]No matches found.[/yellow]")
        return
    for index, result in enumerate(results, start=1):
        display_path = str(Path(result.path).expanduser())
        console.print(f"[bold]{index}. {display_path}[/bold]")
        console.print(f"   Score: {result.score:.2f}")
        console.print(f"   Snippet: {result.snippet}")


@app.command("ask")
def ask_command(question: str, limit: int = typer.Option(5, min=1, max=20)) -> None:
    console.print(engine().ask(question, limit=limit))


@app.command("status")
def status_command() -> None:
    status = engine().status()
    table = Table(title="OpenMind Status")
    table.add_column("Metric")
    table.add_column("Value")
    table.add_row("App home", status.app_home)
    table.add_row("Sources", str(status.sources))
    table.add_row("Enabled sources", str(status.enabled_sources))
    table.add_row("Files", str(status.files))
    table.add_row("Indexed files", str(status.indexed_files))
    console.print(table)


if __name__ == "__main__":
    app()
