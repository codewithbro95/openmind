from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import questionary
import typer
from questionary import Choice, Style
from rich.console import Console
from rich.live import Live
from rich.progress import Progress
from rich.prompt import Prompt
from rich.table import Table

from openmind import __version__
from openmind.core.config import (
    DEFAULT_IMAGE_DESCRIPTION_MODEL,
    DEFAULT_LMSTUDIO_BASE_URL,
    IndexingSettings,
    ModelSettings,
    OpenMindConfig,
    ProviderSettings,
)
from openmind.core.engine import OpenMindEngine
from openmind.core.errors import SourceRemovalBlockedError
from openmind.core.models import IndexJob, IndexSummary
from openmind.providers.lmstudio.errors import LMStudioConnectionError, LMStudioError
from openmind.providers.lmstudio.models import LMStudioModel, split_models, vision_models

app = typer.Typer(help="OpenMind local AI memory engine.")
source_app = typer.Typer(help="Manage user-approved folders.")
index_app = typer.Typer(help="Index local files.")
models_app = typer.Typer(help="Manage LM Studio models.")
provider_app = typer.Typer(help="Inspect provider status.")
dev_app = typer.Typer(help="Developer tools.")
api_app = typer.Typer(help="Manage local API access.")
app.add_typer(source_app, name="source")
app.add_typer(index_app, name="index")
app.add_typer(models_app, name="models")
app.add_typer(provider_app, name="provider")
app.add_typer(dev_app, name="dev")
app.add_typer(api_app, name="api")
console = Console()

OPENMIND_BANNER = r"""
  ___                   __  __ _           _
 / _ \ _ __   ___ _ __ |  \/  (_)_ __   __| |
| | | | '_ \ / _ \ '_ \| |\/| | | '_ \ / _` |
| |_| | |_) |  __/ | | | |  | | | | | | (_| |
 \___/| .__/ \___|_| |_|_|  |_|_|_| |_|\__,_|
      |_|
""".strip("\n")

PROMPT_STYLE = Style(
    [
        ("qmark", "fg:#00d7af bold"),
        ("question", "bold"),
        ("answer", "fg:#00d7af bold"),
        ("pointer", "fg:#00d7af bold"),
        ("highlighted", "fg:#00d7af bold"),
        ("selected", "fg:#00d7af"),
        ("instruction", "fg:#808080"),
    ]
)

NO_MODEL = "__openmind_no_model__"
CUSTOM_FOLDER = "__openmind_custom_folder__"


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"openmind {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show the installed OpenMind version and exit.",
    ),
) -> None:
    pass


def engine() -> OpenMindEngine:
    return OpenMindEngine()


@app.command("init", help="Initialize OpenMind's local app data.")
def init_command() -> None:
    paths = engine().init()
    console.print("[green]OpenMind initialized[/green]")
    console.print(f"Home: {paths.home}")
    console.print(f"SQLite: {paths.sqlite_path}")
    console.print(f"LanceDB: {paths.lancedb_path}")


@app.command("setup", help="Configure models, sources, and background indexing.")
def setup_command() -> None:
    current = engine()
    paths = current.init()
    console.print(f"[bold cyan]{OPENMIND_BANNER}[/bold cyan]")
    console.print("[bold]Welcome to OpenMind.[/bold]")
    console.print("OpenMind creates a private AI memory over your local files.")
    console.print("Checking local environment...")
    console.print(f"[green]✓[/green] OpenMind home: {paths.home}")
    console.print("[green]✓[/green] SQLite ready")
    console.print("[green]✓[/green] LanceDB ready")

    provider_choice = _select_prompt(
        "Choose AI provider",
        choices=[Choice("LM Studio", value="lmstudio")],
        default="lmstudio",
    )
    if provider_choice != "lmstudio":
        raise typer.BadParameter("Only LM Studio is supported right now.")

    base_url = _text_prompt("LM Studio base URL", default=DEFAULT_LMSTUDIO_BASE_URL)
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
    image_models = vision_models(models)

    chat_model = _choose_model("Available chat models", chat_models, allow_empty=True)
    embedding_model = _choose_model(
        "Available embedding models",
        embedding_models,
        allow_empty=False,
    )
    image_model = _choose_image_model(image_models, chat_models)

    config.models.chat_model = chat_model.key if chat_model else ""
    config.models.embedding_model = embedding_model.key
    config.extraction.images.enabled = image_model is not None
    config.extraction.images.model = (
        image_model.key if image_model else DEFAULT_IMAGE_DESCRIPTION_MODEL
    )
    current.save_config(config)

    console.print("Loading selected models...")
    try:
        client = current.lmstudio_client()
        if chat_model:
            _load_lmstudio_model(client, chat_model.key, "Chat model")
        else:
            console.print("[yellow]Search-only mode enabled because no chat model was selected.[/yellow]")
        _load_lmstudio_model(client, embedding_model.key, "Embedding model")
        if image_model:
            _load_lmstudio_model(client, image_model.key, "Image description model")
        else:
            console.print(
                "[yellow]Image indexing disabled because no vision model was selected.[/yellow]"
            )
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
    current = engine()
    try:
        source = current.add_source(path)
    except sqlite3.IntegrityError:
        _print_existing_source_status(current, path)
        return
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    console.print(f"[green]Added source[/green] {source.id}: {source.path}")


