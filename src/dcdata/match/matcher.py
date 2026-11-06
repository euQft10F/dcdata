"""Auction -> DC credit event matching, by link only.

An auction carries one link, ``isda_link``. Stages, tried per auction in this order (first hit wins):

1. ``exact_link``      ``isda_link`` is a DC detail page URL and its path was already canonical
                       (only case / trailing slash / scheme / ``www.`` differ).
2. ``normalized_link`` same, but only after the '/cds/' path repair (e.g. '/lcds/cds/...').
3. ``document_link``   ``isda_link`` is a document URL found in dc_documents.csv (``url_normalized``);
                       if several events link that document, the best-ranked one is used and the
                       match is flagged ``needs_review``.
4. ``unmatched``       no usable link. There is deliberately no name-based guess.

``match_auctions`` is the entry point; it is pure (no I/O).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import date

from ..schemas import AUCTIONS_COLUMNS, MATCHES_COLUMNS
from ..urls import dc_path_repaired, dc_url_key, doc_url_key

log = logging.getLogger(__name__)

DECIDED = "Question Decided"


def _iso_date(value: str | None) -> date | None:
    """Parse the leading ``YYYY-MM-DD`` of a CSV cell (dates or ISO datetimes); None if absent or invalid."""
    value = (value or "").strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


class _EventIndex:
    """Lookups over the DC events and documents tables, built once per run.

    ``by_dc_id``           dc_id -> event row
    ``by_url_key``         ``dc_url_key(dc_url)`` -> event row (stages 1-2)
    ``dc_ids_by_doc_key``  ``doc_url_key(url_normalized)`` -> dc_ids of events whose Procedural
                           History links that document (stage 3)

    Events are visited in dc_id order, so a duplicate dc_id or URL key resolves deterministically
    to the smallest dc_id.
    """

    def __init__(self, events: Iterable[dict], documents: Iterable[dict]):
        self.by_dc_id: dict[str, dict] = {}
        self.by_url_key: dict[str, dict] = {}
        for event in sorted(events, key=lambda e: e.get("dc_id", "")):
            dc_id = event.get("dc_id", "")
            if not dc_id or dc_id in self.by_dc_id:
                continue
            self.by_dc_id[dc_id] = event
            if event.get("dc_url"):
                self.by_url_key.setdefault(dc_url_key(event["dc_url"]), event)
        self.dc_ids_by_doc_key: dict[str, set[str]] = {}
        for doc in documents:
            url, dc_id = doc["url_normalized"], doc["dc_id"]
            if url and dc_id in self.by_dc_id:
                self.dc_ids_by_doc_key.setdefault(doc_url_key(url), set()).add(dc_id)


def _rank_document_events(auction: dict, index: _EventIndex, dc_ids: Iterable[str]) -> list[str]:
    """Order events that all link the same document: decided questions first, then the one
    submitted closest to the auction date, then ``dc_id`` (a pure deterministic tie-break)."""
    auction_date = _iso_date(auction.get("auction_date"))

    def key(dc_id: str) -> tuple:
        event = index.by_dc_id[dc_id]
        submitted = _iso_date(event.get("submitted_date"))
        gap = abs((auction_date - submitted).days) if auction_date and submitted else 10**9
        return (event.get("outcome", "") != DECIDED, gap, dc_id)

    return sorted(dc_ids, key=key)


def _base_row(auction: dict) -> dict:
    """matches.csv row holding the auction's own columns, with every match column empty."""
    row = {c: auction.get(c, "") for c in AUCTIONS_COLUMNS}
    row.update({c: "" for c in MATCHES_COLUMNS if c not in row})
    return row


def _fill_event(row: dict, event: dict) -> None:
    """Copy the matched event's identity columns into a matches.csv row (``dc_*`` columns)."""
    row["dc_id"] = event.get("dc_id", "")
    row["dc_url"] = event.get("dc_url", "")
    row["dc_reference_entity"] = event.get("reference_entity", "")
    row["dc_issue_number"] = event.get("issue_number", "")
    row["dc_submitted_date"] = event.get("submitted_date", "")
    row["dc_outcome"] = event.get("outcome", "")


def _sort_key(row: dict) -> tuple:
    """Order matches by auction date, then numerically by auction_id (non-numeric ids last)."""
    auction_id = row.get("auction_id", "")
    try:
        id_key = (0, int(auction_id), "")
    except ValueError:
        id_key = (1, 0, auction_id)
    return (row.get("auction_date", ""), id_key)


def match_auction(auction: dict, index: _EventIndex) -> dict:
    """Match one auction to at most one DC event; returns its matches.csv row."""
    row = _base_row(auction)
    row["needs_review"] = "false"
    link = (auction.get("isda_link") or "").strip()

    if link:
        # Stages 1-2: the link is a DC detail page.
        event = index.by_url_key.get(dc_url_key(link))
        if event is not None:
            _fill_event(row, event)
            row["match_method"] = "normalized_link" if dc_path_repaired(link) else "exact_link"
            row["n_candidates"] = "1"
            return row

        # Stage 3: the link is a document that some event's Procedural History links.
        dc_ids = index.dc_ids_by_doc_key.get(doc_url_key(link))
        if dc_ids:
            ranked = _rank_document_events(auction, index, dc_ids)
            _fill_event(row, index.by_dc_id[ranked[0]])
            row["match_method"] = "document_link"
            row["n_candidates"] = str(len(ranked))
            if len(ranked) > 1:
                # Several events link the same document: the pick is a tie-break, so review it.
                row["runner_up_dc_id"] = ranked[1]
                row["needs_review"] = "true"
            return row

    # Stage 4: no link, or a link to nothing we know.
    row["match_method"] = "unmatched"
    row["n_candidates"] = "0"
    return row


def match_auctions(auctions: list[dict], events: list[dict], documents: list[dict]) -> list[dict]:
    """One matches.csv row (``schemas.MATCHES_COLUMNS``) per auction, sorted by date then auction_id.

    ``events`` and ``documents`` are the rows of dc_credit_events.csv and dc_documents.csv."""
    index = _EventIndex(events, documents)
    rows = [match_auction(a, index) for a in auctions]
    rows.sort(key=_sort_key)
    return rows
