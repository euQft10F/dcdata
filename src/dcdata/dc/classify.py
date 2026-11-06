"""Classify Procedural History links into document types. [Work package B]"""

from __future__ import annotations

import re
from collections.abc import Collection
from datetime import date
from urllib.parse import urlsplit

from ..urls import url_filename

# Ordered rules, first match wins (PLAN.md section 5.B, with two documented refinements).
#
# Refinements over the plain PLAN table:
# * "meeting statement" is checked *before* the decision rule. Meeting statements are never DC
#   Decisions, but their titles can mention one ("Meeting Statement regarding the Decision ..."),
#   which would otherwise be caught by ``\bdecision\b``. A bare "statement" (e.g. "EMEA DC
#   Statement 01032012") stays after the decision rule, as in the PLAN, so that a decision whose
#   title merely mentions a statement is still a decision.
# * auction_info ("Required Information for Auction Settlement Terms", "Auction Checklist") is
#   checked *before* auction_terms, because those titles contain "Auction Settlement Terms" but are
#   only the checklist of information requested for the terms, not the terms themselves.
#
# Note on rule dc_decision: ``\bdetermination\b`` already cannot match "Determinations"; the
# lookahead is kept from the PLAN for clarity. "EMEA Determinations Committee Decision ..." is a
# decision through ``\bdecision\b``; "Auction Timetable" decisions are decisions too.
_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("redline", re.compile(r"\bredline\b")),
    ("statement", re.compile(r"\bmeeting statement\b")),
    ("dc_decision", re.compile(r"\bdecision\b|\bresolutions?\b|\bdetermination\b(?!s committee\b)")),
    ("final_list", re.compile(r"\bfinal list\b")),
    ("initial_list", re.compile(r"\binitial list\b")),
    ("preliminary_list", re.compile(r"\bpreliminary list\b")),
    ("auction_info", re.compile(r"\bauction (?:checklist|information)\b|\brequired information\b")),
    ("auction_terms", re.compile(r"\bauction settlement terms\b|\bauction terms\b")),
    ("bidders", re.compile(r"\bparticipating bidders\b")),
    ("statement", re.compile(r"\bstatement\b")),
]

# Anchor texts that say nothing about the document; classify on the URL filename instead.
_GENERIC_TEXTS = {
    "",
    "view attachment",
    "attachment",
    "click here",
    "here",
    "pdf",
    "download",
    "download pdf",
    "view",
    "view pdf",
    "view document",
    "document",
    "link",
    "more",
    "read more",
}

_PDF_PATH_RE = re.compile(r"\.pdf(?:/|$)", re.IGNORECASE)


def _filename_words(url: str) -> str:
    """URL filename as words: unquoted, '-'/'_' -> spaces, extension stripped."""
    name = url_filename(url)
    name = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", name)
    return re.sub(r"[-_]+", " ", name)


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def _is_generic(text: str) -> bool:
    t = _norm(re.sub(r"[^\w\s]", " ", text))
    return t in _GENERIC_TEXTS or not re.search(r"[a-z]", t)


def classify_link(text: str, url: str) -> str:
    """-> one of redline, dc_decision, final_list, initial_list, preliminary_list, auction_terms,
    bidders, statement, auction_info, other_pdf, other_link."""
    subject = _filename_words(url) if _is_generic(text or "") else text
    subject = _norm(subject)
    for doc_type, pattern in _RULES:
        if pattern.search(subject):
            return doc_type
    if _PDF_PATH_RE.search(urlsplit((url or "").strip()).path):
        return "other_pdf"
    return "other_link"


_ISSUE_RE = re.compile(r"Issue Number\s*:?\s*(\d{10})(?!\d)", re.IGNORECASE)


def extract_issue_number(text: str) -> str:
    m = _ISSUE_RE.search(text or "")
    return m.group(1) if m else ""


_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
_MONTH_NAME = (
    r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
    r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
)
# MM/DD/YY or MM/DD/YYYY (US style, as used in Americas DC link texts).
_US_NUMERIC_RE = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})(?!\d)")
_MONTH_D_YYYY_RE = re.compile(rf"\b{_MONTH_NAME}\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.I)
_D_MONTH_YYYY_RE = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+{_MONTH_NAME},?\s+(\d{{4}})\b", re.I)
_ISO_RE = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
_EIGHT_DIGITS_RE = re.compile(r"(?<!\d)(\d{8})(?!\d)")

_MIN_YEAR, _MAX_YEAR = 1990, 2099


def _mkdate(y: int, m: int, d: int) -> date | None:
    if not (_MIN_YEAR <= y <= _MAX_YEAR):
        return None
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _month_num(name: str) -> int:
    return _MONTHS[name.lower()[:3]]


def _named_dates(s: str) -> date | None:
    """'Month D, YYYY' or 'D Month YYYY' -- whichever appears first."""
    found: list[tuple[int, date]] = []
    for m in _MONTH_D_YYYY_RE.finditer(s):
        d = _mkdate(int(m.group(3)), _month_num(m.group(1)), int(m.group(2)))
        if d:
            found.append((m.start(), d))
            break
    for m in _D_MONTH_YYYY_RE.finditer(s):
        d = _mkdate(int(m.group(3)), _month_num(m.group(2)), int(m.group(1)))
        if d:
            found.append((m.start(), d))
            break
    return min(found)[1] if found else None


def _compact_dates(s: str) -> date | None:
    """ISO 'YYYY-MM-DD', then 8-digit 'YYYYMMDD' / 'DDMMYYYY' (accepted only if exactly one reading
    is a valid date; with the 1990-2099 year range the two readings cannot both be valid)."""
    for m in _ISO_RE.finditer(s):
        d = _mkdate(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d:
            return d
    for m in _EIGHT_DIGITS_RE.finditer(s):
        g = m.group(1)
        candidates = {
            c
            for c in (
                _mkdate(int(g[:4]), int(g[4:6]), int(g[6:])),  # YYYYMMDD
                _mkdate(int(g[4:]), int(g[2:4]), int(g[:2])),  # DDMMYYYY
            )
            if c
        }
        if len(candidates) == 1:
            return candidates.pop()
    return None


def _text_date(text: str) -> date | None:
    for m in _US_NUMERIC_RE.finditer(text):
        year = int(m.group(3))
        if year < 100:  # DC decisions start in 2009; '98' is 1998, not 2098
            year += 2000 if year < 90 else 1900
        d = _mkdate(year, int(m.group(1)), int(m.group(2)))
        if d:
            return d
    return _named_dates(text) or _compact_dates(text)


def _filename_date(url: str) -> date | None:
    raw = url_filename(url)
    # Numeric dashed dates in filenames ("decision-08-10-26") are ambiguous (MM-DD vs DD-MM) and
    # are not parsed; named months ("dc-decision-17-may-2023") and compact forms are.
    return _compact_dates(raw) or _named_dates(_filename_words(url))


def extract_doc_date(text: str, url: str) -> str:
    """ISO date parsed from link text (or the URL filename), '' if none."""
    d = _text_date(text or "") or _filename_date(url or "")
    return d.isoformat() if d else ""


def annotate_link(link: dict, target_types: Collection[str]) -> dict:
    """Return a copy of ``link`` with doc_type, is_target, doc_issue_number, doc_date added."""
    text = link["link_text"]
    url = link["url_normalized"]
    doc_type = classify_link(text, url)
    out = dict(link)
    out["doc_type"] = doc_type
    out["is_target"] = doc_type in target_types
    out["doc_issue_number"] = extract_issue_number(text)
    out["doc_date"] = extract_doc_date(text, url)
    return out