@source_app.command("list")
def source_list() -> None:
    _print_sources(engine().list_sources())


@source_app.command(
    "remove",
    help="Remove a source and its indexed memory without deleting user files.",
)
def source_remove(source_id: str) -> None:
    try:
        result = engine().remove_source(source_id)
    except SourceRemovalBlockedError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    if result is None:
        raise typer.BadParameter(f"Unknown source id: {source_id}")
    console.print(f"[green]Removed source[/green] {result.source_id}")
    console.print(f"File records removed: {result.files_removed}")
    console.print(f"Memory chunks removed: {result.chunks_removed}")
    console.print(f"Original folder and files were not deleted: {result.source_path}")


@index_app.callback(invoke_without_command=True)
def index_command(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is not None:
        return
    current = engine()
    current.init()
    summary = IndexSummary()
    console.print("Discovering supported files...")
    records = current.discover_files()
    summary.files_seen = len(records)
    console.print(f"Discovered {len(records)} supported file(s).")
    issues: list[tuple[str, str, str]] = []
    with Progress(console=console) as progress:
        task = progress.add_task("Checking files", total=len(records))
        for file_record in records:
            progress.update(task, description=f"Checking {file_record.name}")
            file_summary = current._index_file(file_record)
            summary.files_indexed += file_summary.files_indexed
            summary.files_skipped += file_summary.files_skipped
            summary.files_already_indexed += file_summary.files_already_indexed
            summary.errors += file_summary.errors
            summary.chunks_created += file_summary.chunks_created
            if file_record.status in {"skipped", "error"} and file_record.error:
                issues.append((file_record.status, file_record.path, file_record.error))
            progress.advance(task)
    console.print("[green]Index complete[/green]")
    console.print(f"Files seen: {summary.files_seen}")
    console.print(f"Files indexed: {summary.files_indexed}")
    console.print(f"Files skipped: {summary.files_skipped}")
    console.print(f"Files already indexed: {summary.files_already_indexed}")
    console.print(f"Files failed: {summary.errors}")
    console.print(f"Chunks created: {summary.chunks_created}")
    if summary.files_already_indexed:
        console.print(
            "[green]"
            f"{summary.files_already_indexed} unchanged file(s) were already indexed "
            "and are accessible in OpenMind."
            "[/green]"
        )
    if issues:
        console.print("[yellow]Files needing attention:[/yellow]")
        for status, path, error in issues:
            console.print(f"- {status}: {path}")
            console.print(f"  {error}")


@index_app.command("start")
def index_start() -> None:
    job = engine().start_index_job()
    console.print("[green]Background indexing started[/green]")
    console.print(f"Job: {job.id}")
    console.print("Run: openmind index status")


@index_app.command("status")
def index_status(
    once: bool = typer.Option(False, "--once", help="Print the current status once and exit."),
    refresh: float = typer.Option(1.0, min=0.2, help="Seconds between live status updates."),
) -> None:
    current = engine()
    job = current.index_job_status()
    if job is None:
        console.print("[yellow]No indexing job has been started.[/yellow]")
        return
    if once:
        console.print(_index_job_table(job))
        return

    try:
        with Live(_index_job_table(job), console=console, refresh_per_second=4) as live:
            while True:
                updated = current.index_job_status()
                if updated is None:
                    live.update("[yellow]No indexing job has been started.[/yellow]")
                else:
                    live.update(_index_job_table(updated))
                time.sleep(refresh)
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopped watching indexing status.[/yellow]")


@index_app.command("pause")
def index_pause() -> None:
    job = engine().pause_index_job()
    if job is None:
        console.print("[yellow]No indexing job has been started.[/yellow]")
        return
    if job.status == "pause_requested":
        console.print("Pause requested. Indexing will pause after the current file finishes.")
    else:
        console.print(f"Indexing status: {job.status}")


@index_app.command("resume")
def index_resume() -> None:
    job = engine().resume_index_job()
    if job is None:
        console.print("[yellow]No indexing job has been started.[/yellow]")
        return
    if job.status == "running":
        console.print("Indexing resumed.")
    else:
        console.print(f"Indexing status: {job.status}")


@index_app.command("stop")
def index_stop() -> None:
    job = engine().stop_index_job()
    if job is None:
        console.print("[yellow]No indexing job has been started.[/yellow]")
        return
    if job.status == "stop_requested":
        console.print("Stop requested. Indexing will stop after the current file finishes.")
    else:
        console.print(f"Indexing status: {job.status}")


@index_app.command("worker", hidden=True)
def index_worker(job_id: str = typer.Option(..., "--job-id")) -> None:
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
            _load_lmstudio_model(current.lmstudio_client(), model_key, "Model")
        else:
            results = current.load_configured_models()
            _print_model_load_summary(results)
    except LMStudioError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc


@models_app.command("update")
def models_update(
    load: bool = typer.Option(
        True,
        "--load/--no-load",
        help="Load the newly selected models after saving them.",
    ),
) -> None:
    current = engine()
    current.init()
    config = current.config.model_copy(deep=True)
    current_provider_name = config.provider.name
    current_chat_model = config.models.chat_model if current_provider_name == "lmstudio" else ""
    current_embedding_model = (
        config.models.embedding_model if current_provider_name == "lmstudio" else ""
    )
    current_image_model = (
        config.extraction.images.model
        if current_provider_name == "lmstudio" and config.extraction.images.enabled
        else ""
    )

    provider_choice = _select_prompt(
        "Choose AI provider",
        choices=[Choice("LM Studio", value="lmstudio")],
        default="lmstudio",
    )
    if provider_choice != "lmstudio":
        raise typer.BadParameter("Only LM Studio is supported right now.")

    default_base_url = (
        config.provider.base_url
        if config.provider.name == "lmstudio"
        else DEFAULT_LMSTUDIO_BASE_URL
    )
    base_url = _text_prompt("LM Studio base URL", default=default_base_url)
    config.provider = ProviderSettings(
        name="lmstudio",
        base_url=base_url,
        api_token_env=config.provider.api_token_env or "LM_API_TOKEN",
    )
    console.print(f"Fetching LM Studio models from {base_url}...")
    try:
        models = current.lmstudio_client(config).list_models()
    except LMStudioConnectionError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    chat_models, embedding_models = split_models(models)
    image_models = vision_models(models)
    chat_model_key = _choose_model_key(
        "Available chat models",
        chat_models,
        allow_empty=True,
        current_key=current_chat_model,
    )
    embedding_model_key = _choose_model_key(
        "Available embedding models",
        embedding_models,
        allow_empty=False,
        current_key=current_embedding_model,
    )
    image_model_key = _choose_model_key(
        "Available image description models",
        image_models,
        allow_empty=True,
        current_key=current_image_model,
        empty_label="Disable image indexing",
        missing_message=(
            "No vision model was detected in LM Studio. Image indexing will stay disabled."
        ),
    )

    config.models.chat_model = chat_model_key
    config.models.embedding_model = embedding_model_key
    config.extraction.images.enabled = bool(image_model_key)
    config.extraction.images.model = image_model_key or DEFAULT_IMAGE_DESCRIPTION_MODEL
    try:
        transition = current.update_model_config(config, load=load)
    except LMStudioError as exc:
        console.print(f"[yellow]{exc}[/yellow]")
        if current.config == config:
            console.print("The new selection was saved. Retry loading with: openmind models load")
        else:
            console.print("The model update was not completed. Check LM Studio and try again.")
        return

    console.print("[green]Saved model configuration.[/green]")
    if not load:
        console.print("Run `openmind models load` when you are ready to load the selected models.")
        return

    _print_model_unload_summary(transition.unload_results)
    if not chat_model_key:
        console.print("[yellow]Search-only mode enabled because no chat model was selected.[/yellow]")
    if not image_model_key:
        console.print("[yellow]Image indexing disabled.[/yellow]")
    _print_model_load_summary(transition.load_results)


@provider_app.command("status")
def provider_status() -> None:
    ok, message = engine().provider_status()
    color = "green" if ok else "yellow"
    console.print(f"[{color}]{message}[/{color}]")


@app.command("serve", help="Start the authenticated local OpenMind API.")
def serve_command(
    port: int = typer.Option(8765, min=1, max=65535, help="Local API port."),
    allow_origin: list[str] | None = typer.Option(
        None,
        "--allow-origin",
        help="Allow an exact browser origin. Repeat for multiple origins; wildcards are refused.",
    ),
) -> None:
    from openmind.api.app import create_app
    from openmind.api.auth import ensure_api_token, token_path

    current = engine()
    current.init()
    ensure_api_token(current.paths.home)
    origins = [_validate_api_origin(origin) for origin in (allow_origin or [])]

    console.print("[bold]OpenMind local API[/bold]")
    console.print(f"Server: http://127.0.0.1:{port}")
    console.print(f"Docs: http://127.0.0.1:{port}/docs")
    console.print(f"API token: {token_path(current.paths.home)}")
    console.print("The server accepts local connections only. Press Ctrl+C to stop.")

    import uvicorn

    uvicorn.run(
        create_app(
            engine=current,
            allowed_origins=origins,
        ),
        host="127.0.0.1",
        port=port,
        log_level="info",
        access_log=False,
    )


@api_app.command("token", help="Show or rotate the local API bearer token.")
def api_token_command(
    rotate: bool = typer.Option(
        False,
        "--rotate",
        help="Replace the API token and invalidate existing client credentials.",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip rotation confirmation."),
) -> None:
    from openmind.api.auth import ensure_api_token, rotate_api_token

    current = engine()
    current.init()
    if rotate:
        if not yes and not typer.confirm(
            "Rotate the API token and disconnect clients using the current token?",
            default=False,
        ):
            console.print("[yellow]Token rotation cancelled.[/yellow]")
            return
        token = rotate_api_token(current.paths.home)
        console.print("[green]API token rotated.[/green]")
    else:
        token = ensure_api_token(current.paths.home)
    console.print(token, markup=False, highlight=False)


@dev_app.command("logs")
def dev_logs(
    follow: bool = typer.Option(True, "--follow/--no-follow", help="Keep watching for new log lines."),
    lines: int = typer.Option(80, min=1, max=1000, help="Number of recent lines to show first."),
    log: str = typer.Option(
        "openmind",
        "--log",
        help="Which OpenMind log to show: openmind, index, or all.",
    ),
    lm_studio: bool = typer.Option(
        False,
        "--lm-studio",
        help="Run LM Studio's `lms log stream` instead of OpenMind log files.",
    ),
) -> None:
    if lm_studio:
        _stream_lmstudio_logs()
        return

    current = engine()
    current.init()
    log_files = _select_log_files(current.paths.logs_path, log)
    if not log_files:
        console.print(f"[yellow]No log files found in {current.paths.logs_path}[/yellow]")
        return
    _tail_log_files(log_files, lines=lines, follow=follow)


@app.command("search", help="Search indexed local memory.")
def search_command(query: str, limit: int = typer.Option(5, min=1, max=50)) -> None:
    try:
        results = engine().search(query, limit=limit)
    except LMStudioError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    if not results:
        console.print("[yellow]No matches found.[/yellow]")
        return
    for index, result in enumerate(results, start=1):
        display_path = str(Path(result.path).expanduser())
        console.print(f"[bold]{index}. {display_path}[/bold]")
        console.print(f"   Score: {result.score:.2f}")
        console.print(f"   Snippet: {result.snippet}")


@app.command("ask", help="Ask grounded questions or start an interactive session.")
def ask_command(
    question: str | None = typer.Argument(None),
    limit: int = typer.Option(5, min=1, max=20),
    stream: bool = typer.Option(True, "--stream/--no-stream", help="Stream answer tokens."),
    show_thinking: bool = typer.Option(
        False,
        "--show-thinking",
        help="Show provider-returned thinking/reasoning when the model exposes it.",
    ),
) -> None:
    if question is None:
        _interactive_ask(limit=limit, stream=stream, show_thinking=show_thinking)
        return

    try:
        current = engine()
        if stream:
            for chunk in current.ask_stream(
                question,
                limit=limit,
                show_thinking=show_thinking,
            ):
                console.print(chunk, end="", markup=False, highlight=False, soft_wrap=True)
            console.print()
        else:
            console.print(current.ask(question, limit=limit, show_thinking=show_thinking))
    except LMStudioError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc


@app.command("status", help="Show OpenMind storage and indexing information.")
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


@app.command("flush", help="Clear indexed memory without deleting user files.")
def flush_command(
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip the confirmation prompt.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would be removed without deleting anything.",
    ),
    include_sources: bool = typer.Option(
        False,
        "--include-sources",
        help="Also remove saved source folder records. User files are never deleted.",
    ),
    wait: float = typer.Option(
        10.0,
        "--wait",
        min=0.0,
        help="Seconds to wait for an active index job to stop.",
    ),
) -> None:
    current = engine()
    home = current.paths.home.expanduser().resolve()
    _validate_uninstall_home(home)

    console.print("[bold]OpenMind flush[/bold]")
    console.print("This clears OpenMind's indexed memory and indexing state.")
    console.print(f"App home: {home}")
    console.print()
    console.print("Will remove:")
    console.print(f"- SQLite file records and indexing jobs: {current.paths.sqlite_path}")
    console.print(f"- LanceDB vectors and chunks: {current.paths.lancedb_path}")
    console.print(f"- Logs: {current.paths.logs_path}")
    if include_sources:
        console.print("- Saved source folder records")
    console.print()
    console.print("Will keep:")
    console.print(f"- Config: {current.paths.config_path}")
    console.print(f"- Local API token: {home / 'api_token'}")
    if not include_sources:
        console.print("- Saved source folder records")
    console.print("- User source folders and files")
    console.print("- Installed Python package")
    console.print("- Provider apps and downloaded models")

    if not home.exists():
        console.print("[yellow]OpenMind app home does not exist. Nothing to flush.[/yellow]")
        return

    current.init()
    counts = current.sqlite.index_state_counts()
    console.print()
    console.print("Current indexed state:")
    console.print(f"- Sources: {counts['sources']}")
    console.print(f"- File records: {counts['files']}")
    console.print(f"- Indexed files: {counts['indexed_files']}")
    console.print(f"- Index jobs: {counts['index_jobs']}")
    console.print(f"- Index runs: {counts['index_runs']}")

    if dry_run:
        console.print("[yellow]Dry run only. No indexed data was removed.[/yellow]")
        return

    if not yes:
        prompt = "Flush OpenMind indexed memory and indexing state"
        if include_sources:
            prompt += ", including saved source records"
        confirmed = typer.confirm(prompt + "?", default=False)
        if not confirmed:
            console.print("[yellow]Flush cancelled.[/yellow]")
            return

    if not _stop_active_index_job_for_flush(current, wait_seconds=wait):
        console.print(
            "[red]An index job is still active. Run `openmind index stop`, wait for it "
            "to stop, then run `openmind flush` again.[/red]"
        )
        raise typer.Exit(1)

    removed_counts = current.sqlite.flush_index_state(include_sources=include_sources)
    _reset_lancedb(current.paths.lancedb_path)
    removed_logs = _clear_log_files(current.paths.logs_path)

    console.print("[green]OpenMind indexed memory flushed.[/green]")
    console.print(f"Removed file records: {removed_counts['files']}")
    console.print(f"Removed indexed file records: {removed_counts['indexed_files']}")
    console.print(f"Removed index jobs: {removed_counts['index_jobs']}")
    console.print(f"Removed index runs: {removed_counts['index_runs']}")
    if include_sources:
        console.print(f"Removed source records: {removed_counts['sources']}")
    console.print(f"Removed log files: {removed_logs}")
    console.print("User files were not deleted.")
    console.print("Run `openmind index start` to build memory again.")


@app.command("uninstall", help="Remove OpenMind local data and optionally the package.")
def uninstall_command(
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip the confirmation prompt.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would be removed without deleting anything.",
    ),
    remove_package: bool = typer.Option(
        False,
        "--package",
        help="Also uninstall the openmind-core package from the current Python environment.",
    ),
) -> None:
    current = engine()
    home = current.paths.home.expanduser().resolve()
    _validate_uninstall_home(home)

    console.print("[bold]OpenMind uninstall[/bold]")
    console.print("This removes OpenMind-owned local data:")
    console.print(f"- App home: {home}")
    console.print(f"- Config: {current.paths.config_path}")
    console.print(f"- Local API token: {home / 'api_token'}")
    console.print(f"- SQLite state: {current.paths.sqlite_path}")
    console.print(f"- LanceDB memory: {current.paths.lancedb_path}")
    console.print(f"- Logs: {current.paths.logs_path}")
    if remove_package:
        console.print("- Python package: openmind-core")
    console.print()
    console.print("This does not delete user source folders, LM Studio, or downloaded models.")

    if not home.exists():
        console.print("[yellow]OpenMind app home does not exist. Nothing to remove.[/yellow]")
        if not remove_package:
            return

    if dry_run:
        console.print("[yellow]Dry run only. No files were removed.[/yellow]")
        return

    if not yes:
        prompt = "Delete OpenMind local data"
        if remove_package:
            prompt += " and uninstall the Python package"
        confirmed = typer.confirm(prompt + "?", default=False)
        if not confirmed:
            console.print("[yellow]Uninstall cancelled.[/yellow]")
            return

    if home.exists():
        _request_index_stop_before_uninstall(current)
        shutil.rmtree(home)
        console.print("[green]OpenMind local data removed.[/green]")

    if remove_package:
        _uninstall_python_package()
    else:
        console.print("To remove the installed Python package from this environment, run:")
        console.print("uv pip uninstall openmind-core")


