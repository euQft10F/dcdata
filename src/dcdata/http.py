"""HTTP fetching: rate-limited, retrying, with an optional on-disk cache.

The Fetcher never raises on 4xx responses; it returns the status so callers can record it.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from . import config

log = logging.getLogger(__name__)

RETRY_STATUSES = {429, 500, 502, 503, 504}


class _RetryableStatus(Exception):
    def __init__(self, response: httpx.Response):
        super().__init__(f"HTTP {response.status_code} for {response.request.url}")
        self.response = response


@dataclass
class FetchResult:
    status: int
    final_url: str
    content: bytes
    headers: dict[str, str] = field(default_factory=dict)
    from_cache: bool = False

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def json(self):
        return json.loads(self.content)


class Fetcher:
    def __init__(
        self,
        cache_dir: Path | None = None,
        delay: float = config.REQUEST_DELAY_S,
        max_retries: int = config.MAX_RETRIES,
        timeout: float = config.TIMEOUT_S,
        user_agent: str = config.USER_AGENT,
        client: httpx.Client | None = None,
    ):
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.delay = delay
        self.max_retries = max_retries
        self._last_request: dict[str, float] = {}
        self.client = client or httpx.Client(
            headers={"User-Agent": user_agent},
            follow_redirects=True,
            timeout=timeout,
        )
        self.n_network_requests = 0

    # ------------------------------------------------------------------ public API
    def get(
        self,
        url: str,
        *,
        cache_key: str | None = None,
        refresh: bool = False,
        headers: dict[str, str] | None = None,
    ) -> FetchResult:
        return self._fetch("GET", url, cache_key=cache_key, refresh=refresh, headers=headers)

    def post_form(
        self,
        url: str,
        data: dict[str, str],
        *,
        cache_key: str | None = None,
        refresh: bool = False,
        headers: dict[str, str] | None = None,
    ) -> FetchResult:
        return self._fetch("POST", url, data=data, cache_key=cache_key, refresh=refresh, headers=headers)

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> Fetcher:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------------ internals
    def _cache_paths(self, cache_key: str) -> tuple[Path, Path]:
        assert self.cache_dir is not None
        body = self.cache_dir / cache_key
        return body, body.with_name(body.name + ".meta.json")

    def _read_cache(self, cache_key: str) -> FetchResult | None:
        if not self.cache_dir:
            return None
        body, meta = self._cache_paths(cache_key)
        if not (body.exists() and meta.exists()):
            return None
        m = json.loads(meta.read_text(encoding="utf-8"))
        return FetchResult(
            status=m["status"],
            final_url=m["final_url"],
            content=body.read_bytes(),
            headers={"content-type": m.get("content_type", "")},
            from_cache=True,
        )

    def _write_cache(self, cache_key: str, res: FetchResult) -> None:
        if not self.cache_dir:
            return
        body, meta = self._cache_paths(cache_key)
        body.parent.mkdir(parents=True, exist_ok=True)
        tmp = body.with_name(body.name + ".part")
        tmp.write_bytes(res.content)
        tmp.replace(body)
        meta.write_text(
            json.dumps(
                {
                    "status": res.status,
                    "final_url": res.final_url,
                    "content_type": res.headers.get("content-type", ""),
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )

    def _throttle(self, url: str) -> None:
        host = urlsplit(url).netloc.lower()
        last = self._last_request.get(host)
        if last is not None:
            wait = self.delay - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
        self._last_request[host] = time.monotonic()

    def _fetch(self, method, url, *, data=None, cache_key=None, refresh=False, headers=None):
        if cache_key and not refresh:
            cached = self._read_cache(cache_key)
            if cached is not None:
                return cached

        @retry(
            reraise=True,
            stop=stop_after_attempt(self.max_retries + 1),
            wait=wait_exponential(multiplier=2, min=2, max=30),
            retry=retry_if_exception_type((httpx.TransportError, _RetryableStatus)),
        )
        def do() -> httpx.Response:
            self._throttle(url)
            self.n_network_requests += 1
            log.debug("%s %s", method, url)
            resp = self.client.request(method, url, data=data, headers=headers)
            if resp.status_code in RETRY_STATUSES:
                raise _RetryableStatus(resp)
            return resp

        try:
            resp = do()
        except _RetryableStatus as e:  # retries exhausted: report the status, do not raise
            resp = e.response
        res = FetchResult(
            status=resp.status_code,
            final_url=str(resp.url),
            content=resp.content,
            headers={k.lower(): v for k, v in resp.headers.items()},
        )
        # Only cache successful responses so transient failures are retried next run.
        if cache_key and res.ok:
            self._write_cache(cache_key, res)
        return res
