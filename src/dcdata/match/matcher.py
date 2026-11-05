"""Auction -> DC credit event matching. [Work package D]

Stages, evaluated per auction in this order (PLAN.md section 5.D.2):

1. ``exact_link``      normalize_dc_url(isda_link) == event dc_url, and the raw path was already canonical
                       (only case / trailing slash / scheme differ).
2. ``normalized_link`` as above, but only after the '/cds/' path repair (e.g. '/lcds/cds/...').
3. ``document_link``   isda_link is a document URL found in dc_documents.url_normalized.
4. ``fuzzy``           name score + date window + deterministic ranking.
5. ``unmatched``
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date
from urllib.parse import urlsplit, urlunsplit

from rapidfuzz import fuzz

from ..schemas import AUCTIONS_COLUMNS, MATCHES_COLUMNS
from ..urls import normalize_dc_url, normalize_url, quote_href
from .normalize import normalize_name

log = logging.getLogger(__name__)

DECIDED = "Question Decided"
REVIEW_MARGIN = 3.0


@dataclass(frozen=True)
class Candidate:
    dc_id: str
    score: float
    gap_days: int | None
    decided: bool

    def rank_key(self) -> tuple:
        gap = abs(self.gap_days) if self.gap_days is not None else 10**9
        # dc_id is the last element: a pure deterministic tie-break.
        return (self.decided, round(self.score), -gap, self.dc_id)


def get_scorer(name: str) -> Callable[[str, str], float]:
    scorer = getattr(fuzz, name, None)
    if scorer is None or not callable(scorer):
        raise ValueError(f"unknown rapidfuzz.fuzz scorer: {name!r}")
    return scorer


def _parse_date(s: str | None) -> date | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _url_key(url: str) -> str:
    """Comparison key for DC detail URLs: normalised, lowercased."""
    return normalize_dc_url(url).lower()


def _doc_key(url: str) -> str:
    """Comparison key for document URLs: normalize_url, case- and trailing-slash-insensitive path."""
    parts = urlsplit(normalize_url(url))
    path = parts.path.lower().rstrip("/")
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, ""))


def _link_was_canonical(isda_link: str) -> bool:
    """True when normalize_dc_url did not need to repair the path (only case/slash/scheme)."""
    raw_path = urlsplit(quote_href(isda_link)).path.lower()
    if not raw_path.endswith("/"):
        raw_path += "/"
    return raw_path == urlsplit(normalize_dc_url(isda_link)).path.lower()


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
                self.by_url.setdefault(_url_key(ev["dc_url"]), ev)
        self.names = {
            dc_id: normalize_name(ev.get("reference_entity", "")) for dc_id, ev in self.by_id.items()
        }
        self.submitted = {dc_id: _parse_date(ev.get("submitted_date")) for dc_id, ev in self.by_id.items()}
        self.decided = {dc_id: ev.get("outcome", "") == DECIDED for dc_id, ev in self.by_id.items()}
        self.docs: dict[str, set[str]] = {}
        for doc in documents:
            url = doc.get("url_normalized") or doc.get("url") or ""
            dc_id = doc.get("dc_id", "")
            if url and dc_id in self.by_id:
                self.docs.setdefault(_doc_key(url), set()).add(dc_id)


def _auction_names(auction: dict) -> list[str]:
    names = []
    for col in ("legal_name", "short_name"):
        n = normalize_name(auction.get(col, ""))
        if n and n not in names:
            names.append(n)
    return names


def _score(names: list[str], entity: str, scorer: Callable[[str, str], float]) -> float:
    if not entity or not names:
        return 0.0
    return max(float(scorer(n, entity)) for n in names)


def rank_candidates(
    auction: dict,
    index: _EventIndex,
    scorer: Callable[[str, str], float],
    threshold: float | None,
    date_window: tuple[int, int] | None,
    restrict_to: Iterable[str] | None = None,
) -> list[Candidate]:
    """Candidates sorted best first. ``threshold``/``date_window`` of None disable that filter
    (used to break ties among document_link candidates)."""
    names = _auction_names(auction)
    auction_date = _parse_date(auction.get("auction_date"))
    dc_ids = sorted(restrict_to) if restrict_to is not None else list(index.by_id)
    out: list[Candidate] = []
    for dc_id in dc_ids:
        submitted = index.submitted.get(dc_id)
        gap = (auction_date - submitted).days if (auction_date and submitted) else None
        if date_window is not None:
            if gap is None or not (date_window[0] <= gap <= date_window[1]):
                continue
        score = _score(names, index.names.get(dc_id, ""), scorer)
        if threshold is not None and score < threshold:
            continue
        out.append(Candidate(dc_id, score, gap, index.decided.get(dc_id, False)))
    out.sort(key=Candidate.rank_key, reverse=True)
    return out


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


def _fmt_score(score: float) -> str:
    r = round(score, 1)
    return str(int(r)) if float(r).is_integer() else str(r)


def _fill_ranked(row: dict, ranked: list[Candidate]) -> None:
    row["n_candidates"] = str(len(ranked))
    if len(ranked) > 1:
        row["runner_up_dc_id"] = ranked[1].dc_id
        row["runner_up_score"] = _fmt_score(ranked[1].score)


def _needs_review(ranked: list[Candidate]) -> bool:
    if len(ranked) < 2:
        return False
    best, runner = ranked[0], ranked[1]
    close = best.score - runner.score <= REVIEW_MARGIN and best.decided == runner.decided
    return close or len(ranked) > 1


def _sort_key(row: dict) -> tuple:
    aid = row.get("auction_id", "")
    try:
        aid_key = (0, int(aid), "")
    except ValueError:
        aid_key = (1, 0, aid)
    return (row.get("auction_date", ""), aid_key)


def match_one(
    auction: dict,
    index: _EventIndex,
    scorer: Callable[[str, str], float],
    threshold: float,
    date_window: tuple[int, int],
) -> dict:
    row = _base_row(auction)
    row["needs_review"] = "false"
    link = (auction.get("isda_link") or "").strip()

    # 1/2. detail-page link
    if link:
        ev = index.by_url.get(_url_key(link))
        if ev is not None:
            _fill_event(row, ev)
            row["match_method"] = "exact_link" if _link_was_canonical(link) else "normalized_link"
            row["match_score"] = "100"
            row["n_candidates"] = "1"
            return row

    # 3. document link
    if link:
        dc_ids = index.docs.get(_doc_key(link))
        if dc_ids:
            if len(dc_ids) == 1:
                ranked = [Candidate(next(iter(dc_ids)), 100.0, None, False)]
            else:
                ranked = rank_candidates(auction, index, scorer, None, None, restrict_to=dc_ids)
            _fill_event(row, index.by_id[ranked[0].dc_id])
            row["match_method"] = "document_link"
            row["match_score"] = "100"
            _fill_ranked(row, ranked)
            return row

    # 4. fuzzy
    ranked = rank_candidates(auction, index, scorer, threshold, date_window)
    if ranked:
        best = ranked[0]
        _fill_event(row, index.by_id[best.dc_id])
        row["match_method"] = "fuzzy"
        row["match_score"] = _fmt_score(best.score)
        _fill_ranked(row, ranked)
        row["needs_review"] = "true" if _needs_review(ranked) else "false"
        return row

    # 5. unmatched
    row["match_method"] = "unmatched"
    row["n_candidates"] = "0"
    return row


def match_auctions(
    auctions: list[dict],
    events: list[dict],
    documents: list[dict],
    scorer: str = "token_sort_ratio",
    threshold: float = 80.0,
    date_window: tuple[int, int] = (-7, 365),
) -> list[dict]:
    """One dict per auction with schemas.MATCHES_COLUMNS."""
    scorer_fn = get_scorer(scorer)
    index = _EventIndex(events, documents)
    window = (int(date_window[0]), int(date_window[1]))
    rows = [match_one(a, index, scorer_fn, float(threshold), window) for a in auctions]
    rows.sort(key=_sort_key)
    return rows
