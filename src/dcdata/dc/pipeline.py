"""Orchestrates the DC scrape: archive -> detail pages -> classify -> download -> markdown -> CSVs."""

from __future__ import annotations

import logging
from collections import Counter
from pathlib import Path

from .. import csvio, schemas
from ..config import Settings
from ..http import Fetcher
from ..urls import slug_dir
from .archive import fetch_archive, parse_archive_row
from .classify import annotate_link
from .detail import parse_procedural_history
from .documents import convert_documents, download_documents

log = logging.getLogger(__name__)


def _detail_status(res, parsed) -> str:
    if not res.ok:
        return f"http_{res.status}"
    return "ok" if parsed is not None else "ok_no_history"


def run_dc(
    settings: Settings,
    fetcher: Fetcher,
    limit: int | None = None,
    download: bool = True,
    markdown: bool = True,
) -> dict:
    out = settings.output_dir
    base_dir = Path.cwd()

    raw_rows = fetch_archive(fetcher, refresh=settings.refresh)
    events = [parse_archive_row(r) for r in raw_rows]
    events.sort(key=lambda e: (e["submitted_date"], e["dc_id"]))
    log.info("archive: %d credit events", len(events))
    if limit is not None:
        events = events[:limit]

    history: list[dict] = []
    links: list[dict] = []
    for i, ev in enumerate(events, 1):
        dc_id = ev["dc_id"]
        if not ev["dc_url"]:
            log.warning("archive row %r has no detail link; skipping", ev["reference_entity"])
            ev.update(detail_fetch_status="no_detail_url", n_history_entries=0, n_target_documents=0)
            continue
        try:
            res = fetcher.get(
                ev["dc_url"], cache_key=f"dc/pages/{slug_dir(dc_id)}.html", refresh=settings.refresh
            )
            parsed = parse_procedural_history(res.text, dc_id, res.final_url) if res.ok else None
            ev["detail_fetch_status"] = _detail_status(res, parsed)
        except Exception as e:  # network failure after retries: record and continue
            log.warning("detail %s failed: %r", dc_id, e)
            parsed, ev["detail_fetch_status"] = None, f"error:{type(e).__name__}"
        entries, ev_links = parsed if parsed is not None else ([], [])
        ev_links = [annotate_link(lk, settings.target_doc_types) for lk in ev_links]
        ev["n_history_entries"] = len(entries)
        ev["n_target_documents"] = sum(1 for lk in ev_links if lk["is_target"])
        history.extend(entries)
        links.extend(ev_links)
        log.info(
            "[%d/%d] %s: %d entries, %d links, %d target (%s)",
            i,
            len(events),
            dc_id,
            len(entries),
            len(ev_links),
            ev["n_target_documents"],
            ev["detail_fetch_status"],
        )

    history.sort(key=lambda r: (r["dc_id"], r["entry_seq"]))
    links.sort(key=lambda r: (r["dc_id"], r["entry_seq"], r["link_seq"]))

    if download:
        links = download_documents(
            fetcher, links, settings.documents_dir, base_dir=base_dir, refresh=settings.refresh
        )
        if markdown:
            links = convert_documents(
                links,
                settings.markdown_dir,
                settings.documents_dir,
                base_dir=base_dir,
                refresh=settings.refresh,
            )
    else:
        for lk in links:
            lk["download_status"] = "not_attempted" if lk["is_target"] else "skipped_not_target"

    csvio.write_csv(events, out / "dc_credit_events.csv", schemas.DC_EVENTS_COLUMNS)
    csvio.write_csv(history, out / "dc_procedural_history.csv", schemas.DC_HISTORY_COLUMNS)
    csvio.write_csv(links, out / "dc_documents.csv", schemas.DC_DOCUMENTS_COLUMNS)

    summary = {
        "n_events": len(events),
        "n_history_entries": len(history),
        "n_links": len(links),
        "n_target_links": sum(1 for lk in links if lk["is_target"]),
        "detail_status": dict(sorted(Counter(e["detail_fetch_status"] for e in events).items())),
        "doc_types": dict(sorted(Counter(lk["doc_type"] for lk in links).items())),
        "download_status": dict(sorted(Counter(lk["download_status"] for lk in links).items())),
        "md_status": dict(
            sorted(Counter(lk.get("md_status", "") for lk in links if lk.get("md_status")).items())
        ),
    }
    log.info("dc summary: %s", summary)
    return summary
