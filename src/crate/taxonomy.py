"""Map a classified item to a destination folder using the config taxonomy."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from .analyze.metadata import Meta
from .config import Config

REVIEW_DIR = "_Review"

_LOOP_CATEGORY = {
    "kick": "drums", "snare": "drums", "clap": "drums", "hat": "drums", "cymbal": "drums",
    "tom": "drums", "rim": "drums", "drum": "drums",
    "perc": "perc", "top": "perc",
    "bass": "bass", "808": "bass",
    "melodic": "melodic", "vocal": "vocal", "fx": "fx",
}  # fmt: skip
_ONESHOT_CATEGORY = {"drum": "perc", "top": "perc"}


@dataclass(frozen=True)
class Route:
    folder: str  # relative to the library root, posix style
    label: str
    confidence: float


def route_audio(meta: Meta, cfg: Config) -> Route:
    if meta.type is None:
        return Route(REVIEW_DIR, "unknown", 0.0)
    if meta.loop:
        key = _LOOP_CATEGORY.get(meta.type)
        cat = cfg.taxonomy.loops.get(key) if key else None
        label = f"loop/{key}"
    else:
        key = _ONESHOT_CATEGORY.get(meta.type, meta.type)
        cat = cfg.taxonomy.one_shots.get(key)
        label = f"oneshot/{key}"
    if cat is None or meta.confidence < cfg.review_threshold:
        return Route(REVIEW_DIR, label, meta.confidence)
    folder = PurePosixPath(*PurePosixPath(cat.folder).parts[: cfg.max_depth])
    return Route(str(folder), label, meta.confidence)


def route_midi(cfg: Config) -> Route:
    return Route(cfg.non_audio.midi, "midi", 1.0)