def _interactive_ask(limit: int, stream: bool, show_thinking: bool) -> None:
    current = engine()
    history: list[dict[str, str]] = []
    console.print("[bold]OpenMind chat[/bold]")
    console.print("Ask questions about your local memory. Type /exit to leave, /clear to reset.")
    while True:
        try:
            question = Prompt.ask("[bold cyan]you[/bold cyan]").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]Closed OpenMind chat.[/yellow]")
            return

        if not question:
            continue
        command = question.lower()
        if command in {"/exit", "/quit", "exit", "quit"}:
            console.print("[yellow]Closed OpenMind chat.[/yellow]")
            return
        if command == "/clear":
            history.clear()
            console.print("[green]Session memory cleared.[/green]")
            continue

        console.print("[bold green]openmind[/bold green] ", end="")
        try:
            if stream:
                chunks: list[str] = []
                for chunk in current.ask_stream(
                    question,
                    limit=limit,
                    show_thinking=show_thinking,
                    history=history,
                ):
                    chunks.append(chunk)
                    console.print(chunk, end="", markup=False, highlight=False, soft_wrap=True)
                console.print()
                answer = "".join(chunks).strip()
            else:
                answer = current.ask(
                    question,
                    limit=limit,
                    show_thinking=show_thinking,
                    history=history,
                )
                console.print(answer)
        except LMStudioError as exc:
            console.print(f"[red]{exc}[/red]")
            continue

        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": answer})


