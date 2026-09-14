from sync.google_sheets import rows_to_records
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
