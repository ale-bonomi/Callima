"""Find files under the given paths, extract archives to staging, record provenance."""

from __future__ import annotations

import os
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

AUDIO_EXT = {".wav", ".aif", ".aiff", ".mp3", ".flac", ".ogg"}
MIDI_EXT = {".mid", ".midi"}
PRESET_EXT = {".fxp", ".fxb", ".vital", ".adv", ".adg", ".nmsv", ".h2p"}
ARCHIVE_EXT = {".zip"}
UNSUPPORTED_ARCHIVE_EXT = {".rar", ".7z"}
JUNK_DIRS = {"__MACOSX"}
JUNK_FILES = {".DS_Store", "Thumbs.db"}


@dataclass
class Item:
    path: Path  # where the file physically is now (staging path if extracted)
    original: str  # human-readable original location (zip!/inner/path for archives)
    pack: str | None
    folders: tuple[str, ...]  # folder names, outermost first
    kind: str  # audio | midi | preset | other
    staged: bool
    root: Path  # input root (used by `unpack` to flatten into)


@dataclass
class ScanResult:
    items: list[Item] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class _Base:
    original_root: str
    archive: bool
    pack: str | None
    prefix: tuple[str, ...]
    staged: bool
    root: Path


def kind_of(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in AUDIO_EXT:
        return "audio"
    if ext in MIDI_EXT:
        return "midi"
    if ext in PRESET_EXT:
        return "preset"
    return "other"


def is_junk(name: str) -> bool:
    return name in JUNK_FILES or name.startswith("._")


def safe_extract_zip(archive: Path, dest: Path) -> list[str]:
    """Extract member by member, refusing absolute paths and `..` (zip-slip)."""
    warnings: list[str] = []
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            parts = Path(info.filename).parts
            if not parts or Path(info.filename).is_absolute() or ".." in parts:
                warnings.append(f"{archive}: unsafe member skipped: {info.filename}")
                continue
            if any(p in JUNK_DIRS for p in parts) or is_junk(parts[-1]):
                continue
            target = dest.joinpath(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                while chunk := src.read(1 << 20):
                    out.write(chunk)
    return warnings


def _infer_pack(path: Path, directory: Path) -> str | None:
    parts = path.parts
    if "packs" in parts[:-1]:
        i = parts.index("packs")
        if i + 1 < len(parts) - 1:
            return parts[i + 1]
    rel = path.relative_to(directory)
    return rel.parts[0] if len(rel.parts) > 1 else directory.name


def scan(inputs: list[Path], staging: Path) -> ScanResult:
    res = ScanResult()
    counter = [0]

    def walk(directory: Path, base: _Base) -> None:
        for dirpath, dirnames, filenames in os.walk(directory):
            dirnames[:] = sorted(
                d for d in dirnames if d not in JUNK_DIRS and not d.startswith(".")
            )
            for fn in sorted(filenames):
                p = Path(dirpath) / fn
                rel = p.relative_to(directory)
                if is_junk(fn):
                    continue
                try:
                    size = p.stat().st_size
                except OSError as e:
                    res.skipped.append((str(p), f"unreadable: {e}"))
                    continue
                if size == 0:
                    res.skipped.append((str(p), "zero-byte"))
                    continue
                ext = p.suffix.lower()
                original = f"{base.original_root}/{rel}" if base.archive else str(p)
                if ext in ARCHIVE_EXT:
                    counter[0] += 1
                    dest = staging / f"a{counter[0]}"
                    dest.mkdir(parents=True, exist_ok=True)
                    try:
                        res.warnings += safe_extract_zip(p, dest)
                    except zipfile.BadZipFile:
                        res.skipped.append((original, "bad zip"))
                        continue
                    walk(
                        dest,
                        _Base(
                            original_root=original + "!",
                            archive=True,
                            pack=p.stem,
                            prefix=(*base.prefix, *rel.parts[:-1], p.stem),
                            staged=True,
                            root=base.root,
                        ),
                    )
                    continue
                if ext in UNSUPPORTED_ARCHIVE_EXT:
                    res.warnings.append(f"{original}: {ext} archives not supported yet; skipped")
                    continue
                kind = kind_of(p)
                if kind == "other":
                    res.skipped.append((original, "not a sample/midi/preset"))
                    continue
                pack = base.pack if base.archive else _infer_pack(p, directory)
                res.items.append(
                    Item(
                        path=p,
                        original=original,
                        pack=pack,
                        folders=(*base.prefix, *rel.parts[:-1]),
                        kind=kind,
                        staged=base.staged,
                        root=base.root,
                    )
                )

    for inp in inputs:
        inp = inp.resolve()
        if inp.is_dir():
            walk(inp, _Base(str(inp), False, None, (inp.name,), False, inp))
        elif inp.is_file():
            # single file or archive: treat the parent as the walk root, but only this file
            tmp_res = _single(inp, staging, counter)
            res.items += tmp_res.items
            res.warnings += tmp_res.warnings
            res.skipped += tmp_res.skipped
        else:
            res.warnings.append(f"{inp}: not found")
    return res


def _single(path: Path, staging: Path, counter: list[int]) -> ScanResult:
    """Scan one file by linking it into a throwaway walk of its own."""
    res = ScanResult()
    ext = path.suffix.lower()
    if ext in ARCHIVE_EXT:
        counter[0] += 1000
        dest = staging / f"s{counter[0]}"
        dest.mkdir(parents=True, exist_ok=True)
        try:
            res.warnings += safe_extract_zip(path, dest)
        except zipfile.BadZipFile:
            res.skipped.append((str(path), "bad zip"))
            return res
        sub = scan([dest], staging)
        root = path.parent / path.stem
        for it in sub.items:
            res.items.append(
                Item(
                    it.path,
                    it.original.replace(str(dest), f"{path}!", 1),
                    path.stem,
                    (path.stem, *it.folders[1:]),
                    it.kind,
                    True,
                    root,
                )
            )
        res.warnings += sub.warnings
        res.skipped += sub.skipped
        return res
    kind = kind_of(path)
    if kind == "other" or is_junk(path.name):
        res.skipped.append((str(path), "not a sample/midi/preset"))
    else:
        res.items.append(
            Item(path, str(path), path.parent.name, (path.parent.name,), kind, False, path.parent)
        )
    return res
