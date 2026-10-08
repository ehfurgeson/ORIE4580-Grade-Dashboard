"""Normalize the wide checkoff worksheet into syllabus-linked standards."""
from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable
from datetime import datetime
import json
import re
from typing import Any

from .checkoff_mappings import COLUMN_MAPPINGS, OPPORTUNITY_HEADER_GROUPS, OPPORTUNITY_IDS
from .standards import STANDARDS

NETID_COLUMN = "NetID"
NETID_PATTERN = re.compile(r"[a-z]{2,3}[0-9]+\Z")
STATUSES = {"complete", "incomplete"}
MAX_LABEL_LENGTH = 200
MAX_WORKSHEET_COLUMNS = 702  # The live transport reads A:ZZ.
_BIDI_CONTROLS = frozenset(chr(value) for value in (
    0x061C, 0x200E, 0x200F, 0x202A, 0x202B, 0x202C, 0x202D, 0x202E,
    0x2066, 0x2067, 0x2068, 0x2069,
))


def valid_checkoff_header(value: Any) -> bool:
    """Return whether a Sheet header is safe bounded display metadata."""
    return (
        isinstance(value, str)
        and bool(value.strip())
        and len(value) <= MAX_LABEL_LENGTH
        and not any(ord(character) < 32 or ord(character) == 127 for character in value)
        and not any(character in _BIDI_CONTROLS for character in value)
    )


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
        standard_id, opportunity_id, label = COLUMN_MAPPINGS[header]
        key = (standard_id, opportunity_id)
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

    by_standard: dict[str, list[dict[str, Any]]] = {standard_id: [] for standard_id in STANDARDS}
    for (standard_id, _), opportunity in grouped.items():
        opportunity["status"] = (
            "complete"
            if all(item["status"] == "complete" for item in opportunity["requirements"])
            else "incomplete"
        )
        by_standard[standard_id].append(opportunity)

    return [
        {
            "id": standard_id,
            "name": name,
            "checkmarks": by_standard[standard_id],
        }
        for standard_id, name in STANDARDS.items()
    ]


def rows_to_simple_records(
    rows: Iterable[dict[str, Any]], *, updated_at: str, worksheet: str
) -> list[dict[str, Any]]:
    """Normalize worksheet rows for merging with Gradescope results."""
    rows = list(rows)
    if not rows:
        raise ValueError("Google worksheet contains no student rows")
    headers = list(rows[0])
    if headers.count(NETID_COLUMN) != 1:
        raise ValueError(f"Google worksheet must contain exactly one {NETID_COLUMN!r} column")
    item_headers = [header for header in headers if header != NETID_COLUMN]
    if not item_headers:
        raise ValueError("Google worksheet must contain at least one checkoff column")
    if len(headers) > MAX_WORKSHEET_COLUMNS:
        raise ValueError("Google worksheet has too many columns")
    if any(not isinstance(header, str) or not header.strip() for header in item_headers):
        raise ValueError("Google worksheet has an empty checkoff header")
    if any(isinstance(header, str) and len(header) > MAX_LABEL_LENGTH for header in item_headers):
        raise ValueError("Google worksheet has a checkoff header that is too long")
    if any(not valid_checkoff_header(header) for header in item_headers):
        raise ValueError("Google worksheet has an unsafe checkoff header")
    mapped = [header for header in item_headers if header in COLUMN_MAPPINGS]
    unmapped = [header for header in item_headers if header not in COLUMN_MAPPINGS]
    mapped_opportunities = {COLUMN_MAPPINGS[header][1] for header in mapped}
    for opportunity_id in mapped_opportunities:
        actual_headers = frozenset(
            header for header in mapped if COLUMN_MAPPINGS[header][1] == opportunity_id
        )
        if actual_headers not in OPPORTUNITY_HEADER_GROUPS[opportunity_id]:
            raise ValueError(f"mapped checkoff headers for {opportunity_id!r} are incomplete or ambiguous")
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
            "updated_at": updated_at,
            "worksheet": worksheet,
            "student": {"netid": netid},
            "unmapped_columns": list(unmapped),
            "standards": _mapped_standards(row, mapped, row_number),
        })
    return records


