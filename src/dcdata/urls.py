"""URL helpers shared by the DC scraper and the matcher."""

from __future__ import annotations

from urllib.parse import quote, urlsplit, urlunsplit

from . import config

_SAFE = ":/?#[]@!$&'()*+,;=%~"


def quote_href(href: str) -> str:
    """Percent-encode spaces and unsafe characters, leaving existing %xx escapes intact."""
    return quote(href.strip(), safe=_SAFE)


def _is_dc_host(host: str) -> bool:
    return host.lower() in config.DC_HOSTS


def normalize_url(url: str) -> str:
    """Generic normalisation used for document URLs: quote, lowercase scheme/host,
    http->https for the DC domain, drop fragment. Path case and trailing slash are kept."""
    parts = urlsplit(quote_href(url))
    scheme = parts.scheme.lower()
    host = parts.netloc.lower()
    if _is_dc_host(host) and scheme == "http":
        scheme = "https"
    return urlunsplit((scheme, host, parts.path, parts.query, ""))


def normalize_dc_url(url: str) -> str:
    """Canonical form of a DC detail-page URL.

    lowercase scheme/host, http->https, keep www., take the path from the LAST '/cds/'
    (repairs '/lcds/cds/...'), ensure a trailing slash, drop query and fragment.
    """
    parts = urlsplit(quote_href(url))
    scheme = parts.scheme.lower() or "https"
    if scheme == "http":
        scheme = "https"
    host = parts.netloc.lower()
    path = parts.path
    idx = path.rfind("/cds/")
    if idx >= 0:
        path = path[idx:]
    if not path.endswith("/"):
        path += "/"
    return urlunsplit((scheme, host, path, "", ""))


def dc_id_from_url(url: str) -> str:
    """'https://www.cdsdeterminationscommittees.org/cds/foo-2/' -> 'cds/foo-2'."""
    return urlsplit(normalize_dc_url(url)).path.strip("/")


def slug_dir(dc_id: str) -> str:
    """Filesystem-safe folder name for a dc_id: 'cds/foo-2' -> 'cds_foo-2'."""
    return dc_id.replace("/", "_")
