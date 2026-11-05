"""Download target PDFs and convert them to Markdown. [Work package B]"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

import httpx

from .. import urls
from ..http import Fetcher
from ..pdfmd import pdf_to_markdown

log = logging.getLogger(__name__)

PDF_MAGIC = b"%PDF-"
_UNSAFE_RE = re.compile(r"[^A-Za-z0-9._-]")
_MAX_BASENAME = 120
# Sidecar next to each PDF that remembers the post-redirect URL, so a rerun that reuses the file
# on disk reports the same final_url as the run that downloaded it (byte-identical CSVs).
_META_SUFFIX = ".meta.json"

_DOWNLOAD_FIELDS = ("download_status", "final_url", "sha256", "size_bytes", "pdf_path")


def safe_basename(url: str) -> str:
    """Last non-empty URL path segment, unquoted, '.pdf' stripped, unsafe chars -> '_', <=120 chars."""
    segments = [s for s in urlsplit(url).path.split("/") if s]
    name = unquote(segments[-1]) if segments else ""
    name = re.sub(r"\.pdf$", "", name, flags=re.IGNORECASE)
    name = _UNSAFE_RE.sub("_", name)[:_MAX_BASENAME]
    return name or "document"


def _rel_posix(path: Path, base_dir: Path | None) -> str:
    base = Path(base_dir) if base_dir is not None else Path.cwd()
    abs_path = Path(path).resolve()
    try:
        return abs_path.relative_to(base.resolve()).as_posix()
    except ValueError:
        return abs_path.as_posix()


def _from_rel(path_str: str, base_dir: Path | None) -> Path:
    p = Path(path_str)
    if p.is_absolute():
        return p
    return (Path(base_dir) if base_dir is not None else Path.cwd()) / p


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(data)
    tmp.replace(path)


def _meta_path(pdf: Path) -> Path:
    return pdf.with_name(pdf.name + _META_SUFFIX)


def _read_meta_final_url(pdf: Path) -> str:
    try:
        return str(json.loads(_meta_path(pdf).read_text(encoding="utf-8")).get("final_url", ""))
    except (OSError, ValueError):
        return ""


def _download_one(fetcher: Fetcher, url: str, dest: Path, pdf_path: str, refresh: bool) -> dict:
    empty = {"download_status": "", "final_url": "", "sha256": "", "size_bytes": "", "pdf_path": ""}
    if dest.exists() and not refresh:
        data = dest.read_bytes()
        log.debug("reuse %s", pdf_path)
        return {
            "download_status": "ok",
            "final_url": _read_meta_final_url(dest),
            "sha256": _sha256(data),
            "size_bytes": len(data),
            "pdf_path": pdf_path,
        }
    try:
        res = fetcher.get(url)
    except (httpx.HTTPError, httpx.InvalidURL, OSError, ValueError) as e:
        status = f"error:{type(e).__name__}"
        log.info("download %s -> %s", url, status)
        return {**empty, "download_status": status}
    if not res.ok:
        status = f"http_{res.status}"
        log.info("download %s -> %s", url, status)
        return {**empty, "download_status": status, "final_url": res.final_url}
    if res.content[:5] != PDF_MAGIC:
        log.info("download %s -> not_pdf", url)
        return {**empty, "download_status": "not_pdf", "final_url": res.final_url}
    try:
        _write_atomic(dest, res.content)
        _write_atomic(_meta_path(dest), json.dumps({"final_url": res.final_url, "url": url}).encode())
    except OSError as e:
        status = f"error:{type(e).__name__}"
        log.info("download %s -> %s", url, status)
        return {**empty, "download_status": status, "final_url": res.final_url}
    log.info("download %s -> ok (%d bytes) %s", url, len(res.content), pdf_path)
    return {
        "download_status": "ok",
        "final_url": res.final_url,
        "sha256": _sha256(res.content),
        "size_bytes": len(res.content),
        "pdf_path": pdf_path,
    }


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
    documents_dir = Path(documents_dir)
    results: dict[str, dict] = {}  # url_normalized -> download fields
    taken: dict[tuple[str, str], str] = {}  # (folder, file name) -> url_normalized
    out: list[dict] = []
    for link in links:
        row = dict(link)
        if not _truthy(link.get("is_target")):
            row.update({k: "" for k in _DOWNLOAD_FIELDS})
            row["download_status"] = "skipped_not_target"
            out.append(row)
            continue
        url = link.get("url_normalized") or urls.normalize_url(link.get("url") or "")
        if url not in results:
            folder = urls.slug_dir(link.get("dc_id") or "")
            name = safe_basename(url)
            other = taken.get((folder, name))
            if other is not None and other != url:
                name = f"{name}__{hashlib.sha1(url.encode('utf-8')).hexdigest()[:8]}"
            taken[(folder, name)] = url
            dest = documents_dir / folder / f"{name}.pdf"
            results[url] = _download_one(fetcher, url, dest, _rel_posix(dest, base_dir), refresh)
        row.update(results[url])
        out.append(row)
    return out


def _truthy(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return bool(value)


def _md_dest(pdf: Path, markdown_dir: Path, documents_dir: Path) -> Path:
    try:
        rel = pdf.resolve().relative_to(Path(documents_dir).resolve())
    except ValueError:
        rel = Path(pdf.parent.name) / pdf.name
    return Path(markdown_dir) / rel.with_suffix(".md")


def convert_documents(
    links: list[dict],
    markdown_dir: Path,
    documents_dir: Path,
    base_dir: Path | None = None,
    refresh: bool = False,
) -> list[dict]:
    """Return copies of ``links`` with md_path and md_status filled for rows whose download_status == 'ok'."""
    done: dict[str, tuple[str, str]] = {}  # pdf_path -> (md_path, md_status)
    out: list[dict] = []
    for link in links:
        row = dict(link)
        pdf_path = link.get("pdf_path") or ""
        if link.get("download_status") != "ok" or not pdf_path:
            row["md_path"] = ""
            row["md_status"] = ""
            out.append(row)
            continue
        if pdf_path not in done:
            pdf = _from_rel(pdf_path, base_dir)
            md = _md_dest(pdf, markdown_dir, documents_dir)
            status = pdf_to_markdown(pdf, md, refresh=refresh)
            done[pdf_path] = (_rel_posix(md, base_dir), status)
        row["md_path"], row["md_status"] = done[pdf_path]
        out.append(row)
    return out
