import json
import sys

import pytest

from scripts import pull_local_grades, set_exam_retry_visibility
from scripts.refresh_combined_dashboard import _acquire_lock
from sync.exam_publication import write_publication_state, visible_records
from sync.local_grades import load_local_grades
from sync.simple_generate import EXAM3_HIDDEN_RULE, EXAM_RETRY_HIDDEN_RULE, update_authorization_files, write_simple_release
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
    (tmp_path / 'pdfs').mkdir()
    (tmp_path / 'pdfs' / '123.pdf').write_bytes(b'%PDF-1.4 synthetic scan')
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
    pdfs = source.parent / 'pdfs'
    cache = tmp_path / 'cache'
    cache.mkdir()
    source = source.rename(cache / 'examiner-exports')
    sys.argv[1] = str(source)
    sys.argv.extend(['--pdfs', str(pdfs)])
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
    pdf = student / 'exam3.pdf'
    assert pdf.read_bytes() == b'%PDF-1.4 synthetic scan'
    inode = pdf.stat().st_ino
    # Filename identity is sufficient: the immutable source is not recopied.
    (pdfs / '123.pdf').write_bytes(b'not copied again')
    pull_local_grades.main()
    assert pdf.stat().st_ino == inode
    assert pdf.read_bytes() == b'%PDF-1.4 synthetic scan'
    pdfs.rename(tmp_path / 'removed-pdfs')
    pull_local_grades.main()
    assert pdf.stat().st_ino == inode
    write_simple_release(visible_records(json.loads(state.read_text())['records'], False), output,
                         exam3_visible=visible)
    assert pdf.stat().st_ino == inode


@pytest.mark.parametrize('failure', ['visible', 'missing_state', 'invalid_export', 'locked', 'missing_pdf'])
def test_failed_import_preserves_live_release(tmp_path, monkeypatch, failure):
    source, state, output, lock, netid = setup(tmp_path, monkeypatch,
        visible=failure == 'visible', require_hidden=True)
    before = {p.relative_to(output): p.read_bytes() for p in output.rglob('*') if p.is_file()}
    handle = None
    if failure == 'missing_state':
        state.unlink()
    elif failure == 'invalid_export':
        next(source.glob('student-*/123.json')).write_text('{}')
    elif failure == 'locked':
        handle = _acquire_lock(lock)
    elif failure == 'missing_pdf':
        (source.parent / 'pdfs' / '123.pdf').unlink()
    try:
        with pytest.raises(SystemExit):
            pull_local_grades.main()
    finally:
        if handle:
            handle.close()
    assert before == {p.relative_to(output): p.read_bytes() for p in output.rglob('*') if p.is_file()}


def test_manual_pull_is_a_noop_without_a_completed_batch(tmp_path, monkeypatch, capsys):
    source, state, output, lock, netid = setup(tmp_path, monkeypatch)
    pull_local_grades.main()
    review = output / netid / 'exam3.json'
    original = review.read_bytes()
    source.rename(tmp_path / 'removed-export-cache')
    pull_local_grades.main()
    source.mkdir()
    (source / '.building-incomplete').mkdir()
    pull_local_grades.main()
    assert review.read_bytes() == original
    assert capsys.readouterr().out.count('No completed exports') == 2


def test_manifest_selects_adapter_and_rejects_unknown_exam(tmp_path):
    folder = batch(tmp_path)
    assert set(load_local_grades(tmp_path, {'abc123'})) == {'exam3.json'}
    manifest = folder / 'manifest.json'
    value = json.loads(manifest.read_text())
    value['exam'] = 4
    manifest.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='Unsupported'):
        load_local_grades(tmp_path, {'abc123'})


def test_explicit_pdf_refresh_replaces_cached_scan(tmp_path, monkeypatch):
    source, state, output, lock, netid = setup(tmp_path, monkeypatch)
    pull_local_grades.main()
    original_state = state.read_bytes()
    pdf = output / netid / 'exam3.pdf'
    original_inode = pdf.stat().st_ino
    (source.parent / 'pdfs' / '123.pdf').write_bytes(b'%PDF-1.4 corrected synthetic scan')
    monkeypatch.setattr(sys, 'argv', [*sys.argv, '--refresh-pdfs'])
    pull_local_grades.main()
    assert pdf.read_bytes() == b'%PDF-1.4 corrected synthetic scan'
    assert pdf.stat().st_ino != original_inode
    assert state.read_bytes() == original_state
    (source.parent / 'pdfs' / '123.pdf').unlink()
    before = {p.relative_to(output): p.read_bytes() for p in output.rglob('*') if p.is_file()}
    with pytest.raises(SystemExit):
        pull_local_grades.main()
    assert before == {p.relative_to(output): p.read_bytes() for p in output.rglob('*') if p.is_file()}


def test_exam_retry_imports_beside_exam3_and_is_hidden_until_released(tmp_path, monkeypatch):
    source, state, output, lock, netid = setup(tmp_path, monkeypatch, visible=True)
    pull_local_grades.main()
    retry = tmp_path / 'retry' / 'exports'
    batch(retry, email=netid + '@cornell.edu', exam='retry')
    (tmp_path / 'retry' / 'pdfs').mkdir()
    (tmp_path / 'retry' / 'pdfs' / '123.pdf').write_bytes(b'%PDF-1.4 synthetic retry scan')
    monkeypatch.setattr(sys, 'argv', ['pull_local_grades', str(retry), '--state', str(state), '--output', str(output),
                                      '--lock-file', str(lock), '--require-hidden'])
    pull_local_grades.main()     # Exam 3 is visible; the retry is not, so this is allowed.
    student = output / netid
    assert json.loads((student / 'exam_retry.json').read_text())['exam'] == 'retry'
    assert (student / 'exam_retry.pdf').read_bytes() == b'%PDF-1.4 synthetic retry scan'
    assert (student / 'exam3.pdf').read_bytes() == b'%PDF-1.4 synthetic scan'
    retry_page = (student / 'exam_retry' / 'index.html').read_text()
    assert '<h1>Exam Retry</h1>' in retry_page
    assert 'data-exam="retry" data-source="../exam_retry.json"' in retry_page
    htaccess = (student / '.htaccess').read_text()
    assert EXAM_RETRY_HIDDEN_RULE in htaccess and EXAM3_HIDDEN_RULE not in htaccess
    update_authorization_files(output)
    assert (student / '.htaccess').read_text() == htaccess
    # Pulling Exam 3 again keeps the retry's review and scan.
    monkeypatch.setattr(sys, 'argv', ['pull_local_grades', str(source), '--state', str(state), '--output', str(output),
                                      '--lock-file', str(lock)])
    pull_local_grades.main()
    assert (student / 'exam_retry.json').is_file() and (student / 'exam_retry.pdf').is_file()

    monkeypatch.setattr(sys, 'argv', ['set_exam_retry_visibility', 'on', str(state), str(output),
                                      '--lock-file', str(lock)])
    set_exam_retry_visibility.main()
    update_authorization_files(output)
    assert EXAM_RETRY_HIDDEN_RULE not in (student / '.htaccess').read_text()
