"""PDF -> Markdown via pymupdf4llm. [Work package B]"""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

MIN_TEXT_CHARS = 20


def _status_for(text: str) -> str:
    return "ok" if len(text.strip()) >= MIN_TEXT_CHARS else "empty_text"


def _convert(pdf_path: Path) -> str:
    import pymupdf
    import pymupdf4llm

    # Keep MuPDF's own stderr chatter (e.g. on corrupt files) out of the run log; errors still raise.
    pymupdf.TOOLS.mupdf_display_errors(False)
    pymupdf.TOOLS.mupdf_display_warnings(False)
    # pymupdf4llm 2.x uses the layout engine when available. Its default use_ocr=True would try OCR
    # (Tesseract) on pages without text; OCR is out of scope, so disable it for deterministic output.
    # show_progress defaults to False, passed explicitly so no progress bar is ever printed.
    return pymupdf4llm.to_markdown(str(pdf_path), show_progress=False, use_ocr=False)


def pdf_to_markdown(pdf_path: Path, md_path: Path, refresh: bool = False) -> str:
    """Convert; return 'ok' | 'empty_text' | 'error:<ExcType>'.

    If ``md_path`` exists, is at least as new as the PDF and ``refresh`` is false, the conversion is
    skipped and the status is recomputed from the existing file (so reruns report the same status)."""
    pdf_path = Path(pdf_path)
    md_path = Path(md_path)
    try:
        if not refresh and md_path.exists() and md_path.stat().st_mtime >= pdf_path.stat().st_mtime:
            return _status_for(md_path.read_text(encoding="utf-8"))
        text = _convert(pdf_path)
        if not isinstance(text, str):  # page_chunks or similar would give a list
            raise TypeError(f"unexpected to_markdown result {type(text).__name__}")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        md_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = md_path.with_name(md_path.name + ".part")
        tmp.write_bytes(text.encode("utf-8"))
        tmp.replace(md_path)
    except Exception as e:  # noqa: BLE001 - any conversion failure is recorded, never fatal
        status = f"error:{type(e).__name__}"
        log.warning("markdown %s -> %s", pdf_path, status)
        return status
    status = _status_for(text)
    log.info("markdown %s -> %s", md_path.as_posix(), status)
    return status
