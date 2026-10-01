"""Merge manual Google checkoffs with normalized Gradescope autograder results."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
from typing import Any

from .checkoff_mappings import MANUAL_ONLY_OPPORTUNITY_IDS
from .gradescope import validate_snapshot
from .gradescope_exam import EXAM_OPPORTUNITIES, ExamImport
from .simple_checkoffs import (
    NETID_PATTERN, STATUSES as MANUAL_STATUSES, validate_manual_record,
)
from .standards import STANDARDS

SCHEMA_VERSION = 5
AUTOGRADER_STATUSES = {
    "passed", "failed", "pending", "error", "not_submitted",
    "not_configured", "not_found",
}


def _later_timestamp(first: str, second: str) -> str:
    one = datetime.fromisoformat(first.replace("Z", "+00:00"))
    two = datetime.fromisoformat(second.replace("Z", "+00:00"))
    return first if one >= two else second


def merge_checkoffs_with_autograders(
    records: list[dict[str, Any]],
    snapshot: dict[str, Any],
    *,
    allow_unconfigured: bool = False,
    allow_missing_students: bool = False,
) -> list[dict[str, Any]]:
    """Return dashboard records with verified Lab requirements; inputs are not mutated.

    Strict mode requires each manual opportunity to have one configured
    Gradescope assignment and every Google student to exist in the Gradescope
    snapshot. Local canaries may explicitly allow unconfigured opportunities.
    """
    if not isinstance(records, list) or not records:
        raise ValueError("Google checkoff records must be a nonempty list")
    for index, record in enumerate(records):
        errors = validate_manual_record(record)
        if errors:
            raise ValueError(f"Google record {index} is invalid: {'; '.join(errors)}")
    snapshot_errors = validate_snapshot(snapshot)
    if snapshot_errors:
        raise ValueError("Gradescope snapshot is invalid: " + "; ".join(snapshot_errors))

    assignments = snapshot["assignments"]
    configured = [item["opportunity_id"] for item in assignments]
    if len(configured) != len(set(configured)):
        raise ValueError("Gradescope snapshot has duplicate opportunity mappings")
    gradescope_students = {student["netid"]: student for student in snapshot["students"]}

    available_opportunities = {
        checkmark["id"]
        for record in records
        for standard in record["standards"]
        for checkmark in standard["checkmarks"]
    }
    unknown = set(configured) - available_opportunities
    if unknown:
        raise ValueError("Gradescope assignments map to opportunities absent from the Google Sheet")
    manual_only_configured = set(configured) & MANUAL_ONLY_OPPORTUNITY_IDS
    if manual_only_configured:
        raise ValueError("manual-only opportunities must not have Gradescope assignment mappings")
    if not allow_unconfigured:
        autograded_opportunities = available_opportunities - MANUAL_ONLY_OPPORTUNITY_IDS
        missing = autograded_opportunities - set(configured)
        if missing:
            raise ValueError("manual opportunities are missing Gradescope assignment mappings")

    merged_records: list[dict[str, Any]] = []
    for original in records:
        record = deepcopy(original)
        netid = record["student"]["netid"]
        gradescope_student = gradescope_students.get(netid)
        if gradescope_student is None and not (allow_unconfigured or allow_missing_students):
            raise ValueError(f"Google student {netid} is missing from the Gradescope snapshot")
        result_map = {
            result["opportunity_id"]: result
            for result in (gradescope_student or {}).get("autograders", [])
        }
        record['schema_version'] = SCHEMA_VERSION
        record["updated_at"] = _later_timestamp(record["updated_at"], snapshot["generated_at"])
        for standard in record["standards"]:
            for checkmark in standard["checkmarks"]:
                manual_details = deepcopy(checkmark["requirements"])
                manual_status = checkmark["status"]
                result = result_map.get(checkmark["id"])
                if result is not None:
                    autograder_status = result["status"]
                elif checkmark["id"] not in configured:
                    autograder_status = "not_configured"
                else:
                    autograder_status = "not_found"
                manual_requirement = {
                    "id": "manual",
                    "label": "Manual checkoff",
                    "source": "google_sheets",
                    "status": manual_status,
                    "details": manual_details,
                }
                if checkmark["id"] in MANUAL_ONLY_OPPORTUNITY_IDS:
                    checkmark["requirements"] = [manual_requirement]
                    checkmark["status"] = manual_status
                else:
                    checkmark["requirements"] = [
                        manual_requirement,
                        {
                            "id": "autograder",
                            "label": "Autograder",
                            "source": "gradescope",
                            "status": autograder_status,
                            "details": [],
                        },
                    ]
                    checkmark["status"] = (
                        "complete"
                        if manual_status == "complete" and autograder_status == "passed"
                        else "incomplete"
                    )
        errors = validate_combined_record(record)
        if errors:
            raise ValueError(f"combined record for {netid} is invalid: {'; '.join(errors)}")
        merged_records.append(record)
    return merged_records


def validate_combined_record(record: Any) -> list[str]:
    """Validate the local combined dashboard schema without throwing."""
    errors: list[str] = []
    expected = {"schema_version", "updated_at", "worksheet", "student", "standards"}
    if not isinstance(record, dict) or set(record) != expected:
        return ["record fields do not match the combined schema"]
    if record.get('schema_version') != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    try:
        timestamp = datetime.fromisoformat(record.get("updated_at", "").replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            errors.append("updated_at must include a timezone")
    except (AttributeError, ValueError):
        errors.append("updated_at is invalid")
    if not isinstance(record.get("worksheet"), str) or not record["worksheet"].strip():
        errors.append("worksheet is required")
    student = record.get("student")
    netid = student.get("netid") if isinstance(student, dict) else None
    if not isinstance(netid, str) or not NETID_PATTERN.fullmatch(netid):
        errors.append("student.netid is invalid")

    standards = record.get("standards")
    standard_ids: set[str] = set()
    opportunity_ids: set[str] = set()
    if not isinstance(standards, list) or not standards:
        errors.append("standards must be a nonempty list")
    else:
        for standard in standards:
            if not isinstance(standard, dict) or set(standard) != {"id", "name", "checkmarks"}:
                errors.append("a standard is malformed")
                continue
            standard_id = standard["id"]
            name = STANDARDS.get(standard_id) if isinstance(standard_id, str) else None
            if not name or standard["name"] != name:
                errors.append("a standard does not match the syllabus mapping")
            elif standard_id in standard_ids:
                errors.append("duplicate standard")
            else:
                standard_ids.add(standard_id)
            checkmarks = standard["checkmarks"]
            if not isinstance(checkmarks, list):
                errors.append("standard checkmarks must be a list")
                continue
            for checkmark in checkmarks:
                fields = {"id", "label", "kind", "status", "requirements"}
                if not isinstance(checkmark, dict) or set(checkmark) != fields:
                    errors.append("a checkmark is malformed")
                    continue
                opportunity = checkmark["id"]
                if not isinstance(opportunity, str) or opportunity in opportunity_ids:
                    errors.append("checkmark ID is invalid or duplicated")
                else:
                    opportunity_ids.add(opportunity)
                requirements = checkmark["requirements"]
                requirement_fields = {"id", "label", "source", "status", "details"}
                if checkmark["kind"] == "green":
                    if checkmark["status"] not in MANUAL_STATUSES:
                        errors.append("lab checkmark status is invalid")
                    manual_only = opportunity in MANUAL_ONLY_OPPORTUNITY_IDS
                    expected_requirement_ids = {"manual"} if manual_only else {"manual", "autograder"}
                    expected_requirement_count = len(expected_requirement_ids)
                    if not isinstance(requirements, list) or len(requirements) != expected_requirement_count:
                        errors.append("lab checkmark has the wrong requirements")
                        continue
                    by_id = {
                        item.get("id"): item for item in requirements
                        if isinstance(item, dict) and isinstance(item.get("id"), str)
                    }
                    if set(by_id) != expected_requirement_ids:
                        errors.append("checkmark requirement IDs are invalid")
                        continue
                    manual = by_id["manual"]
                    if set(manual) != requirement_fields:
                        errors.append("a checkmark requirement is malformed")
                        continue
                    if manual["source"] != "google_sheets" or manual["status"] not in MANUAL_STATUSES:
                        errors.append("manual requirement is invalid")
                    details = manual["details"]
                    if not isinstance(details, list) or not details or any(
                        not isinstance(item, dict)
                        or set(item) != {"label", "status"}
                        or not isinstance(item["label"], str)
                        or item["status"] not in MANUAL_STATUSES
                        for item in details
                    ):
                        errors.append("manual requirement details are invalid")
                    elif manual["status"] != (
                        "complete" if all(item["status"] == "complete" for item in details) else "incomplete"
                    ):
                        errors.append("manual requirement does not match its details")
                    if manual_only:
                        expected_status = manual["status"]
                    else:
                        auto = by_id["autograder"]
                        if set(auto) != requirement_fields:
                            errors.append("a checkmark requirement is malformed")
                            continue
                        if auto["source"] != "gradescope" or auto["status"] not in AUTOGRADER_STATUSES or auto["details"] != []:
                            errors.append("autograder requirement is invalid")
                        expected_status = (
                            "complete"
                            if manual["status"] == "complete" and auto["status"] == "passed"
                            else "incomplete"
                        )
                    if checkmark["status"] != expected_status:
                        errors.append("checkmark status does not match its requirements")
                elif checkmark["kind"] in {"purple", "shiny_purple"}:
                    if checkmark["status"] not in {"complete", "incomplete", "not_graded"}:
                        errors.append("exam checkmark status is invalid")
                    if not isinstance(requirements, list) or len(requirements) != 1:
                        errors.append("exam checkmark must have one score requirement")
                        continue
                    score = requirements[0]
                    if (
                        not isinstance(score, dict)
                        or set(score) != requirement_fields
                        or score["id"] != "exam_score"
                        or score["source"] != "gradescope_exam"
                        or score["status"] != checkmark["status"]
                        or score["details"] != []
                    ):
                        errors.append("exam score requirement is invalid")
                else:
                    errors.append("checkmark kind is invalid")
    if standard_ids != set(STANDARDS):
        errors.append("record must contain every currently defined standard")
    try:
        json.dumps(record, allow_nan=False)
    except (TypeError, ValueError):
        errors.append("record must contain finite JSON")
    return errors


def merge_exam_checkmarks(
    records: list[dict[str, Any]], exam: ExamImport
) -> list[dict[str, Any]]:
    """Add optional Exam 1 marks without changing the dashboard schema."""
    expected_netids = {record["student"]["netid"] for record in records}
    if set(exam.by_netid) != expected_netids:
        raise ValueError("Exam 1 student set does not match the dashboard records")
    merged = deepcopy(records)
    definitions = {item["id"]: item for item in EXAM_OPPORTUNITIES}
    for record in merged:
        if validate_combined_record(record):
            raise ValueError("Exam 1 can only be merged into valid dashboard records")
        netid = record["student"]["netid"]
        standards = {standard["id"]: standard for standard in record["standards"]}
        results = exam.by_netid[netid]
        if {item.get("id") for item in results} != set(definitions) or len(results) != len(definitions):
            raise ValueError("Exam 1 results do not match the configured questions")
        for result in results:
            definition = definitions[result["id"]]
            for field in ("question", "standard_id", "label", "kind"):
                if result.get(field) != definition[field]:
                    raise ValueError("Exam 1 result mapping was modified")
            status = result.get("status")
            if status not in {"complete", "incomplete", "not_graded"}:
                raise ValueError("Exam 1 result status is invalid")
            standards[definition["standard_id"]]["checkmarks"].append({
                "id": definition["id"],
                "label": definition["label"],
                "kind": definition["kind"],
                "status": status,
                "requirements": [{
                    "id": "exam_score",
                    "label": "Exam 1 question score",
                    "source": "gradescope_exam",
                    "status": status,
                    "details": [],
                }],
            })
        errors = validate_combined_record(record)
        if errors:
            raise ValueError(f"combined Exam 1 record for {netid} is invalid: {'; '.join(errors)}")
    return merged
