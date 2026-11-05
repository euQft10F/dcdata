"""Classify Procedural History links into document types. [Work package B]"""

from __future__ import annotations

from collections.abc import Iterable


def classify_link(text: str, url: str) -> str:
    """-> one of redline, dc_decision, final_list, initial_list, preliminary_list, auction_terms,
    bidders, statement, auction_info, other_pdf, other_link."""
    raise NotImplementedError


def extract_issue_number(text: str) -> str:
    raise NotImplementedError


def extract_doc_date(text: str, url: str) -> str:
    """ISO date parsed from link text (or the URL filename), '' if none."""
    raise NotImplementedError


def annotate_link(link: dict, target_types: Iterable[str]) -> dict:
    """Return a copy of ``link`` with doc_type, is_target, doc_issue_number, doc_date added."""
    raise NotImplementedError