def _choose_model(
    title: str,
    models: list[LMStudioModel],
    allow_empty: bool,
    empty_label: str = "Search-only mode (no chat model)",
) -> LMStudioModel | None:
    if not models:
        if allow_empty:
            console.print("[yellow]No chat model found. Continuing in search-only mode.[/yellow]")
            return None
        console.print("[red]No embedding model found in LM Studio.[/red]")
        console.print("OpenMind needs an embedding model to build local memory.")
        console.print("Download one manually in LM Studio, then run setup again.")
        raise typer.Exit(1)

    choices = [_model_choice(model) for model in models]
    if allow_empty:
        choices.append(Choice(empty_label, value=NO_MODEL))
    selected = _select_prompt(title, choices=choices, default=models[0].key)
    if selected == NO_MODEL:
        return None
    return next(model for model in models if model.key == selected)


def _choose_image_model(
    image_models: list[LMStudioModel],
    chat_models: list[LMStudioModel],
) -> LMStudioModel | None:
    if image_models:
        return _choose_model(
            "Choose an image description model",
            image_models,
            allow_empty=True,
            empty_label="Disable image indexing",
        )

    console.print("[yellow]No vision model was detected in LM Studio.[/yellow]")
    console.print(
        "OpenMind can index images when a vision model such as "
        f"{DEFAULT_IMAGE_DESCRIPTION_MODEL} is available through LM Studio."
    )
    if not chat_models:
        console.print("Image indexing will be disabled for now.")
        return None

    action = _select_prompt(
        "Image indexing",
        choices=[
            Choice("Disable image indexing for now", value="disable"),
            Choice("Choose from available chat models", value="choose"),
        ],
        default="disable",
    )
    if action == "disable":
        console.print("Image indexing will be disabled for now.")
        return None
    return _choose_model(
        "Choose an image description model",
        chat_models,
        allow_empty=True,
        empty_label="Disable image indexing",
    )


