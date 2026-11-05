"""DC detail page: Procedural History parsing. [Work package A]"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, NavigableString, Tag

from .. import urls

_WS = re.compile(r"\s+")
_SKIP_TAGS = {"h4", "time"}


def _clean(text: str | None) -> str:
    # \s also matches U+00A0 (&nbsp;) for str patterns.
    return _WS.sub(" ", text or "").strip()


def _body_nodes(li: Tag) -> list:
    """Direct children of an entry ``<li>`` that make up its body (everything but heading and time)."""
    return [c for c in li.children if not (isinstance(c, Tag) and c.name in _SKIP_TAGS)]


def _paragraphs(li: Tag) -> list[str]:
    """Body text blocks. lxml flattens the page's nested ``<p><p>..</p></p>`` into sibling ``<p>``s;
    any other container (div, ul, ...) contributes its own ``<p>`` descendants, or its whole text."""
    out: list[str] = []
    for node in _body_nodes(li):
        if isinstance(node, NavigableString):
            if type(node) is NavigableString:  # skip comments, CDATA, etc.
                out.append(_clean(str(node)))
            continue
        if not isinstance(node, Tag):
            continue
        if node.name != "p":
            inner = node.find_all("p")
            if inner:
                out.extend(_clean(p.get_text(" ", strip=True)) for p in inner)
                continue
        out.append(_clean(node.get_text(" ", strip=True)))
    return [t for t in out if t]


def _links(li: Tag) -> list[Tag]:
    found: list[Tag] = []
    for node in _body_nodes(li):
        if not isinstance(node, Tag):
            continue
        anchors = [node] if node.name == "a" and node.has_attr("href") else []
        anchors += node.find_all("a", href=True)
        for a in anchors:
            href = a["href"].strip()
            if not href or href.startswith("#") or href.lower().startswith("mailto:"):
                continue
            found.append(a)
    return found


def parse_procedural_history(html: str, dc_id: str) -> tuple[list[dict], list[dict]] | None:
    """Parse ``ul.ProceduralHistory``.

    Returns ``None`` if the page has no Procedural History list, else ``(entries, links)``:
      entries: dicts with schemas.DC_HISTORY_COLUMNS
      links:   dicts with dc_id, entry_seq, link_seq, heading, entry_datetime, link_text, url,
               url_normalized (= urls.normalize_url(url)).
    entry_seq 0 = oldest (page order reversed).
    """
    soup = BeautifulSoup(html, "lxml")
    lists = soup.select("ul.ProceduralHistory")
    # Ignore any ProceduralHistory list nested inside another one; use the outermost (first) list.
    outer = [u for u in lists if u.find_parent("ul", class_="ProceduralHistory") is None]
    if not outer:
        return None
    ul = outer[0]

    items = ul.find_all("li", recursive=False)
    entries: list[dict] = []
    links: list[dict] = []
    for seq, li in enumerate(reversed(items)):
        h4 = li.find("h4", recursive=False) or li.find("h4")
        heading = _clean(h4.get_text(" ", strip=True)) if h4 else ""
        time_tag = li.find("time", recursive=False) or li.find("time", attrs={"datetime": True})
        entry_datetime = (time_tag.get("datetime") or "").strip() if time_tag else ""
        anchors = _links(li)
        entries.append(
            {
                "dc_id": dc_id,
                "entry_seq": seq,
                "heading": heading,
                "entry_datetime": entry_datetime,
                "entry_text": "\n".join(_paragraphs(li)),
                "n_links": len(anchors),
            }
        )
        for link_seq, a in enumerate(anchors):
            href = a["href"].strip()
            links.append(
                {
                    "dc_id": dc_id,
                    "entry_seq": seq,
                    "link_seq": link_seq,
                    "heading": heading,
                    "entry_datetime": entry_datetime,
                    "link_text": _clean(a.get_text(" ", strip=True)),
                    "url": href,
                    "url_normalized": urls.normalize_url(href),
                }
            )
    return entries, links
