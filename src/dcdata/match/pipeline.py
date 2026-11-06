"""The ``match`` step: read the scraped CSVs, match auctions to DC events, write the two joined CSVs.

Inputs  (from ``dcdata dc`` / ``dcdata auctions``): auctions.csv, dc_credit_events.csv, dc_documents.csv.
Outputs: matches.csv (auction-centric, see ``matcher``) and credit_events_with_auctions.csv
(event-centric left join, see ``build_joined``).
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime
from pathlib import Path

from ..config import Settings
from ..csvio import read_csv, write_csv
from ..schemas import (
    DC_EVENTS_COLUMNS,
    JOINED_AUCTION_COLUMNS,
    JOINED_COLUMNS,
    MATCH_METHODS,
    MATCHES_COLUMNS,
)
from .matcher import match_auctions

log = logging.getLogger(__name__)

AUCTIONS_CSV = "auctions.csv"
EVENTS_CSV = "dc_credit_events.csv"
DOCUMENTS_CSV = "dc_documents.csv"
MATCHES_CSV = "matches.csv"
JOINED_CSV = "credit_events_with_auctions.csv"

# Which command creates each input CSV, for the "file not found" hint.
_PRODUCER = {AUCTIONS_CSV: "dcdata auctions", EVENTS_CSV: "dcdata dc", DOCUMENTS_CSV: "dcdata dc"}


def _read_input(path: Path) -> list[dict]:
    """Read one of the scraper's CSVs, or fail with the command that produces it."""
    if not path.exists():
        raise FileNotFoundError(f"{path} not found; run `{_PRODUCER[path.name]}` first to create it")
    return read_csv(path)


def _int_or(value: str, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _datetime_sort_key(value: str) -> tuple:
    """Chronological key for an ISO datetime with offset; unparsable values sort first."""
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return (0, 0.0, value or "")
    return (1, parsed.timestamp(), value)


def latest_decision_dates(documents: list[dict]) -> dict[str, str]:
    """dc_id -> max(doc_date or entry_datetime[:10]) over its dc_decision documents."""
    latest: dict[str, str] = {}
    for doc in documents:
        if doc.get("doc_type") != "dc_decision":
            continue
        value = doc.get("doc_date") or (doc.get("entry_datetime") or "")[:10]
        if not value:
            continue
        dc_id = doc.get("dc_id", "")
        if value > latest.get(dc_id, ""):
            latest[dc_id] = value
    return latest


def final_list_pdf_paths(documents: list[dict]) -> dict[str, str]:
    """dc_id -> pdf_path of the most recent final_list doc (by entry_datetime, entry_seq, link_seq)
    that has a pdf_path."""
    best: dict[str, tuple] = {}  # dc_id -> (recency key, pdf_path)
    for doc in documents:
        if doc.get("doc_type") != "final_list" or not doc.get("pdf_path"):
            continue
        recency = (
            _datetime_sort_key(doc.get("entry_datetime", "")),
            _int_or(doc.get("entry_seq", "")),
            _int_or(doc.get("link_seq", "")),
        )
        dc_id = doc.get("dc_id", "")
        if dc_id not in best or recency > best[dc_id][0]:
            best[dc_id] = (recency, doc["pdf_path"])
    return {dc_id: pdf_path for dc_id, (_, pdf_path) in best.items()}


def build_joined(events: list[dict], matches: list[dict], documents: list[dict]) -> list[dict]:
    """DC-centric left join: every event, once per matched auction (once with empty auction
    columns if it has none), plus its latest decision date and final-list PDF path."""
    matches_by_dc_id: dict[str, list[dict]] = {}
    for match in matches:
        if match.get("dc_id"):
            matches_by_dc_id.setdefault(match["dc_id"], []).append(match)
    decision_dates = latest_decision_dates(documents)
    final_list_paths = final_list_pdf_paths(documents)
    rows = []
    for event in events:
        base = {c: event.get(c, "") for c in DC_EVENTS_COLUMNS}
        dc_id = event.get("dc_id", "")
        base["latest_decision_date"] = decision_dates.get(dc_id, "")
        base["final_list_pdf_path"] = final_list_paths.get(dc_id, "")
        for match in matches_by_dc_id.get(dc_id) or [None]:  # None: event without an auction
            row = dict(base)
            for column in JOINED_AUCTION_COLUMNS:
                row[column] = match.get(column, "") if match is not None else ""
            rows.append(row)

    def sort_key(row: dict) -> tuple:
        # Events by (submitted_date, dc_id); within an event, auctions by date then numeric id.
        # The `== ""` terms sort missing values last.
        auction_id = row.get("auction_id", "")
        return (
            row.get("submitted_date", ""),
            row.get("dc_id", ""),
            row.get("auction_date", "") == "",
            row.get("auction_date", ""),
            auction_id == "",
            _int_or(auction_id),
        )

    rows.sort(key=sort_key)
    return rows


def run_match(settings: Settings) -> dict:
    """Run the match step; returns the summary stored in run_log.json."""
    out_dir = settings.output_dir
    auctions = _read_input(out_dir / AUCTIONS_CSV)
    events = _read_input(out_dir / EVENTS_CSV)
    documents = _read_input(out_dir / DOCUMENTS_CSV)
    log.info("match: %d auctions, %d DC events, %d DC documents", len(auctions), len(events), len(documents))
    matches = match_auctions(auctions, events, documents)
    write_csv(matches, out_dir / MATCHES_CSV, MATCHES_COLUMNS)
    joined = build_joined(events, matches, documents)
    write_csv(joined, out_dir / JOINED_CSV, JOINED_COLUMNS)

    counts = Counter(m["match_method"] for m in matches)
    methods = {m: counts.get(m, 0) for m in MATCH_METHODS}
    matched_dc_ids = {m["dc_id"] for m in matches if m.get("dc_id")}
    summary = {
        "n_auctions": len(matches),
        "methods": methods,
        "n_needs_review": sum(1 for m in matches if m.get("needs_review") == "true"),
        "n_events": len(events),
        "n_events_with_auction": sum(1 for e in events if e.get("dc_id") in matched_dc_ids),
    }
    log.info("match methods: %s", methods)
    log.info(
        "wrote %s (%d rows) and %s (%d rows); %d need review",
        MATCHES_CSV,
        len(matches),
        JOINED_CSV,
        len(joined),
        summary["n_needs_review"],
    )
    return summary
