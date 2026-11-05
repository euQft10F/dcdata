"""Deterministic CSV reading/writing (UTF-8, no BOM, \\n line endings, QUOTE_MINIMAL)."""

from __future__ import annotations

import csv
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path


def _fmt(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        # Avoid platform-dependent repr noise; integers render without ".0".
        return str(int(value)) if value.is_integer() else repr(value)
    return str(value)


def write_csv(rows: Iterable[Mapping], path: Path | str, columns: Sequence[str]) -> int:
    """Write rows (dicts) with exactly ``columns`` in that order. Extra keys are ignored,
    missing keys become empty strings. Rows are written in the order given (callers sort).
    Writes atomically. Returns the number of rows written."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    n = 0
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
        w.writerow(columns)
        for row in rows:
            w.writerow([_fmt(row.get(c)) for c in columns])
            n += 1
    tmp.replace(path)
    return n


def read_csv(path: Path | str) -> list[dict[str, str]]:
    with Path(path).open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))
