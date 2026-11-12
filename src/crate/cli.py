"""Command-line interface."""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from . import db, mover, planner
from .config import CRATE_HOME, Config, default_config_path, load_config, save_config
from .scan import ScanResult, scan

app = typer.Typer(help="Ableton-first audio sample organizer.", no_args_is_help=True)
console = Console()

Apply = Annotated[bool, typer.Option("--apply", help="Execute the plan (default is dry run).")]
Paths = Annotated[list[Path], typer.Argument(help="Files or folders (drag them in).")]


@dataclass
class State:
    config_path: Path | None = None
    verbose: bool = False
    jobs: int | None = None


@app.callback()
def main(
    ctx: typer.Context,
    config: Annotated[Path | None, typer.Option("--config", help="Config file.")] = None,
    verbose: Annotated[bool, typer.Option("--verbose")] = False,
    jobs: Annotated[int | None, typer.Option("--jobs", help="Parallel workers.")] = None,
) -> None:
    ctx.obj = State(config, verbose, jobs)


def _cfg(ctx: typer.Context) -> Config:
    return load_config(ctx.obj.config_path)


def _db_path() -> Path:
    return CRATE_HOME / "library.db"


def clean_path(p: Path) -> Path:
    """Undo shell-escaping/quoting left over from drag-and-drop."""
    s = str(p).strip().strip("'\"").replace("\\ ", " ")
    return Path(s).expanduser()


def _paths(paths: list[Path]) -> list[Path]:
    return [clean_path(p) for p in paths]


@app.command()
def init(ctx: typer.Context) -> None:
    """Create config + DB; ask for the library root."""
    path = ctx.obj.config_path or default_config_path()
    cfg = load_config(path) if path.exists() else Config()
    default = str(cfg.library_roots[0])
    root = typer.prompt("Library root (where sorted samples will live)", default=default)
    splice = typer.prompt("Splice folder", default=str(cfg.splice_folder))
    cfg.library_roots = [Path(root)]
    cfg.splice_folder = Path(splice)
    save_config(cfg, path)
    db.connect(_db_path()).close()
    console.print(f"Config written to {path}; database at {_db_path()}")


def _scan_plan(
    ctx: typer.Context, paths: list[Path], router_kind: str
) -> tuple[Config, ScanResult, planner.Plan, Path]:
    cfg = _cfg(ctx)
    CRATE_HOME.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="staging-", dir=CRATE_HOME))
    with console.status("Scanning..."):
        result = scan(_paths(paths), staging)
    router = planner.sort_router(cfg) if router_kind == "sort" else planner.flatten_router
    plan = planner.build_plan(result.items, cfg, router, [cfg.splice_folder])
    return cfg, result, plan, staging


def _run(ctx: typer.Context, paths: list[Path], apply: bool, command: str, kind: str) -> None:
    from .render import show_plan

    cfg, result, plan, staging = _scan_plan(ctx, paths, kind)
    try:
        show_plan(console, plan, result, apply)
        if not apply or not plan.ops:
            return
        conn = db.connect(_db_path())
        batch = mover.execute(conn, plan, command, cfg.root)
        conn.close()
        console.print(f"[green]Done.[/] Batch {batch}. Undo with: crate undo {batch}")
    finally:
        shutil.rmtree(staging, ignore_errors=True)


@app.command()
def unpack(ctx: typer.Context, paths: Paths, apply: Apply = False) -> None:
    """Flatten nested pack folders and extract zips (no analysis)."""
    _run(ctx, paths, apply, "unpack", "flatten")


@app.command()
def sort(ctx: typer.Context, paths: Paths, apply: Apply = False) -> None:
    """Plan/apply moves into the library structure."""
    _run(ctx, paths, apply, "sort", "sort")


@app.command()
def ingest(ctx: typer.Context, paths: Paths, apply: Apply = False) -> None:
    """Unpack, classify and sort in one shot (the main daily command)."""
    _run(ctx, paths, apply, "ingest", "sort")


@app.command()
def undo(
    batch_id: Annotated[int | None, typer.Argument()] = None,
) -> None:
    """Reverse a batch (default: the latest)."""
    conn = db.connect(_db_path())
    batch = batch_id if batch_id is not None else mover.latest_done_batch(conn)
    if batch is None:
        console.print("Nothing to undo.")
        raise typer.Exit()
    warnings = mover.undo(conn, batch)
    for w in warnings:
        console.print(f"[yellow]warning:[/] {w}")
    status = conn.execute("SELECT status FROM batches WHERE id=?", (batch,)).fetchone()
    console.print(f"Batch {batch}: {status['status'] if status else 'unknown'}")


@app.command()
def status(ctx: typer.Context) -> None:
    """Library stats and recent batches."""
    conn = db.connect(_db_path())
    n = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    console.print(f"Tracked files: {n}")
    table = Table(title="Recent batches")
    for col in ("id", "when", "command", "status", "ops"):
        table.add_column(col)
    for b in conn.execute(
        "SELECT b.*, (SELECT COUNT(*) FROM ops o WHERE o.batch_id=b.id) AS n"
        " FROM batches b ORDER BY id DESC LIMIT 10"
    ):
        table.add_row(str(b["id"]), b["created_at"], b["command"], b["status"], str(b["n"]))
    console.print(table)
