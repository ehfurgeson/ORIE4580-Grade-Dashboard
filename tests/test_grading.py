import copy
import json
from pathlib import Path

from sync.grading import estimate_grade, summarize


def load_record():
    record = json.loads(Path("fixtures/grades.json").read_text())
    record["course"] = "ORIE 5581"
    return record


def opportunity(identifier, kind="purple"):
    return {
        "id": identifier,
        "label": identifier,
        "source": "exam" if kind == "purple" else "lab",
        "kind": kind,
        "status": "complete",
    }


def test_summary_counts_only_complete_checkmarks():
    summary = summarize(load_record())
    assert summary == {
        "standards": 12,
        "green": 2,
        "purple": 0,
        "purple_standards": 0,
        "missing": 22,
        "estimated_grade": None,
    }


def test_a_plus_boundary_uses_floor_and_ordered_first_match():
    record = load_record()
    record["standards"] = copy.deepcopy(record["standards"][:3])
    for index, standard in enumerate(record["standards"]):
        standard["opportunities"] = [
            opportunity(f"p{index}-1"),
            opportunity(f"p{index}-2"),
        ]
    # n=3: floor(1.5n)=4. All standards have purple and none are missing.
    summary = summarize(record)
    assert summary["purple"] == 6
    assert summary["purple_standards"] == 3
    assert summary["missing"] == 0
    assert summary["estimated_grade"] == "A+"


def test_repeated_purples_do_not_inflate_standards_covered():
    record = load_record()
    record["standards"] = copy.deepcopy(record["standards"][:4])
    record["standards"][0]["opportunities"] = [opportunity(f"p{i}") for i in range(8)]
    for index, standard in enumerate(record["standards"][1:], start=1):
        standard["opportunities"] = [opportunity(f"g{index}-1", "green"), opportunity(f"g{index}-2", "green")]
    summary = summarize(record)
    assert summary["purple"] == 8
    assert summary["purple_standards"] == 1
    assert summary["missing"] == 0
    assert summary["estimated_grade"] is None


def test_exact_c_boundary():
    record = load_record()
    record["standards"] = copy.deepcopy(record["standards"][:4])
    # n=4 requires two purple standards, two total purples, <=4 missing.
    for index, standard in enumerate(record["standards"]):
        standard["opportunities"] = [opportunity(f"p{index}")] if index < 2 else []
    summary = summarize(record)
    assert summary["missing"] == 6
    assert summary["estimated_grade"] is None
    record["standards"][2]["opportunities"] = [opportunity("g2-1", "green"), opportunity("g2-2", "green")]
    summary = summarize(record)
    assert summary["missing"] == 4
    assert summary["estimated_grade"] == "C"


def test_every_syllabus_grade_boundary():
    cases = [
        ("A+", 12, 18, 1),
        ("A", 11, 15, 1),
        ("A−", 11, 12, 2),
        ("B+", 9, 12, 2),
        ("B", 9, 9, 2),
        ("B−", 9, 9, 4),
        ("C+", 6, 9, 4),
        ("C", 6, 6, 4),
    ]
    for expected, purple_standards, purple_total, missing in cases:
        assert estimate_grade(12, purple_standards, purple_total, missing) == expected


def test_ehf38_fake_fixture_is_valid_and_demonstrates_b_threshold():
    from sync.validate import validate_record

    record = json.loads(Path("fixtures/ehf38-grades.fake.json").read_text())
    assert validate_record(record) == []
    assert summarize(record) == {
        "standards": 12,
        "green": 13,
        "purple": 9,
        "purple_standards": 9,
        "missing": 2,
        "estimated_grade": "B",
    }
