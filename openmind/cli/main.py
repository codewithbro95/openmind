from __future__ import annotations

import sqlite3
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from openmind.core.config import (
    DEFAULT_LMSTUDIO_BASE_URL,
    IndexingSettings,
    ModelSettings,
    OpenMindConfig,
    ProviderSettings,
)
from openmind.core.engine import OpenMindEngine
from openmind.core.models import IndexJob
from openmind.providers.lmstudio.errors import LMStudioConnectionError, LMStudioError
from openmind.providers.lmstudio.models import LMStudioModel, split_models

app = typer.Typer(help="OpenMind local AI memory engine.")
source_app = typer.Typer(help="Manage user-approved folders.")
index_app = typer.Typer(help="Index local files.")
models_app = typer.Typer(help="Manage LM Studio models.")
provider_app = typer.Typer(help="Inspect provider status.")
app.add_typer(source_app, name="source")
app.add_typer(index_app, name="index")
app.add_typer(models_app, name="models")
app.add_typer(provider_app, name="provider")
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


@app.command("setup")
def setup_command() -> None:
    current = engine()
    paths = current.init()
    console.print("[bold]Welcome to OpenMind.[/bold]")
    console.print("OpenMind creates a private AI memory over your local files.")
    console.print("Checking local environment...")
    console.print(f"[green]✓[/green] OpenMind home: {paths.home}")
    console.print("[green]✓[/green] SQLite ready")
    console.print("[green]✓[/green] LanceDB ready")

    console.print("Choose AI provider:")
    console.print("1. LM Studio")
    provider_choice = typer.prompt("Selected", default="1")
    if provider_choice.strip() != "1":
        raise typer.BadParameter("Only LM Studio is supported in v0.2.")

    base_url = typer.prompt("LM Studio base URL", default=DEFAULT_LMSTUDIO_BASE_URL)
    config = OpenMindConfig(
        provider=ProviderSettings(name="lmstudio", base_url=base_url, api_token_env="LM_API_TOKEN"),
        models=ModelSettings(chat_model="", embedding_model=""),
        indexing=IndexingSettings(auto_start_after_setup=True, background=True),
    )
    current.save_config(config)

    console.print(f"Checking LM Studio server at {base_url}...")
    try:
        models = current.list_lmstudio_models()
    except LMStudioConnectionError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    console.print("[green]✓[/green] LM Studio server detected")
    chat_models, embedding_models = split_models(models)

    chat_model = _choose_model("Available chat models", chat_models, allow_empty=True)
    embedding_model = _choose_model("Available embedding models", embedding_models, allow_empty=False)

    config.models.chat_model = chat_model.key if chat_model else ""
    config.models.embedding_model = embedding_model.key
    current.save_config(config)

    console.print("Loading selected models...")
    try:
        client = current.lmstudio_client()
        if chat_model:
            client.load_model(chat_model.key)
            console.print("[green]✓[/green] Chat model loaded")
        else:
            console.print("[yellow]Search-only mode enabled because no chat model was selected.[/yellow]")
        client.load_model(embedding_model.key)
        console.print("[green]✓[/green] Embedding model loaded")
    except LMStudioError as exc:
        console.print(f"[yellow]{exc}[/yellow]")
        console.print("You can retry loading models with: openmind models load")

    _choose_sources(current)

    console.print("Starting background indexing...")
    job = current.start_index_job()
    console.print("[green]OpenMind setup complete.[/green]")
    console.print("Indexing has started in the background.")
    console.print(f"Job: {job.id}")
    console.print("Check progress anytime with:")
    console.print("openmind index status")


