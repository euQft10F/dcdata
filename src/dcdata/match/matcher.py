"""Auction -> DC credit event matching, by link only.

Stages, evaluated per auction in this order:

1. ``exact_link``      the auction's ``isda_link`` is a DC detail page URL, and its path was already
                       canonical (only case / trailing slash / scheme / ``www.`` differ).
2. ``normalized_link`` same, but only after the '/cds/' path repair (e.g. '/lcds/cds/...').
3. ``document_link``   ``isda_link`` is a document URL found in dc_documents.url_normalized.
4. ``unmatched``       no usable link. There is deliberately no name-based guess.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import date

from ..schemas import AUCTIONS_COLUMNS, MATCHES_COLUMNS
from ..urls import dc_path_repaired, dc_url_key, doc_url_key

log = logging.getLogger(__name__)

DECIDED = "Question Decided"


def _parse_date(s: str | None) -> date | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


class _EventIndex:
    """Precomputed lookups over the DC events table."""

    def __init__(self, events: Iterable[dict], documents: Iterable[dict]):
        self.by_id: dict[str, dict] = {}
        self.by_url: dict[str, dict] = {}
        for ev in sorted(events, key=lambda e: e.get("dc_id", "")):
            dc_id = ev.get("dc_id", "")
            if not dc_id or dc_id in self.by_id:
                continue
            self.by_id[dc_id] = ev
            if ev.get("dc_url"):
                self.by_url.setdefault(dc_url_key(ev["dc_url"]), ev)
        self.docs: dict[str, set[str]] = {}
        for doc in documents:
            url, dc_id = doc["url_normalized"], doc["dc_id"]
            if url and dc_id in self.by_id:
                self.docs.setdefault(doc_url_key(url), set()).add(dc_id)


def _rank_document_events(auction: dict, index: _EventIndex, dc_ids: Iterable[str]) -> list[str]:
    """Order events that all link the same document: decided questions first, then the one
    submitted closest to the auction date, then ``dc_id`` (a pure deterministic tie-break)."""
    auction_date = _parse_date(auction.get("auction_date"))

    def key(dc_id: str) -> tuple:
        ev = index.by_id[dc_id]
        submitted = _parse_date(ev.get("submitted_date"))
        gap = abs((auction_date - submitted).days) if auction_date and submitted else 10**9
        return (ev.get("outcome", "") != DECIDED, gap, dc_id)

    return sorted(dc_ids, key=key)


def _base_row(auction: dict) -> dict:
    row = {c: auction.get(c, "") for c in AUCTIONS_COLUMNS}
    row.update({c: "" for c in MATCHES_COLUMNS if c not in row})
    return row


def _fill_event(row: dict, ev: dict) -> None:
    row["dc_id"] = ev.get("dc_id", "")
    row["dc_url"] = ev.get("dc_url", "")
    row["dc_reference_entity"] = ev.get("reference_entity", "")
    row["dc_issue_number"] = ev.get("issue_number", "")
    row["dc_submitted_date"] = ev.get("submitted_date", "")
    row["dc_outcome"] = ev.get("outcome", "")


def _sort_key(row: dict) -> tuple:
    aid = row.get("auction_id", "")
    try:
        aid_key = (0, int(aid), "")
    except ValueError:
        aid_key = (1, 0, aid)
    return (row.get("auction_date", ""), aid_key)


def match_one(auction: dict, index: _EventIndex) -> dict:
    row = _base_row(auction)
    row["needs_review"] = "false"
    link = (auction.get("isda_link") or "").strip()

    if link:
        # 1/2. detail-page link
        ev = index.by_url.get(dc_url_key(link))
        if ev is not None:
            _fill_event(row, ev)
            row["match_method"] = "normalized_link" if dc_path_repaired(link) else "exact_link"
            row["n_candidates"] = "1"
            return row

        # 3. document link
        dc_ids = index.docs.get(doc_url_key(link))
        if dc_ids:
            ranked = _rank_document_events(auction, index, dc_ids)
            _fill_event(row, index.by_id[ranked[0]])
            row["match_method"] = "document_link"
            row["n_candidates"] = str(len(ranked))
            if len(ranked) > 1:
                # Several events link the same document: the pick is a tie-break, so review it.
                row["runner_up_dc_id"] = ranked[1]
                row["needs_review"] = "true"
            return row

    # 4. unmatched
    row["match_method"] = "unmatched"
    row["n_candidates"] = "0"
    return row


def match_auctions(auctions: list[dict], events: list[dict], documents: list[dict]) -> list[dict]:
    """One dict per auction with schemas.MATCHES_COLUMNS."""
    index = _EventIndex(events, documents)
    rows = [match_one(a, index) for a in auctions]
    rows.sort(key=_sort_key)
    return rows
