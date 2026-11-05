"""Small shared helpers: atomic file writes and whitespace cleaning."""

from __future__ import annotations

import re
from pathlib import Path

_WS = re.compile(r"\s+")


def write_atomic(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` via a sibling ``.part`` file and an atomic rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(data)
    tmp.replace(path)


def clean_text(text: str | None) -> str:
    """Collapse all whitespace runs (incl. U+00A0) to one space and strip."""
    return _WS.sub(" ", text or "").strip()
