"""Config schema (pydantic) and YAML load/save."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

CRATE_HOME = Path("~/.crate").expanduser()


class RenameConfig(BaseModel):
    enabled: bool = False
    template: str = "{type}_{character}_{key}_{bpm}_{original}"


class Category(BaseModel):
    folder: str
    split_by: str | None = None


def _default_one_shots() -> dict[str, Category]:
    return {
        "kick": Category(folder="One Shots/Kicks", split_by="punch"),
        "snare": Category(folder="One Shots/Snares", split_by="snare_body"),
        "clap": Category(folder="One Shots/Claps"),
        "hat": Category(folder="One Shots/Hats & Cymbals"),
        "cymbal": Category(folder="One Shots/Hats & Cymbals"),
        "perc": Category(folder="One Shots/Percussion"),
        "tom": Category(folder="One Shots/Percussion"),
        "rim": Category(folder="One Shots/Percussion"),
        "bass": Category(folder="One Shots/808 & Bass"),
        "808": Category(folder="One Shots/808 & Bass"),
        "melodic": Category(folder="One Shots/Melodic"),
        "vocal": Category(folder="One Shots/Vocals"),
        "fx": Category(folder="One Shots/FX"),
    }


def _default_loops() -> dict[str, Category]:
    return {
        "drums": Category(folder="Loops/Drums", split_by="feel"),
        "perc": Category(folder="Loops/Tops & Percs", split_by="feel"),
        "bass": Category(folder="Loops/Bass"),
        "melodic": Category(folder="Loops/Melodic"),
        "vocal": Category(folder="Loops/Vocals"),
        "fx": Category(folder="Loops/FX & Textures"),
    }


class Taxonomy(BaseModel):
    one_shots: dict[str, Category] = Field(default_factory=_default_one_shots)
    loops: dict[str, Category] = Field(default_factory=_default_loops)


class NonAudio(BaseModel):
    midi: str = "MIDI"
    other: str = "leave"


class Config(BaseModel):
    library_roots: list[Path] = Field(default_factory=lambda: [Path("~/Music/Samples Library")])
    splice_folder: Path = Path("~/Splice/Samples")
    external_volumes: bool = True
    review_threshold: float = Field(0.6, ge=0, le=1)
    split_folder_threshold: int = Field(300, ge=1)
    max_depth: int = Field(3, ge=1, le=3)
    rename: RenameConfig = Field(default_factory=RenameConfig)
    duplicates: str = Field("trash", pattern="^(trash|quarantine|keep|symlink)$")
    # True: copy new files and leave originals (keeps Splice's "downloaded" state).
    keep_originals: bool = True
    taxonomy: Taxonomy = Field(default_factory=Taxonomy)
    non_audio: NonAudio = Field(default_factory=NonAudio)

    @property
    def root(self) -> Path:
        return self.library_roots[0].expanduser()


def default_config_path() -> Path:
    return CRATE_HOME / "config.yaml"


def load_config(path: Path | None = None) -> Config:
    path = path or default_config_path()
    if not path.exists():
        return Config()
    data = yaml.safe_load(path.read_text()) or {}
    return Config.model_validate(data)


def save_config(cfg: Config, path: Path | None = None) -> Path:
    path = path or default_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(cfg.model_dump(mode="json"), sort_keys=False))
    return path
