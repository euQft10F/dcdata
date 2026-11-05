"""Entity-name normalisation for fuzzy matching. [Work package D]"""

from __future__ import annotations

import re
import unicodedata

# Legal-form / stop tokens. Multi-word entries are matched as whole-token sequences only.
_SUFFIXES: tuple[tuple[str, ...], ...] = tuple(
    sorted(
        {
            tuple(s.split())
            for s in (
                "the",
                "plc",
                "public limited company",
                "limited",
                "ltd",
                "llc",
                "l l c",
                "inc",
                "incorporated",
                "corp",
                "corporation",
                "co",
                "company",
                "sa",
                "s a",
                "sas",
                "s a s",
                "sab de cv",
                "s a b de c v",
                "ag",
                "nv",
                "n v",
                "bv",
                "b v",
                "spa",
                "s p a",
                "asa",
                "ab",
                "oyj",
                "gmbh",
                "lp",
                "l p",
                "holding",
                "holdings",
                "group",
                "sociedad anonima",
                "societa per azioni",
            )
        },
        key=lambda t: (-len(t), t),  # longest sequences first
    )
)

# Token sequences that start a "formerly known as ..." tail; everything from there on is dropped.
_FORMERLY: tuple[tuple[str, ...], ...] = (
    ("formerly", "known", "as"),
    ("f", "k", "a"),
    ("fka",),
    ("formerly",),
)

_PAREN_RE = re.compile(r"\([^()]*\)")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def _ascii_fold(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")


def _cut_formerly(tokens: list[str]) -> list[str]:
    for i in range(len(tokens)):
        for seq in _FORMERLY:
            if tuple(tokens[i : i + len(seq)]) == seq:
                return tokens[:i]
    return tokens


def _strip_suffixes(tokens: list[str]) -> list[str]:
    out: list[str] = []
    i = 0
    n = len(tokens)
    while i < n:
        for seq in _SUFFIXES:
            if tuple(tokens[i : i + len(seq)]) == seq:
                i += len(seq)
                break
        else:
            out.append(tokens[i])
            i += 1
    return out


def normalize_name(s: str) -> str:
    """Normalise an entity name for fuzzy comparison.

    NFKD -> ASCII, lowercase, '&' -> 'and', drop parenthesised text, non-alphanumerics -> space,
    drop a "formerly known as ..." tail, remove legal-suffix/stop token sequences, collapse spaces.
    If every token is a stop token, the tokens before suffix removal are kept.
    """
    if not s:
        return ""
    text = _ascii_fold(s).lower().replace("&", " and ")
    prev = None
    while prev != text:  # handle nested parentheses
        prev = text
        text = _PAREN_RE.sub(" ", text)
    text = _NON_ALNUM_RE.sub(" ", text)
    tokens = _cut_formerly(text.split())
    stripped = _strip_suffixes(tokens)
    return " ".join(stripped or tokens)
