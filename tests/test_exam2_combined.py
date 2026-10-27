"""Canonical Exam 2 marks share schema 6 without publishing source evidence."""
from copy import deepcopy
import json

import pytest

from sync.combined_checkoffs import (
    merge_checkoffs_with_autograders, merge_exam_checkmarks, validate_combined_record,
)
from sync.gradescope_exam import EXAM_OPPORTUNITIES, ExamImport
from sync.gradescope_exam2 import EXAM2_OPPORTUNITIES
from test_combined_checkoffs import google_record, snapshot, find_checkmark


def labs():
    return merge_checkoffs_with_autograders([google_record()], snapshot(), allow_unconfigured=True)


def exam(opportunities=EXAM2_OPPORTUNITIES):
    return ExamImport({"abc123": [{**item, "status": "complete"} for item in opportunities]}, True, "ok")


def merged():
    return merge_exam_checkmarks(labs(), exam(), opportunities=EXAM2_OPPORTUNITIES)[0]


def test_both_exams_share_schema_and_preserve_lab_and_input():
    original = labs()
    before = deepcopy(original)
    exam1 = merge_exam_checkmarks(original, exam(EXAM_OPPORTUNITIES))
    both = merge_exam_checkmarks(exam1, exam(), opportunities=EXAM2_OPPORTUNITIES)[0]
    assert original == before
    assert both["schema_version"] == 6
    assert validate_combined_record(both) == []
    assert find_checkmark(both, "lab1-q1-2")["status"] == "complete"
    assert sum(item["kind"] != "green" for standard in both["standards"] for item in standard["checkmarks"]) == 18
    assert find_checkmark(both, "exam2-q12")["kind"] == "shiny_purple"


def test_q8_runtime_shiny_replaces_the_single_purple_mark():
    imported = exam()
    imported.by_netid["abc123"][7]["kind"] = "shiny_purple"
    record = merge_exam_checkmarks(labs(), imported, opportunities=EXAM2_OPPORTUNITIES)[0]
    marks = [item for standard in record["standards"] for item in standard["checkmarks"] if item["id"] == "exam2-q8"]
    assert len(marks) == 1
    assert marks[0]["kind"] == "shiny_purple"
    assert validate_combined_record(record) == []


@pytest.mark.parametrize("status", ["incomplete", "not_graded"])
def test_q8_shiny_is_only_valid_for_complete_outcomes(status):
    imported = exam()
    imported.by_netid["abc123"][7].update(kind="shiny_purple", status=status)
    with pytest.raises(ValueError, match="mapping"):
        merge_exam_checkmarks(labs(), imported, opportunities=EXAM2_OPPORTUNITIES)
    record = merged()
    mark = find_checkmark(record, "exam2-q8")
    mark.update(kind="shiny_purple", status=status)
    mark["requirements"][0]["status"] = status
    assert validate_combined_record(record)


@pytest.mark.parametrize("field,value", [
    ("kind", "shiny_purple"), ("standard_id", "S6"),
    ("label", "Exam 2 Version 1 · Question 1"), ("question", 2),
    ("status", "passed"),
])
def test_merge_rejects_unapproved_result_mapping(field, value):
    imported = exam()
    imported.by_netid["abc123"][0][field] = value
    with pytest.raises(ValueError):
        merge_exam_checkmarks(labs(), imported, opportunities=EXAM2_OPPORTUNITIES)


def test_merge_rejects_modified_catalog_duplicates_and_wrong_roster():
    modified = tuple({**item, "label": "unreviewed"} for item in EXAM2_OPPORTUNITIES)
    with pytest.raises(ValueError, match="approved catalog"):
        merge_exam_checkmarks(labs(), exam(modified), opportunities=modified)
    imported = exam()
    imported.by_netid["abc123"][0] = deepcopy(imported.by_netid["abc123"][1])
    with pytest.raises(ValueError, match="configured questions"):
        merge_exam_checkmarks(labs(), imported, opportunities=EXAM2_OPPORTUNITIES)
    with pytest.raises(ValueError, match="student set"):
        merge_exam_checkmarks(labs(), ExamImport({}, False, "missing"), opportunities=EXAM2_OPPORTUNITIES)


def test_student_payload_drops_private_import_evidence():
    imported = exam()
    for result in imported.by_netid["abc123"]:
        result.update(raw_score="PRIVATE_SCORE", assignment_id="PRIVATE_SOURCE", version="PRIVATE_VERSION")
    imported = ExamImport(imported.by_netid, True, "PRIVATE_DIAGNOSTIC")
    record = merge_exam_checkmarks(labs(), imported, opportunities=EXAM2_OPPORTUNITIES)[0]
    assert "PRIVATE_" not in json.dumps(record)
    assert validate_combined_record(record) == []
    for standard in record["standards"]:
        for mark in standard["checkmarks"]:
            if mark["id"].startswith("exam2-"):
                assert mark["requirements"][0]["label"] == "Exam 2 question score"
                assert mark["requirements"][0]["details"] == []


@pytest.mark.parametrize("field,value", [
    ("id", "exam2-q99"), ("label", "Exam 2 Version 1"), ("kind", "shiny_purple"),
])
def test_validator_rejects_unapproved_canonical_fields(field, value):
    record = merged()
    find_checkmark(record, "exam2-q1")[field] = value
    assert validate_combined_record(record)


def test_validator_rejects_duplicate_marks_and_private_requirement_details():
    record = merged()
    standard = next(item for item in record["standards"] if item["id"] == "S1")
    standard["checkmarks"].append(deepcopy(find_checkmark(record, "exam2-q1")))
    assert validate_combined_record(record)
    record = merged()
    score = find_checkmark(record, "exam2-q1")["requirements"][0]
    score["details"] = [{"score": 4, "version": 1}]
    assert validate_combined_record(record)
    score["details"] = []
    score["label"] = "Exam 2 Version 1 score 4"
    assert validate_combined_record(record)
