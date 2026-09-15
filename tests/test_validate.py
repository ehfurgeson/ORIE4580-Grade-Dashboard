import copy
import json
from pathlib import Path

import pytest

from sync.generate import write_record, write_records
from sync.validate import validate_all, validate_record


@pytest.fixture
def valid():
    return json.loads(Path("fixtures/grades.json").read_text())


def test_fixture_valid(valid):
    assert validate_record(valid) == []


@pytest.mark.parametrize("field,value,message", [
    ("status", "maybe", "status"),
    ("kind", "blue", "kind"),
    ("source", "exam", "source does not match"),
])
def test_rejects_bad_opportunity_fields(valid, field, value, message):
    valid["standards"][0]["opportunities"][0][field] = value
    assert any(message in error for error in validate_record(valid))


@pytest.mark.parametrize("timestamp", ["2026-09-14", "2026-09-14T12:00:00"])
def test_rejects_timestamp_without_timezone(valid, timestamp):
    valid["updated_at"] = timestamp
    assert any("updated_at" in error for error in validate_record(valid))


@pytest.mark.parametrize("student_id", ["../other", "é123", "-test", "test-"])
def test_rejects_unsafe_student_id(valid, student_id):
    valid["student"]["id"] = student_id
    assert any("student.id" in error for error in validate_record(valid))


def test_malformed_ids_return_errors_instead_of_crashing(valid):
    valid["student"]["id"] = []
    valid["standards"][0]["id"] = []
    valid["standards"][0]["opportunities"][0]["id"] = []
    errors = validate_all([valid])
    assert len(errors) >= 3


def test_full_courses_require_all_twelve_standards(valid):
    valid["standards"].pop()
    assert any("12-standard" in error for error in validate_record(valid))


def test_5581_may_use_a_syllabus_subset(valid):
    valid["course"] = "ORIE 5581"
    valid["standards"] = valid["standards"][:3]
    assert validate_record(valid) == []


def test_rejects_duplicate_student_batch_without_writing(valid, tmp_path):
    with pytest.raises(ValueError, match="duplicate student id"):
        write_records([valid, copy.deepcopy(valid)], tmp_path)
    assert list(tmp_path.rglob("grades.json")) == []


def test_atomic_generation_leaves_no_temp_file(valid, tmp_path):
    path = write_record(valid, tmp_path)
    assert json.loads(path.read_text())["student"]["id"] == "test123"
    assert list(path.parent.glob("*.tmp")) == []


def test_accepts_shiny_purple_exam_opportunity(valid):
    item = valid["standards"][0]["opportunities"][0]
    item["kind"] = "shiny_purple"
    item["source"] = "exam"
    assert validate_record(valid) == []
