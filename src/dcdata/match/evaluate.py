"""Fuzzy-only accuracy against exact-link ground truth. [Work package D]"""

from __future__ import annotations

from ..config import DATE_WINDOW_DAYS, FUZZY_SCORERS
from .matcher import _EventIndex, get_scorer, rank_candidates

THRESHOLDS = (95, 90, 85, 80, 75, 70)


def evaluate_grid(
    auctions: list[dict],
    events: list[dict],
    documents: list[dict],
    matches: list[dict],
    date_window: tuple[int, int] = DATE_WINDOW_DAYS,
) -> tuple[int, list[dict]]:
    """Score fuzzy-only matching against the ``exact_link`` rows of ``matches``.

    Return (n_ground_truth, rows) with keys scorer, threshold, correct, wrong, none."""
    truth = {r["auction_id"]: r["dc_id"] for r in matches if r["match_method"] == "exact_link"}
    gt_auctions = [a for a in auctions if a["auction_id"] in truth]
    index = _EventIndex(events, documents)
    rows = []
    for name in FUZZY_SCORERS:
        scorer = get_scorer(name)
        # Score once without a cutoff; each threshold's best candidate is the first one above it.
        ranked = {a["auction_id"]: rank_candidates(a, index, scorer, None, date_window) for a in gt_auctions}
        for threshold in THRESHOLDS:
            counts = {"correct": 0, "wrong": 0, "none": 0}
            for aid, cands in ranked.items():
                best = next((c for c in cands if c.score >= threshold), None)
                key = "none" if best is None else "correct" if best.dc_id == truth[aid] else "wrong"
                counts[key] += 1
            rows.append({"scorer": name, "threshold": threshold, **counts})
    return len(gt_auctions), rows


def format_table(n_truth: int, rows: list[dict]) -> str:
    header = ("scorer", "threshold", "correct", "wrong", "none")
    widths = [max(len(h), *(len(str(r[h])) for r in rows)) if rows else len(h) for h in header]
    lines = [f"Fuzzy-only accuracy vs {n_truth} exact-link auctions"]
    lines.append("  ".join(h.ljust(w) for h, w in zip(header, widths, strict=True)))
    lines.append("  ".join("-" * w for w in widths))
    for r in rows:
        lines.append("  ".join(str(r[h]).ljust(w) for h, w in zip(header, widths, strict=True)))
    return "\n".join(lines)