@source_app.command("add")
def source_add(path: str) -> None:
    try:
        source = engine().add_source(path)
    except (FileNotFoundError, NotADirectoryError, sqlite3.IntegrityError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    console.print(f"[green]Added source[/green] {source.id}: {source.path}")


@source_app.command("list")
def source_list() -> None:
    _print_sources(engine().list_sources())


@source_app.command("remove")
def source_remove(source_id: str) -> None:
    removed = engine().remove_source(source_id)
    if not removed:
        raise typer.BadParameter(f"Unknown source id: {source_id}")
    console.print(f"[green]Removed source[/green] {source_id}")


@index_app.callback(invoke_without_command=True)
def index_command(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is not None:
        return
    summary = engine().index()
    console.print("[green]Index complete[/green]")
    console.print(f"Files seen: {summary.files_seen}")
    console.print(f"Files indexed: {summary.files_indexed}")
    console.print(f"Files skipped: {summary.files_skipped}")
    console.print(f"Files failed: {summary.errors}")
    console.print(f"Chunks created: {summary.chunks_created}")


@index_app.command("start")
def index_start() -> None:
    job = engine().start_index_job()
    console.print("[green]Background indexing started[/green]")
    console.print(f"Job: {job.id}")
    console.print("Run: openmind index status")


@index_app.command("status")
def index_status() -> None:
    job = engine().index_job_status()
    if job is None:
        console.print("[yellow]No indexing job has been started.[/yellow]")
        return
    _print_index_job(job)


@index_app.command("pause")
def index_pause() -> None:
    job = engine().pause_index_job()
    if job is None:
        console.print("[yellow]No indexing job has been started.[/yellow]")
        return
    console.print(f"Indexing status: {job.status}")


@index_app.command("resume")
def index_resume() -> None:
    job = engine().resume_index_job()
    if job is None:
        console.print("[yellow]No indexing job has been started.[/yellow]")
        return
    console.print(f"Indexing status: {job.status}")


@index_app.command("stop")
def index_stop() -> None:
    job = engine().stop_index_job()
    if job is None:
        console.print("[yellow]No indexing job has been started.[/yellow]")
        return
    console.print(f"Indexing status: {job.status}")


@index_app.command("worker", hidden=True)
def index_worker(job_id: str) -> None:
    final_job = engine().run_index_worker(job_id)
    console.print(f"Index worker finished with status: {final_job.status}")


@models_app.command("list")
def models_list() -> None:
    try:
        models = engine().list_lmstudio_models()
    except LMStudioConnectionError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    _print_models("LM Studio models", models)


@models_app.command("load")
def models_load(model_key: str | None = typer.Argument(None)) -> None:
    current = engine()
    try:
        if model_key:
            current.lmstudio_client().load_model(model_key)
            console.print(f"[green]Loaded model[/green] {model_key}")
        else:
            loaded = current.load_configured_models()
            console.print(f"[green]Loaded configured models[/green] ({len(loaded)})")
    except LMStudioError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc


@provider_app.command("status")
def provider_status() -> None:
    ok, message = engine().provider_status()
    color = "green" if ok else "yellow"
    console.print(f"[{color}]{message}[/{color}]")


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


def _choose_model(
    title: str,
    models: list[LMStudioModel],
    allow_empty: bool,
) -> LMStudioModel | None:
    if not models:
        if allow_empty:
            console.print("[yellow]No chat model found. Continuing in search-only mode.[/yellow]")
            return None
        console.print("[red]No embedding model found in LM Studio.[/red]")
        console.print("OpenMind needs an embedding model to build local memory.")
        console.print("Download one manually in LM Studio, then run setup again.")
        raise typer.Exit(1)

    console.print(title + ":")
    for index, model in enumerate(models, start=1):
        loaded = " loaded" if model.is_loaded else ""
        console.print(f"{index}. {model.display_name} ({model.key}){loaded}")
    choice = typer.prompt("Choose model", default="1")
    try:
        selected_index = int(choice) - 1
        return models[selected_index]
    except (ValueError, IndexError) as exc:
        raise typer.BadParameter("Invalid model selection.") from exc


def _choose_sources(current: OpenMindEngine) -> None:
    candidates = [
        Path("~/Documents").expanduser(),
        Path("~/Downloads").expanduser(),
        Path("~/Desktop").expanduser(),
    ]
    available = [path for path in candidates if path.exists() and path.is_dir()]
    console.print("Choose folders to index:")
    for index, path in enumerate(available, start=1):
        console.print(f"{index}. {path}")
    console.print(f"{len(available) + 1}. Add custom folder")
    raw = typer.prompt("Selected numbers, comma separated", default="1")
    selected_paths: list[Path] = []
    for part in [value.strip() for value in raw.split(",") if value.strip()]:
        try:
            index = int(part)
        except ValueError as exc:
            raise typer.BadParameter(f"Invalid folder selection: {part}") from exc
        if 1 <= index <= len(available):
            selected_paths.append(available[index - 1])
        elif index == len(available) + 1:
            selected_paths.append(Path(typer.prompt("Custom folder")).expanduser())
    for path in selected_paths:
        try:
            source = current.add_source(str(path))
            console.print(f"[green]✓[/green] {source.path}")
        except sqlite3.IntegrityError:
            console.print(f"[green]✓[/green] {path} already added")


def _print_sources(sources) -> None:
    table = Table(title="Sources")
    table.add_column("ID")
    table.add_column("Path")
    table.add_column("Recursive")
    table.add_column("Enabled")
    for source in sources:
        table.add_row(source.id, source.path, str(source.recursive), str(source.enabled))
    console.print(table)


def _print_models(title: str, models: list[LMStudioModel]) -> None:
    table = Table(title=title)
    table.add_column("Type")
    table.add_column("Key")
    table.add_column("Name")
    table.add_column("Loaded")
    table.add_column("Context")
    for model in models:
        table.add_row(
            model.type,
            model.key,
            model.display_name,
            str(model.is_loaded),
            str(model.max_context_length or ""),
        )
    console.print(table)


def _print_index_job(job: IndexJob) -> None:
    table = Table(title="Indexing Status")
    table.add_column("Metric")
    table.add_column("Value")
    table.add_row("Job", job.id)
    table.add_row("State", job.status)
    table.add_row("Files discovered", str(job.total_files))
    table.add_row("Files processed", str(job.processed_files))
    table.add_row("Files indexed", str(job.indexed_files))
    table.add_row("Files skipped", str(job.skipped_files))
    table.add_row("Files failed", str(job.failed_files))
    table.add_row("Chunks created", str(job.total_chunks))
    table.add_row("Progress", f"{job.progress_percent:.1f}%")
    table.add_row("Current file", job.current_file or "")
    if job.error:
        table.add_row("Error", job.error)
    console.print(table)


if __name__ == "__main__":
    app()
