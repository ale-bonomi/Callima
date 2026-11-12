"""Rich output for plans."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from .planner import Plan
from .scan import ScanResult


def show_plan(
    console: Console, plan: Plan, scan: ScanResult, apply: bool, limit: int = 200
) -> None:
    for w in scan.warnings:
        console.print(f"[yellow]warning:[/] {w}")
    table = Table(title="Plan" if apply else "Plan (dry run)", show_lines=False)
    table.add_column("Action")
    table.add_column("From", overflow="fold")
    table.add_column("To", overflow="fold")
    table.add_column("Conf", justify="right")
    table.add_column("Note")
    shown = [o for o in plan.ops if not o.sidecar]
    for o in shown[:limit]:
        table.add_row(
            o.mode, o.original, str(o.dst), f"{o.confidence:.2f}",
            "renamed (collision)" if o.renamed else "",
        )  # fmt: skip
    console.print(table)
    if len(shown) > limit:
        console.print(f"... and {len(shown) - limit} more")

    counts = Table(title="Per destination folder")
    counts.add_column("Folder", overflow="fold")
    counts.add_column("Files", justify="right")
    for folder, n in sorted(plan.per_folder().items()):
        counts.add_row(folder, str(n))
    console.print(counts)

    sidecars = sum(1 for o in plan.ops if o.sidecar)
    console.print(
        f"{len(shown)} files, {sidecars} .asd sidecars, {len(plan.skipped)} skipped"
        f" ({len(scan.skipped)} ignored during scan)"
    )
    if not apply:
        console.print("[bold]Dry run.[/] Re-run with [cyan]--apply[/] to execute.")
