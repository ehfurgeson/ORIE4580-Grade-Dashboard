from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
import json

import pytest

from scripts.migrate_lab89_publication import migrate_lab89_state
from sync.checkoff_mappings import (
    AUTOGRADER_OPPORTUNITY_IDS, COLUMN_MAPPINGS, LAB_MAPPING_VERSION,
    MANUAL_ONLY_OPPORTUNITY_IDS, opportunity_from_assignment_title,
)
from sync.combined_checkoffs import merge_checkoffs_with_autograders, validate_combined_record
from sync.completion_cache import build_completion_cache, filter_completion_cache, lab_contract_fingerprint
from sync.exam_publication import load_publication_state, write_publication_state
from sync.gradescope import build_snapshot, evaluate_submission, load_config
from sync.simple_checkoffs import rows_to_simple_records
from sync.simple_generate import write_simple_release
from sync.standards import STANDARDS
from test_gradescope import FakeSource, payload
from test_exam2_combined import merged

NOW = '2026-11-12T20:00:00Z'


def config():
    return load_config('deployment/gradescope.toml.example')


def lab9_snapshot(status='passed'):
    cfg = config()
    rule = next(r for r in cfg.assignments if r.opportunity_id == 'lab9-q1')
    source = FakeSource({('member-1', rule.assignment_id): [payload((1, 1, 1) if status == 'passed' else (1, 0, 1))]})
    snapshot, _ = build_snapshot(source, replace(cfg, minimum_roster_members=1), generated_at=NOW)
    return snapshot


@pytest.mark.parametrize('manual', [True, False])
@pytest.mark.parametrize('autograder', ['passed', 'failed'])
def test_lab89_green_requirements_and_published_output(tmp_path, manual, autograder):
    records = rows_to_simple_records([{
        **{column: False for column in COLUMN_MAPPINGS},
        'NetID': 'abc123', 'Lab 8 - Q1': manual,
        'Lab 9 - Q1': manual, 'Lab 9 - Q2': manual,
    }], updated_at=NOW, worksheet='Fake checkoffs')
    combined = merge_checkoffs_with_autograders(records, lab9_snapshot(autograder))
    record = combined[0]
    assert validate_combined_record(record) == []
    assert record['unmapped_columns'] == []
    assert len(record['standards']) == 9
    for sid, opp in [('S8', 'lab8-q1'), ('S7', 'lab9-q1'), ('S9', 'lab9-q2')]:
        standard = next(s for s in record['standards'] if s['id'] == sid)
        assert standard['name'] == STANDARDS[sid]
        mark = next(m for m in standard['checkmarks'] if m['id'] == opp)
        expected = manual and (opp != 'lab9-q1' or autograder == 'passed')
        assert mark['status'] == ('complete' if expected else 'incomplete')
        assert [r['id'] for r in mark['requirements']] == (['manual', 'autograder'] if opp == 'lab9-q1' else ['manual'])
    write_simple_release(combined, tmp_path / 'students')
    assert json.loads((tmp_path / 'students/abc123/checkoffs.json').read_text()) == record


def test_lab9_exact_contract_and_cache_eligibility():
    cfg = config()
    assert len(cfg.assignments) == 13
    assert {r.opportunity_id for r in cfg.assignments} == AUTOGRADER_OPPORTUNITY_IDS
    assert {'lab8-q1', 'lab9-q2'} <= MANUAL_ONLY_OPPORTUNITY_IDS
    assert opportunity_from_assignment_title('Lab 9, Q1') == 'lab9-q1'
    rule = next(r for r in cfg.assignments if r.opportunity_id == 'lab9-q1')
    assert (rule.assignment_id, rule.expected_score, rule.expected_test_count, rule.expected_test_maxima) == (9030150, Decimal(3), 3, (Decimal(1),) * 3)
    assert evaluate_submission(payload(), rule) == 'passed'
    assert evaluate_submission(payload((1, 0, 1)), rule) == 'failed'
    assert evaluate_submission(payload((1, 1)), rule) == 'contract_mismatch'
    cache = build_completion_cache(cfg, lab9_snapshot(), frozenset(), written_at=NOW)
    labs, _ = filter_completion_cache(cache, cfg, {'abc123'})
    assert labs == {('abc123', 'lab9-q1')}
    assert not {'lab8-q1', 'lab9-q2'} & cache['lab_contracts'].keys()
    assert LAB_MAPPING_VERSION == 'lab-mapping-v7'
    changed = replace(rule, contract_version='lab9-q1-v2')
    assert lab_contract_fingerprint(cfg, changed) != lab_contract_fingerprint(cfg, rule)
    # A valid old cache still cannot carry evidence across the mapping release.
    old = deepcopy(cache)
    old['lab_contracts']['lab9-q1']['contract']['title_mapping_version'] = 'lab-mapping-v6'
    assert filter_completion_cache(old, cfg, {'abc123'})[0] == frozenset()


def old_state(visible, exam3_visible):
    record = merged()
    record['standards'] = record['standards'][:7]
    record['unmapped_columns'] = ['Lab 8 - Q1', 'Lab 9 - Q1', 'Lab 9 - Q2', 'Lab 10 - Q1']
    return dict(schema_version=1, visible=visible, exam3_visible=exam3_visible,
                collected_at=record['updated_at'], records=[record])


@pytest.mark.parametrize('visible', [True, False])
@pytest.mark.parametrize('exam3_visible', [True, False])
def test_publication_migration_preserves_marks_flags_and_privacy(tmp_path, visible, exam3_visible):
    state = old_state(visible, exam3_visible)
    before = deepcopy(state)
    migrated = migrate_lab89_state(state)
    assert state == before
    assert migrated['visible'] is visible and migrated['exam3_visible'] is exam3_visible
    assert migrated['collected_at'] == before['collected_at']
    record = migrated['records'][0]
    assert record['standards'][:7] == before['records'][0]['standards']
    assert record['standards'][7:] == [dict(id=s, name=STANDARDS[s], checkmarks=[]) for s in ['S8', 'S9']]
    assert record['unmapped_columns'] == ['Lab 10 - Q1']
    path = tmp_path / 'state.json'
    write_publication_state(path, migrated)
    assert load_publication_state(path) == migrated
    assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError, match='S1–S7'):
        migrate_lab89_state(migrated)


@pytest.mark.parametrize('mutation', ['wording', 'missing', 'visibility', 'mark'])
def test_publication_migration_fails_closed(mutation):
    state = old_state(False, False)
    if mutation == 'wording':
        state['records'][0]['standards'][6]['name'] = 'Standard 7'
    elif mutation == 'missing':
        state['records'][0]['standards'].pop()
    elif mutation == 'visibility':
        state['visible'] = 'false'
    else:
        state['records'][0]['standards'][0]['checkmarks'][0]['status'] = 'guessed'
    with pytest.raises(ValueError):
        migrate_lab89_state(state)
