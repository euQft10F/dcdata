"""The ``dc`` step: archive -> detail pages -> classify links -> download PDFs -> Markdown -> CSVs.

Terminology: an *event* is one credit-event question (a dc_events row, keyed by ``dc_id``); a
*history entry* is one dated Procedural History item of an event; a *link* is one hyperlink inside
an entry (a dc_documents row).
"""

from __future__ import annotations

import logging
from collections import Counter
from pathlib import Path

from .. import csvio, schemas
from ..config import Settings
from ..http import Fetcher, FetchResult
from ..urls import slug_dir
from .archive import fetch_archive, parse_archive_row
from .classify import annotate_link
from .detail import parse_procedural_history
from .documents import convert_documents, download_documents

log = logging.getLogger(__name__)


def _detail_status(response: FetchResult, parsed: tuple | None) -> str:
    """``detail_fetch_status`` of an event whose detail page was fetched without raising."""
    if not response.ok:
        return f"http_{response.status}"
    return "ok" if parsed is not None else "ok_no_history"


def _scrape_detail(fetcher: Fetcher, settings: Settings, event: dict) -> tuple[list[dict], list[dict]]:
    """Fetch and parse one event's detail page. Returns ``(history entries, classified links)``.

    Sets ``detail_fetch_status``, ``n_history_entries`` and ``n_target_documents`` on ``event``.
    A failed fetch is recorded in the status and yields no entries; it never raises."""
    dc_id = event["dc_id"]
    try:
        response = fetcher.get(
            event["dc_url"], cache_key=f"dc/pages/{slug_dir(dc_id)}.html", refresh=settings.refresh
        )
        parsed = parse_procedural_history(response.text, dc_id, response.final_url) if response.ok else None
        event["detail_fetch_status"] = _detail_status(response, parsed)
    except Exception as e:  # network failure after retries: record and continue
        log.warning("detail %s failed: %r", dc_id, e)
        parsed, event["detail_fetch_status"] = None, f"error:{type(e).__name__}"
    entries, links = parsed if parsed is not None else ([], [])
    links = [annotate_link(link, settings.target_doc_types) for link in links]
    event["n_history_entries"] = len(entries)
    event["n_target_documents"] = sum(1 for link in links if link["is_target"])
    return entries, links


def _counts(values) -> dict:
    """Value -> count, sorted by value, for the run_log summary."""
    return dict(sorted(Counter(values).items()))


def run_dc(
    settings: Settings,
    fetcher: Fetcher,
    limit: int | None = None,
    download: bool = True,
    markdown: bool = True,
) -> dict:
    """Run the DC step, write its three CSVs, and return the summary stored in run_log.json.

    ``limit`` keeps only the first N events (oldest first); ``download`` / ``markdown`` switch the
    PDF download and PDF -> Markdown stages off."""
    output_dir = settings.output_dir
    base_dir = Path.cwd()  # pdf_path / md_path are recorded relative to the working directory

    # Stage 1: every credit-event question from the archive, oldest first.
    events = [parse_archive_row(row) for row in fetch_archive(fetcher, refresh=settings.refresh)]
    events.sort(key=lambda e: (e["submitted_date"], e["dc_id"]))
    log.info("archive: %d credit events", len(events))
    if limit is not None:
        events = events[:limit]

    # Stage 2: each event's detail page -> history entries and (classified) links.
    history: list[dict] = []
    links: list[dict] = []
    for i, event in enumerate(events, 1):
        if not event["dc_url"]:
            log.warning("archive row %r has no detail link; skipping", event["reference_entity"])
            event.update(detail_fetch_status="no_detail_url", n_history_entries=0, n_target_documents=0)
            continue
        entries, event_links = _scrape_detail(fetcher, settings, event)
        history.extend(entries)
        links.extend(event_links)
        log.info(
            "[%d/%d] %s: %d entries, %d links, %d target (%s)",
            i,
            len(events),
            event["dc_id"],
            len(entries),
            len(event_links),
            event["n_target_documents"],
            event["detail_fetch_status"],
        )

    history.sort(key=lambda entry: (entry["dc_id"], entry["entry_seq"]))
    links.sort(key=lambda link: (link["dc_id"], link["entry_seq"], link["link_seq"]))

    # Stages 3-4: download the target PDFs, then convert them to Markdown.
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
        for link in links:
            link["download_status"] = "not_attempted" if link["is_target"] else "skipped_not_target"

    csvio.write_csv(events, output_dir / "dc_credit_events.csv", schemas.DC_EVENTS_COLUMNS)
    csvio.write_csv(history, output_dir / "dc_procedural_history.csv", schemas.DC_HISTORY_COLUMNS)
    csvio.write_csv(links, output_dir / "dc_documents.csv", schemas.DC_DOCUMENTS_COLUMNS)

    summary = {
        "n_events": len(events),
        "n_history_entries": len(history),
        "n_links": len(links),
        "n_target_links": sum(1 for link in links if link["is_target"]),
        "detail_status": _counts(e["detail_fetch_status"] for e in events),
        "doc_types": _counts(link["doc_type"] for link in links),
        "download_status": _counts(link["download_status"] for link in links),
        "md_status": _counts(link["md_status"] for link in links if link.get("md_status")),
    }
    log.info("dc summary: %s", summary)
    return summary
