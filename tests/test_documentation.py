from pathlib import Path

from sync.checkoff_mappings import COLUMN_MAPPINGS, MANUAL_ONLY_OPPORTUNITY_IDS
from sync.gradescope import load_config
from sync.gradescope_exam import EXAM_OPPORTUNITIES


def test_standards_document_links_the_catalog_and_contains_opportunity_mappings():
    document = Path("docs/standards.md").read_text()

    assert '(../sync/standards.py)' in document

    for column, (standard_id, opportunity_id, _label) in COLUMN_MAPPINGS.items():
        assert f"`{column}`" in document
        assert f"`{standard_id}`" in document
        assert f"`{opportunity_id}`" in document

    for opportunity_id in MANUAL_ONLY_OPPORTUNITY_IDS:
        assert f"`{opportunity_id}`" in document
        assert "Manual-only" in document

    config = load_config("deployment/gradescope.toml.example")
    for rule in config.assignments:
        assert f"`{rule.assignment_id}`" in document
        assert f"`{rule.opportunity_id}`" in document

    for opportunity in EXAM_OPPORTUNITIES:
        assert f"`{opportunity['id']}`" in document
        assert f"`{opportunity['standard_id']}`" in document
        assert opportunity["kind"].replace("_", " ").casefold() in document.casefold()


def test_maintenance_uses_standards_document_instead_of_local_notes():
    maintenance = Path("docs/maintenance.md").read_text()
    assert "standards.md" in maintenance
    assert "notes.md" not in maintenance
    assert "§17" not in maintenance
