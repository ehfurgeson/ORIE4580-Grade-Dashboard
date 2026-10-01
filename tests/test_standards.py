from sync.checkoff_mappings import COLUMN_MAPPINGS
from sync.google_sheets import rows_to_records
from sync.gradescope_exam import EXAM_OPPORTUNITIES
from sync.simple_checkoffs import rows_to_simple_records, validate_manual_record
from sync.standards import STANDARDS
from sync.validate import validate_record


def test_row_and_wide_importers_use_the_same_standard_ids_and_wording():
    common = {
        'updated_at': '2026-10-01T12:00:00Z',
        'course': 'ORIE 4580',
        'student_id': 'abc123',
        'student_name': "Example Student",
    }
    row_record = rows_to_records([
        {**common, 'standard_id': standard_id} for standard_id in STANDARDS
    ])[0]
    wide_record = rows_to_simple_records(
        [{'NetID': 'abc123', **{column: False for column in COLUMN_MAPPINGS}}],
        updated_at=common['updated_at'], worksheet="Lab Checkoffs",
    )[0]

    assert validate_record(row_record) == []
    assert validate_manual_record(wide_record) == []
    assert [(item['id'], item['name']) for item in row_record['standards']] == [
        (item['id'], item['name']) for item in wide_record['standards']
    ]


def test_lab_and_exam_mappings_reference_the_shared_catalog():
    assert {mapping[0] for mapping in COLUMN_MAPPINGS.values()} <= set(STANDARDS)
    assert {item['standard_id'] for item in EXAM_OPPORTUNITIES} <= set(STANDARDS)
