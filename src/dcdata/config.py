"""Central configuration constants. Everything here can be overridden from the CLI."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

DC_BASE = "https://www.cdsdeterminationscommittees.org"
DC_ARCHIVE_DATA_URL = f"{DC_BASE}/credit-default-swaps-archive/data/"
DC_HOSTS = {"www.cdsdeterminationscommittees.org", "cdsdeterminationscommittees.org"}

CF_API = "https://api.creditfixings.com/api"
CF_ORIGIN = "https://www.creditfixings.com"
CF_RESULTS_UI = "https://www.creditfixings.com/#/auction-results/{ticker}"

# Generic client identification. Never put personal contact details here.
USER_AGENT = "dcdata-research-scraper/0.1"
REQUEST_DELAY_S = 1.0  # minimum gap between requests to the same host
MAX_RETRIES = 4  # retries on 429/5xx/transport errors (exponential backoff 2..30 s)
TIMEOUT_S = 60.0

TARGET_DOC_TYPES = frozenset(
    {"dc_decision", "final_list", "initial_list", "preliminary_list", "auction_terms"}
)

FUZZY_SCORERS = ("ratio", "token_sort_ratio", "token_set_ratio", "partial_ratio", "WRatio")
FUZZY_SCORER = "token_sort_ratio"
FUZZY_THRESHOLD = 80.0
DATE_WINDOW_DAYS = (-7, 365)  # (auction_date - dc_submitted_date).days must fall inside this range

DATA_DIR = Path("data")


@dataclass
class Settings:
    """Runtime settings passed through the pipelines."""

    data_dir: Path = DATA_DIR
    refresh: bool = False
    delay: float = REQUEST_DELAY_S
    target_doc_types: frozenset[str] = field(default_factory=lambda: TARGET_DOC_TYPES)
    fuzzy_scorer: str = FUZZY_SCORER
    fuzzy_threshold: float = FUZZY_THRESHOLD
    date_window_days: tuple[int, int] = DATE_WINDOW_DAYS

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def documents_dir(self) -> Path:
        return self.data_dir / "documents"

    @property
    def markdown_dir(self) -> Path:
        return self.data_dir / "markdown"

    @property
    def output_dir(self) -> Path:
        return self.data_dir / "output"
