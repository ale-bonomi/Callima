"""Build a plan (pure with respect to the library: only reads) from scanned items."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .analyze import metadata
from .config import Config
from .hashing import file_hash
from .scan import Item
from .taxonomy import Route, route_audio, route_midi


@dataclass
class PlannedOp:
    src: Path
    dst: Path
    mode: str  # move | copy | extract
    label: str
    confidence: float
    original: str
    pack: str | None
    renamed: bool = False  # collision suffix added
    sidecar: bool = False


@dataclass
class Plan:
    ops: list[PlannedOp] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    prune_roots: list[Path] = field(default_factory=list)

    def per_folder(self) -> Counter[str]:
        return Counter(str(o.dst.parent) for o in self.ops if not o.sidecar)


Router = Callable[[Item], tuple[Path, str, float] | None]


def sort_router(cfg: Config) -> Router:
    root = cfg.root

    def route(item: Item) -> tuple[Path, str, float] | None:
        if item.kind == "audio":
            meta = metadata.parse(item.path.stem, item.folders)
            r: Route = route_audio(meta, cfg)
        elif item.kind == "midi":
            r = route_midi(cfg)
        else:
            return None  # presets & others: Milestone 6
        return root / r.folder, r.label, r.confidence

    return route


def flatten_router(item: Item) -> tuple[Path, str, float] | None:
    return item.root, "flatten", 1.0


def _unique(dst: Path, taken: set[Path]) -> Path:
    n = 2
    while True:
        cand = dst.with_name(f"{dst.stem} ({n}){dst.suffix}")
        if cand not in taken and not cand.exists():
            return cand
        n += 1


def build_plan(items: list[Item], cfg: Config, router: Router, copy_roots: list[Path]) -> Plan:
    """`copy_roots`: files under these folders are copied (originals left in place)."""
    plan = Plan()
    taken: set[Path] = set()
    copy_roots = [r.expanduser().resolve() for r in copy_roots]
    plan.prune_roots = sorted({it.root for it in items if not it.staged})

    for item in items:
        routed = router(item)
        if routed is None:
            plan.skipped.append((item.original, f"{item.kind}: not routed yet"))
            continue
        folder, label, conf = routed
        src = item.path
        dst = folder / src.name

        if dst.exists() and src.resolve() == dst.resolve():
            plan.skipped.append((item.original, "already in place"))
            continue

        renamed = False
        if dst in taken or dst.exists():
            if dst not in taken and dst.exists() and _same_content(src, dst):
                plan.skipped.append((item.original, f"identical file already at {dst}"))
                continue
            dst = _unique(dst, taken)
            renamed = True

        if item.staged:
            mode = "extract"
        elif cfg.keep_originals and any(src.resolve().is_relative_to(r) for r in copy_roots):
            mode = "copy"
        else:
            mode = "move"

        taken.add(dst)
        plan.ops.append(PlannedOp(src, dst, mode, label, conf, item.original, item.pack, renamed))

        sidecar = src.with_name(src.name + ".asd")
        if sidecar.exists():
            sdst = dst.with_name(dst.name + ".asd")
            if not sdst.exists():
                taken.add(sdst)
                plan.ops.append(
                    PlannedOp(sidecar, sdst, mode, label, conf, item.original + ".asd",
                              item.pack, renamed, sidecar=True)
                )  # fmt: skip
    return plan


def _same_content(a: Path, b: Path) -> bool:
    try:
        if a.stat().st_size != b.stat().st_size:
            return False
        return file_hash(a) == file_hash(b)
    except OSError:
        return False
