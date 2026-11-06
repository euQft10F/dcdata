"""URL helpers shared by the DC scraper and the matcher."""

from __future__ import annotations

from urllib.parse import quote, unquote, urlsplit, urlunsplit

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


def _split_dc_url(url: str) -> tuple[str, bool]:
    """``(canonical_url, repaired)`` -- see normalize_dc_url. ``repaired`` is True when a path
    prefix before the last '/cds/' had to be dropped (e.g. '/lcds/cds/...')."""
    parts = urlsplit(quote_href(url))
    scheme = parts.scheme.lower() or "https"
    if scheme == "http":
        scheme = "https"
    host = parts.netloc.lower()
    path = parts.path
    idx = path.lower().rfind("/cds/")
    if idx >= 0:
        path = path[idx:]
    if not path.endswith("/"):
        path += "/"
    return urlunsplit((scheme, host, path, "", "")), idx > 0


def normalize_dc_url(url: str) -> str:
    """Canonical form of a DC detail-page URL.

    lowercase scheme/host, http->https, keep www., take the path from the LAST '/cds/'
    (repairs '/lcds/cds/...'), ensure a trailing slash, drop query and fragment.
    """
    return _split_dc_url(url)[0]


def dc_path_repaired(url: str) -> bool:
    """True when normalize_dc_url had to drop a path prefix before '/cds/' (e.g. '/lcds/cds/...')."""
    return _split_dc_url(url)[1]


def dc_url_key(url: str) -> str:
    """Comparison key for DC detail-page URLs: case-insensitive, and 'www.' is ignored on DC hosts."""
    parts = urlsplit(normalize_dc_url(url).lower())
    host = parts.netloc
    if _is_dc_host(host) and host.startswith("www."):
        host = host[4:]
    return urlunsplit((parts.scheme, host, parts.path, "", ""))


def doc_url_key(url: str) -> str:
    """Comparison key for document URLs: normalize_url with a case- and trailing-slash-insensitive path."""
    parts = urlsplit(normalize_url(url))
    return urlunsplit((parts.scheme, parts.netloc, parts.path.lower().rstrip("/"), parts.query, ""))


def dc_id_from_url(url: str) -> str:
    """'https://www.cdsdeterminationscommittees.org/cds/foo-2/' -> 'cds/foo-2'."""
    return urlsplit(normalize_dc_url(url)).path.strip("/")


def url_filename(url: str) -> str:
    """Last non-empty path segment of ``url``, unquoted ('' if none)."""
    segments = [s for s in urlsplit(url.strip()).path.split("/") if s]
    return unquote(segments[-1]) if segments else ""


def slug_dir(dc_id: str) -> str:
    """Filesystem-safe folder name for a dc_id: 'cds/foo-2' -> 'cds_foo-2'."""
    return dc_id.replace("/", "_")
