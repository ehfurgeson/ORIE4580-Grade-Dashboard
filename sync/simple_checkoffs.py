"""Normalize the wide checkoff worksheet into syllabus-linked standards."""
from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable
from datetime import datetime
import json
import re
from typing import Any

from .checkoff_mappings import COLUMN_MAPPINGS, STANDARDS

NETID_COLUMN = "NetID"
NETID_PATTERN = re.compile(r"[a-z]{2,3}[0-9]+\Z")
STATUSES = {"complete", "incomplete"}
MAX_LABEL_LENGTH = 200
SCHEMA_VERSION = 2


def normalize_checkbox(value: Any, *, row_number: int, column: str) -> str:
    """Convert a Google Sheets checkbox value to a bounded dashboard status."""
    if value is True or (isinstance(value, str) and value.strip().casefold() == "true"):
        return "complete"
    if value is False or (isinstance(value, str) and value.strip().casefold() == "false"):
        return "incomplete"
    raise ValueError(f"row {row_number} column {column!r} is not a True/False checkbox")


def _mapped_standards(row: dict[str, Any], item_headers: list[str], row_number: int) -> list[dict[str, Any]]:
    grouped: OrderedDict[tuple[str, str], dict[str, Any]] = OrderedDict()
    for header in item_headers:
        standard_key, opportunity_id, label = COLUMN_MAPPINGS[header]
        key = (standard_key, opportunity_id)
        opportunity = grouped.setdefault(key, {
            "id": opportunity_id,
            "label": label,
            "kind": "green",
            "requirements": [],
        })
        if opportunity["label"] != label:
            raise ValueError(f"mapping for {opportunity_id!r} has inconsistent labels")
        opportunity["requirements"].append({
            "label": header,
            "status": normalize_checkbox(row[header], row_number=row_number, column=header),
        })

    by_standard: dict[str, list[dict[str, Any]]] = {standard_key: [] for standard_key in STANDARDS}
    for (standard_key, _), opportunity in grouped.items():
        opportunity["status"] = (
            "complete"
            if all(item["status"] == "complete" for item in opportunity["requirements"])
            else "incomplete"
        )
        by_standard[standard_key].append(opportunity)

    return [
        {
            "key": standard_key,
            "id": standard["id"],
            "name": standard["name"],
            "checkmarks": by_standard[standard_key],
        }
        for standard_key, standard in STANDARDS.items()
    ]


def rows_to_simple_records(
    rows: Iterable[dict[str, Any]], *, updated_at: str, worksheet: str
) -> list[dict[str, Any]]:
    """Convert one wide worksheet row per NetID to the mapped dashboard schema."""
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
    unmapped = [header for header in item_headers if header not in COLUMN_MAPPINGS]
    if unmapped:
        raise ValueError("unmapped checkoff column(s): " + ", ".join(repr(item) for item in unmapped))
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
        records.append({
            "schema_version": SCHEMA_VERSION,
            "updated_at": updated_at,
            "worksheet": worksheet,
            "student": {"netid": netid},
            "standards": _mapped_standards(row, item_headers, row_number),
        })
    return records


def validate_simple_record(record: Any) -> list[str]:
    """Validate a mapped record before writing it into a protected directory."""
    errors: list[str] = []
    if not isinstance(record, dict):
        return ["record must be an object"]
    expected = {"schema_version", "updated_at", "worksheet", "student", "standards"}
    if set(record) != expected:
        errors.append("record fields do not match the mapped schema")
    if record.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
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

    standards = record.get("standards")
    if not isinstance(standards, list) or not standards:
        errors.append("standards must be a nonempty list")
    else:
        ids: set[str] = set()
        opportunity_ids: set[str] = set()
        for s_index, standard in enumerate(standards):
            if not isinstance(standard, dict) or set(standard) != {"key", "id", "name", "checkmarks"}:
                errors.append(f"standards[{s_index}] is invalid")
                continue
            standard_key = standard["key"]
            definition = STANDARDS.get(standard_key)
            if not definition or standard["id"] != definition["id"] or standard["name"] != definition["name"]:
                errors.append(f"standards[{s_index}] does not match the syllabus mapping")
            elif standard_key in ids:
                errors.append(f"duplicate standard: {standard_key}")
            ids.add(standard_key)
            if not isinstance(standard["checkmarks"], list):
                errors.append(f"standards[{s_index}].checkmarks must be a list")
                continue
            for c_index, checkmark in enumerate(standard["checkmarks"]):
                prefix = f"standards[{s_index}].checkmarks[{c_index}]"
                required = {"id", "label", "kind", "status", "requirements"}
                if not isinstance(checkmark, dict) or set(checkmark) != required:
                    errors.append(f"{prefix} is invalid")
                    continue
                if checkmark["id"] in opportunity_ids:
                    errors.append(f"duplicate checkmark: {checkmark['id']}")
                opportunity_ids.add(checkmark["id"])
                if checkmark["kind"] != "green" or checkmark["status"] not in STATUSES:
                    errors.append(f"{prefix} has an invalid kind or status")
                requirements = checkmark["requirements"]
                if not isinstance(requirements, list) or not requirements:
                    errors.append(f"{prefix}.requirements must be a nonempty list")
                elif any(
                    not isinstance(item, dict)
                    or set(item) != {"label", "status"}
                    or item.get("status") not in STATUSES
                    for item in requirements
                ):
                    errors.append(f"{prefix}.requirements is invalid")
                elif checkmark["status"] != (
                    "complete" if all(item["status"] == "complete" for item in requirements) else "incomplete"
                ):
                    errors.append(f"{prefix}.status does not match its requirements")
        if ids != set(STANDARDS):
            errors.append("record must contain every currently defined standard")
    try:
        json.dumps(record, allow_nan=False)
    except (TypeError, ValueError):
        errors.append("record must contain only JSON-serializable, finite values")
    return errors
