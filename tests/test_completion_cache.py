from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from sync.completion_cache import (
    exam_contract,
    exam_contract_fingerprint,
    filter_completion_cache,
    lab_contract,
    lab_contract_fingerprint,
    load_completion_cache,
    validate_completion_cache,
    write_completion_cache_atomic,
)
from sync.gradescope import AdapterConfig, AssignmentRule, ExamRule


NOW = "2025-01-02T03:04:05Z"


def _config(*, finalized: bool = True) -> AdapterConfig:
    rule = AssignmentRule(
        assignment_id=101,
        opportunity_id="lab1-q1-2",
        contract_version="lab1-q1-2-v1",
        expected_score=Decimal("3.0"),
        expected_test_count=2,
        expected_test_maxima=(Decimal("1.0"), Decimal("2.00")),
    )
    # The cache supports both the current adapter and the planned versioned ExamRule.
    exam = SimpleNamespace(
        assignment_id=202,
        title="Exam 1",
        rubric_version="exam1-final-v1",
        rubric_finalized=finalized,
        expected_question_count=6,
        expected_question_score=Decimal("1.0"),
        earn_threshold=Decimal("0.80"),
    )
    return AdapterConfig(course_id=303, assignments=(rule,), maximum_roster_members=10, exam=exam)


def _cache(config: AdapterConfig | None = None) -> dict:
    config = config or _config()
    rule = config.assignments[0]
    lab = lab_contract(config, rule)
    exam = exam_contract(config)
    return {
        "schema_version": 1,
        "course_id": config.course_id,
        "written_at": NOW,
        "lab_contracts": {
            rule.opportunity_id: {
                "fingerprint": lab_contract_fingerprint(config, rule),
                "contract": lab,
            }
        },
        "lab_passes": [
            {"netid": "abc123", "opportunity_id": rule.opportunity_id, "verified_at": NOW}
        ],
        "exam_contract": {
            "fingerprint": exam_contract_fingerprint(config),
            "contract": exam,
        },
        "exam_completions": [
            {"netid": "abc123", "opportunity_id": "exam1-q3", "verified_at": NOW}
        ],
        "google": {
            "spreadsheet_id": None,
            "worksheet_id": None,
            "metadata_etag": None,
            "values_etag": None,
            "worksheet_title": None,
            "normalized_records": None,
        },
        "exam_export": {"etag": None},
    }


def test_valid_cache_round_trip_is_canonical_and_private(tmp_path: Path) -> None:
    config = _config()
    cache = _cache(config)
    path = tmp_path / "completion-cache.json"

    assert validate_completion_cache(cache, config=config) == []
    assert write_completion_cache_atomic(cache, path) == path
    assert load_completion_cache(path, config=config) == cache
    assert os.stat(path).st_mode & 0o777 == 0o600
    expected = json.dumps(cache, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    assert path.read_text(encoding="utf-8") == expected


def test_atomic_failure_preserves_prior_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sync.completion_cache as module

    path = tmp_path / "cache.json"
    path.write_text("prior", encoding="utf-8")
    monkeypatch.setattr(module.os, "replace", lambda *_: (_ for _ in ()).throw(OSError("boom")))
    with pytest.raises(OSError, match="boom"):
        write_completion_cache_atomic(_cache(), path)
    assert path.read_text(encoding="utf-8") == "prior"
    assert not list(tmp_path.glob(".cache.json.*"))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(extra="not allowed"),
        lambda value: value.update(schema_version=2),
        lambda value: value.update(course_id=999),
        lambda value: value.update(written_at="not-a-time"),
        lambda value: value["lab_passes"][0].update(netid="ABC123"),
        lambda value: value["lab_passes"][0].update(opportunity_id="lab99-q1"),
        lambda value: value["lab_passes"].append(deepcopy(value["lab_passes"][0])),
        lambda value: value["lab_contracts"]["lab1-q1-2"]["contract"].update(raw_score=3),
        lambda value: value["exam_completions"][0].update(email="abc123@cornell.edu"),
        lambda value: value["google"].update(normalized_records=[]),
    ],
)
def test_strict_validation_rejects_schema_and_private_data(mutation) -> None:
    config = _config()
    value = _cache(config)
    mutation(value)
    assert validate_completion_cache(value, config=config)


