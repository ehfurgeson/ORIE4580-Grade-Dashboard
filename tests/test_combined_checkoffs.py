import json
from pathlib import Path

import pytest

from sync.combined_checkoffs import merge_checkoffs_with_autograders, validate_combined_record
from sync.checkoff_mappings import COLUMN_MAPPINGS, OPPORTUNITY_IDS
from sync.simple_checkoffs import rows_to_simple_records, validate_simple_record
from sync.simple_generate import write_simple_release


NOW = "2026-09-23T18:00:00Z"


def google_record(*, first=True, second=True, third=True, q3=True):
    rows = [{
        "NetID": "abc123",
        "Lab 1 - Q1.3": first,
        "Lab 1 - Q2.3": second,
        "Lab 1 - Q2.4": third,
        "Lab 1 - Q3": q3,
    }]
    return rows_to_simple_records(rows, updated_at=NOW, worksheet="Lab Checkoffs")[0]


def google_q1_only_record():
    rows = [{
        "NetID": "abc123",
        "Lab 1 - Q1.3": True,
        "Lab 1 - Q2.3": True,
        "Lab 1 - Q2.4": True,
    }]
    return rows_to_simple_records(rows, updated_at=NOW, worksheet="Lab Checkoffs")[0]


def snapshot(status="passed", *, include_student=True):
    return {
        "schema_version": 1,
        "source": "gradescope_unofficial_read_only",
        "course_id": 1379687,
        "generated_at": "2026-09-23T18:05:00Z",
        "assignments": [{
            "assignment_id": 8532000,
            "opportunity_id": "lab1-q1-2",
            "contract_version": "lab1-q1-2-v1",
            "expected_score": "3",
            "expected_test_count": 3,
            "expected_test_maxima": ["1", "1", "1"],
            "title_mapping_override": False,
        }],
        "students": ([{
            "netid": "abc123",
            "autograders": [{
                "opportunity_id": "lab1-q1-2",
                "status": status,
                "pass_evidence": "current_history" if status == "passed" else None,
                "submissions_observed": 2,
                "submissions_checked": 2,
            }],
        }] if include_student else [{
            "netid": "xy99",
            "autograders": [{
                "opportunity_id": "lab1-q1-2",
                "status": status,
                "pass_evidence": "current_history" if status == "passed" else None,
                "submissions_observed": 1,
                "submissions_checked": 1,
            }],
        }]),
        "unmatched_members": 0,
    }


def find_checkmark(record, opportunity_id):
    return next(
        checkmark
        for standard in record["standards"]
        for checkmark in standard["checkmarks"]
        if checkmark["id"] == opportunity_id
    )


def test_both_manual_and_autograder_are_required_for_green_checkmark():
    complete = merge_checkoffs_with_autograders(
        [google_record()], snapshot("passed"), allow_unconfigured=True
    )[0]
    checkmark = find_checkmark(complete, "lab1-q1-2")
    assert checkmark["status"] == "complete"
    assert [(item["id"], item["status"]) for item in checkmark["requirements"]] == [
        ("manual", "complete"), ("autograder", "passed")
    ]

    manual_missing = merge_checkoffs_with_autograders(
        [google_record(second=False)], snapshot("passed"), allow_unconfigured=True
    )[0]
    assert find_checkmark(manual_missing, "lab1-q1-2")["status"] == "incomplete"

    autograder_missing = merge_checkoffs_with_autograders(
        [google_record()], snapshot("failed"), allow_unconfigured=True
    )[0]
    assert find_checkmark(autograder_missing, "lab1-q1-2")["status"] == "incomplete"


def test_lab_1_group_keeps_three_sheet_details_under_one_manual_requirement():
    record = merge_checkoffs_with_autograders(
        [google_record()], snapshot(), allow_unconfigured=True
    )[0]
    manual = find_checkmark(record, "lab1-q1-2")["requirements"][0]
    assert manual["label"] == "Manual checkoff"
    assert len(manual["details"]) == 3


def test_unconfigured_opportunity_is_visible_and_never_earned():
    record = merge_checkoffs_with_autograders(
        [google_record()], snapshot(), allow_unconfigured=True
    )[0]
    q3 = find_checkmark(record, "lab1-q3")
    assert q3["requirements"][1]["status"] == "not_configured"
    assert q3["status"] == "incomplete"


def test_strict_merge_rejects_missing_assignment_or_student_mapping():
    with pytest.raises(ValueError, match="missing Gradescope assignment mappings"):
        merge_checkoffs_with_autograders([google_record()], snapshot())
    with pytest.raises(ValueError, match="missing from the Gradescope snapshot"):
        merge_checkoffs_with_autograders(
            [google_q1_only_record()], snapshot(include_student=False), allow_unconfigured=False
        )


def test_combined_schema_validation_and_publisher(tmp_path):
    record = merge_checkoffs_with_autograders(
        [google_record()], snapshot(), allow_unconfigured=True
    )[0]
    assert record["schema_version"] == 3
    assert validate_combined_record(record) == []
    assert validate_simple_record(record) == []
    paths = write_simple_release([record], tmp_path / "students")
    assert len(paths) == 1
    saved = json.loads(paths[0].read_text())
    assert saved["schema_version"] == 3


def test_tampered_combined_status_fails_validation():
    record = merge_checkoffs_with_autograders(
        [google_record()], snapshot(), allow_unconfigured=True
    )[0]
    find_checkmark(record, "lab1-q1-2")["status"] = "incomplete"
    assert any("does not match" in error for error in validate_combined_record(record))


def test_frontend_displays_both_requirement_sources_safely():
    script = Path("static/simple-dashboard.js").read_text()
    assert "Manual checkoff" not in script  # label comes from validated JSON
    assert "Autograder error" in script
    assert "Not connected yet" in script
    assert "innerHTML" not in script


def test_strict_merge_covers_every_configured_lab_opportunity():
    row = {"NetID": "abc123", **{column: True for column in COLUMN_MAPPINGS}}
    record = rows_to_simple_records([row], updated_at=NOW, worksheet="Lab Checkoffs")[0]
    opportunities = sorted(OPPORTUNITY_IDS)
    full_snapshot = {
        "schema_version": 1,
        "source": "gradescope_unofficial_read_only",
        "course_id": 1379687,
        "generated_at": "2026-09-23T18:05:00Z",
        "assignments": [
            {
                "assignment_id": 9000000 + index,
                "opportunity_id": opportunity,
                "contract_version": f"{opportunity}-v1",
                "expected_score": "1",
                "expected_test_count": 1,
                "expected_test_maxima": ["1"],
                "title_mapping_override": False,
            }
            for index, opportunity in enumerate(opportunities)
        ],
        "students": [{
            "netid": "abc123",
            "autograders": [
                {
                    "opportunity_id": opportunity,
                    "status": "passed",
                    "pass_evidence": "current_history",
                    "submissions_observed": 1,
                    "submissions_checked": 1,
                }
                for opportunity in opportunities
            ],
        }],
        "unmatched_members": 0,
    }
    merged = merge_checkoffs_with_autograders([record], full_snapshot)[0]
    checkmarks = [item for standard in merged["standards"] for item in standard["checkmarks"]]
    assert {item["id"] for item in checkmarks} == OPPORTUNITY_IDS
    assert all(item["status"] == "complete" for item in checkmarks)
    assert validate_combined_record(merged) == []
