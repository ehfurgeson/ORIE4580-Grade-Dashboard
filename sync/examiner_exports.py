"""Read completed local exam exports without accessing grading inputs or runs."""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re

from .simple_checkoffs import NETID_PATTERN


def _read(path: Path, exam=3) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Exam export must contain regular files")
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict) or value.get('schema_version') != 1 or value.get('exam') != exam:
        raise ValueError("Unsupported exam export format")
    return value


def _timestamp(value):
    if not isinstance(value, str):
        raise ValueError("Missing exam export timestamp")
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError("Exam export timestamp needs a timezone")
    return stamp


def load_reviews(root: Path, netids: set[str], *, exam=3) -> dict[str, dict]:
    """Replay completed batches; the newest exported version of each question wins.

    ``exam`` is the exports' exam: 3 (Examiner) or 'retry' (Examinator, same format).

    Unknown roster members are ignored, but their export identity is still checked.
    """
    if not root.is_dir() or root.is_symlink():
        raise ValueError("Exam export root must be a readable directory")
    batches = []
    for folder in root.iterdir():
        if not folder.name.startswith('student-'):
            continue  # Includes Examiner's unfinished .building-* directories.
        if not re.fullmatch(r'student-[0-9a-f]{16}', folder.name) or folder.is_symlink() or not folder.is_dir():
            raise ValueError("Unsafe exam export directory")
        manifest = _read(folder / 'manifest.json', exam)
        batches.append((_timestamp(manifest.get('exported_at')), folder, manifest))
    batches.sort(key=lambda batch: (batch[0], batch[1].name))
    reviews = {}
    for stamp, folder, manifest in batches:
        entries = manifest.get('entries')
        if not isinstance(entries, list) or not entries:
            raise ValueError("Exam manifest needs exported entries")
        expected = {}
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("Invalid exam manifest entry")
            identifier, question = entry.get('id'), entry.get('question')
            if not isinstance(identifier, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', identifier):
                raise ValueError("Unsafe exam submission ID")
            if not isinstance(question, str) or not re.fullmatch(r'q[1-9][0-9]*', question):
                raise ValueError("Invalid exam question ID")
            questions = expected.setdefault(identifier, set())
            if question in questions:
                raise ValueError("Duplicate exam manifest entry")
            questions.add(question)
        batch_netids = set()
        for identifier, question_ids in expected.items():
            document = _read(folder / (identifier + '.json'), exam)
            student = document.get('student')
            if not isinstance(student, dict) or student.get('id') != identifier:
                raise ValueError("Exam submission identity mismatch")
            email = student.get('email')
            if not isinstance(email, str) or not email.lower().endswith('@cornell.edu'):
                raise ValueError("Exam export requires a Cornell NetID email for each student")
            netid = email.lower().removesuffix('@cornell.edu')
            if not NETID_PATTERN.fullmatch(netid) or netid in batch_netids:
                raise ValueError("Invalid or duplicate NetID in exam export")
            batch_netids.add(netid)
            if _timestamp(document.get('exported_at')) != stamp:
                raise ValueError("Exam manifest and review timestamps disagree")
            questions = document.get('questions')
            if not isinstance(questions, list) or any(not isinstance(q, dict) for q in questions):
                raise ValueError("Invalid questions in exam review")
            ids = [q.get('id') for q in questions]
            if any(not isinstance(qid, str) for qid in ids) or len(ids) != len(set(ids)) or set(ids) != question_ids:
                raise ValueError("Exam manifest and review questions disagree")
            for question in questions:
                if question.get('normal_credit') not in ('met', 'not_met', 'blank') or question.get('shiny_credit') not in (None, 'met', 'not_met', 'blank'):
                    raise ValueError("Exam credit decision is not finalized")
            if netid not in netids:
                continue
            review = reviews.setdefault(netid, {**document, 'questions': [], 'question_exported_at': {}})
            merged = {q['id']: q for q in review['questions']}
            versions = review['question_exported_at']
            for question in questions:
                qid = question['id']
                if qid in versions and _timestamp(versions[qid]) == stamp and merged[qid] != question:
                    raise ValueError("Conflicting exam exports have the same timestamp")
                merged[qid] = question
                versions[qid] = document['exported_at']
            review['questions'] = sorted(merged.values(), key=lambda q: int(q['id'][1:]))
            review['exported_at'] = document['exported_at']
            review['student'] = document['student']
    return reviews


def merge_review(previous: dict, incoming: dict) -> dict:
    """Keep the published version of each question until a newer export supplies it."""
    merged = {question['id']: question for question in previous['questions']}
    previous_versions = previous.get('question_exported_at', {})
    versions = {qid: previous_versions.get(qid, previous['exported_at']) for qid in merged}
    updated = False
    for question in incoming['questions']:
        qid = question['id']
        stamp = incoming['question_exported_at'][qid]
        if qid in versions and _timestamp(versions[qid]) >= _timestamp(stamp):
            continue
        merged[qid] = question
        versions[qid] = stamp
        updated = True
    if not updated:
        return previous
    newest = max((incoming, previous), key=lambda document: _timestamp(document['exported_at']))
    return {**newest, 'questions': sorted(merged.values(), key=lambda q: int(q['id'][1:])),
            'question_exported_at': versions}
