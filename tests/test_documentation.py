from pathlib import Path

from sync.checkoff_mappings import COLUMN_MAPPINGS, MANUAL_ONLY_OPPORTUNITY_IDS, STANDARDS
from sync.gradescope import load_config
from sync.gradescope_exam import EXAM_OPPORTUNITIES
from sync.standards import STANDARDS as RUBRIC_STANDARDS


def test_standards_document_contains_the_rubric_and_executable_mappings():
    document = Path("docs/standards.md").read_text()

    for rubric_id, (_category, wording) in RUBRIC_STANDARDS.items():
        assert f"| {rubric_id} |" in document
        assert wording in document

    for semantic_key, standard in STANDARDS.items():
        assert f"`{semantic_key}`" in document
        assert standard["id"] in document
        assert standard["name"] in document

    for column, (semantic_key, opportunity_id, _label) in COLUMN_MAPPINGS.items():
        assert f"`{column}`" in document
        assert f"`{semantic_key}`" in document
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
        assert f"`{opportunity['standard_key']}`" in document
        assert opportunity["kind"].replace("_", " ").casefold() in document.casefold()


def test_maintenance_uses_standards_document_instead_of_local_notes():
    maintenance = Path("docs/maintenance.md").read_text()
    assert "standards.md" in maintenance
    assert "notes.md" not in maintenance
    assert "§17" not in maintenance
