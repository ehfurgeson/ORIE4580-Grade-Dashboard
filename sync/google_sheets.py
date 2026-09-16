"""Convert already-fetched Google Sheets rows to the dashboard schema."""
from __future__ import annotations

from collections.abc import Iterable
import csv
from pathlib import Path
from typing import Any

from .standards import STANDARDS

REQUIRED_COLUMNS = {
    "updated_at", "course", "student_id", "student_name", "standard_id",
}


def load_csv(path: str | Path) -> list[dict[str, str]]:
    """Load a private Google Sheets CSV export without logging row contents."""
    with Path(path).open(newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames is None:
            raise ValueError("Google Sheets CSV has no header row")
        missing = sorted(REQUIRED_COLUMNS - set(reader.fieldnames))
        if missing:
            raise ValueError("Google Sheets CSV missing columns: " + ", ".join(missing))
        rows = list(reader)
    if not rows:
        raise ValueError("Google Sheets CSV contains no data rows")
    return rows


def rows_to_records(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group one-opportunity-per-row sheet data into per-student records.

    The caller owns API authentication. Empty cells may not stand in for a
    standard; the source sheet must include every evaluated standard.
    """
    records: dict[str, dict[str, Any]] = {}
    standards_by_student: dict[str, dict[str, dict[str, Any]]] = {}

    for row_number, row in enumerate(rows, start=2):
        missing = sorted(REQUIRED_COLUMNS - row.keys())
        if missing:
            raise ValueError(f"row {row_number} missing columns: {', '.join(missing)}")
        student_id = str(row["student_id"]).strip()
        record = records.get(student_id)
        identity = (row["updated_at"], row["course"], str(row["student_name"]).strip())
        if record is None:
            record = records[student_id] = {
                "updated_at": identity[0],
                "course": identity[1],
                "student": {"id": student_id, "name": identity[2]},
                "standards": [],
            }
            standards_by_student[student_id] = {}
        elif identity != (record["updated_at"], record["course"], record["student"]["name"]):
            raise ValueError(f"row {row_number} has inconsistent student metadata")

        standard_id = str(row["standard_id"]).strip()
        if standard_id not in STANDARDS:
            raise ValueError(f"row {row_number} has unknown standard: {standard_id}")
        category, name = STANDARDS[standard_id]
        standard = standards_by_student[student_id].get(standard_id)
        if standard is None:
            standard = standards_by_student[student_id][standard_id] = {
                "id": standard_id, "name": name, "category": category, "opportunities": [],
            }
            record["standards"].append(standard)
        opportunity_id = str(row.get("opportunity_id", "")).strip()
        if opportunity_id:
            opportunity_columns = {"opportunity_label", "source", "kind", "status"}
            missing_opportunity = sorted(opportunity_columns - row.keys())
            if missing_opportunity:
                raise ValueError(
                    f"row {row_number} missing opportunity columns: {', '.join(missing_opportunity)}"
                )
            standard["opportunities"].append({
                "id": opportunity_id,
                "label": str(row["opportunity_label"]).strip(),
                "source": row["source"],
                "kind": row["kind"],
                "status": row["status"],
            })

    return list(records.values())