def _choose_model_key(
    title: str,
    models: list[LMStudioModel],
    allow_empty: bool,
    current_key: str = "",
    empty_label: str = "Search-only mode (no chat model)",
    missing_message: str | None = None,
) -> str:
    if not models:
        if allow_empty:
            console.print(
                "[yellow]"
                f"{missing_message or 'No chat model found. Search-only mode will be used.'}"
                "[/yellow]"
            )
            return ""
        console.print("[red]No embedding model found in LM Studio.[/red]")
        console.print("OpenMind needs an embedding model to build local memory.")
        console.print("Download one manually in LM Studio, then run this command again.")
        raise typer.Exit(1)

    choices: list[Choice] = []
    model_keys = {model.key for model in models}
    if current_key and current_key not in model_keys:
        choices.append(Choice(f"Keep current model ({current_key})", value=current_key))
    choices.extend(_model_choice(model) for model in models)
    if allow_empty:
        choices.append(Choice(empty_label, value=NO_MODEL))

    default = current_key if current_key in model_keys else models[0].key
    selected = _select_prompt(title, choices=choices, default=default)
    if selected == NO_MODEL:
        return ""
    return str(selected)


def _model_choice(model: LMStudioModel) -> Choice:
    loaded = "  [loaded]" if model.is_loaded else ""
    return Choice(f"{model.display_name} ({model.key}){loaded}", value=model.key)


