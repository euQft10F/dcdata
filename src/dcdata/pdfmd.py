"""PDF -> Markdown via pymupdf4llm. [Work package B]"""

from __future__ import annotations

from pathlib import Path


def pdf_to_markdown(pdf_path: Path, md_path: Path, refresh: bool = False) -> str:
    """Convert; return 'ok' | 'empty_text' | 'error:<ExcType>'."""
    raise NotImplementedError
