"""Allocate checkboxes and compute standards-based grading progress."""
from __future__ import annotations

from math import floor
from typing import Any

KIND_PRIORITY = {"purple": 0, "shiny_purple": 1, "green": 2}

# Ordered highest to lowest. Thresholds are inclusive; missing is a maximum.
GRADE_RULES = (
    ("A+", lambda n: n, lambda n: floor(2 * n), lambda n: n - 1, 1),
    ("A", lambda n: n - 1, lambda n: floor(1.5 * n), lambda _n: 1, 1),
    ("A−", lambda n: n - 1, lambda n: n, lambda _n: 0, 2),
    ("B+", lambda n: floor(0.75 * n), lambda n: n, lambda _n: 0, 2),
    ("B", lambda n: floor(0.75 * n), lambda n: floor(0.75 * n), lambda _n: 0, 2),
    ("B−", lambda n: floor(0.75 * n), lambda n: floor(0.75 * n), lambda _n: 0, 4),
    ("C+", lambda n: floor(0.5 * n), lambda n: floor(0.75 * n), lambda _n: 0, 4),
    ("C", lambda n: floor(0.5 * n), lambda n: floor(0.5 * n), lambda _n: 0, 4),
)


def allocate_standard(opportunities: list[dict[str, Any]]) -> dict[str, Any]:
    """Allocate earned checkmarks to two linked boxes, then shiny boxes.

    The two linked boxes use purple, shiny purple, then green priority. A shiny
    purple used there counts as both purple and shiny. Every earned shiny
    purple not selected for a linked box fills an unlimited shiny checkbox.
    All shiny checkmarks count toward both color totals; extra green and regular
    purple checkmarks do not count.
    """
    earned = [item for item in opportunities if item["status"] == "complete"]
    ranked = sorted(enumerate(earned), key=lambda pair: (KIND_PRIORITY[pair[1]["kind"]], pair[0]))
    linked = [item for _, item in ranked[:2]]
    linked_object_ids = {id(item) for item in linked}
    shiny_pool = [
        item for item in earned
        if item["kind"] == "shiny_purple" and id(item) not in linked_object_ids
    ]
    return {"linked": linked, "shiny": shiny_pool, "missing": 2 - len(linked)}


def estimate_grade(
    n: int,
    purple_standards: int,
    purple_total: int,
    shiny_total: int,
    missing: int,
) -> str | None:
    """Return the first satisfied grading-scale condition."""
    return next(
        (
            grade
            for grade, standards_needed, purple_needed, shiny_needed, max_missing in GRADE_RULES
            if purple_standards >= standards_needed(n)
            and purple_total >= purple_needed(n)
            and shiny_total >= shiny_needed(n)
            and missing <= max_missing
        ),
        None,
    )


def summarize(record: dict[str, Any]) -> dict[str, int | str | None]:
    """Return allocated checkbox totals and the current satisfied threshold."""
    n = len(record["standards"])
    green_total = 0
    purple_total = 0
    purple_standards = 0
    shiny_total = 0
    missing = 0

    for standard in record["standards"]:
        allocation = allocate_standard(standard["opportunities"])
        linked = allocation["linked"]
        green_total += sum(item["kind"] == "green" for item in linked)
        linked_purple = sum(item["kind"] in {"purple", "shiny_purple"} for item in linked)
        # Shiny purple is a purple subtype and always fills either a linked or
        # unlimited shiny box. It therefore contributes to both color totals.
        purple_total += linked_purple + len(allocation["shiny"])
        purple_standards += linked_purple > 0
        shiny_total += sum(
            item["kind"] == "shiny_purple" and item["status"] == "complete"
            for item in standard["opportunities"]
        )
        missing += allocation["missing"]

    estimate = estimate_grade(n, purple_standards, purple_total, shiny_total, missing)
    return {
        "standards": n,
        "green": green_total,
        "purple": purple_total,
        "shiny": shiny_total,
        "purple_standards": purple_standards,
        "missing": missing,
        "estimated_grade": estimate,
    }