def _select_prompt(
    message: str,
    choices: list[Choice],
    default: Any = None,
) -> Any:
    answer = questionary.select(
        message,
        choices=choices,
        default=default,
        style=PROMPT_STYLE,
        instruction="(Use arrow keys and press Enter)",
        use_indicator=True,
    ).ask()
    if answer is None:
        raise typer.Abort()
    return answer


def _checkbox_prompt(message: str, choices: list[Choice]) -> list[Any]:
    answer = questionary.checkbox(
        message,
        choices=choices,
        style=PROMPT_STYLE,
        instruction="(Use arrow keys, Space to select, Enter to continue)",
        validate=lambda selected: bool(selected) or "Select at least one option.",
    ).ask()
    if answer is None:
        raise typer.Abort()
    return answer


def _text_prompt(message: str, default: str = "") -> str:
    answer = questionary.text(
        message,
        default=default,
        style=PROMPT_STYLE,
    ).ask()
    if answer is None:
        raise typer.Abort()
    return answer.strip()


def _validate_api_origin(origin: str) -> str:
    try:
        from openmind.api.cors import validate_cors_origin

        return validate_cors_origin(origin)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


def _load_lmstudio_model(client, model_key: str, label: str) -> dict:
    result = client.load_model_if_needed(model_key)
    if result.get("skipped"):
        console.print(f"[green]✓[/green] {label} already loaded: {model_key}")
    else:
        console.print(f"[green]✓[/green] {label} loaded: {model_key}")
    return result