def validate_manual_record(record: Any) -> list[str]:
    """Validate normalized worksheet input before the Gradescope merge."""
    errors: list[str] = []
    if not isinstance(record, dict):
        return ["record must be an object"]
    expected = {"updated_at", "worksheet", "student", "unmapped_columns", "standards"}
    if set(record) != expected:
        errors.append("record fields do not match the mapped schema")
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

    unmapped = record.get("unmapped_columns")
    unmapped_names: list[str] = []
    if not isinstance(unmapped, list):
        errors.append("unmapped_columns must be a list")
    else:
        if len(unmapped) > MAX_WORKSHEET_COLUMNS - 1:
            errors.append("unmapped_columns is too large")
        if any(not valid_checkoff_header(item) for item in unmapped):
            errors.append("unmapped_columns contains an invalid header")
        unmapped_names = [item for item in unmapped if isinstance(item, str)]
        if len(unmapped_names) != len(set(unmapped_names)):
            errors.append("unmapped_columns contains a duplicate header")
        if any(item in COLUMN_MAPPINGS for item in unmapped_names):
            errors.append("unmapped_columns contains a mapped header")

    standards = record.get("standards")
    detail_headers: set[str] = set()
    if not isinstance(standards, list) or not standards:
        errors.append("standards must be a nonempty list")
    else:
        ids: set[str] = set()
        opportunity_ids: set[str] = set()
        for s_index, standard in enumerate(standards):
            if not isinstance(standard, dict) or set(standard) != {"id", "name", "checkmarks"}:
                errors.append(f"standards[{s_index}] is invalid")
                continue
            standard_id = standard["id"]
            name = STANDARDS.get(standard_id) if isinstance(standard_id, str) else None
            if not name or standard["name"] != name:
                errors.append(f"standards[{s_index}] does not match the syllabus mapping")
            elif standard_id in ids:
                errors.append(f"duplicate standard: {standard_id}")
            if isinstance(standard_id, str):
                ids.add(standard_id)
            if not isinstance(standard["checkmarks"], list):
                errors.append(f"standards[{s_index}].checkmarks must be a list")
                continue
            for c_index, checkmark in enumerate(standard["checkmarks"]):
                prefix = f"standards[{s_index}].checkmarks[{c_index}]"
                required = {"id", "label", "kind", "status", "requirements"}
                if not isinstance(checkmark, dict) or set(checkmark) != required:
                    errors.append(f"{prefix} is invalid")
                    continue
                opportunity = checkmark["id"]
                if not isinstance(opportunity, str) or opportunity not in OPPORTUNITY_IDS:
                    errors.append(f"{prefix} has an unknown checkmark ID")
                elif opportunity in opportunity_ids:
                    errors.append(f"duplicate checkmark: {opportunity}")
                else:
                    opportunity_ids.add(opportunity)
                authoritative = [
                    (header, mapping) for header, mapping in COLUMN_MAPPINGS.items()
                    if mapping[1] == opportunity
                ] if isinstance(opportunity, str) else []
                if authoritative and any(
                    mapping[0] != standard_id or mapping[2] != checkmark["label"]
                    for _header, mapping in authoritative
                ):
                    errors.append(f"{prefix} does not match the approved mapping")
                if (
                    checkmark["kind"] != "green"
                    or not isinstance(checkmark["status"], str)
                    or checkmark["status"] not in STATUSES
                ):
                    errors.append(f"{prefix} has an invalid kind or status")
                requirements = checkmark["requirements"]
                if not isinstance(requirements, list) or not requirements:
                    errors.append(f"{prefix}.requirements must be a nonempty list")
                    continue
                valid_requirements = True
                local_headers: set[str] = set()
                for item in requirements:
                    if (
                        not isinstance(item, dict)
                        or set(item) != {"label", "status"}
                        or not isinstance(item.get("status"), str)
                        or item.get("status") not in STATUSES
                        or not isinstance(item.get("label"), str)
                    ):
                        valid_requirements = False
                        continue
                    header = item["label"]
                    mapping = COLUMN_MAPPINGS.get(header)
                    if mapping is None or mapping[0] != standard_id or mapping[1] != opportunity or mapping[2] != checkmark["label"]:
                        valid_requirements = False
                    if header in local_headers or header in detail_headers:
                        valid_requirements = False
                    local_headers.add(header)
                    detail_headers.add(header)
                if frozenset(local_headers) not in OPPORTUNITY_HEADER_GROUPS.get(opportunity, ()):
                    valid_requirements = False
                if not valid_requirements:
                    errors.append(f"{prefix}.requirements is invalid")
                elif checkmark["status"] != (
                    "complete" if all(item["status"] == "complete" for item in requirements) else "incomplete"
                ):
                    errors.append(f"{prefix}.status does not match its requirements")
        if ids != set(STANDARDS):
            errors.append("record must contain every currently defined standard")
    if len(detail_headers) + len(unmapped_names) > MAX_WORKSHEET_COLUMNS - 1:
        errors.append("record contains too many Sheet columns")
    try:
        json.dumps(record, allow_nan=False)
    except (TypeError, ValueError):
        errors.append("record must contain only JSON-serializable, finite values")
    return errors
