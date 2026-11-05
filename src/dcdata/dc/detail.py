"""DC detail page: Procedural History parsing. [Work package A]"""

from __future__ import annotations


def parse_procedural_history(html: str, dc_id: str) -> tuple[list[dict], list[dict]] | None:
    """Parse ``ul.ProceduralHistory``.

    Returns ``None`` if the page has no Procedural History list, else ``(entries, links)``:
      entries: dicts with schemas.DC_HISTORY_COLUMNS
      links:   dicts with dc_id, entry_seq, link_seq, heading, entry_datetime, link_text, url,
               url_normalized (= urls.normalize_url(url)).
    entry_seq 0 = oldest (page order reversed).
    """
    raise NotImplementedError
