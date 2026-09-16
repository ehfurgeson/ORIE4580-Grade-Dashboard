from sync.generate import write_records
from sync.google_sheets import load_csv, rows_to_records
from sync.grading import summarize
from sync.standards import STANDARDS
from sync.validate import validate_all


def test_adapter_emits_valid_standards_schema():
    common = {
        "updated_at": "2026-09-14T12:00:00Z",
        "course": "ORIE 4580",
        "student_id": "abc123",
        "student_name": "Example Student",
    }
    rows = [{**common, "standard_id": standard_id} for standard_id in STANDARDS]
    rows[0].update({
        "opportunity_id": "lab-1-p1",
        "opportunity_label": "Lab 1",
        "source": "lab",
        "kind": "green",
        "status": "complete",
    })
    records = rows_to_records(rows)
    assert validate_all(records) == []
    assert len(records[0]["standards"]) == 12


def test_adapter_rejects_inconsistent_student_metadata():
    rows = [
        {"updated_at": "2026-09-14T12:00:00Z", "course": "ORIE 5581", "student_id": "abc123", "student_name": "A", "standard_id": "P1"},
        {"updated_at": "2026-09-14T12:00:00Z", "course": "ORIE 5581", "student_id": "abc123", "student_name": "B", "standard_id": "P2"},
    ]
    try:
        rows_to_records(rows)
    except ValueError as error:
        assert "inconsistent" in str(error)
    else:
        raise AssertionError("expected inconsistent metadata to fail")


def test_fake_csv_runs_end_to_end(tmp_path):
    rows = load_csv("fixtures/google-sheet.fake.csv")
    records = rows_to_records(rows)
    assert validate_all(records) == []
    assert len(rows) == 27
    assert summarize(records[0])["estimated_grade"] == "B"
    paths = write_records(records, tmp_path)
    assert paths == [tmp_path / "ehf38" / "grades.json"]
    assert paths[0].exists()


def test_csv_rejects_missing_required_headers(tmp_path):
    source = tmp_path / "bad.csv"
    source.write_text("student_id,student_name\nabc123,Example\n")
    try:
        load_csv(source)
    except ValueError as error:
        assert "missing columns" in str(error)
    else:
        raise AssertionError("expected missing headers to fail")