def _print_model_load_summary(results: list[dict]) -> None:
    loaded_count = sum(1 for result in results if not result.get("skipped"))
    skipped_count = sum(1 for result in results if result.get("skipped"))
    console.print(
        f"[green]Configured models ready[/green] "
        f"({loaded_count} loaded, {skipped_count} already loaded)"
    )


def _print_model_unload_summary(results: list[dict]) -> None:
    for result in results:
        model_key = result.get("model", "")
        if result.get("skipped"):
            console.print(f"[dim]Previous model was not loaded: {model_key}[/dim]")
        else:
            console.print(f"[green]✓[/green] Previous model unloaded: {model_key}")


def _print_existing_source_status(current: OpenMindEngine, path: str) -> None:
    source_path = Path(path).expanduser().resolve()
    existing = next((source for source in current.list_sources() if source.path == str(source_path)), None)
    if existing is None:
        console.print(f"[yellow]Source already exists:[/yellow] {source_path}")
        return

    indexed_count = current.sqlite.indexed_file_count_for_source(existing.id)
    console.print(f"[yellow]Source already added[/yellow] {existing.id}: {existing.path}")
    if indexed_count:
        console.print(
            "[green]"
            f"{indexed_count} indexed file(s) from this source are already accessible "
            "in OpenMind."
            "[/green]"
        )
    else:
        console.print("This source is registered but does not have indexed files yet.")


def _request_index_stop_before_uninstall(current: OpenMindEngine) -> None:
    try:
        job = current.index_job_status()
    except sqlite3.Error:
        return
    if job is None or job.status in {"completed", "failed", "stopped"}:
        return
    stopped = current.stop_index_job()
    if stopped and stopped.status in {"stop_requested", "stopped"}:
        console.print("[yellow]Requested active index job to stop before uninstalling.[/yellow]")


def _stop_active_index_job_for_flush(current: OpenMindEngine, wait_seconds: float) -> bool:
    try:
        job = current.index_job_status()
    except sqlite3.Error:
        return True
    if job is None or _is_terminal_index_status(job.status):
        return True

    console.print("[yellow]Requesting active index job to stop before flushing.[/yellow]")
    current.stop_index_job()
    deadline = time.time() + wait_seconds
    while time.time() <= deadline:
        updated = current.index_job_status()
        if updated is None or _is_terminal_index_status(updated.status):
            return True
        time.sleep(0.5)
    return False


def _is_terminal_index_status(status: str) -> bool:
    return status in {"completed", "failed", "stopped"}


def _reset_lancedb(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def _clear_log_files(path: Path) -> int:
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)
        return 0
    removed = 0
    for log_file in path.glob("*.log"):
        if log_file.is_file():
            log_file.unlink()
            removed += 1
    return removed


def _validate_uninstall_home(home: Path) -> None:
    unsafe_paths = {Path("/").resolve(), Path.home().resolve(), Path.cwd().resolve()}
    if home in unsafe_paths:
        raise typer.BadParameter(f"Refusing to uninstall unsafe OpenMind home: {home}")
    if home.parent == home:
        raise typer.BadParameter(f"Refusing to uninstall unsafe OpenMind home: {home}")


def _uninstall_python_package() -> None:
    console.print("Uninstalling openmind-core from the current Python environment...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "uninstall", "-y", "openmind-core"],
        check=False,
    )
    if result.returncode == 0:
        console.print("[green]openmind-core package removed from this environment.[/green]")
    else:
        console.print("[yellow]Could not uninstall openmind-core automatically.[/yellow]")
        console.print("You can remove it manually with:")
        console.print("uv pip uninstall openmind-core")


