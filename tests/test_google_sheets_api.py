import pytest

from sync.google_sheets_api import READ_ONLY_SCOPE, values_to_rows


def test_api_uses_read_only_scope():
    assert READ_ONLY_SCOPE.endswith("/spreadsheets.readonly")


def test_values_to_rows_pads_missing_cells_and_skips_blank_rows():
    values = [
        ["student_id", "student_name", "status"],
        ["abc123", "Example"],
        [],
    ]
    assert values_to_rows(values) == [
        {"student_id": "abc123", "student_name": "Example", "status": ""}
    ]


@pytest.mark.parametrize("values,message", [
    ([], "empty"),
    ([["student_id", "student_id"], ["a", "b"]], "duplicate"),
    ([["student_id", ""], ["a", "b"]], "empty header"),
])
def test_values_to_rows_rejects_bad_sheets(values, message):
    with pytest.raises(ValueError, match=message):
        values_to_rows(values)
