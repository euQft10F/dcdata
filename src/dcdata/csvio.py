"""Deterministic CSV reading/writing (UTF-8, no BOM, \\n line endings, QUOTE_MINIMAL)."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from .util import write_atomic


def fmt_value(value) -> str:
    """CSV cell text: None -> '', bools -> true/false, integral floats without '.0'."""
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
    buf = io.StringIO()
    w = csv.writer(buf, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    w.writerow(columns)
    n = 0
    for row in rows:
        w.writerow([fmt_value(row.get(c)) for c in columns])
        n += 1
    write_atomic(Path(path), buf.getvalue().encode("utf-8"))
    return n


def read_csv(path: Path | str) -> list[dict[str, str]]:
    with Path(path).open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))