def test_loader_rejects_invalid_json_duplicate_keys_and_nonfinite(tmp_path: Path) -> None:
    path = tmp_path / "cache.json"
    for text in ('{"x":', '{"x":1,"x":2}', '{"x":NaN}'):
        path.write_text(text, encoding="utf-8")
        assert load_completion_cache(path) is None
    assert load_completion_cache(tmp_path / "missing") is None


def test_decimal_contract_is_normalized_and_exam_name_keeps_spaces() -> None:
    config = _config()
    lab = lab_contract(config, config.assignments[0])
    exam = exam_contract(config)
    assert lab["expected_score"] == "3"
    assert lab["expected_test_maxima"] == ["1", "2"]
    assert exam["expected_question_score"] == "1"
    assert exam["earn_threshold"] == "0.8"
    assert exam["title"] == "Exam 1"


def test_fingerprints_are_stable_and_cover_contract_components() -> None:
    config = _config()
    first = lab_contract_fingerprint(config, config.assignments[0])
    equivalent_rule = SimpleNamespace(**{
        "expected_test_maxima": (Decimal("1.00"), Decimal("2")),
        "expected_test_count": 2,
        "expected_score": Decimal("3.000"),
        "contract_version": "lab1-q1-2-v1",
        "opportunity_id": "lab1-q1-2",
        "assignment_id": 101,
        "title_mapping_override": False,
    })
    assert lab_contract_fingerprint(config, equivalent_rule) == first
    for field, changed in (
        ("assignment_id", 102),
        ("contract_version", "lab1-q1-2-v2"),
        ("expected_score", Decimal("4")),
        ("expected_test_count", 1),
        ("title_mapping_override", True),
    ):
        data = vars(equivalent_rule).copy()
        data[field] = changed
        if field == "expected_test_count": data["expected_test_maxima"] = (Decimal("1"),)
        assert lab_contract_fingerprint(config, SimpleNamespace(**data)) != first

    exam_first = exam_contract_fingerprint(config)
    for field, changed in (
        ("assignment_id", 203), ("title", "Exam 1 Final"),
        ("rubric_version", "exam1-final-v2"), ("rubric_finalized", False),
        ("expected_question_score", Decimal("2")), ("earn_threshold", Decimal("0.7")),
    ):
        changed_exam = SimpleNamespace(**vars(config.exam))
        setattr(changed_exam, field, changed)
        changed_config = SimpleNamespace(exam=changed_exam)
        assert exam_contract_fingerprint(changed_config) != exam_first


def test_filter_requires_current_roster_matching_contract_and_finalized_exam() -> None:
    config = _config()
    cache = _cache(config)
    labs, exams = filter_completion_cache(cache, config, {"abc123"})
    assert labs == frozenset({("abc123", "lab1-q1-2")})
    assert exams == frozenset({("abc123", "exam1-q3")})
    assert filter_completion_cache(cache, config, set()) == (frozenset(), frozenset())

    changed_rule = SimpleNamespace(**vars(config.assignments[0]))
    changed_rule.contract_version = "lab1-q1-2-v2"
    changed_config = SimpleNamespace(
        course_id=config.course_id, assignments=(changed_rule,), exam=config.exam,
        maximum_roster_members=10,
    )
    labs, exams = filter_completion_cache(cache, changed_config, {"abc123"})
    assert not labs
    assert exams

    unfinalized = _config(finalized=False)
    # Its own cache is structurally valid, but Exam reuse is deliberately disabled.
    labs, exams = filter_completion_cache(_cache(unfinalized), unfinalized, {"abc123"})
    assert labs
    assert not exams


def test_wrong_course_and_contract_fingerprint_are_rejected() -> None:
    config = _config()
    cache = _cache(config)
    other = SimpleNamespace(course_id=304, assignments=config.assignments, exam=config.exam, maximum_roster_members=10)
    assert any("course_id" in error for error in validate_completion_cache(cache, config=other))
    cache["lab_contracts"]["lab1-q1-2"]["fingerprint"] = "sha256:" + "0" * 64
    assert any("fingerprint" in error for error in validate_completion_cache(cache, config=config))


def test_future_dated_cache_is_rejected():
    config = _config()
    cache = _cache(config)
    cache["written_at"] = "2099-01-01T00:00:00Z"
    assert any("future" in error for error in validate_completion_cache(cache, config=config))


def test_loader_rejects_cache_with_group_or_world_permissions(tmp_path: Path) -> None:
    path = tmp_path / "cache.json"
    write_completion_cache_atomic(_cache(), path)
    path.chmod(0o640)
    assert load_completion_cache(path, config=_config()) is None
