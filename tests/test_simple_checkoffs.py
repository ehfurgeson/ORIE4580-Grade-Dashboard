from pathlib import Path

import pytest

from sync.simple_checkoffs import rows_to_simple_records, validate_simple_record
from sync.simple_generate import write_simple_release


UPDATED_AT = "2026-09-17T12:00:00Z"


def make_rows():
    return [
        {
            "NetID": "abc123",
            "Lab 1 - Q1.3": "True",
            "Lab 1 - Q2.3": "True",
            "Lab 1 - Q2.4": "True",
            "Lab 1 - Q3": "False",
            "Lab 2 - Q1": "True",
            "Lab 2 - Q2": "True",
            "Lab 2 - Q3": "False",
        },
        {
            "NetID": "xy99",
            "Lab 1 - Q1.3": "False",
            "Lab 1 - Q2.3": "True",
            "Lab 1 - Q2.4": "True",
            "Lab 1 - Q3": "True",
            "Lab 2 - Q1": "False",
            "Lab 2 - Q2": "False",
            "Lab 2 - Q3": "True",
        },
    ]


def test_wide_rows_map_headers_to_standards_and_aggregate_lab_1():
    records = rows_to_simple_records(make_rows(), updated_at=UPDATED_AT, worksheet="Lab Checkoffs")
    record = records[0]
    assert record["schema_version"] == 2
    assert [standard["id"] for standard in record["standards"]] == ["S1", "S2", "S3"]
    s1 = record["standards"][0]
    assert s1["key"] == "uniform_samplers"
    assert [(item["id"], item["status"]) for item in s1["checkmarks"]] == [
        ("lab1-q1-2", "complete"),
        ("lab1-q3", "incomplete"),
        ("lab2-q1", "complete"),
    ]
    assert len(s1["checkmarks"][0]["requirements"]) == 3
    assert validate_simple_record(record) == []


def test_grouped_checkmark_requires_every_recorded_requirement():
    record = rows_to_simple_records(make_rows()[1:], updated_at=UPDATED_AT, worksheet="Lab Checkoffs")[0]
    checkmark = record["standards"][0]["checkmarks"][0]
    assert checkmark["status"] == "incomplete"


def test_lab_3_maps_to_updated_handout_standards():
    rows = [{
        "NetID": "abc123",
        "Lab 3 - Q1": True,
        "Lab 3 - Q2.1": True,
        "Lab 3 - Q2.2": True,
        "Lab 3 - Q2.3": False,
        "Lab 3 - Q2.4": True,
        "Lab 3 - Q3": True,
    }]
    record = rows_to_simple_records(rows, updated_at=UPDATED_AT, worksheet="Lab Checkoffs")[0]
    assert [(item["id"], item["status"]) for item in record["standards"][1]["checkmarks"]] == [
        ("lab3-q1", "complete")
    ]
    assert [(item["id"], item["status"]) for item in record["standards"][2]["checkmarks"]] == [
        ("lab3-q2", "incomplete"), ("lab3-q3", "complete")
    ]


@pytest.mark.parametrize(
    "rows,message",
    [
        ([{"student": "abc123", "Lab 2 - Q1": "True"}], "exactly one"),
        ([{"NetID": "../abc", "Lab 2 - Q1": "True"}], "invalid Cornell NetID"),
        ([{"NetID": "abc123", "Lab 2 - Q1": "maybe"}], "True/False"),
        ([{"NetID": "ABC123", "Lab 2 - Q1": "True"}, {"NetID": "abc123", "Lab 2 - Q1": "False"}], "duplicate"),
        ([{"NetID": "abc123"}], "at least one"),
        ([{"NetID": "abc123", "Lab 4 - Q1": "True"}], "unmapped checkoff"),
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
    invalid = [{**valid[0], "schema_version": 999}]
    with pytest.raises(ValueError, match="invalid simple records"):
        write_simple_release(invalid, output)
    assert (output / "abc123" / "checkoffs.json").exists()


def test_frontend_renders_mapped_text_without_inner_html():
    script = Path("static/simple-dashboard.js").read_text()
    assert ".textContent = standard.name" not in script  # rendered via the safe make() helper
    assert "element.textContent = text" in script
    assert "innerHTML" not in script


def test_flat_styles_and_shiny_shimmer_are_accessible():
    simple = Path("static/simple-style.css").read_text()
    full = Path("static/style.css").read_text()
    assert "border-radius: 0 !important" in simple
    assert "shiny-checkmark-shimmer" in full
    assert "prefers-reduced-motion: reduce" in full


def test_simple_landing_links_only_valid_netid_paths():
    landing = Path("deployment/simple-index.html").read_text()
    assert "^[a-z]{2,3}[0-9]+$" in landing
    assert "students/${encodeURIComponent(netid)}/" in landing
    assert "dashboard.js" not in landing
