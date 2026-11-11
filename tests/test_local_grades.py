import json
import sys

import pytest

from scripts import pull_local_grades
from scripts.refresh_combined_dashboard import _acquire_lock
from sync.exam_publication import write_publication_state, visible_records
from sync.local_grades import load_local_grades
from sync.simple_generate import EXAM3_HIDDEN_RULE, write_simple_release
from test_exam2_combined import merged
from test_examiner_exports import batch


def setup(tmp_path, monkeypatch, *, visible=False, require_hidden=False):
    source = tmp_path / 'exports'
    state_path = tmp_path / 'private' / 'state.json'
    lock = tmp_path / 'private' / 'refresh.lock'
    output = tmp_path / 'served' / 'students'
    record = merged()
    netid = record['student']['netid']
    batch(source, email=netid + '@cornell.edu')
    state = {'schema_version': 1, 'visible': False, 'exam3_visible': visible,
             'collected_at': '2026-10-27T12:00:00Z', 'records': [record]}
    write_publication_state(state_path, state)
    write_simple_release(visible_records(state['records'], False), output, exam3_visible=visible)
    monkeypatch.setattr(sys, 'argv', ['pull_local_grades', str(source), '--state', str(state_path),
                        '--output', str(output), '--lock-file', str(lock)] +
                        (['--require-hidden'] if require_hidden else []))
    return source, state_path, output, lock, netid


@pytest.mark.parametrize('visible', [False, True])
def test_offline_import_preserves_grades_visibility_and_state(tmp_path, monkeypatch, visible):
    source, state, output, lock, netid = setup(tmp_path, monkeypatch, visible=visible)
    old_state = state.read_bytes()
    student = output / netid
    old_grades = (student / 'checkoffs.json').read_bytes()
    # A network call is always a bug in this command.
    import socket
    monkeypatch.setattr(socket.socket, 'connect', lambda *args: pytest.fail("Unexpected network call"))
    pull_local_grades.main()
    assert state.read_bytes() == old_state
    assert (student / 'checkoffs.json').read_bytes() == old_grades
    document = json.loads((student / 'exam3.json').read_text())
    assert document['published_at'] != json.loads(old_grades)['updated_at']
    assert document['exported_at'] == '2026-11-11T01:00:00Z'
    assert (EXAM3_HIDDEN_RULE in (student / '.htaccess').read_text()) is not visible
    assert not list(output.rglob('manifest.json'))


@pytest.mark.parametrize('failure', ['visible', 'missing_state', 'invalid_export', 'locked', 'empty'])
def test_failed_import_preserves_live_release(tmp_path, monkeypatch, failure):
    source, state, output, lock, netid = setup(tmp_path, monkeypatch,
        visible=failure == 'visible', require_hidden=True)
    before = {p.relative_to(output): p.read_bytes() for p in output.rglob('*') if p.is_file()}
    handle = None
    if failure == 'missing_state':
        state.unlink()
    elif failure == 'invalid_export':
        next(source.glob('student-*/123.json')).write_text('{}')
    elif failure == 'empty':
        import shutil
        shutil.rmtree(next(source.iterdir()))
    elif failure == 'locked':
        handle = _acquire_lock(lock)
    try:
        with pytest.raises(SystemExit):
            pull_local_grades.main()
    finally:
        if handle:
            handle.close()
    assert before == {p.relative_to(output): p.read_bytes() for p in output.rglob('*') if p.is_file()}


def test_manifest_selects_adapter_and_rejects_unknown_exam(tmp_path):
    folder = batch(tmp_path)
    assert set(load_local_grades(tmp_path, {'abc123'})) == {'exam3.json'}
    manifest = folder / 'manifest.json'
    value = json.loads(manifest.read_text())
    value['exam'] = 4
    manifest.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='Unsupported'):
        load_local_grades(tmp_path, {'abc123'})
