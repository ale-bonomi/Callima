"""Streaming file hashes."""

from __future__ import annotations

import hashlib
from pathlib import Path


def file_hash(path: Path) -> str:
    h = hashlib.blake2b(digest_size=20)
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()
