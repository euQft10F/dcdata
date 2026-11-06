"""Read CSVs, match, write matches.csv and credit_events_with_auctions.csv. [Work package D]"""

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

_PRODUCER = {AUCTIONS_CSV: "dcdata auctions", EVENTS_CSV: "dcdata dc", DOCUMENTS_CSV: "dcdata dc"}


def _read_input(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"{path} not found; run `{_PRODUCER[path.name]}` first to create it")
    return read_csv(path)


def _int_or(s: str, default: int = 0) -> int:
    try:
        return int(s)
    except (TypeError, ValueError):
        return default


def _dt_key(s: str) -> tuple:
    """Chronological key for an ISO datetime with offset; unparsable values sort first."""
    try:
        dt = datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return (0, 0.0, s or "")
    return (1, dt.timestamp(), s)


def latest_decision_dates(documents: list[dict]) -> dict[str, str]:
    """dc_id -> max(doc_date or entry_datetime[:10]) over its dc_decision documents."""
    out: dict[str, str] = {}
    for d in documents:
        if d.get("doc_type") != "dc_decision":
            continue
        value = d.get("doc_date") or (d.get("entry_datetime") or "")[:10]
        if not value:
            continue
        dc_id = d.get("dc_id", "")
        if value > out.get(dc_id, ""):
            out[dc_id] = value
    return out


def final_list_pdf_paths(documents: list[dict]) -> dict[str, str]:
    """dc_id -> pdf_path of the most recent final_list doc (by entry_datetime, entry_seq, link_seq)
    that has a pdf_path."""
    best: dict[str, tuple] = {}
    for d in documents:
        if d.get("doc_type") != "final_list" or not d.get("pdf_path"):
            continue
        key = (
            _dt_key(d.get("entry_datetime", "")),
            _int_or(d.get("entry_seq", "")),
            _int_or(d.get("link_seq", "")),
        )
        dc_id = d.get("dc_id", "")
        if dc_id not in best or key > best[dc_id][0]:
            best[dc_id] = (key, d["pdf_path"])
    return {dc_id: v[1] for dc_id, v in best.items()}


def build_joined(events: list[dict], matches: list[dict], documents: list[dict]) -> list[dict]:
    """DC-centric left join (PLAN.md section 4.6)."""
    by_dc: dict[str, list[dict]] = {}
    for m in matches:
        if m.get("dc_id"):
            by_dc.setdefault(m["dc_id"], []).append(m)
    decision = latest_decision_dates(documents)
    final_list = final_list_pdf_paths(documents)
    rows = []
    for ev in events:
        base = {c: ev.get(c, "") for c in DC_EVENTS_COLUMNS}
        dc_id = ev.get("dc_id", "")
        base["latest_decision_date"] = decision.get(dc_id, "")
        base["final_list_pdf_path"] = final_list.get(dc_id, "")
        auctions = by_dc.get(dc_id) or [None]
        for m in auctions:
            row = dict(base)
            for c in JOINED_AUCTION_COLUMNS:
                row[c] = m.get(c, "") if m is not None else ""
            rows.append(row)

    def sort_key(r: dict) -> tuple:
        aid = r.get("auction_id", "")
        return (
            r.get("submitted_date", ""),
            r.get("dc_id", ""),
            r.get("auction_date", "") == "",
            r.get("auction_date", ""),
            aid == "",
            _int_or(aid),
        )

    rows.sort(key=sort_key)
    return rows


def run_match(settings: Settings) -> dict:
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
    matched_dc = {m["dc_id"] for m in matches if m.get("dc_id")}
    summary = {
        "n_auctions": len(matches),
        "methods": methods,
        "n_needs_review": sum(1 for m in matches if m.get("needs_review") == "true"),
        "n_events": len(events),
        "n_events_with_auction": sum(1 for e in events if e.get("dc_id") in matched_dc),
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
