from pathlib import Path

import pytest

from sync.simple_checkoffs import rows_to_simple_records, validate_simple_record
from sync.simple_generate import write_simple_release


UPDATED_AT = "2026-09-17T12:00:00Z"


def make_rows():
    return [
        {"NetID": "abc123", "Lab 1 - Q1": "True", "Lab 1 - Q2": "False"},
        {"NetID": "xy99", "Lab 1 - Q1": "False", "Lab 1 - Q2": "True"},
    ]


def test_wide_rows_preserve_headers_and_normalize_checkboxes():
    records = rows_to_simple_records(make_rows(), updated_at=UPDATED_AT, worksheet="Lab Checkoffs")
    assert records[0] == {
        "updated_at": UPDATED_AT,
        "worksheet": "Lab Checkoffs",
        "student": {"netid": "abc123"},
        "items": [
            {"name": "Lab 1 - Q1", "status": "complete"},
            {"name": "Lab 1 - Q2", "status": "incomplete"},
        ],
    }
    assert validate_simple_record(records[0]) == []


@pytest.mark.parametrize(
    "rows,message",
    [
        ([{"student": "abc123", "Lab": "True"}], "exactly one"),
        ([{"NetID": "../abc", "Lab": "True"}], "invalid Cornell NetID"),
        ([{"NetID": "abc123", "Lab": "maybe"}], "True/False"),
        ([{"NetID": "ABC123", "Lab": "True"}, {"NetID": "abc123", "Lab": "False"}], "duplicate"),
        ([{"NetID": "abc123"}], "at least one"),
    ],
)
def test_wide_rows_reject_unsafe_or_ambiguous_input(rows, message):
    with pytest.raises(ValueError, match=message):
        rows_to_simple_records(rows, updated_at=UPDATED_AT, worksheet="Lab Checkoffs")


def test_publisher_creates_exact_netid_authorization(tmp_path):
    records = rows_to_simple_records(make_rows()[:1], updated_at=UPDATED_AT, worksheet="Lab Checkoffs")
    output = tmp_path / "students"
    paths = write_simple_release(records, output)
    student_dir = output / "abc123"
    assert paths == [student_dir / "checkoffs.json"]
    assert "Options -Indexes" in (output / ".htaccess").read_text()
    assert (student_dir / "index.html").exists()
    rule = (student_dir / ".htaccess").read_text()
    assert "Require shib-user abc123" in rule
    assert "shib-attr" not in rule
    assert "valid-user" not in rule
    assert "Options -Indexes" in rule
    assert 'private, no-store, max-age=0' in rule


def test_new_release_removes_students_not_in_selected_batch(tmp_path):
    output = tmp_path / "students"
    records = rows_to_simple_records(make_rows(), updated_at=UPDATED_AT, worksheet="Lab Checkoffs")
    write_simple_release(records, output)
    assert (output / "xy99").exists()
    write_simple_release(records[:1], output)
    assert (output / "abc123").exists()
    assert not (output / "xy99").exists()


def test_invalid_batch_does_not_replace_previous_release(tmp_path):
    output = tmp_path / "students"
    valid = rows_to_simple_records(make_rows()[:1], updated_at=UPDATED_AT, worksheet="Lab Checkoffs")
    write_simple_release(valid, output)
    invalid = [{**valid[0], "items": [{"name": "Lab", "status": "unknown"}]}]
    with pytest.raises(ValueError, match="invalid simple records"):
        write_simple_release(invalid, output)
    assert (output / "abc123" / "checkoffs.json").exists()


def test_frontend_renders_sheet_text_without_inner_html():
    script = Path("static/simple-dashboard.js").read_text()
    assert ".textContent = item.name" in script
    assert "innerHTML" not in script


def test_simple_landing_links_only_valid_netid_paths():
    landing = Path("deployment/simple-index.html").read_text()
    assert "^[a-z]{2,3}[0-9]+$" in landing
    assert "students/${encodeURIComponent(netid)}/" in landing
    assert "dashboard.js" not in landing
