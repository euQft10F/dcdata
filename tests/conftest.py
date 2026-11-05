"""Shared test helpers (importable as ``from conftest import ...``)."""

from pathlib import Path

import pymupdf

FIXTURES = Path(__file__).parent / "fixtures"


def make_pdf(path: Path, text: str | None = None) -> None:
    """Write a one-page PDF at ``path`` (parents created), optionally containing ``text``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    page = doc.new_page()
    if text:
        page.insert_text((72, 72), text, fontsize=12)
    doc.save(str(path))
    doc.close()
