"""Fuzzy-only accuracy against exact-link ground truth. [Work package D]"""

from __future__ import annotations

from ..config import DATE_WINDOW_DAYS, FUZZY_SCORER, FUZZY_THRESHOLD
from .matcher import _EventIndex, get_scorer, match_auctions, rank_candidates

SCORERS = ("ratio", "token_sort_ratio", "token_set_ratio", "partial_ratio", "WRatio")
THRESHOLDS = (95, 90, 85, 80, 75, 70)


def evaluate_grid(
    auctions: list[dict],
    events: list[dict],
    documents: list[dict],
    date_window: tuple[int, int] = DATE_WINDOW_DAYS,
) -> tuple[int, list[dict]]:
    """Return (n_ground_truth, rows) with keys scorer, threshold, correct, wrong, none."""
    matched = match_auctions(
        auctions, events, documents, scorer=FUZZY_SCORER, threshold=FUZZY_THRESHOLD, date_window=date_window
    )
    truth = {r["auction_id"]: r["dc_id"] for r in matched if r["match_method"] == "exact_link"}
    gt_auctions = [a for a in auctions if a.get("auction_id") in truth]
    index = _EventIndex(events, documents)
    rows = []
    for name in SCORERS:
        scorer = get_scorer(name)
        for threshold in THRESHOLDS:
            correct = wrong = none = 0
            for a in gt_auctions:
                ranked = rank_candidates(a, index, scorer, float(threshold), date_window)
                if not ranked:
                    none += 1
                elif ranked[0].dc_id == truth[a["auction_id"]]:
                    correct += 1
                else:
                    wrong += 1
            rows.append(
                {"scorer": name, "threshold": threshold, "correct": correct, "wrong": wrong, "none": none}
            )
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


def evaluate(auctions: list[dict], events: list[dict], documents: list[dict]) -> str:
    """Return a printable table of correct/wrong/none per scorer x threshold."""
    n_truth, rows = evaluate_grid(auctions, events, documents)
    return format_table(n_truth, rows)
