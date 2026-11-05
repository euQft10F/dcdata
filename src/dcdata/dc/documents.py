"""Download target PDFs and convert them to Markdown. [Work package B]"""

from __future__ import annotations

from pathlib import Path

from ..http import Fetcher


def download_documents(
    fetcher: Fetcher,
    links: list[dict],
    documents_dir: Path,
    base_dir: Path | None = None,
    refresh: bool = False,
) -> list[dict]:
    """Return copies of ``links`` (already annotated) with download_status, final_url, sha256,
    size_bytes, pdf_path filled. Only ``is_target`` links are downloaded; dedupe by url_normalized.
    pdf_path is POSIX, relative to ``base_dir`` (default: cwd) when possible."""
    raise NotImplementedError


def convert_documents(
    links: list[dict],
    markdown_dir: Path,
    documents_dir: Path,
    base_dir: Path | None = None,
    refresh: bool = False,
) -> list[dict]:
    """Return copies of ``links`` with md_path and md_status filled for rows whose download_status == 'ok'."""
    raise NotImplementedError
