import copy
import json
from pathlib import Path

from sync.grading import allocate_standard, estimate_grade, summarize


def load_record():
    record = json.loads(Path("fixtures/grades.json").read_text())
    record["course"] = "ORIE 5581"
    return record


def opportunity(identifier, kind="purple", status="complete"):
    return {
        "id": identifier,
        "label": identifier,
        "source": "lab" if kind == "green" else "exam",
        "kind": kind,
        "status": status,
    }


def test_summary_counts_only_complete_checkmarks():
    assert summarize(load_record()) == {
        "standards": 12,
        "green": 2,
        "purple": 0,
        "shiny": 0,
        "purple_standards": 0,
        "missing": 22,
        "estimated_grade": None,
    }


def test_checkbox_priority_and_extra_checkmarks():
    opportunities = [
        opportunity("g1", "green"),
        opportunity("s1", "shiny_purple"),
        opportunity("p1"),
        opportunity("p2"),
        opportunity("s2", "shiny_purple"),
        opportunity("g2", "green"),
    ]
    allocation = allocate_standard(opportunities)
    assert [item["id"] for item in allocation["linked"]] == ["p1", "p2"]
    assert [item["id"] for item in allocation["shiny"]] == ["s1", "s2"]
    assert allocation["missing"] == 0


def test_shiny_used_in_linked_box_counts_as_purple_not_shiny_pool():
    record = load_record()
    record["standards"] = copy.deepcopy(record["standards"][:1])
    record["standards"][0]["opportunities"] = [
        opportunity("s1", "shiny_purple"),
        opportunity("g1", "green"),
    ]
    summary = summarize(record)
    assert summary["purple"] == 1
    assert summary["purple_standards"] == 1
    assert summary["shiny"] == 1
    assert summary["green"] == 1
    assert summary["missing"] == 0


def test_a_plus_exact_boundary_allows_one_missing_linked_box():
    record = load_record()
    record["standards"] = copy.deepcopy(record["standards"][:3])
    record["standards"][0]["opportunities"] = [
        opportunity("p0-1"), opportunity("p0-2"), opportunity("s0", "shiny_purple")
    ]
    record["standards"][1]["opportunities"] = [opportunity("p1-1"), opportunity("p1-2")]
    record["standards"][2]["opportunities"] = [opportunity("s2", "shiny_purple")]
    summary = summarize(record)
    assert summary["purple"] == 6  # floor(2n)
    assert summary["purple_standards"] == 3
    assert summary["shiny"] == 2  # n - 1
    assert summary["missing"] == 1
    assert summary["estimated_grade"] == "A+"


def test_repeated_non_shiny_purples_do_not_count_after_linked_boxes_fill():
    record = load_record()
    record["standards"] = copy.deepcopy(record["standards"][:4])
    record["standards"][0]["opportunities"] = [opportunity(f"p{i}") for i in range(8)]
    for index, standard in enumerate(record["standards"][1:], start=1):
        standard["opportunities"] = [
            opportunity(f"g{index}-1", "green"),
            opportunity(f"g{index}-2", "green"),
        ]
    summary = summarize(record)
    assert summary["purple"] == 2
    assert summary["purple_standards"] == 1
    assert summary["missing"] == 0
    assert summary["estimated_grade"] is None


def test_exact_c_boundary():
    record = load_record()
    record["standards"] = copy.deepcopy(record["standards"][:4])
    for index, standard in enumerate(record["standards"]):
        standard["opportunities"] = [opportunity(f"p{index}")] if index < 2 else []
    assert summarize(record)["estimated_grade"] is None
    record["standards"][2]["opportunities"] = [
        opportunity("g2-1", "green"),
        opportunity("g2-2", "green"),
    ]
    summary = summarize(record)
    assert summary["missing"] == 4
    assert summary["estimated_grade"] == "C"


def test_every_syllabus_grade_boundary():
    cases = [
        ("A+", 12, 24, 11, 0),
        ("A", 11, 18, 1, 1),
        ("A−", 11, 12, 0, 2),
        ("B+", 9, 12, 0, 2),
        ("B", 9, 9, 0, 2),
        ("B−", 9, 9, 0, 4),
        ("C+", 6, 9, 0, 4),
        ("C", 6, 6, 0, 4),
    ]
    for expected, purple_standards, purple_total, shiny_total, missing in cases:
        assert estimate_grade(12, purple_standards, purple_total, shiny_total, missing) == expected


def test_a_threshold_requires_a_shiny_checkbox():
    assert estimate_grade(12, 11, 18, 0, 1) == "A−"
    assert estimate_grade(12, 11, 18, 1, 1) == "A"


def test_ehf38_fake_fixture_is_valid_and_demonstrates_all_colors():
    from sync.validate import validate_record

    record = json.loads(Path("fixtures/ehf38-grades.fake.json").read_text())
    assert validate_record(record) == []
    assert summarize(record) == {
        "standards": 12,
        "green": 12,
        "purple": 11,
        "shiny": 2,
        "purple_standards": 9,
        "missing": 2,
        "estimated_grade": "B",
    }


def test_a_uses_floor_for_odd_standard_count():
    assert estimate_grade(3, 2, 4, 1, 1) == "A"


def test_unused_shiny_counts_in_both_color_totals():
    record = load_record()
    record["standards"] = copy.deepcopy(record["standards"][:1])
    record["standards"][0]["opportunities"] = [
        opportunity("p1"), opportunity("p2"), opportunity("s1", "shiny_purple")
    ]
    summary = summarize(record)
    assert summary["purple"] == 3
    assert summary["shiny"] == 1
    assert summary["purple_standards"] == 1
    assert summary["missing"] == 0
