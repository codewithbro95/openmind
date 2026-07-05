from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path

import typer
from rich.console import Console
from rich.live import Live
from rich.prompt import Prompt
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
dev_app = typer.Typer(help="Developer tools.")
app.add_typer(source_app, name="source")
app.add_typer(index_app, name="index")
app.add_typer(models_app, name="models")
app.add_typer(provider_app, name="provider")
app.add_typer(dev_app, name="dev")
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
            _load_lmstudio_model(client, chat_model.key, "Chat model")
        else:
            console.print("[yellow]Search-only mode enabled because no chat model was selected.[/yellow]")
        _load_lmstudio_model(client, embedding_model.key, "Embedding model")
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
    config = current.config
    current_provider_name = config.provider.name
    current_chat_model = config.models.chat_model if current_provider_name == "lmstudio" else ""
    current_embedding_model = (
        config.models.embedding_model if current_provider_name == "lmstudio" else ""
    )

    console.print("Choose AI provider:")
    console.print("1. LM Studio")
    provider_choice = typer.prompt("Selected", default="1")
    if provider_choice.strip() != "1":
        raise typer.BadParameter("Only LM Studio is supported in v0.2.")

    default_base_url = (
        config.provider.base_url
        if config.provider.name == "lmstudio"
        else DEFAULT_LMSTUDIO_BASE_URL
    )
    base_url = typer.prompt("LM Studio base URL", default=default_base_url)
    config.provider = ProviderSettings(
        name="lmstudio",
        base_url=base_url,
        api_token_env=config.provider.api_token_env or "LM_API_TOKEN",
    )
    current.save_config(config)

    console.print(f"Fetching LM Studio models from {base_url}...")
    try:
        models = current.list_lmstudio_models()
    except LMStudioConnectionError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    chat_models, embedding_models = split_models(models)
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

    config.models.chat_model = chat_model_key
    config.models.embedding_model = embedding_model_key
    current.save_config(config)
    console.print("[green]Saved model configuration.[/green]")

    if not load:
        console.print("Run `openmind models load` when you are ready to load the selected models.")
        return

    console.print("Loading selected models...")
    try:
        client = current.lmstudio_client()
        results = []
        if chat_model_key:
            results.append(_load_lmstudio_model(client, chat_model_key, "Chat model"))
        else:
            console.print("[yellow]Search-only mode enabled because no chat model was selected.[/yellow]")
        results.append(_load_lmstudio_model(client, embedding_model_key, "Embedding model"))
        _print_model_load_summary(results)
    except LMStudioError as exc:
        console.print(f"[yellow]{exc}[/yellow]")
        console.print("You can retry loading models with: openmind models load")


@provider_app.command("status")
def provider_status() -> None:
    ok, message = engine().provider_status()
    color = "green" if ok else "yellow"
    console.print(f"[{color}]{message}[/{color}]")


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


@app.command("search")
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


@app.command("ask")
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


def _choose_model_key(
    title: str,
    models: list[LMStudioModel],
    allow_empty: bool,
    current_key: str = "",
) -> str:
    if not models:
        if allow_empty:
            console.print("[yellow]No chat model found. Search-only mode will be used.[/yellow]")
            return ""
        console.print("[red]No embedding model found in LM Studio.[/red]")
        console.print("OpenMind needs an embedding model to build local memory.")
        console.print("Download one manually in LM Studio, then run this command again.")
        raise typer.Exit(1)

    console.print(title + ":")
    if current_key:
        console.print(f"Current: {current_key}")
    if allow_empty:
        console.print("0. Search-only mode (no chat model)")
    for index, model in enumerate(models, start=1):
        loaded = " loaded" if model.is_loaded else ""
        console.print(f"{index}. {model.display_name} ({model.key}){loaded}")

    default = "keep" if current_key else "1"
    choice = typer.prompt("Choose model", default=default).strip()
    if current_key and choice.lower() in {"keep", "k"}:
        return current_key
    if allow_empty and choice.lower() in {"0", "none", "skip", "search-only"}:
        return ""
    try:
        selected_index = int(choice) - 1
        return models[selected_index].key
    except (ValueError, IndexError) as exc:
        raise typer.BadParameter("Invalid model selection.") from exc


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
