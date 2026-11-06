"""DC archive list (DataTables JSON endpoint) fetching and row parsing."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from urllib.parse import unquote_plus, urljoin

from bs4 import BeautifulSoup

from .. import config, urls
from ..http import Fetcher
from ..util import clean_text

log = logging.getLogger(__name__)

PAGE_SIZE = 500
N_COLUMNS = 8
CATEGORY_COLUMN = 2

_FURTHER_INFO_LABEL = re.compile(r"^further information provided by question submitter\s*:?\s*", re.I)
_QUESTION_PREFIX = re.compile(r"^question\s*:\s*", re.I)

# ceMeta_3 <em> label (lowercased, without the trailing colon) -> output column
_META_LABELS = {
    "issue number": "issue_number",
    "submitted by": "submitted_by",
    "committee": "committee",
    "coverage election": "coverage_election",
}


def build_archive_form(category: str, start: int, length: int) -> list[tuple[str, str]]:
    """Full DataTables 1.9 form the archive endpoint expects; column 2 (category) is filtered by ``category``."""
    form: list[tuple[str, str]] = [
        ("sEcho", "1"),
        ("iColumns", str(N_COLUMNS)),
        ("sColumns", ""),
        ("iDisplayStart", str(start)),
        ("iDisplayLength", str(length)),
    ]
    for i in range(N_COLUMNS):
        form.append((f"mDataProp_{i}", str(i)))
    form += [("sSearch", ""), ("bRegex", "false")]
    for i in range(N_COLUMNS):
        form += [
            (f"sSearch_{i}", category if i == CATEGORY_COLUMN else ""),
            (f"bRegex_{i}", "false"),
            (f"bSearchable_{i}", "true"),
        ]
    for i in range(N_COLUMNS):
        form.append((f"bSortable_{i}", "true"))
    form += [
        ("iSortCol_0", "0"),
        ("sSortDir_0", "asc"),
        ("iSortingCols", "1"),
        ("pageType", "credit-default-swaps-archive"),
    ]
    return form


def fetch_archive(fetcher: Fetcher, category: str = "credit-event", refresh: bool = False) -> list[list]:
    """Return all raw aaData rows for ``category`` (paginated, cached under dc/archive_<category>_<start>.json)."""
    rows: list[list] = []
    start = 0
    total: int | None = None
    while total is None or start < total:
        form = build_archive_form(category, start, PAGE_SIZE)
        # httpx's ``data=`` only accepts a mapping; the form keys are unique, so a dict keeps
        # every field (and, being insertion-ordered, the DataTables field order).
        response = fetcher.post_form(
            config.DC_ARCHIVE_DATA_URL,
            dict(form),
            cache_key=f"dc/archive_{category}_{start}.json",
            refresh=refresh,
        )
        if response.status != 200:
            raise RuntimeError(f"DC archive request failed: HTTP {response.status} (start={start})")
        try:
            payload = response.json()
        except ValueError as e:
            fetcher.invalidate(f"dc/archive_{category}_{start}.json")
            raise RuntimeError(f"DC archive returned a non-JSON body (start={start})") from e
        page = payload.get("aaData") or []
        total = int(payload.get("iTotalDisplayRecords", 0) or 0)
        log.info("DC archive %s: start=%d got %d rows (total %d)", category, start, len(page), total)
        if not page:
            break
        rows.extend(page)
        start += len(page)

    kept = []
    for row in rows:
        if len(row) > CATEGORY_COLUMN and row[CATEGORY_COLUMN] == category:
            kept.append(row)
        else:
            log.warning("Dropping archive row with unexpected category: %r", row[:4])
    if len(rows) != total:
        log.warning("DC archive: collected %d rows but server reported %d", len(rows), total)
    return kept


def epoch_to_date(value) -> str:
    """int/str epoch -> 'YYYY-MM-DD' (UTC); '' for empty/invalid."""
    if value is None or isinstance(value, bool):
        return ""
    try:
        ts = int(str(value).strip())
        return datetime.fromtimestamp(ts, tz=UTC).date().isoformat()
    except (ValueError, OverflowError, OSError):
        return ""


def _parse_long_date(text: str) -> str:
    """'March 5, 2012' -> '2012-03-05'; '' if the text is not in that format."""
    try:
        return datetime.strptime(clean_text(text), "%B %d, %Y").date().isoformat()
    except ValueError:
        return ""


def _parse_date_updated(cell) -> str:
    """Column 0 holds ``<long date text>' '<epoch>``; prefer the epoch, fall back to the text."""
    text, _, epoch = str(cell or "").partition("' '")
    epoch_date = epoch_to_date(epoch)
    text_date = _parse_long_date(text)
    if not epoch_date:
        return text_date
    if text_date and text_date != epoch_date:
        log.debug("date_updated mismatch: text %s vs epoch %s", text_date, epoch_date)
    return epoch_date


def _parse_html_block(block: str) -> dict:
    """Fields embedded in the row's URL-encoded HTML cell (column 7): the detail-page link
    (``dc_id``, ``dc_url``), question text, transaction type, the ``ceMeta_3`` list and the
    submitter's further information."""
    soup = BeautifulSoup(unquote_plus(block or ""), "lxml")
    out = {
        "dc_id": "",
        "dc_url": "",
        "committee": "",
        "question": "",
        "transaction_type": "",
        "issue_number": "",
        "submitted_by": "",
        "coverage_election": "",
        "further_information": "",
    }

    title = soup.select_one("h2.credit-title")
    if title:
        out["question"] = _QUESTION_PREFIX.sub("", clean_text(title.get_text(" ", strip=True)))

    transaction_type = soup.select_one("p.ceMeta_2 strong")
    if transaction_type:
        out["transaction_type"] = clean_text(transaction_type.get_text(" ", strip=True))

    for li in soup.select("ul.ceMeta_3 li"):
        em = li.find("em")
        if not em:
            continue
        label = clean_text(em.get_text(" ", strip=True)).rstrip(":").strip().lower()
        column = _META_LABELS.get(label)
        if not column:
            continue
        strong = li.find("strong")
        if strong:
            value = strong.get_text(" ", strip=True)
        else:
            full = clean_text(li.get_text(" ", strip=True))
            value = full[len(clean_text(em.get_text(" ", strip=True))) :]
        out[column] = clean_text(value)

    more = soup.select_one("a.more-link[href]")
    if more:
        href = urljoin(config.DC_BASE + "/", more["href"].strip())
        out["dc_url"] = urls.normalize_dc_url(href)
        out["dc_id"] = urls.dc_id_from_url(href)

    content = soup.select_one("div.entry-content")
    if content:
        text = clean_text(content.get_text(" ", strip=True))
        out["further_information"] = _FURTHER_INFO_LABEL.sub("", text).strip()
    return out


def parse_archive_row(row: list) -> dict:
    """One aaData row -> dict with DC_EVENTS_COLUMNS except n_history_entries, n_target_documents,
    detail_fetch_status (filled by the pipeline).

    Row layout: 0 date_updated ('<text>' '<epoch>'), 1 committee_code, 2 category, 3 reference
    entity, 4 submitted (epoch), 5 status, 6 outcome, 7 HTML block (see ``_parse_html_block``)."""
    cells = list(row) + [""] * (N_COLUMNS - len(row))
    html = _parse_html_block(str(cells[7] or ""))
    return {
        **html,
        "reference_entity": clean_text(str(cells[3] or "")),
        "committee_code": str(cells[1] or ""),
        "category": str(cells[2] or ""),
        "date_updated": _parse_date_updated(cells[0]),
        "submitted_date": epoch_to_date(cells[4]),
        "status": clean_text(str(cells[5] or "")),
        "outcome": clean_text(str(cells[6] or "")),
    }
