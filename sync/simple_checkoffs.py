"""Normalize a wide checkbox worksheet without mapping columns to standards."""
from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
import json
import re
from typing import Any

NETID_COLUMN = "NetID"
NETID_PATTERN = re.compile(r"[a-z]{2,3}[0-9]+\Z")
STATUSES = {"complete", "incomplete"}
MAX_LABEL_LENGTH = 200


def normalize_checkbox(value: Any, *, row_number: int, column: str) -> str:
    """Convert a Google Sheets checkbox value to a bounded dashboard status."""
    if value is True or (isinstance(value, str) and value.strip().casefold() == "true"):
        return "complete"
    if value is False or (isinstance(value, str) and value.strip().casefold() == "false"):
        return "incomplete"
    raise ValueError(f"row {row_number} column {column!r} is not a True/False checkbox")


def rows_to_simple_records(
    rows: Iterable[dict[str, Any]], *, updated_at: str, worksheet: str
) -> list[dict[str, Any]]:
    """Convert one wide worksheet row per NetID to the simple dashboard schema."""
    rows = list(rows)
    if not rows:
        raise ValueError("Google worksheet contains no student rows")
    headers = list(rows[0])
    if headers.count(NETID_COLUMN) != 1:
        raise ValueError(f"Google worksheet must contain exactly one {NETID_COLUMN!r} column")
    item_headers = [header for header in headers if header != NETID_COLUMN]
    if not item_headers:
        raise ValueError("Google worksheet must contain at least one checkoff column")
    if any(not isinstance(header, str) or not header.strip() for header in item_headers):
        raise ValueError("Google worksheet has an empty checkoff header")
    if any(len(header) > MAX_LABEL_LENGTH for header in item_headers):
        raise ValueError("Google worksheet has a checkoff header that is too long")
    if not isinstance(worksheet, str) or not worksheet.strip():
        raise ValueError("worksheet title is required")
    try:
        parsed_time = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        if parsed_time.tzinfo is None:
            raise ValueError
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError("updated_at must be an ISO-8601 timestamp with a timezone") from error

    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    expected_keys = set(headers)
    for row_number, row in enumerate(rows, start=2):
        if set(row) != expected_keys:
            raise ValueError(f"row {row_number} does not match the worksheet headers")
        netid = str(row[NETID_COLUMN]).strip().lower()
        if not NETID_PATTERN.fullmatch(netid):
            raise ValueError(f"row {row_number} has an invalid Cornell NetID")
        if netid in seen:
            raise ValueError(f"duplicate NetID in row {row_number}")
        seen.add(netid)
        items = [
            {
                "name": header,
                "status": normalize_checkbox(row[header], row_number=row_number, column=header),
            }
            for header in item_headers
        ]
        records.append({
            "updated_at": updated_at,
            "worksheet": worksheet,
            "student": {"netid": netid},
            "items": items,
        })
    return records


def validate_simple_record(record: Any) -> list[str]:
    """Validate a record before it is written into a protected NetID directory."""
    errors: list[str] = []
    if not isinstance(record, dict):
        return ["record must be an object"]
    if set(record) != {"updated_at", "worksheet", "student", "items"}:
        errors.append("record fields do not match the simple schema")
    try:
        parsed_time = datetime.fromisoformat(record.get("updated_at", "").replace("Z", "+00:00"))
        if parsed_time.tzinfo is None:
            errors.append("updated_at must include a timezone")
    except (AttributeError, TypeError, ValueError):
        errors.append("updated_at must be an ISO-8601 timestamp")
    if not isinstance(record.get("worksheet"), str) or not record["worksheet"].strip():
        errors.append("worksheet is required")
    student = record.get("student")
    netid = student.get("netid") if isinstance(student, dict) else None
    if not isinstance(netid, str) or not NETID_PATTERN.fullmatch(netid):
        errors.append("student.netid is invalid")
    items = record.get("items")
    if not isinstance(items, list) or not items:
        errors.append("items must be a nonempty list")
    else:
        names: set[str] = set()
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                errors.append(f"items[{index}] must be an object")
                continue
            name = item.get("name")
            if not isinstance(name, str) or not name.strip() or len(name) > MAX_LABEL_LENGTH:
                errors.append(f"items[{index}].name is invalid")
            elif name in names:
                errors.append(f"duplicate item name: {name}")
            else:
                names.add(name)
            if item.get("status") not in STATUSES:
                errors.append(f"items[{index}].status is invalid")
    try:
        json.dumps(record, allow_nan=False)
    except (TypeError, ValueError):
        errors.append("record must contain only JSON-serializable, finite values")
    return errors
