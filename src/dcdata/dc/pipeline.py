"""Orchestrates the DC scrape. [Phase 2 - main agent]"""

from __future__ import annotations

from ..config import Settings
from ..http import Fetcher


def run_dc(
    settings: Settings,
    fetcher: Fetcher,
    limit: int | None = None,
    download: bool = True,
    markdown: bool = True,
) -> dict:
    raise NotImplementedError