def _choose_sources(current: OpenMindEngine) -> None:
    candidates = [
        Path("~/Documents").expanduser(),
        Path("~/Downloads").expanduser(),
        Path("~/Desktop").expanduser(),
    ]
    available = [path for path in candidates if path.exists() and path.is_dir()]
    selected_paths = _choose_source_paths(available)

    seen_paths: set[Path] = set()
    for path in selected_paths:
        normalized_path = path.expanduser().resolve()
        if normalized_path in seen_paths:
            console.print(f"[yellow]Already selected in this setup run:[/yellow] {normalized_path}")
            continue
        seen_paths.add(normalized_path)
        try:
            source = current.add_source(str(normalized_path))
            console.print(f"[green]✓[/green] {source.path}")
        except sqlite3.IntegrityError:
            _print_existing_source_status(current, str(normalized_path))


def _choose_source_paths(available: list[Path]) -> list[Path]:
    choices = [Choice(str(path), value=str(path)) for path in available]
    choices.append(
        Choice(
            "Add a custom folder...",
            value=CUSTOM_FOLDER,
        )
    )
    selected = _checkbox_prompt("Choose folders to index", choices)
    selected_paths = [Path(value) for value in selected if value != CUSTOM_FOLDER]

    if CUSTOM_FOLDER in selected:
        raw_path = _text_prompt("Custom folder path")
        custom_path = Path(raw_path).expanduser()
        if not custom_path.exists() or not custom_path.is_dir():
            raise typer.BadParameter(f"Folder does not exist or is not a directory: {raw_path}")
        selected_paths.append(custom_path)
    return selected_paths


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
    console.print(_index_job_table(job))


def _index_job_table(job: IndexJob) -> Table:
    table = Table(title="Indexing Status")
    table.add_column("Metric")
    table.add_column("Value")
    table.add_row("Job", job.id)
    table.add_row("State", job.status)
    table.add_row("Files discovered", str(job.total_files))
    table.add_row("Files processed", str(job.processed_files))
    table.add_row("Files indexed", str(job.indexed_files))
    table.add_row("Files skipped", str(job.skipped_files))
    table.add_row("Already indexed", str(job.already_indexed_files))
    table.add_row("Files failed", str(job.failed_files))
    table.add_row("Chunks created", str(job.total_chunks))
    table.add_row("Progress", f"{job.progress_percent:.1f}%")
    table.add_row("Current file", job.current_file or "")
    if job.error:
        table.add_row("Error", job.error)
    return table


def _select_log_files(logs_path: Path, log: str) -> list[Path]:
    if log == "openmind":
        return [logs_path / "openmind.log"] if (logs_path / "openmind.log").exists() else []
    if log == "index":
        return sorted(logs_path.glob("index-*.log"))
    if log == "all":
        files = [logs_path / "openmind.log"] if (logs_path / "openmind.log").exists() else []
        files.extend(sorted(logs_path.glob("index-*.log")))
        return files
    raise typer.BadParameter("Log must be one of: openmind, index, all")


def _tail_log_files(paths: list[Path], lines: int, follow: bool) -> None:
    positions: dict[Path, int] = {}
    for path in paths:
        if not path.exists():
            continue
        recent = path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
        for line in recent:
            _print_log_line(path, line)
        positions[path] = path.stat().st_size

    if not follow:
        return

    console.print("[dim]Watching logs. Press Ctrl-C to stop.[/dim]")
    try:
        while True:
            for path in paths:
                if not path.exists():
                    continue
                position = positions.get(path, 0)
                with path.open("r", encoding="utf-8", errors="replace") as handle:
                    handle.seek(position)
                    for line in handle:
                        _print_log_line(path, line.rstrip("\n"))
                    positions[path] = handle.tell()
            time.sleep(1)
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopped watching logs.[/yellow]")


def _print_log_line(path: Path, line: str) -> None:
    if not line:
        return
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        console.print(f"[dim]{path.name}[/dim] {line}")
        return
    event = payload.pop("event", "log")
    timestamp = payload.pop("time", "")
    message = payload.pop("message", "")
    details = " ".join(f"{key}={value}" for key, value in payload.items())
    console.print(f"[dim]{timestamp}[/dim] [bold]{event}[/bold] {message} [dim]{details}[/dim]")


def _stream_lmstudio_logs() -> None:
    if shutil.which("lms") is None:
        console.print("[red]LM Studio CLI `lms` was not found on PATH.[/red]")
        console.print("Install or expose the LM Studio CLI, then run: lms log stream")
        raise typer.Exit(1)
    console.print("[dim]Running `lms log stream`. Press Ctrl-C to stop.[/dim]")
    try:
        subprocess.run(["lms", "log", "stream"], check=False)
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopped LM Studio log stream.[/yellow]")


if __name__ == "__main__":
    app()
