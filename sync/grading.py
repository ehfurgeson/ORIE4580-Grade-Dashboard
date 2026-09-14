"""Compute standards-based grading progress from a validated record."""
from __future__ import annotations

from math import floor
from typing import Any

# Ordered from highest to lowest, as specified by the tentative syllabus scale.
GRADE_RULES = (
    ("A+", lambda n: n, lambda n: floor(1.5 * n), 1),
    ("A", lambda n: n - 1, lambda n: floor(1.25 * n), 1),
    ("A−", lambda n: n - 1, lambda n: n, 2),
    ("B+", lambda n: floor(0.75 * n), lambda n: n, 2),
    ("B", lambda n: floor(0.75 * n), lambda n: floor(0.75 * n), 2),
    ("B−", lambda n: floor(0.75 * n), lambda n: floor(0.75 * n), 4),
    ("C+", lambda n: floor(0.5 * n), lambda n: floor(0.75 * n), 4),
    ("C", lambda n: floor(0.5 * n), lambda n: floor(0.5 * n), 4),
)


def estimate_grade(n: int, purple_standards: int, purple_total: int, missing: int) -> str | None:
    """Return the first satisfied tentative syllabus grade condition."""
    return next(
        (
            grade
            for grade, standards_needed, purple_needed, max_missing in GRADE_RULES
            if purple_standards >= standards_needed(n)
            and purple_total >= purple_needed(n)
            and missing <= max_missing
        ),
        None,
    )


def summarize(record: dict[str, Any]) -> dict[str, int | str | None]:
    """Return checkmark totals and the first currently satisfied grade rule.

    Call this only after validating the record. ``complete`` is the only status
    that represents an earned checkmark. The estimate is informational because
    the syllabus scale is tentative.
    """
    standards = record["standards"]
    purple_by_standard = []
    totals_by_standard = []
    green_total = 0
    purple_total = 0

    for standard in standards:
        complete = [item for item in standard["opportunities"] if item["status"] == "complete"]
        green = sum(item["kind"] == "green" for item in complete)
        purple = sum(item["kind"] == "purple" for item in complete)
        green_total += green
        purple_total += purple
        purple_by_standard.append(purple)
        totals_by_standard.append(green + purple)

    n = len(standards)
    purple_standards = sum(count > 0 for count in purple_by_standard)
    missing = sum(max(0, 2 - count) for count in totals_by_standard)
    estimate = estimate_grade(n, purple_standards, purple_total, missing)
    return {
        "standards": n,
        "green": green_total,
        "purple": purple_total,
        "purple_standards": purple_standards,
        "missing": missing,
        "estimated_grade": estimate,
    }
