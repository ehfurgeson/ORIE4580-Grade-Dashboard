"""Validation for the private, stable grade-dashboard schema."""
from __future__ import annotations

from datetime import datetime
import json
import re
from typing import Any

from .standards import COURSES, FULL_STANDARD_COURSES, STANDARDS

STATUSES = {"complete", "incomplete", "not_graded", "excused"}
CATEGORIES = {"Probability", "Statistics", "Modeling"}
SOURCES_BY_KIND = {
    "green": {"lab"},
    "purple": {"exam", "exam_like"},
    "shiny_purple": {"exam", "exam_like"},
}
STUDENT_ID_PATTERN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}[A-Za-z0-9])?\Z")


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_record(record: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(record, dict):
        return ["record must be an object"]

    for key in ("updated_at", "course", "student", "standards"):
        if key not in record:
            errors.append(f"missing required field: {key}")

    course = record.get("course")
    if course not in COURSES:
        errors.append("course must be ORIE 4580, ORIE 5580, or ORIE 5581")

    updated_at = record.get("updated_at")
    try:
        parsed_time = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        if parsed_time.tzinfo is None:
            errors.append("updated_at must include a timezone")
    except (AttributeError, TypeError, ValueError):
        errors.append("updated_at must be an ISO-8601 timestamp")

    student = record.get("student")
    if not isinstance(student, dict):
        errors.append("student must be an object")
    else:
        student_id = student.get("id")
        if not _nonempty_string(student_id):
            errors.append("student.id is required")
        elif not STUDENT_ID_PATTERN.fullmatch(student_id):
            errors.append("student.id must contain only ASCII letters, digits, or internal hyphens")
        if not _nonempty_string(student.get("name")):
            errors.append("student.name is required")

    standards = record.get("standards")
    if not isinstance(standards, list) or not standards:
        errors.append("standards must be a nonempty list")
    else:
        standard_ids: set[str] = set()
        for i, standard in enumerate(standards):
            prefix = f"standards[{i}]"
            if not isinstance(standard, dict):
                errors.append(f"{prefix} must be an object")
                continue

            standard_id = standard.get("id")
            if not _nonempty_string(standard_id):
                errors.append(f"{prefix}.id is required")
            elif standard_id in standard_ids:
                errors.append(f"duplicate standard id: {standard_id}")
            else:
                standard_ids.add(standard_id)
            if not _nonempty_string(standard.get("name")):
                errors.append(f"{prefix}.name is required")
            category = standard.get("category")
            if category not in CATEGORIES:
                errors.append(f"{prefix}.category is invalid")
            if _nonempty_string(standard_id) and standard_id not in STANDARDS:
                errors.append(f"{prefix}.id is not in the syllabus standards catalog")
            elif _nonempty_string(standard_id) and standard_id in STANDARDS:
                expected_category, expected_name = STANDARDS[standard_id]
                if category != expected_category:
                    errors.append(f"{prefix}.category does not match the syllabus catalog")
                if standard.get("name") != expected_name:
                    errors.append(f"{prefix}.name does not match the syllabus catalog")

            opportunities = standard.get("opportunities")
            if not isinstance(opportunities, list):
                errors.append(f"{prefix}.opportunities must be a list")
                continue

            opportunity_ids: set[str] = set()
            for j, item in enumerate(opportunities):
                item_prefix = f"{prefix}.opportunities[{j}]"
                if not isinstance(item, dict):
                    errors.append(f"{item_prefix} must be an object")
                    continue

                identifier = item.get("id")
                if not _nonempty_string(identifier):
                    errors.append(f"{item_prefix}.id is required")
                elif identifier in opportunity_ids:
                    errors.append(f"duplicate opportunity id in {standard_id}: {identifier}")
                else:
                    opportunity_ids.add(identifier)
                if not _nonempty_string(item.get("label")):
                    errors.append(f"{item_prefix}.label is required")

                kind = item.get("kind")
                source = item.get("source")
                if kind not in SOURCES_BY_KIND:
                    errors.append(f"{item_prefix}.kind is invalid")
                elif source not in SOURCES_BY_KIND[kind]:
                    errors.append(f"{item_prefix}.source does not match {kind} checkmark rules")
                if item.get("status") not in STATUSES:
                    errors.append(f"{item_prefix}.status is invalid")

        if course in FULL_STANDARD_COURSES and standard_ids != set(STANDARDS):
            missing = sorted(set(STANDARDS) - standard_ids)
            extra = sorted(standard_ids - set(STANDARDS))
            detail = []
            if missing:
                detail.append("missing " + ", ".join(missing))
            if extra:
                detail.append("unexpected " + ", ".join(extra))
            errors.append("standards must match the 12-standard syllabus catalog (" + "; ".join(detail) + ")")

    try:
        json.dumps(record, allow_nan=False)
    except (TypeError, ValueError):
        errors.append("record must contain only JSON-serializable, finite values")
    return errors


def validate_all(records: Any) -> list[str]:
    if not isinstance(records, list) or not records:
        return ["records must be a nonempty list"]

    errors: list[str] = []
    seen: set[str] = set()
    for i, record in enumerate(records):
        errors.extend(f"student {i}: {error}" for error in validate_record(record))
        student = record.get("student") if isinstance(record, dict) else None
        student_id = student.get("id") if isinstance(student, dict) else None
        if isinstance(student_id, str) and student_id:
            if student_id in seen:
                errors.append(f"duplicate student id: {student_id}")
            seen.add(student_id)
    return errors
