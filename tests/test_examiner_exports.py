import json
import shutil

import pytest

from sync.examiner_exports import load_reviews
from sync.simple_generate import write_simple_release
from test_simple_checkoffs import make_rows, published_records


def batch(root, number=1, questions=None, email='abc123@cornell.edu', *, exam=3):
    folder = root / f'student-{number:016x}'
    folder.mkdir(parents=True)
    questions = questions or [{'id': 'q1', 'normal_credit': 'met', 'shiny_credit': None}]
    header = {'schema_version': 1, 'exam': exam, 'exported_at': f'2026-11-11T{number:02}:00:00Z'}
    document = {**header, 'student': {'id': '123', 'email': email}, 'questions': questions}
    (folder / '123.json').write_text(json.dumps(document))
    manifest = {**header, 'entries': [{'id': '123', 'question': q['id']} for q in questions],
                'skipped': [{'reason': 'private staff detail'}]}
    (folder / 'manifest.json').write_text(json.dumps(manifest))
    return folder


def test_partial_exports_replace_questions_and_keep_others(tmp_path):
    batch(tmp_path, questions=[{'id': q, 'normal_credit': 'met', 'shiny_credit': None} for q in ('q1', 'q2')])
    batch(tmp_path, 2, [{'id': 'q1', 'normal_credit': 'not_met', 'shiny_credit': None}])
    (tmp_path / '.building-incomplete').mkdir()
    result = load_reviews(tmp_path, {'abc123'})['abc123']
    assert [(q['id'], q['normal_credit']) for q in result['questions']] == [('q1', 'not_met'), ('q2', 'met')]
    assert 'private staff detail' not in json.dumps(result)
    assert load_reviews(tmp_path, {'xy99'}) == {}


def test_publish_preserve_and_retract(tmp_path):
    root, output = tmp_path / 'exports', tmp_path / 'students'
    folder = batch(root)
    records = published_records(make_rows())
    write_simple_release(records, output, examiner_exports=root)
    review = output / 'abc123' / 'exam3.json'
    original = review.read_bytes()
    assert json.loads(original)['published_at'] == records[0]['updated_at']
    assert review.stat().st_mode & 0o777 == 0o640
    assert not (output / 'xy99' / 'exam3.json').exists()
    assert not list(output.rglob('manifest.json'))
    write_simple_release(records, output)  # Also used by the Exam 2 visibility switch.
    assert review.read_bytes() == original
    shutil.rmtree(folder)
    write_simple_release(records, output, examiner_exports=root)
    assert not review.exists()


def test_scheduled_pull_uses_both_caches_and_preserves_reviews_when_batches_disappear(tmp_path):
    exam3, retry, output = (tmp_path / name for name in ('examiner-exports', 'retry-exports', 'students'))
    exam3_pdfs, retry_pdfs = tmp_path / 'exam-scans', tmp_path / 'retry-scans'
    question = lambda qid, credit: {'id': qid, 'normal_credit': credit, 'shiny_credit': None}
    batch(exam3, questions=[question('q1', 'met'), question('q2', 'met')])
    correction = batch(exam3, 3, [question('q1', 'not_met')])
    batch(retry, exam='retry')
    retry_pdfs.mkdir()
    (retry_pdfs / '123.pdf').write_bytes(b'synthetic retry scan')
    sources = {exam3: exam3_pdfs, retry: retry_pdfs}
    records = published_records(make_rows())
    write_simple_release(records, output, local_grade_sources=sources)
    student = output / 'abc123'
    exam3_review = student / 'exam3.json'
    retry_review = student / 'exam_retry.json'
    original_retry = retry_review.read_bytes()
    assert (student / 'exam_retry.pdf').read_bytes() == b'synthetic retry scan'

    shutil.rmtree(correction)
    shutil.rmtree(retry)
    shutil.rmtree(retry_pdfs)
    batch(exam3, 2, [question('q2', 'not_met')])
    write_simple_release(records, output, local_grade_sources=sources)
    exam3_document = json.loads(exam3_review.read_text())
    assert exam3_document['questions'] == [question('q1', 'not_met'), question('q2', 'not_met')]
    assert retry_review.read_bytes() == original_retry
    assert (student / 'exam_retry.pdf').read_bytes() == b'synthetic retry scan'

    shutil.rmtree(exam3)
    exam3.mkdir()
    (exam3 / '.building-incomplete').mkdir()
    records[0]['updated_at'] = '2026-11-20T02:00:00+00:00'
    write_simple_release(records, output, local_grade_sources=sources)
    assert json.loads(exam3_review.read_text()) == exam3_document
    assert retry_review.read_bytes() == original_retry
    assert json.loads((student / 'checkoffs.json').read_text())['updated_at'] == records[0]['updated_at']


def test_scheduled_pull_does_not_roll_back_older_published_format(tmp_path):
    root, output = tmp_path / 'exports', tmp_path / 'students'
    records = published_records(make_rows())
    batch(root, 1)
    newer = batch(root, 2, [{'id': 'q1', 'normal_credit': 'not_met', 'shiny_credit': None}])
    write_simple_release(records, output, local_grades=root)
    review = output / 'abc123' / 'exam3.json'
    saved = json.loads(review.read_text())
    del saved['question_exported_at']
    review.write_text(json.dumps(saved))
    shutil.rmtree(newer)
    write_simple_release(records, output, local_grades=root)
    assert json.loads(review.read_text()) == saved


@pytest.mark.parametrize('damage', ['missing', 'identity', 'symlink', 'manifest', 'credit'])
def test_invalid_batch_preserves_live_release(tmp_path, damage):
    root, output = tmp_path / 'exports', tmp_path / 'students'
    folder = batch(root)
    records = published_records(make_rows())
    write_simple_release(records, output, examiner_exports=root)
    previous = (output / 'abc123' / 'exam3.json').read_bytes()
    path = folder / '123.json'
    document = json.loads(path.read_text())
    if damage == 'missing':
        path.unlink()
    elif damage == 'symlink':
        other = tmp_path / 'other.json'
        path.rename(other)
        path.symlink_to(other)
    else:
        if damage == 'identity':
            document['student']['id'] = '456'
        elif damage == 'manifest':
            document['questions'][0]['id'] = 'q2'
        else:
            document['questions'][0]['normal_credit'] = 'not_checked'
        path.write_text(json.dumps(document))
    with pytest.raises((ValueError, OSError)):
        write_simple_release(records, output, examiner_exports=root)
    assert (output / 'abc123' / 'exam3.json').read_bytes() == previous


def test_missing_source_and_non_cornell_identity_fail(tmp_path):
    with pytest.raises(ValueError):
        load_reviews(tmp_path / 'missing', {'abc123'})
    batch(tmp_path, email='abc123@example.com')
    with pytest.raises(ValueError):
        load_reviews(tmp_path, {'abc123'})
