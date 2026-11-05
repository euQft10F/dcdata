"""DC archive list (DataTables JSON endpoint) fetching and row parsing. [Work package A]"""

from __future__ import annotations

from ..http import Fetcher


def build_archive_form(category: str, start: int, length: int) -> list[tuple[str, str]]:
    """Full DataTables 1.9 form (PLAN.md 1.1). Column 2 filtered by ``category``."""
    raise NotImplementedError


def fetch_archive(fetcher: Fetcher, category: str = "credit-event", refresh: bool = False) -> list[list]:
    """Return all raw aaData rows for ``category`` (paginated, cached under dc/archive_<category>_<start>.json)."""
    raise NotImplementedError


def epoch_to_date(value) -> str:
    """int/str epoch -> 'YYYY-MM-DD' (UTC); '' for empty/invalid."""
    raise NotImplementedError


def parse_archive_row(row: list) -> dict:
    """One aaData row -> dict with DC_EVENTS_COLUMNS except n_history_entries, n_target_documents,
    detail_fetch_status (filled by the pipeline)."""
    raise NotImplementedError
