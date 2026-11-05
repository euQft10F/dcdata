"""Fuzzy-only accuracy against exact-link ground truth. [Work package D]"""

from __future__ import annotations


def evaluate(auctions: list[dict], events: list[dict], documents: list[dict]) -> str:
    """Return a printable table of correct/wrong/none per scorer x threshold."""
    raise NotImplementedError
