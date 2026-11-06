"""Download target PDFs and convert them to Markdown. [Work package B]"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path

import httpx

from .. import schemas, urls
from ..http import Fetcher
from ..pdfmd import pdf_to_markdown
from ..util import write_atomic

log = logging.getLogger(__name__)

PDF_MAGIC = b"%PDF-"
_UNSAFE_RE = re.compile(r"[^A-Za-z0-9._-]")
_MAX_BASENAME = 120
# Sidecar next to each destination PDF recording the download outcome (final_url, status, sha256,
# size). A rerun reuses it instead of re-hashing the PDF, and does not re-request links that failed
# permanently (404/410/not_pdf), so reruns are fast and report byte-identical rows.
_META_SUFFIX = ".meta.json"
# not_pdf is not listed: a 200 HTML page (maintenance, bot challenge) may be transient.
_PERMANENT_FAILURES = {"http_404", "http_410"}

_DOWNLOAD_FIELDS = tuple(c for c in schemas.DC_DOWNLOAD_COLUMNS if c not in ("md_path", "md_status"))


def safe_basename(url: str) -> str:
    """Last non-empty URL path segment, unquoted, '.pdf' stripped, unsafe chars -> '_', <=120 chars."""
    name = re.sub(r"\.pdf$", "", urls.url_filename(url), flags=re.IGNORECASE)
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


def _meta_path(pdf: Path) -> Path:
    return pdf.with_name(pdf.name + _META_SUFFIX)


def _read_meta(pdf: Path) -> dict:
    try:
        return json.loads(_meta_path(pdf).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _outcome(status: str, final_url: str = "", data: bytes | None = None, pdf_path: str = "") -> dict:
    out = dict.fromkeys(_DOWNLOAD_FIELDS, "")
    out.update(download_status=status, final_url=final_url)
    if data is not None:
        out.update(sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data), pdf_path=pdf_path)
    return out


def _write_meta(dest: Path, url: str, out: dict) -> None:
    meta = {k: out[k] for k in ("download_status", "final_url", "sha256", "size_bytes")}
    write_atomic(_meta_path(dest), json.dumps({**meta, "url": url}, sort_keys=True).encode())


def _from_meta(dest: Path, url: str, pdf_path: str) -> dict | None:
    """Outcome recorded by an earlier run, or None if the link must be (re)fetched."""
    meta = _read_meta(dest)
    if meta and meta.get("url") != url:  # the file name now belongs to a different URL
        return None
    status = meta.get("download_status")
    if status in _PERMANENT_FAILURES:
        return _outcome(status, meta.get("final_url", ""))
    if not dest.exists():
        return None
    if status == "ok" and meta.get("sha256") and meta.get("size_bytes") == dest.stat().st_size:
        out = _outcome("ok", meta.get("final_url", ""))
        out.update(sha256=meta["sha256"], size_bytes=meta["size_bytes"], pdf_path=pdf_path)
        return out
    # PDF without a complete sidecar (older run, or the PDF changed): hash it once and record that.
    out = _outcome("ok", meta.get("final_url", ""), dest.read_bytes(), pdf_path)
    _write_meta(dest, url, out)
    return out


def _download_one(fetcher: Fetcher, url: str, dest: Path, pdf_path: str, refresh: bool) -> dict:
    if not refresh and (cached := _from_meta(dest, url, pdf_path)) is not None:
        log.debug("reuse %s -> %s", url, cached["download_status"])
        return cached
    try:
        res = fetcher.get(url)
    except (httpx.HTTPError, httpx.InvalidURL, OSError, ValueError) as e:
        out = _outcome(f"error:{type(e).__name__}")
    else:
        if not res.ok:
            out = _outcome(f"http_{res.status}", res.final_url)
        elif res.content[:5] != PDF_MAGIC:
            out = _outcome("not_pdf", res.final_url)
        else:
            out = _outcome("ok", res.final_url, res.content, pdf_path)
            try:
                write_atomic(dest, res.content)
            except OSError as e:
                out = _outcome(f"error:{type(e).__name__}", res.final_url)
    if out["download_status"] == "ok" or out["download_status"] in _PERMANENT_FAILURES:
        _write_meta(dest, url, out)
    log.info("download %s -> %s %s", url, out["download_status"], out["pdf_path"])
    return out


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
        if not link["is_target"]:
            out.append({**link, **_outcome("skipped_not_target")})
            continue
        url = link["url_normalized"]
        if url not in results:
            folder = urls.slug_dir(link["dc_id"])
            name = safe_basename(url)
            # Compare names case-insensitively: Windows/macOS file systems do.
            other = taken.get((folder, name.lower()))
            if other is not None and other != url:
                name = f"{name}__{hashlib.sha1(url.encode('utf-8')).hexdigest()[:8]}"
            taken[(folder, name.lower())] = url
            dest = documents_dir / folder / f"{name}.pdf"
            results[url] = _download_one(fetcher, url, dest, _rel_posix(dest, base_dir), refresh)
        out.append({**link, **results[url]})
    return out


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
