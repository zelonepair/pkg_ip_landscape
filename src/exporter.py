"""Utilities for exporting patent records to CSV."""

from __future__ import annotations

import csv
from typing import Iterable


def write_csv(records: Iterable[dict], path: str, include_era: bool) -> None:
    fieldnames = [
        "publication_number",
        "publication_date",
        "title",
        "abstract",
        "assignee",
        "cpc_codes",
        "description",
        "first_claim",
        "coating_type",
        "classification_confidence",
    ]
    if include_era:
        fieldnames.append("era")

    with open(path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            row = {
                "publication_number": record.get("publication_number"),
                "publication_date": record.get("publication_date"),
                "title": record.get("title"),
                "abstract": record.get("abstract"),
                "assignee": record.get("assignee"),
                "cpc_codes": "; ".join(record.get("cpc_codes") or []),
                "description": record.get("description"),
                "first_claim": record.get("first_claim"),
                "coating_type": record.get("coating_type"),
                "classification_confidence": record.get("classification_confidence"),
            }
            if include_era:
                row["era"] = record.get("era")
            writer.writerow(row)
