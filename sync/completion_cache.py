"""Private positive-only completion cache.

This module deliberately stores only verified Lab passes and finalized Exam
question completions.  It does not store scores or source-system identifiers.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Any, TypeAlias

from .checkoff_mappings import COLUMN_MAPPINGS, LAB_MAPPING_VERSION, OPPORTUNITY_IDS
from .gradescope_exam import EXAM_MAPPING_VERSION, EXAM_OPPORTUNITIES

CompletionCache: TypeAlias = dict[str, Any]

SCHEMA_VERSION = 1
_NETID = re.compile(r"[a-z]{2,3}[0-9]+\Z")
_IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}\Z")
_FINGERPRINT = re.compile(r"sha256:[0-9a-f]{64}\Z")
_MAX_FILE_BYTES = 16_000_000
_MAX_ENTRIES = 100_000

_TOP_FIELDS = {
    "schema_version", "course_id", "written_at", "lab_contracts", "lab_passes",
    "exam_contract", "exam_completions", "google", "exam_export",
}
_LAB_CONTRACT_FIELDS = {
    "assignment_id", "opportunity_id", "contract_version", "expected_score",
    "expected_test_count", "expected_test_maxima", "title_mapping_override",
    "title_mapping_version",
}
_EXAM_CONTRACT_FIELDS = {
    "assignment_id", "title", "rubric_version", "rubric_finalized",
    "mapping_version", "expected_question_count", "expected_question_score",
    "earn_threshold",
}


def _decimal_text(value: object) -> str:
    """Return a finite Decimal in a single, non-exponent canonical form."""
    if isinstance(value, bool):
        raise ValueError("boolean is not a decimal")
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError("invalid decimal") from error
    if not number.is_finite():
        raise ValueError("decimal must be finite")
    if number == 0:
        return "0"
    result = format(number, "f")
    if "." in result:
        result = result.rstrip("0").rstrip(".")
    return result


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _fingerprint(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value)).hexdigest()


def _lab_mapping(opportunity_id: str) -> list[dict[str, str]]:
    rows = [
        {"column": column, "standard_key": mapping[0], "label": mapping[2]}
        for column, mapping in COLUMN_MAPPINGS.items()
        if mapping[1] == opportunity_id
    ]
    return sorted(rows, key=lambda row: row["column"])


def _exam_mapping() -> list[dict[str, object]]:
    return [
        {
            "id": item["id"], "question": item["question"],
            "standard_key": item["standard_key"], "label": item["label"],
            "kind": item["kind"],
        }
        for item in EXAM_OPPORTUNITIES
    ]


def lab_contract(config: object, rule: object) -> dict[str, object]:
    """Build the normalized, non-secret Lab contract stored in the cache."""
    del config  # Kept in the public API because future mappings can be course-specific.
    contract = {
        "assignment_id": getattr(rule, "assignment_id"),
        "opportunity_id": getattr(rule, "opportunity_id"),
        "contract_version": getattr(rule, "contract_version"),
        "expected_score": _decimal_text(getattr(rule, "expected_score")),
        "expected_test_count": getattr(rule, "expected_test_count"),
        "expected_test_maxima": [
            _decimal_text(value) for value in getattr(rule, "expected_test_maxima")
        ],
        "title_mapping_override": getattr(rule, "title_mapping_override", False),
        "title_mapping_version": LAB_MAPPING_VERSION,
    }
    errors: list[str] = []
    _validate_lab_contract(contract, errors, "lab contract")
    if errors:
        raise ValueError("; ".join(errors))
    return contract


def lab_contract_fingerprint(config: object, rule: object) -> str:
    contract = lab_contract(config, rule)
    payload = {"contract": contract, "effective_mapping": _lab_mapping(str(contract["opportunity_id"]))}
    return _fingerprint(payload)


def exam_contract(config: object) -> dict[str, object]:
    """Build the Exam contract without changing its human-facing title."""
    rule = getattr(config, "exam", None)
    if rule is None:
        raise ValueError("Exam configuration is required")
    contract = {
        "assignment_id": getattr(rule, "assignment_id"),
        "title": getattr(rule, "title"),
        # Legacy configs are explicitly unfinalized and therefore never reusable.
        "rubric_version": getattr(rule, "rubric_version", "legacy-unfinalized"),
        "rubric_finalized": getattr(rule, "rubric_finalized", False),
        "mapping_version": EXAM_MAPPING_VERSION,
        "expected_question_count": getattr(rule, "expected_question_count"),
        "expected_question_score": _decimal_text(getattr(rule, "expected_question_score")),
        "earn_threshold": _decimal_text(getattr(rule, "earn_threshold")),
    }
    errors: list[str] = []
    _validate_exam_contract(contract, errors, "exam contract")
    if errors:
        raise ValueError("; ".join(errors))
    return contract


def exam_contract_fingerprint(config: object) -> str:
    contract = exam_contract(config)
    return _fingerprint({"contract": contract, "effective_mapping": _exam_mapping()})


def _exact_dict(value: object, fields: set[str], errors: list[str], where: str) -> bool:
    if not isinstance(value, dict):
        errors.append(f"{where} must be an object")
        return False
    if set(value) != fields:
        errors.append(f"{where} fields do not match the schema")
        return False
    return True


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _canonical_decimal(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return value == _decimal_text(value)
    except ValueError:
        return False


def _parsed_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _timestamp(value: object) -> bool:
    return _parsed_timestamp(value) is not None


def _validate_lab_contract(value: object, errors: list[str], where: str) -> None:
    if not _exact_dict(value, _LAB_CONTRACT_FIELDS, errors, where):
        return
    assert isinstance(value, dict)
    if not _positive_int(value["assignment_id"]): errors.append(f"{where}.assignment_id is invalid")
    if value["opportunity_id"] not in OPPORTUNITY_IDS: errors.append(f"{where}.opportunity_id is unknown")
    if not isinstance(value["contract_version"], str) or not _IDENTIFIER.fullmatch(value["contract_version"]): errors.append(f"{where}.contract_version is invalid")
    if not _canonical_decimal(value["expected_score"]): errors.append(f"{where}.expected_score is not canonical")
    if not _positive_int(value["expected_test_count"]): errors.append(f"{where}.expected_test_count is invalid")
    maxima = value["expected_test_maxima"]
    if not isinstance(maxima, list) or len(maxima) != value["expected_test_count"] or not all(_canonical_decimal(item) for item in maxima): errors.append(f"{where}.expected_test_maxima is invalid")
    if type(value["title_mapping_override"]) is not bool: errors.append(f"{where}.title_mapping_override must be boolean")
    if value["title_mapping_version"] != LAB_MAPPING_VERSION: errors.append(f"{where}.title_mapping_version is incompatible")


def _validate_exam_contract(value: object, errors: list[str], where: str) -> None:
    if not _exact_dict(value, _EXAM_CONTRACT_FIELDS, errors, where):
        return
    assert isinstance(value, dict)
    if not _positive_int(value["assignment_id"]): errors.append(f"{where}.assignment_id is invalid")
    title = value["title"]
    if not isinstance(title, str) or not title or len(title) > 128 or any(c in title for c in "<>@\r\n"): errors.append(f"{where}.title is invalid")
    if not isinstance(value["rubric_version"], str) or not _IDENTIFIER.fullmatch(value["rubric_version"]): errors.append(f"{where}.rubric_version is invalid")
    if type(value["rubric_finalized"]) is not bool: errors.append(f"{where}.rubric_finalized must be boolean")
    if value["mapping_version"] != EXAM_MAPPING_VERSION: errors.append(f"{where}.mapping_version is incompatible")
    if value["expected_question_count"] != len(EXAM_OPPORTUNITIES): errors.append(f"{where}.expected_question_count is incompatible")
    for field in ("expected_question_score", "earn_threshold"):
        if not _canonical_decimal(value[field]): errors.append(f"{where}.{field} is not canonical")


def _validate_contract_wrapper(value: object, errors: list[str], where: str, *, exam: bool) -> None:
    if not _exact_dict(value, {"fingerprint", "contract"}, errors, where):
        return
    assert isinstance(value, dict)
    contract = value["contract"]
    if exam:
        _validate_exam_contract(contract, errors, f"{where}.contract")
        if isinstance(contract, dict): expected = _fingerprint({"contract": contract, "effective_mapping": _exam_mapping()})
        else: expected = None
    else:
        _validate_lab_contract(contract, errors, f"{where}.contract")
        if isinstance(contract, dict): expected = _fingerprint({"contract": contract, "effective_mapping": _lab_mapping(str(contract.get("opportunity_id", "")))})
        else: expected = None
    fingerprint = value["fingerprint"]
    if not isinstance(fingerprint, str) or not _FINGERPRINT.fullmatch(fingerprint): errors.append(f"{where}.fingerprint is invalid")
    elif expected is not None and fingerprint != expected: errors.append(f"{where}.fingerprint does not match its contract")


def validate_completion_cache(
    value: object, *, config: object | None = None, now: datetime | None = None
) -> list[str]:
    """Return all cache schema errors.  An empty list means the cache is safe."""
    reference_time = now or datetime.now(timezone.utc)
    if reference_time.tzinfo is None:
        raise ValueError("cache validation time must include a timezone")
    errors: list[str] = []
    if not _exact_dict(value, _TOP_FIELDS, errors, "cache"):
        return errors
    assert isinstance(value, dict)
    if value["schema_version"] != SCHEMA_VERSION: errors.append("cache schema_version is incompatible")
    if not _positive_int(value["course_id"]): errors.append("cache course_id is invalid")
    if config is not None and value["course_id"] != getattr(config, "course_id", None): errors.append("cache course_id does not match configuration")
    written_at = _parsed_timestamp(value["written_at"])
    if written_at is None:
        errors.append("cache written_at is invalid")
    elif written_at > reference_time:
        errors.append("cache written_at is in the future")

    contracts = value["lab_contracts"]
    allowed_labs = set(OPPORTUNITY_IDS)
    if config is not None:
        allowed_labs = {getattr(rule, "opportunity_id", None) for rule in getattr(config, "assignments", ())}
    if not isinstance(contracts, dict): errors.append("cache.lab_contracts must be an object")
    else:
        if len(contracts) > 100: errors.append("cache.lab_contracts is too large")
        for opportunity, wrapper in contracts.items():
            if opportunity not in allowed_labs: errors.append("cache.lab_contracts contains an unknown opportunity")
            _validate_contract_wrapper(wrapper, errors, f"cache.lab_contracts[{opportunity!r}]", exam=False)
            if isinstance(wrapper, dict) and isinstance(wrapper.get("contract"), dict) and wrapper["contract"].get("opportunity_id") != opportunity: errors.append("Lab contract key does not match opportunity_id")

    exam_wrapper = value["exam_contract"]
    if exam_wrapper is not None: _validate_contract_wrapper(exam_wrapper, errors, "cache.exam_contract", exam=True)

    max_roster = getattr(config, "maximum_roster_members", 2_000) if config is not None else 2_000
    max_labs = max(1, len(allowed_labs)) * max_roster
    exam_ids = {item["id"] for item in EXAM_OPPORTUNITIES}
    for field, opportunities, maximum in (
        ("lab_passes", allowed_labs, min(_MAX_ENTRIES, max_labs)),
        ("exam_completions", exam_ids, min(_MAX_ENTRIES, max_roster * len(exam_ids))),
    ):
        entries = value[field]
        if not isinstance(entries, list):
            errors.append(f"cache.{field} must be an array")
            continue
        if len(entries) > maximum: errors.append(f"cache.{field} is too large")
        seen: set[tuple[str, str]] = set()
        for index, entry in enumerate(entries):
            where = f"cache.{field}[{index}]"
            if not _exact_dict(entry, {"netid", "opportunity_id", "verified_at"}, errors, where): continue
            assert isinstance(entry, dict)
            netid, opportunity = entry["netid"], entry["opportunity_id"]
            if not isinstance(netid, str) or not _NETID.fullmatch(netid): errors.append(f"{where}.netid is invalid")
            if opportunity not in opportunities: errors.append(f"{where}.opportunity_id is unknown")
            verified_at = _parsed_timestamp(entry["verified_at"])
            if verified_at is None:
                errors.append(f"{where}.verified_at is invalid")
            elif verified_at > reference_time:
                errors.append(f"{where}.verified_at is in the future")
            key = (netid, opportunity)
            if key in seen: errors.append(f"cache.{field} has a duplicate completion")
            seen.add(key)

    google = value["google"]
    if _exact_dict(google, {"spreadsheet_id", "worksheet_id", "metadata_etag", "values_etag", "worksheet_title", "normalized_records"}, errors, "cache.google"):
        assert isinstance(google, dict)
        spreadsheet = google["spreadsheet_id"]
        if spreadsheet is not None and (not isinstance(spreadsheet, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", spreadsheet)): errors.append("cache.google.spreadsheet_id is invalid")
        if google["worksheet_id"] is not None and not _positive_int(google["worksheet_id"]): errors.append("cache.google.worksheet_id is invalid")
        for field in ("metadata_etag", "values_etag"):
            item = google[field]
            if item is not None and (not isinstance(item, str) or len(item) > 512 or any(ord(c) < 32 for c in item)): errors.append(f"cache.google.{field} is invalid")
        title = google["worksheet_title"]
        if title is not None and (not isinstance(title, str) or len(title) > 200 or any(c in title for c in "<>@\r\n")): errors.append("cache.google.worksheet_title is invalid")
        # Normalized Google records need their own schema/version contract.  Until
        # conditional Sheets support exists, fail closed rather than accept data.
        if google["normalized_records"] is not None: errors.append("cache.google.normalized_records is unsupported")

    export = value["exam_export"]
    if _exact_dict(export, {"etag"}, errors, "cache.exam_export"):
        assert isinstance(export, dict)
        etag = export["etag"]
        if etag is not None and (not isinstance(etag, str) or len(etag) > 512 or any(ord(c) < 32 for c in etag)): errors.append("cache.exam_export.etag is invalid")

    try: _canonical_json(value)
    except (TypeError, ValueError, OverflowError): errors.append("cache is not finite JSON")
    return errors


def load_completion_cache(path: str | Path, *, config: object | None = None) -> CompletionCache | None:
    """Load a complete valid cache, or return ``None`` on any unsafe input."""
    path = Path(path)
    try:
        info = path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_mode & 0o077
            or info.st_size > _MAX_FILE_BYTES
        ):
            return None
        def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, item in pairs:
                if key in result: raise ValueError("duplicate JSON key")
                result[key] = item
            return result
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle, object_pairs_hook=reject_duplicates, parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return None
    if validate_completion_cache(value, config=config):
        return None
    return value


def write_completion_cache_atomic(cache: CompletionCache, path: str | Path) -> Path:
    """Validate and atomically write canonical JSON with mode 0600."""
    errors = validate_completion_cache(cache)
    if errors:
        raise ValueError("invalid completion cache: " + "; ".join(errors))
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = _canonical_json(cache) + b"\n"
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        directory_fd = os.open(target.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try: os.fsync(directory_fd)
        finally: os.close(directory_fd)
    except BaseException:
        if descriptor >= 0: os.close(descriptor)
        try: temporary.unlink()
        except FileNotFoundError: pass
        raise
    return target


def filter_completion_cache(
    cache: CompletionCache, config: object, current_netids: set[str] | frozenset[str]
) -> tuple[frozenset[tuple[str, str]], frozenset[tuple[str, str]]]:
    """Return reusable Lab and finalized-Exam positive keys for the current roster."""
    if validate_completion_cache(cache, config=config):
        return frozenset(), frozenset()
    lab_fingerprints = {getattr(rule, "opportunity_id"): lab_contract_fingerprint(config, rule) for rule in getattr(config, "assignments", ())}
    wrappers = cache["lab_contracts"]
    labs = frozenset(
        (entry["netid"], entry["opportunity_id"])
        for entry in cache["lab_passes"]
        if entry["netid"] in current_netids
        and entry["opportunity_id"] in lab_fingerprints
        and wrappers.get(entry["opportunity_id"], {}).get("fingerprint") == lab_fingerprints[entry["opportunity_id"]]
    )
    exams: frozenset[tuple[str, str]] = frozenset()
    rule = getattr(config, "exam", None)
    wrapper = cache["exam_contract"]
    if rule is not None and getattr(rule, "rubric_finalized", False) and wrapper is not None and wrapper["fingerprint"] == exam_contract_fingerprint(config):
        exams = frozenset((entry["netid"], entry["opportunity_id"]) for entry in cache["exam_completions"] if entry["netid"] in current_netids)
    return labs, exams


def build_completion_cache(
    config: object,
    snapshot: dict[str, Any],
    exam_completions: frozenset[tuple[str, str]],
    *,
    written_at: str | None = None,
) -> CompletionCache:
    """Build the next positive-only cache from validated normalized results."""
    from .gradescope import validate_snapshot

    snapshot_errors = validate_snapshot(snapshot)
    if snapshot_errors:
        raise ValueError("cannot cache an invalid Gradescope snapshot")
    if snapshot.get("course_id") != getattr(config, "course_id", None):
        raise ValueError("snapshot course does not match cache configuration")
    if written_at is None:
        written_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    if not _timestamp(written_at):
        raise ValueError("cache write time is invalid")

    contracts: dict[str, dict[str, object]] = {}
    for rule in sorted(getattr(config, "assignments", ()), key=lambda item: item.assignment_id):
        contract = lab_contract(config, rule)
        contracts[rule.opportunity_id] = {
            "fingerprint": lab_contract_fingerprint(config, rule),
            "contract": contract,
        }
    lab_keys = sorted(
        (student["netid"], result["opportunity_id"])
        for student in snapshot["students"]
        for result in student["autograders"]
        if result["status"] == "passed"
    )
    exam_ids = {item["id"] for item in EXAM_OPPORTUNITIES}
    current_netids = {student["netid"] for student in snapshot["students"]}
    safe_exam = sorted(
        (netid, opportunity)
        for netid, opportunity in exam_completions
        if netid in current_netids and opportunity in exam_ids
    )
    exam_rule = getattr(config, "exam", None)
    exam_wrapper = None
    if exam_rule is not None:
        contract = exam_contract(config)
        exam_wrapper = {
            "fingerprint": exam_contract_fingerprint(config),
            "contract": contract,
        }
    cache: CompletionCache = {
        "schema_version": SCHEMA_VERSION,
        "course_id": getattr(config, "course_id"),
        "written_at": written_at,
        "lab_contracts": contracts,
        "lab_passes": [
            {"netid": netid, "opportunity_id": opportunity, "verified_at": written_at}
            for netid, opportunity in lab_keys
        ],
        "exam_contract": exam_wrapper,
        "exam_completions": [
            {"netid": netid, "opportunity_id": opportunity, "verified_at": written_at}
            for netid, opportunity in safe_exam
        ],
        "google": {
            "spreadsheet_id": None, "worksheet_id": None,
            "metadata_etag": None, "values_etag": None,
            "worksheet_title": None, "normalized_records": None,
        },
        "exam_export": {"etag": None},
    }
    errors = validate_completion_cache(cache, config=config)
    if errors:
        raise ValueError("built completion cache is invalid: " + "; ".join(errors))
    return cache
