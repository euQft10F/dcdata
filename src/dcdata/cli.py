"""Command-line interface: dcdata {dc,auctions,match,all}."""

from __future__ import annotations

import argparse
import json
import logging
import platform
import sys
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

from . import __version__, config
from .config import Settings
from .http import Fetcher
from .match.evaluate import SCORERS

log = logging.getLogger("dcdata")


def _csv_list(s: str) -> list[str]:
    return [x.strip() for x in s.split(",") if x.strip()]


def _years(s: str) -> list[int]:
    return [int(x) for x in _csv_list(s)]


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--data-dir",
        type=Path,
        default=config.DATA_DIR,
        help="root for cache/, documents/, markdown/, output/ (default: ./data)",
    )
    common.add_argument("--refresh", action="store_true", help="ignore the HTTP cache and re-download")
    common.add_argument(
        "--delay",
        type=float,
        default=config.REQUEST_DELAY_S,
        help="minimum seconds between requests to the same host (default: 1.0)",
    )
    common.add_argument("-v", "--verbose", action="store_true", help="debug logging")

    dc_opts = argparse.ArgumentParser(add_help=False)
    dc_opts.add_argument(
        "--limit", type=int, default=None, help="only the first N credit events (smoke test)"
    )
    dc_opts.add_argument("--no-download", action="store_true", help="do not download PDFs")
    dc_opts.add_argument("--no-markdown", action="store_true", help="do not convert PDFs to Markdown")
    dc_opts.add_argument(
        "--doc-types",
        type=_csv_list,
        default=None,
        help="comma-separated doc types to download (default: "
        + ",".join(sorted(config.TARGET_DOC_TYPES))
        + ")",
    )

    au_opts = argparse.ArgumentParser(add_help=False)
    au_opts.add_argument(
        "--years", type=_years, default=None, help="comma-separated auction years (default: all)"
    )

    m_opts = argparse.ArgumentParser(add_help=False)
    m_opts.add_argument(
        "--threshold",
        type=float,
        default=config.FUZZY_THRESHOLD,
        help="fuzzy score cutoff 0-100 (default: 80)",
    )
    m_opts.add_argument(
        "--scorer",
        default=config.FUZZY_SCORER,
        choices=SCORERS,
        help="RapidFuzz scorer for the fuzzy fallback (default: token_sort_ratio)",
    )
    m_opts.add_argument(
        "--evaluate", action="store_true", help="also print fuzzy-only accuracy vs. link-based ground truth"
    )

    p = argparse.ArgumentParser(prog="dcdata", description=__doc__)
    p.add_argument("--version", action="version", version=f"dcdata {__version__}")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("dc", parents=[common, dc_opts], help="scrape DC credit events, procedural history, PDFs")
    sub.add_parser("auctions", parents=[common, au_opts], help="scrape creditfixings.com CDS auction results")
    sub.add_parser("match", parents=[common, m_opts], help="match auctions to DC credit events")
    sub.add_parser("all", parents=[common, dc_opts, au_opts, m_opts], help="dc -> auctions -> match")
    return p


def _settings(args) -> Settings:
    s = Settings(data_dir=args.data_dir, refresh=args.refresh, delay=args.delay)
    if getattr(args, "doc_types", None):
        s.target_doc_types = frozenset(args.doc_types)
    if hasattr(args, "threshold"):
        s.fuzzy_threshold = args.threshold
        s.fuzzy_scorer = args.scorer
    return s


def _versions() -> dict:
    out = {"python": platform.python_version(), "dcdata": __version__}
    for pkg in ("httpx", "beautifulsoup4", "lxml", "rapidfuzz", "pymupdf4llm", "pymupdf"):
        try:
            out[pkg] = metadata.version(pkg)
        except metadata.PackageNotFoundError:
            pass
    return out


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    if not args.verbose:
        logging.getLogger("httpx").setLevel(logging.WARNING)

    settings = _settings(args)
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    run_log: dict = {
        "command": args.command,
        "argv": sys.argv[1:] if argv is None else argv,
        "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "versions": _versions(),
        "steps": {},
    }

    with Fetcher(cache_dir=settings.cache_dir, delay=settings.delay) as fetcher:
        if args.command in ("dc", "all"):
            from .dc.pipeline import run_dc

            run_log["steps"]["dc"] = run_dc(
                settings,
                fetcher,
                limit=args.limit,
                download=not args.no_download,
                markdown=not args.no_markdown,
            )
        if args.command in ("auctions", "all"):
            from .auctions.pipeline import run_auctions

            run_log["steps"]["auctions"] = run_auctions(settings, fetcher, years=args.years)
        if args.command in ("match", "all"):
            from .match.pipeline import run_match

            run_log["steps"]["match"] = run_match(settings, evaluate=args.evaluate)
        run_log["network_requests"] = fetcher.n_network_requests

    run_log["finished_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    (settings.output_dir / "run_log.json").write_text(
        json.dumps(run_log, indent=2, default=str), encoding="utf-8"
    )
    log.info("summary: %s", json.dumps(run_log["steps"], default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
