"""Read-only adapter for Gradescope's unofficial private web interface.

The transport is intentionally isolated from the dashboard schema. It emits a
minimal NetID/status snapshot and never persists raw HTML, cookies, emails,
scores, or submission IDs.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import logging
import os
from pathlib import Path
import re
import requests
import tempfile
import time
import tomllib
from typing import Any, Callable, Protocol
from urllib.parse import urljoin, urlparse

from .checkoff_mappings import opportunity_from_assignment_title

SCHEMA_VERSION = 1
SOURCE_NAME = "gradescope_unofficial_read_only"
NETID_EMAIL_PATTERN = re.compile(r"([a-z]{2,3}[0-9]+)@cornell\.edu\Z")
STATUSES = {"passed", "failed", "pending", "error", "not_submitted"}
PROCESSED_SUBMISSION_STATUS = "processed"
PENDING_SUBMISSION_STATUSES = {"processing", "pending", "queued"}
FAILED_SUBMISSION_STATUSES = {"failed"}
HISTORY_SUFFIX = ".json?content=react&only_keys%5B%5D=past_submissions"
BASE_URL = "https://www.gradescope.com"


class GradescopeAdapterError(RuntimeError):
    """Base exception safe for CLI display (contains no response bodies)."""


class GradescopeSchemaError(GradescopeAdapterError):
    """Gradescope or configuration data did not match the expected structure."""


class GradescopeTransportError(GradescopeAdapterError):
    """A login or network request failed."""


@dataclass(frozen=True)
class AssignmentRule:
    assignment_id: int
    opportunity_id: str
    contract_version: str
    expected_score: Decimal
    expected_test_count: int
    expected_test_maxima: tuple[Decimal, ...]
    title_mapping_override: bool = False


@dataclass(frozen=True)
class ExamRule:
    assignment_id: int
    title: str
    expected_question_count: int
    expected_question_score: Decimal
    earn_threshold: Decimal


def assignment_title_matches(actual: str, configured: str) -> bool:
    """Match an upstream title while keeping configured names human-readable."""
    normalize = lambda value: " ".join(value.replace("_", " ").split())
    return normalize(actual) == normalize(configured)


@dataclass(frozen=True)
class AdapterConfig:
    course_id: int
    assignments: tuple[AssignmentRule, ...]
    student_role_values: frozenset[str] = frozenset({"0"})
    non_student_role_values: frozenset[str] = frozenset({"1", "2"})
    timeout_seconds: float = 30.0
    minimum_request_interval_seconds: float = 0.1
    maximum_requests: int = 20_000
    maximum_response_bytes: int = 10_000_000
    minimum_roster_members: int = 1
    maximum_roster_members: int = 2_000
    maximum_submissions_per_student: int = 500
    exam: ExamRule | None = None


@dataclass(frozen=True)
class MemberRef:
    member_id: str
    email: str
    role: str


@dataclass
class SubmissionBatch:
    observed: int
    payloads: Iterator[dict[str, Any]]


class GradescopeSource(Protocol):
    def list_members(self) -> list[MemberRef]: ...
    def submissions(self, member_id: str, assignment_id: int) -> SubmissionBatch: ...


def _decimal(value: Any, *, field: str) -> Decimal:
    if isinstance(value, bool):
        raise GradescopeSchemaError(f"{field} must be numeric")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise GradescopeSchemaError(f"{field} must be numeric") from error
    if not result.is_finite():
        raise GradescopeSchemaError(f"{field} must be finite")
    return result


def load_config(path: str | Path) -> AdapterConfig:
    """Load an explicit course/assignment allowlist from TOML."""
    with Path(path).open("rb") as handle:
        raw = tomllib.load(handle)
    required_top = {"schema_version", "course_id", "roles", "network", "assignments"}
    if set(raw) not in (required_top, required_top | {"exam"}):
        raise ValueError("Gradescope config fields do not match the expected schema")
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"Gradescope config schema_version must be {SCHEMA_VERSION}")
    course_id = raw.get("course_id")
    if not isinstance(course_id, int) or isinstance(course_id, bool) or course_id <= 0:
        raise ValueError("Gradescope course_id must be a positive integer")

    roles = raw.get("roles")
    if not isinstance(roles, dict) or set(roles) != {"student", "non_student"}:
        raise ValueError("Gradescope role config is invalid")
    student_roles = roles["student"]
    non_student_roles = roles["non_student"]
    if (
        not isinstance(student_roles, list)
        or not student_roles
        or not isinstance(non_student_roles, list)
        or any(not isinstance(value, str) or not value for value in student_roles + non_student_roles)
    ):
        raise ValueError("Gradescope role values must be nonempty string lists")
    if len(set(student_roles)) != len(student_roles) or len(set(non_student_roles)) != len(non_student_roles):
        raise ValueError("Gradescope role values must be unique")
    if set(student_roles) & set(non_student_roles):
        raise ValueError("student and non-student role values must be disjoint")

    network = raw.get("network")
    network_fields = {
        "timeout_seconds",
        "minimum_request_interval_seconds",
        "maximum_requests",
        "maximum_response_bytes",
        "minimum_roster_members",
        "maximum_roster_members",
        "maximum_submissions_per_student",
    }
    if not isinstance(network, dict) or set(network) != network_fields:
        raise ValueError("Gradescope network config is invalid")
    timeout = network["timeout_seconds"]
    interval = network["minimum_request_interval_seconds"]
    maximum_requests = network["maximum_requests"]
    maximum_response_bytes = network["maximum_response_bytes"]
    minimum_roster_members = network["minimum_roster_members"]
    maximum_roster_members = network["maximum_roster_members"]
    maximum_submissions = network["maximum_submissions_per_student"]
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not 1 <= timeout <= 120:
        raise ValueError("timeout_seconds must be between 1 and 120")
    if not isinstance(interval, (int, float)) or isinstance(interval, bool) or not 0 <= interval <= 10:
        raise ValueError("minimum_request_interval_seconds must be between 0 and 10")
    limits = {
        "maximum_requests": (maximum_requests, 1, 100_000),
        "maximum_response_bytes": (maximum_response_bytes, 1_024, 100_000_000),
        "minimum_roster_members": (minimum_roster_members, 1, 10_000),
        "maximum_roster_members": (maximum_roster_members, 1, 10_000),
        "maximum_submissions_per_student": (maximum_submissions, 1, 10_000),
    }
    for name, (value, minimum, maximum) in limits.items():
        if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
            raise ValueError(f"{name} must be between {minimum} and {maximum}")

    assignments_raw = raw.get("assignments")
    if not isinstance(assignments_raw, dict) or not assignments_raw:
        raise ValueError("Gradescope config must contain at least one assignment")
    if minimum_roster_members > maximum_roster_members:
        raise ValueError("minimum_roster_members cannot exceed maximum_roster_members")

    rules: list[AssignmentRule] = []
    opportunities: set[str] = set()
    for assignment_key, value in assignments_raw.items():
        try:
            assignment_id = int(assignment_key)
        except (TypeError, ValueError) as error:
            raise ValueError("assignment IDs must be positive integers") from error
        if assignment_id <= 0 or str(assignment_id) != str(assignment_key):
            raise ValueError("assignment IDs must be canonical positive integers")
        expected_fields = {
            "opportunity_id", "contract_version", "expected_score",
            "expected_test_count", "expected_test_maxima", "title_mapping_override",
        }
        if not isinstance(value, dict) or set(value) != expected_fields:
            raise ValueError(f"assignment {assignment_id} config fields are invalid")
        opportunity_id = value["opportunity_id"]
        if not isinstance(opportunity_id, str) or not re.fullmatch(r"[a-z][a-z0-9-]{1,63}", opportunity_id):
            raise ValueError(f"assignment {assignment_id} opportunity_id is invalid")
        if opportunity_id in opportunities:
            raise ValueError(f"duplicate opportunity_id: {opportunity_id}")
        opportunities.add(opportunity_id)
        contract_version = value["contract_version"]
        if not isinstance(contract_version, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}", contract_version):
            raise ValueError(f"assignment {assignment_id} contract_version is invalid")
        try:
            expected_score = _decimal(value["expected_score"], field="expected_score")
        except GradescopeSchemaError as error:
            raise ValueError(f"assignment {assignment_id}: {error}") from error
        expected_test_count = value["expected_test_count"]
        if expected_score <= 0:
            raise ValueError(f"assignment {assignment_id} expected_score must be positive")
        if not isinstance(expected_test_count, int) or isinstance(expected_test_count, bool) or expected_test_count <= 0:
            raise ValueError(f"assignment {assignment_id} expected_test_count must be positive")
        maxima_raw = value["expected_test_maxima"]
        if not isinstance(maxima_raw, list) or len(maxima_raw) != expected_test_count:
            raise ValueError(f"assignment {assignment_id} expected_test_maxima must match expected_test_count")
        try:
            maxima = tuple(_decimal(item, field="expected_test_maxima") for item in maxima_raw)
        except GradescopeSchemaError as error:
            raise ValueError(f"assignment {assignment_id}: {error}") from error
        if any(item < 0 for item in maxima) or sum(maxima, Decimal(0)) != expected_score:
            raise ValueError(f"assignment {assignment_id} expected_test_maxima do not sum to expected_score")
        title_override = value["title_mapping_override"]
        if not isinstance(title_override, bool):
            raise ValueError(f"assignment {assignment_id} title_mapping_override must be boolean")
        rules.append(
            AssignmentRule(
                assignment_id, opportunity_id, contract_version,
                expected_score, expected_test_count, maxima, title_override,
            )
        )
    rules.sort(key=lambda rule: rule.assignment_id)

    exam_rule = None
    exam_raw = raw.get("exam")
    if exam_raw is not None:
        exam_fields = {
            "assignment_id", "title", "expected_question_count",
            "expected_question_score", "earn_threshold",
        }
        if not isinstance(exam_raw, dict) or set(exam_raw) != exam_fields:
            raise ValueError("Gradescope exam config fields are invalid")
        exam_id = exam_raw["assignment_id"]
        exam_title = exam_raw["title"]
        question_count = exam_raw["expected_question_count"]
        if not isinstance(exam_id, int) or isinstance(exam_id, bool) or exam_id <= 0:
            raise ValueError("exam assignment_id must be a positive integer")
        if exam_id in {rule.assignment_id for rule in rules}:
            raise ValueError("exam assignment_id duplicates a lab assignment")
        if not isinstance(exam_title, str) or not exam_title.strip():
            raise ValueError("exam title must be nonempty")
        if "_" in exam_title:
            raise ValueError("exam title must use spaces instead of underscores")
        if not isinstance(question_count, int) or isinstance(question_count, bool) or question_count != 6:
            raise ValueError("Exam 1 expected_question_count must be 6")
        try:
            question_score = _decimal(exam_raw["expected_question_score"], field="expected_question_score")
            threshold = _decimal(exam_raw["earn_threshold"], field="earn_threshold")
        except GradescopeSchemaError as error:
            raise ValueError(str(error)) from error
        if question_score != Decimal("1"):
            raise ValueError("Exam 1 questions must each be configured out of 1")
        if threshold != Decimal("0.8"):
            raise ValueError("Exam 1 earn_threshold must be 0.8")
        exam_rule = ExamRule(exam_id, exam_title, question_count, question_score, threshold)

    return AdapterConfig(
        course_id,
        tuple(rules),
        frozenset(student_roles),
        frozenset(non_student_roles),
        float(timeout),
        float(interval),
        maximum_requests,
        maximum_response_bytes,
        minimum_roster_members,
        maximum_roster_members,
        maximum_submissions,
        exam_rule,
    )


def extract_submission_payload(html: Any) -> dict[str, Any]:
    """Extract exactly one viewer payload from a submission page."""
    if not isinstance(html, str):
        raise GradescopeSchemaError("submission HTML must be text")
    try:
        from bs4 import BeautifulSoup
    except ImportError as error:
        raise RuntimeError("install requirements.txt to parse Gradescope responses") from error
    soup = BeautifulSoup(html, "html.parser")
    blocks = soup.find_all(attrs={"data-react-class": "AssignmentSubmissionViewer"})
    if len(blocks) != 1 or not blocks[0].get("data-react-props"):
        raise GradescopeSchemaError("AssignmentSubmissionViewer properties are missing or duplicated")
    try:
        payload = json.loads(blocks[0]["data-react-props"])
    except (TypeError, json.JSONDecodeError) as error:
        raise GradescopeSchemaError("AssignmentSubmissionViewer properties are invalid JSON") from error
    if not isinstance(payload, dict):
        raise GradescopeSchemaError("AssignmentSubmissionViewer properties must be an object")
    return payload


def netid_from_email(email: Any) -> str | None:
    """Return a NetID only for a canonical Cornell student email address."""
    if not isinstance(email, str):
        return None
    match = NETID_EMAIL_PATTERN.fullmatch(email.strip().casefold())
    return match.group(1) if match else None


def evaluate_submission(payload: Any, rule: AssignmentRule) -> str:
    """Normalize one submission without reading any free-form output text."""
    if not isinstance(payload, dict):
        raise GradescopeSchemaError("submission properties must be an object")
    submission = payload.get("assignment_submission")
    if not isinstance(submission, dict) or not isinstance(submission.get("status"), str):
        raise GradescopeSchemaError("assignment_submission.status is missing")
    submission_status = submission["status"]
    known_statuses = {PROCESSED_SUBMISSION_STATUS} | PENDING_SUBMISSION_STATUSES | FAILED_SUBMISSION_STATUSES
    if submission_status not in known_statuses:
        raise GradescopeSchemaError(f"unknown assignment submission status: {submission_status!r}")
    if "autograder_results" not in payload:
        raise GradescopeSchemaError("autograder_results field is missing")
    results = payload["autograder_results"]
    if results is None:
        return "pending" if submission_status in PENDING_SUBMISSION_STATUSES else "error"
    if not isinstance(results, dict):
        raise GradescopeSchemaError("autograder_results must be an object")
    if "error_code" not in results:
        raise GradescopeSchemaError("autograder_results.error_code is missing")
    if results.get("error_code") not in (None, "", 0, False):
        return "error"
    if submission_status in PENDING_SUBMISSION_STATUSES:
        return "pending"
    if submission_status in FAILED_SUBMISSION_STATUSES:
        return "error"

    tests = results.get("tests")
    if not isinstance(tests, list):
        raise GradescopeSchemaError("autograder_results.tests must be a list")
    if len(tests) != rule.expected_test_count:
        return "contract_mismatch"
    total = _decimal(results.get("score"), field="autograder_results.score")
    maxima: list[Decimal] = []
    scores: list[Decimal] = []
    for index, test in enumerate(tests):
        if not isinstance(test, dict):
            raise GradescopeSchemaError(f"autograder test {index} must be an object")
        score = _decimal(test.get("score"), field=f"autograder test {index} score")
        maximum = _decimal(test.get("max_score"), field=f"autograder test {index} max_score")
        if maximum < 0 or score < 0 or score > maximum:
            raise GradescopeSchemaError(f"autograder test {index} has an invalid score range")
        scores.append(score)
        maxima.append(maximum)
    if tuple(maxima) != rule.expected_test_maxima:
        return "contract_mismatch"
    if total < 0 or total > rule.expected_score:
        raise GradescopeSchemaError("autograder_results.score is outside the configured range")
    if total != sum(scores, Decimal(0)):
        raise GradescopeSchemaError("autograder aggregate score does not equal the test-score sum")
    return "passed" if total == rule.expected_score and scores == maxima else "failed"


def aggregate_status(statuses: Iterable[str]) -> str:
    """Apply pass-any-submission semantics without combining individual tests."""
    values = list(statuses)
    internal_statuses = (STATUSES - {"not_submitted"}) | {"contract_mismatch"}
    if any(value not in internal_statuses for value in values):
        raise ValueError("unknown submission status")
    if "passed" in values:
        return "passed"
    if "pending" in values:
        return "pending"
    if "failed" in values or "contract_mismatch" in values:
        return "failed"
    if "error" in values:
        return "error"
    return "not_submitted"


def _normalize_members(
    members: Iterable[MemberRef], config: AdapterConfig
) -> tuple[dict[str, MemberRef], int]:
    by_netid: dict[str, MemberRef] = {}
    unmatched = 0
    known_roles = config.student_role_values | config.non_student_role_values
    for member in members:
        if member.role not in known_roles:
            raise GradescopeSchemaError(f"unknown Gradescope roster role value: {member.role!r}")
        if member.role in config.non_student_role_values:
            continue
        netid = netid_from_email(member.email)
        if netid is None:
            unmatched += 1
            continue
        if netid in by_netid:
            raise GradescopeSchemaError(f"duplicate Cornell NetID in Gradescope roster: {netid}")
        by_netid[netid] = member
    if len(by_netid) < config.minimum_roster_members:
        raise GradescopeSchemaError("Gradescope canonical student roster fell below the configured minimum")
    if len(by_netid) > config.maximum_roster_members:
        raise GradescopeSchemaError("Gradescope canonical student roster exceeded the configured maximum")
    return by_netid, unmatched


def build_snapshot(
    source: GradescopeSource,
    config: AdapterConfig,
    *,
    generated_at: str | None = None,
    only_netid: str | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """Read and normalize a complete snapshot in memory before any write."""
    members, unmatched = _normalize_members(source.list_members(), config)
    if only_netid is not None:
        normalized = only_netid.strip().casefold()
        if not re.fullmatch(r"[a-z]{2,3}[0-9]+", normalized):
            raise ValueError("only_netid is invalid")
        if normalized not in members:
            raise ValueError("requested NetID is not in the Gradescope roster")
        members = {normalized: members[normalized]}

    if generated_at is None:
        generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    try:
        parsed = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError
    except (AttributeError, ValueError) as error:
        raise ValueError("generated_at must be an ISO-8601 timestamp with timezone") from error

    students: list[dict[str, Any]] = []
    contract_matches = {rule.assignment_id: 0 for rule in config.assignments}
    contract_mismatches = {rule.assignment_id: 0 for rule in config.assignments}
    total_members = len(members)
    for member_index, (netid, member) in enumerate(sorted(members.items()), start=1):
        results: list[dict[str, Any]] = []
        for rule in config.assignments:
            batch = source.submissions(member.member_id, rule.assignment_id)
            statuses: list[str] = []
            checked = 0
            for payload in batch.payloads:
                checked += 1
                status = evaluate_submission(payload, rule)
                statuses.append(status)
                if status == "contract_mismatch":
                    contract_mismatches[rule.assignment_id] += 1
                elif status in {"passed", "failed"}:
                    contract_matches[rule.assignment_id] += 1
                if status == "passed":
                    break
            status = aggregate_status(statuses)
            results.append({
                "opportunity_id": rule.opportunity_id,
                "status": status,
                "pass_evidence": "current_history" if status == "passed" else None,
                "submissions_observed": batch.observed,
                "submissions_checked": checked,
            })
        students.append({"netid": netid, "autograders": results})
        if progress is not None:
            progress(member_index, total_members)

    drifted = [
        assignment_id
        for assignment_id, mismatches in contract_mismatches.items()
        if mismatches and contract_matches[assignment_id] == 0
    ]
    if drifted:
        raise GradescopeSchemaError(
            "configured Lab autograder contract matched no processed submissions"
        )

    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "source": SOURCE_NAME,
        "course_id": config.course_id,
        "generated_at": generated_at,
        "assignments": [
            {
                "assignment_id": rule.assignment_id,
                "opportunity_id": rule.opportunity_id,
                "contract_version": rule.contract_version,
                "expected_score": str(rule.expected_score),
                "expected_test_count": rule.expected_test_count,
                "expected_test_maxima": [str(item) for item in rule.expected_test_maxima],
                "title_mapping_override": rule.title_mapping_override,
            }
            for rule in config.assignments
        ],
        "students": students,
        "unmatched_members": unmatched,
    }
    errors = validate_snapshot(snapshot)
    if errors:
        raise GradescopeSchemaError("invalid normalized snapshot: " + "; ".join(errors))
    return snapshot


def validate_snapshot(snapshot: Any) -> list[str]:
    """Validate normalized output without raising on hostile JSON types."""
    errors: list[str] = []
    expected = {
        "schema_version", "source", "course_id", "generated_at",
        "assignments", "students", "unmatched_members",
    }
    if not isinstance(snapshot, dict) or set(snapshot) != expected:
        return ["snapshot fields do not match schema"]
    if snapshot.get("schema_version") != SCHEMA_VERSION or snapshot.get("source") != SOURCE_NAME:
        errors.append("snapshot version or source is invalid")
    course_id = snapshot.get("course_id")
    if not isinstance(course_id, int) or isinstance(course_id, bool) or course_id <= 0:
        errors.append("course_id is invalid")
    generated_at = snapshot.get("generated_at")
    try:
        if not isinstance(generated_at, str):
            raise ValueError
        timestamp = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            errors.append("generated_at has no timezone")
    except ValueError:
        errors.append("generated_at is invalid")

    assignments = snapshot.get("assignments")
    assignment_opportunities: set[str] = set()
    if not isinstance(assignments, list) or not assignments:
        errors.append("assignments must be a nonempty list")
    else:
        assignment_ids: set[int] = set()
        assignment_fields = {
            "assignment_id", "opportunity_id", "contract_version",
            "expected_score", "expected_test_count", "expected_test_maxima",
            "title_mapping_override",
        }
        for item in assignments:
            if not isinstance(item, dict) or set(item) != assignment_fields:
                errors.append("an assignment is malformed")
                continue
            assignment_id = item["assignment_id"]
            if not isinstance(assignment_id, int) or isinstance(assignment_id, bool) or assignment_id <= 0:
                errors.append("assignment_id is invalid")
            elif assignment_id in assignment_ids:
                errors.append("duplicate assignment_id")
            else:
                assignment_ids.add(assignment_id)
            opportunity = item["opportunity_id"]
            if not isinstance(opportunity, str) or not re.fullmatch(r"[a-z][a-z0-9-]{1,63}", opportunity):
                errors.append("opportunity_id is invalid")
            elif opportunity in assignment_opportunities:
                errors.append("duplicate opportunity_id")
            else:
                assignment_opportunities.add(opportunity)
            contract = item["contract_version"]
            if not isinstance(contract, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}", contract):
                errors.append("contract_version is invalid")
            if not isinstance(item["title_mapping_override"], bool):
                errors.append("title_mapping_override is invalid")
            try:
                expected_score = _decimal(item["expected_score"], field="expected_score")
                if expected_score <= 0:
                    errors.append("expected_score is invalid")
            except GradescopeSchemaError:
                expected_score = None
                errors.append("expected_score is invalid")
            count = item["expected_test_count"]
            maxima_raw = item["expected_test_maxima"]
            if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
                errors.append("expected_test_count is invalid")
            if not isinstance(maxima_raw, list) or not isinstance(count, int) or len(maxima_raw) != count:
                errors.append("expected_test_maxima is invalid")
            else:
                try:
                    maxima = [_decimal(value, field="expected_test_maxima") for value in maxima_raw]
                    if any(value < 0 for value in maxima) or expected_score is None or sum(maxima, Decimal(0)) != expected_score:
                        errors.append("expected_test_maxima is invalid")
                except GradescopeSchemaError:
                    errors.append("expected_test_maxima is invalid")

    students = snapshot.get("students")
    netids: set[str] = set()
    if not isinstance(students, list) or not students:
        errors.append("students must be a nonempty list")
    else:
        for student in students:
            if not isinstance(student, dict) or set(student) != {"netid", "autograders"}:
                errors.append("a student is malformed")
                continue
            netid = student["netid"]
            if not isinstance(netid, str) or not re.fullmatch(r"[a-z]{2,3}[0-9]+", netid):
                errors.append("a student NetID is invalid")
            elif netid in netids:
                errors.append("duplicate student NetID")
            else:
                netids.add(netid)
            results = student["autograders"]
            if not isinstance(results, list) or len(results) != len(assignment_opportunities):
                errors.append("student autograders do not match assignments")
                continue
            found: set[str] = set()
            for result in results:
                result_fields = {
                    "opportunity_id", "status", "pass_evidence",
                    "submissions_observed", "submissions_checked",
                }
                if not isinstance(result, dict) or set(result) != result_fields:
                    errors.append("an autograder result is malformed")
                    continue
                opportunity = result["opportunity_id"]
                if not isinstance(opportunity, str):
                    errors.append("autograder opportunity_id is invalid")
                elif opportunity in found:
                    errors.append("duplicate student opportunity_id")
                else:
                    found.add(opportunity)
                status = result["status"]
                if not isinstance(status, str) or status not in STATUSES:
                    errors.append("an autograder status is invalid")
                evidence = result["pass_evidence"]
                if status == "passed":
                    if evidence not in {"current_history", "previous_snapshot"}:
                        errors.append("passed result has invalid evidence")
                elif evidence is not None:
                    errors.append("non-passed result cannot have pass evidence")
                observed = result["submissions_observed"]
                checked = result["submissions_checked"]
                if (
                    not isinstance(observed, int) or isinstance(observed, bool)
                    or not isinstance(checked, int) or isinstance(checked, bool)
                    or observed < 0 or checked < 0 or checked > observed
                ):
                    errors.append("submission counts are invalid")
            if found != assignment_opportunities:
                errors.append("student opportunity IDs do not match assignments")
    unmatched = snapshot.get("unmatched_members")
    if not isinstance(unmatched, int) or isinstance(unmatched, bool) or unmatched < 0:
        errors.append("unmatched_members is invalid")
    try:
        json.dumps(snapshot, allow_nan=False)
    except (TypeError, ValueError):
        errors.append("snapshot is not finite JSON")
    return errors


def carry_forward_verified_passes(
    current: dict[str, Any], previous: dict[str, Any]
) -> dict[str, Any]:
    """Preserve proven passes when the evaluation contract is unchanged.

    This guards the "ever passed" rule against a later truncated or reordered
    private history response. Configuration changes require explicit migration.
    """
    current_errors = validate_snapshot(current)
    previous_errors = validate_snapshot(previous)
    if current_errors or previous_errors:
        raise ValueError("current and previous snapshots must both be valid")
    if current["course_id"] != previous["course_id"] or current["assignments"] != previous["assignments"]:
        raise ValueError("cannot carry pass evidence across a changed course or assignment contract")

    # Google Sheets is the authoritative dashboard roster. Students may be
    # removed from Gradescope after dropping the class; absent students are not
    # copied into the new snapshot and receive not_found during the merge.
    merged = json.loads(json.dumps(current, allow_nan=False))
    prior = {
        (student["netid"], result["opportunity_id"]): result
        for student in previous["students"]
        for result in student["autograders"]
    }
    for student in merged["students"]:
        for result in student["autograders"]:
            old = prior.get((student["netid"], result["opportunity_id"]))
            if old and old["status"] == "passed" and result["status"] != "passed":
                result["status"] = "passed"
                result["pass_evidence"] = "previous_snapshot"
    errors = validate_snapshot(merged)
    if errors:
        raise ValueError("carried snapshot is invalid: " + "; ".join(errors))
    return merged


def write_snapshot_atomic(snapshot: dict[str, Any], output_path: str | Path) -> Path:
    """Write mode-600 JSON atomically; invalid input never replaces prior output."""
    errors = validate_snapshot(snapshot)
    if errors:
        raise ValueError("invalid Gradescope snapshot: " + "; ".join(errors))
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(snapshot, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    fd, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory_fd = os.open(output.parent, directory_flags)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return output
    finally:
        if temporary.exists():
            temporary.unlink()


class PrivateWebGradescopeSource:
    """Pinned read-only transport over Gradescope's private web endpoints."""

    def __init__(self, email: str, password: str, config: AdapterConfig):
        if not email or not password:
            raise ValueError("Gradescope email and password are required")
        try:
            from bs4 import BeautifulSoup
            from gradescope import Course, Gradescope, Role
        except ImportError as error:
            raise RuntimeError("install requirements.txt to enable Gradescope access") from error

        self._soup_type = BeautifulSoup
        self.config = config
        self._last_request_at: float | None = None
        self._request_count = 0
        self._gradebook_cache: dict[str, list[dict[str, Any]]] = {}
        self._client = Gradescope(auto_login=False, verbose=False)
        self._login_in_progress = True
        original_request = self._client.session.request
        timeout = config.timeout_seconds

        def one_request(method: str, url: str, **kwargs: Any):
            method = method.upper()
            self._validate_same_origin(url)
            if self._login_in_progress:
                if method not in {"GET", "HEAD", "POST"}:
                    raise GradescopeTransportError("unsupported HTTP method during login")
                if method == "POST" and urlparse(url).path != "/login":
                    raise GradescopeTransportError("login POST targeted an unexpected path")
            elif method not in {"GET", "HEAD"}:
                raise GradescopeTransportError("Gradescope adapter is read-only after login")

            retryable = method in {"GET", "HEAD"}
            for attempt in range(3):
                if self._request_count >= self.config.maximum_requests:
                    raise GradescopeTransportError("Gradescope request budget exceeded")
                self._pause()
                self._request_count += 1
                request_options = dict(kwargs)
                request_options["allow_redirects"] = False
                request_options["stream"] = True
                request_options["timeout"] = timeout
                try:
                    response = original_request(method, url, **request_options)
                except requests.RequestException as error:
                    self._last_request_at = time.monotonic()
                    if retryable and attempt < 2:
                        time.sleep(0.5 * (2**attempt))
                        continue
                    raise GradescopeTransportError("Gradescope network request failed") from error
                self._last_request_at = time.monotonic()
                if response.status_code in {429, 500, 502, 503, 504} and retryable and attempt < 2:
                    retry_after = response.headers.get("Retry-After", "")
                    delay = float(retry_after) if retry_after.isdigit() else 0.5 * (2**attempt)
                    response.close()
                    time.sleep(min(delay, 30.0))
                    continue
                return response
            raise GradescopeTransportError("Gradescope retry budget exhausted")

        def read_limited(response):
            declared = response.headers.get("Content-Length")
            if declared and declared.isdigit() and int(declared) > self.config.maximum_response_bytes:
                response.close()
                raise GradescopeTransportError("Gradescope response exceeded the configured size limit")
            content = bytearray()
            try:
                for chunk in response.iter_content(chunk_size=65_536):
                    content.extend(chunk)
                    if len(content) > self.config.maximum_response_bytes:
                        raise GradescopeTransportError("Gradescope response exceeded the configured size limit")
            finally:
                response.close()
            response._content = bytes(content)
            response._content_consumed = True
            return response

        def request_with_safety(method: str, url: str, **kwargs: Any):
            current_method = method.upper()
            current_url = url
            options = dict(kwargs)
            options.pop("allow_redirects", None)
            options.pop("stream", None)
            history = []
            for redirect_count in range(4):
                response = one_request(current_method, current_url, **options)
                self._validate_same_origin(response.url)
                if response.status_code not in {301, 302, 303, 307, 308}:
                    response.history = history
                    return read_limited(response)
                location = response.headers.get("Location")
                if not location or redirect_count == 3:
                    response.close()
                    raise GradescopeTransportError("Gradescope redirect was missing or exceeded the limit")
                next_url = urljoin(current_url, location)
                self._validate_same_origin(next_url)
                history.append(response)
                response.close()
                if response.status_code in {301, 302, 303} and current_method not in {"GET", "HEAD"}:
                    current_method = "GET"
                    for field in ("data", "json", "files"):
                        options.pop(field, None)
                current_url = next_url
            raise GradescopeTransportError("Gradescope redirect limit exceeded")

        self._client.session.request = request_with_safety
        prior_disable = logging.root.manager.disable
        logging.disable(max(prior_disable, logging.INFO))
        try:
            logged_in = self._client.login(email, password)
        except Exception as error:
            raise GradescopeTransportError("Gradescope login request failed") from error
        finally:
            self._login_in_progress = False
            logging.disable(prior_disable)
            self._client.username = None
            self._client.password = None
        if not logged_in:
            raise GradescopeTransportError("Gradescope login was rejected")

        self._course = Course(config.course_id, f"/courses/{config.course_id}", Role.INSTRUCTOR, "", "", "")
        try:
            assignments = self._client.get_assignments(self._course)
        except Exception as error:
            raise GradescopeTransportError("could not read the allowlisted Gradescope course") from error
        available: dict[int, Any] = {}
        for item in assignments:
            assignment_id = getattr(item, "assignment_id", None)
            title = getattr(item, "title", None)
            if (
                not isinstance(assignment_id, int)
                or isinstance(assignment_id, bool)
                or assignment_id <= 0
                or not isinstance(title, str)
                or not title.strip()
            ):
                raise GradescopeSchemaError("Gradescope assignment discovery returned malformed metadata")
            if assignment_id in available:
                raise GradescopeSchemaError("Gradescope assignment discovery returned a duplicate ID")
            available[assignment_id] = item
        missing = [rule.assignment_id for rule in config.assignments if rule.assignment_id not in available]
        if missing:
            raise GradescopeSchemaError("configured assignment IDs were not found in the allowlisted course")
        for rule in config.assignments:
            assignment = available[rule.assignment_id]
            try:
                inferred = opportunity_from_assignment_title(assignment.title)
            except ValueError as error:
                if not rule.title_mapping_override:
                    raise GradescopeSchemaError(str(error)) from error
                inferred = rule.opportunity_id
            if inferred is None:
                raise GradescopeSchemaError("configured Gradescope assignment is not a Lab assignment")
            if inferred != rule.opportunity_id and not rule.title_mapping_override:
                raise GradescopeSchemaError(
                    "Gradescope assignment title maps to a different Google Sheet opportunity"
                )

        self._exam_assignment = None
        if config.exam is not None:
            exam_assignment = available.get(config.exam.assignment_id)
            if exam_assignment is None:
                # Exam data is optional while the rubric is being finalized.
                # The caller converts this condition to not-graded checkmarks.
                return
            if assignment_title_matches(exam_assignment.title, config.exam.title):
                self._exam_assignment = exam_assignment

    @staticmethod
    def _validate_same_origin(url: str) -> None:
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "www.gradescope.com"
            or parsed.port not in (None, 443)
            or parsed.username
            or parsed.password
            or parsed.fragment
        ):
            raise GradescopeTransportError("Gradescope request or redirect left the allowlisted origin")

    def _pause(self) -> None:
        if self._last_request_at is None:
            return
        remaining = self.config.minimum_request_interval_seconds - (time.monotonic() - self._last_request_at)
        if remaining > 0:
            time.sleep(remaining)

    def _get(self, url: str, *, content_type: str):
        try:
            response = self._client.session.get(url)
        except GradescopeAdapterError:
            raise
        except Exception as error:
            raise GradescopeTransportError("Gradescope GET request failed") from error
        if response.status_code != 200:
            raise GradescopeTransportError(f"Gradescope GET request failed ({response.status_code})")
        actual_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().casefold()
        if actual_type != content_type:
            raise GradescopeSchemaError(
                f"Gradescope response content type changed; expected {content_type}"
            )
        return response

    def exam_scores_csv(self) -> str:
        """Fetch the allowlisted Exam 1 score export through the safe session."""
        if self.config.exam is None or self._exam_assignment is None:
            raise GradescopeSchemaError("configured Exam 1 is not available yet")
        try:
            url = self._exam_assignment.get_grades_url()
        except Exception as error:
            raise GradescopeSchemaError("Exam 1 grade-export URL is unavailable") from error
        response = self._get(url, content_type="text/csv")
        try:
            return response.content.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise GradescopeSchemaError("Exam 1 grade export is not UTF-8") from error

    def list_members(self) -> list[MemberRef]:
        try:
            members = self._client.get_members(self._course)
        except Exception as error:
            raise GradescopeSchemaError("Gradescope roster response could not be parsed") from error
        result: list[MemberRef] = []
        for member in members:
            member_id = str(member.member_id)
            role = str(member.role)
            if not member_id.isdigit() or not isinstance(member.email, str) or not role:
                raise GradescopeSchemaError("Gradescope roster member is malformed")
            result.append(MemberRef(member_id, member.email, role))
        student_count = sum(member.role in self.config.student_role_values for member in result)
        unknown_roles = {member.role for member in result} - self.config.student_role_values - self.config.non_student_role_values
        if unknown_roles:
            raise GradescopeSchemaError("Gradescope roster contains an unknown role value")
        if student_count < self.config.minimum_roster_members:
            raise GradescopeSchemaError("Gradescope student roster fell below the configured member minimum")
        if student_count > self.config.maximum_roster_members:
            raise GradescopeSchemaError("Gradescope roster exceeded the configured member limit")
        return result

    def _gradebook(self, member_id: str) -> list[dict[str, Any]]:
        if member_id in self._gradebook_cache:
            return self._gradebook_cache[member_id]
        response = self._get(
            f"{BASE_URL}/courses/{self.config.course_id}/gradebook.json?user_id={member_id}",
            content_type="application/json",
        )
        try:
            data = response.json()
        except (TypeError, ValueError) as error:
            raise GradescopeSchemaError("Gradescope gradebook was not JSON") from error
        if not isinstance(data, list):
            raise GradescopeSchemaError("Gradescope gradebook must be a list")
        self._gradebook_cache[member_id] = data
        return data

    def _submission_url(self, raw_path: str, assignment_id: int) -> str:
        if not raw_path.startswith("/") or raw_path.startswith("//"):
            raise GradescopeSchemaError("submission URL must be a same-site absolute path")
        parsed = urlparse(raw_path)
        expected = re.fullmatch(
            rf"/courses/{self.config.course_id}/assignments/{assignment_id}/submissions/[0-9]+",
            parsed.path,
        )
        if not expected or parsed.query or parsed.fragment or "%" in parsed.path:
            raise GradescopeSchemaError("submission URL is outside the configured course or assignment")
        url = urljoin(BASE_URL, raw_path)
        self._validate_same_origin(url)
        return url

    def _submission_urls(self, member_id: str, assignment_id: int) -> list[str]:
        gradebook = self._gradebook(member_id)
        matching = [
            item.get("assignment")
            for item in gradebook
            if isinstance(item, dict)
            and isinstance(item.get("assignment"), dict)
            and item["assignment"].get("id") == assignment_id
        ]
        if len(matching) > 1:
            raise GradescopeSchemaError("gradebook assignment entry is duplicated")
        if not matching:
            return []
        submission = matching[0].get("submission")
        if submission is None:
            return []
        if not isinstance(submission, dict) or not isinstance(submission.get("url"), str):
            raise GradescopeSchemaError("active submission URL is malformed")
        active = self._submission_url(submission["url"], assignment_id)
        history_response = self._get(active + HISTORY_SUFFIX, content_type="application/json")
        try:
            history_document = history_response.json()
        except (TypeError, ValueError) as error:
            raise GradescopeSchemaError("submission history was not valid JSON") from error
        if not isinstance(history_document, dict) or set(history_document) != {"past_submissions"}:
            raise GradescopeSchemaError("submission history fields changed or indicate unsupported pagination")
        history = history_document["past_submissions"]
        if not isinstance(history, list):
            raise GradescopeSchemaError("past_submissions must be a list")
        urls = [active]
        for item in history:
            if not isinstance(item, dict) or not isinstance(item.get("show_path"), str):
                raise GradescopeSchemaError("a submission-history entry is malformed")
            urls.append(self._submission_url(item["show_path"], assignment_id))
        unique = list(dict.fromkeys(urls))
        if len(unique) > self.config.maximum_submissions_per_student:
            raise GradescopeSchemaError("submission history exceeded the configured limit")
        return unique

    def _payloads(self, urls: list[str]) -> Iterator[dict[str, Any]]:
        for url in urls:
            response = self._get(url, content_type="text/html")
            yield extract_submission_payload(response.text)

    def submissions(self, member_id: str, assignment_id: int) -> SubmissionBatch:
        if assignment_id not in {rule.assignment_id for rule in self.config.assignments}:
            raise GradescopeSchemaError("attempted to access a non-allowlisted assignment")
        urls = self._submission_urls(member_id, assignment_id)
        return SubmissionBatch(len(urls), self._payloads(urls))
