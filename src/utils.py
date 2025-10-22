"""Utility helpers used across the pipeline."""

from __future__ import annotations

import datetime as dt
from typing import Iterable, Iterator, Optional, Sequence, Tuple, TypeVar

from . import config

T = TypeVar("T")


def build_keyword_pattern(keywords: Iterable[str]) -> str:
    escaped_terms = [term.replace("\\", "\\\\").replace("/", "\\/") for term in keywords]
    return "(" + "|".join(escaped_terms) + ")"


def build_cpc_condition(prefixes: Iterable[str]) -> str:
    normalized = [prefix.lower() for prefix in prefixes]
    clauses = [
        f"LOWER(REPLACE(c.code, ' ', '')) LIKE '{prefix}%'"
        for prefix in normalized
    ]
    return " OR ".join(clauses)


def determine_era(publication_year: Optional[int], coating_type: Optional[str]) -> Optional[str]:
    if not publication_year:
        return None

    if publication_year < 1991:
        return "pre-BPA"

    if coating_type in ("Epoxy (BPA)", "Epoxy (BPF)") and publication_year <= 2015:
        return "BPA-era"

    return "modern"


def chunked(sequence: Sequence[T], size: int) -> Iterator[Tuple[T, ...]]:
    if size <= 0:
        raise ValueError("Chunk size must be positive.")
    for index in range(0, len(sequence), size):
        yield tuple(sequence[index : index + size])


def validate_years(start_year: int, end_year: int) -> None:
    current_year = dt.date.today().year
    if start_year < 1900 or end_year > current_year + 1:
        raise ValueError("Year bounds appear to be outside reasonable range.")
    if start_year > end_year:
        raise ValueError("start_year must not exceed end_year.")


KEYWORD_PATTERN = build_keyword_pattern([term.lower() for term in config.KEYWORD_PHRASES])
CPC_CONDITION = build_cpc_condition(config.CPC_PREFIXES)
