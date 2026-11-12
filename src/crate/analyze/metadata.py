"""Filename / folder-name parser: sound type, loop vs one-shot, BPM and key."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# keyword -> canonical sound type
TYPE_KEYWORDS: dict[str, str] = {
    **dict.fromkeys(["kick", "kck", "bassdrum", "bd"], "kick"),
    **dict.fromkeys(["snare", "snr", "snares"], "snare"),
    **dict.fromkeys(["clap", "snap", "claps"], "clap"),
    **dict.fromkeys(["rim", "rimshot", "sidestick"], "rim"),
    **dict.fromkeys(["hat", "hats", "hihat", "hihats", "hh", "ohh", "chh", "openhat"], "hat"),
    **dict.fromkeys(["cymbal", "cymbals", "crash", "ride", "cym"], "cymbal"),
    **dict.fromkeys(["tom", "toms"], "tom"),
    **dict.fromkeys(
        [
            "perc",
            "percs",
            "percussion",
            "shaker",
            "conga",
            "bongo",
            "tambourine",
            "tamb",
            "cowbell",
            "clave",
            "woodblock",
            "triangle",
        ],
        "perc",
    ),
    **dict.fromkeys(["808", "808s", "sub"], "808"),
    **dict.fromkeys(["bass", "bassline", "reese", "bassy"], "bass"),
    **dict.fromkeys(
        ["vox", "vocal", "vocals", "acapella", "acappella", "chant", "shout", "adlib", "adlibs"],
        "vocal",
    ),
    **dict.fromkeys(
        [
            "pad",
            "pads",
            "chord",
            "chords",
            "keys",
            "piano",
            "synth",
            "synths",
            "lead",
            "leads",
            "pluck",
            "plucks",
            "arp",
            "arps",
            "guitar",
            "rhodes",
            "organ",
            "stab",
            "stabs",
            "bell",
            "bells",
            "melody",
            "melodic",
            "melodies",
        ],
        "melodic",
    ),
    **dict.fromkeys(
        [
            "fx",
            "sfx",
            "riser",
            "risers",
            "impact",
            "impacts",
            "sweep",
            "sweeps",
            "texture",
            "textures",
            "foley",
            "noise",
            "atmos",
            "atmosphere",
            "ambience",
            "downlifter",
            "uplifter",
            "whoosh",
            "transition",
            "transitions",
            "glitch",
        ],
        "fx",
    ),
    **dict.fromkeys(["drum", "drums"], "drum"),
    **dict.fromkeys(["top", "tops"], "top"),
}

LOOP_TOKENS = {"loop", "loops", "lp"}
ONESHOT_RE = re.compile(r"one[\s_\-]?shots?|\bshots?\b|\bhits?\b", re.I)

BPM_EXPLICIT = re.compile(r"(?<!\d)(\d{2,3})\s*bpm", re.I)
BPM_BARE = re.compile(r"(?:^|[_\-\s])(\d{2,3})(?=[_\-\s.]|$)")
KEY_RE = re.compile(
    r"(?<![A-Za-z#])([A-G])([#b]?)[_\- ]?((?i:maj(?:or)?|min(?:or)?)|m)(?![A-Za-z])"
)
_TOKEN_RE = re.compile(r"[A-Za-z]+|\d+")
_CAMEL_RE = re.compile(r"(?<=[a-z])(?=[A-Z])")


@dataclass
class Meta:
    type: str | None = None  # kick, snare, ..., drum, top
    loop: bool | None = None  # None = unknown
    bpm: int | None = None
    key: str | None = None
    confidence: float = 0.0
    reason: str = ""
    tokens: list[str] = field(default_factory=list)


def tokenize(text: str) -> list[str]:
    text = _CAMEL_RE.sub(" ", text)
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def _type_of(token: str) -> str | None:
    if token in TYPE_KEYWORDS:
        return TYPE_KEYWORDS[token]
    if token.endswith("s") and token[:-1] in TYPE_KEYWORDS:
        return TYPE_KEYWORDS[token[:-1]]
    return None


def _types_in(text: str) -> list[str]:
    seen: list[str] = []
    for tok in tokenize(text):
        t = _type_of(tok)
        if t and t not in seen:
            seen.append(t)
    return seen


def parse_key(text: str) -> str | None:
    m = KEY_RE.search(text)
    if not m:
        return None
    note, acc, qual = m.groups()
    minor = qual.lower().startswith("min") or qual == "m"
    return f"{note}{acc}{'min' if minor else 'maj'}"


def parse_bpm(stem: str, allow_bare: bool) -> int | None:
    m = BPM_EXPLICIT.search(stem)
    if m and 40 <= int(m.group(1)) <= 220:
        return int(m.group(1))
    if allow_bare:
        for m in BPM_BARE.finditer(stem):
            if 60 <= int(m.group(1)) <= 200:
                return int(m.group(1))
    return None


def _loopness(text: str) -> bool | None:
    if any(t in LOOP_TOKENS for t in tokenize(text)):
        return True
    if ONESHOT_RE.search(text):
        return False
    return None


def parse(stem: str, folders: tuple[str, ...]) -> Meta:
    """Classify from the filename stem and parent folder names (nearest folder last)."""
    meta = Meta(tokens=tokenize(stem))
    near_first = list(reversed(folders))

    # loop vs one-shot: filename beats folders; nearest folder first
    loop = _loopness(stem)
    if loop is None:
        for f in near_first:
            loop = _loopness(f)
            if loop is not None:
                break
    meta.key = parse_key(stem)
    meta.bpm = parse_bpm(stem, allow_bare=loop is True)
    if loop is None and meta.bpm is not None:
        loop = True
    meta.loop = loop

    file_types = _types_in(stem)
    folder_type: str | None = None
    level = 0
    for i, f in enumerate(near_first):
        ft = _types_in(f)
        if ft:
            folder_type, level = ft[0], i
            break

    if file_types:
        meta.type = file_types[0]
        conf = 0.9
        reason = f"filename:{meta.type}"
        if len(file_types) > 1:
            conf, reason = 0.65, f"filename ambiguous:{file_types}"
        elif folder_type and folder_type != meta.type:
            conf, reason = 0.75, f"filename:{meta.type} vs folder:{folder_type}"
        elif folder_type == meta.type:
            conf = 0.95
        meta.confidence, meta.reason = conf, reason
    elif folder_type:
        meta.type = folder_type
        meta.confidence = max(0.5, 0.8 - 0.07 * level)
        meta.reason = f"folder:{folder_type}"
    if meta.type and meta.loop is None:
        meta.confidence = round(meta.confidence - 0.1, 2)
    return meta
