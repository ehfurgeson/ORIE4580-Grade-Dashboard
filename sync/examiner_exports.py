"""Read completed Examiner exports without accessing grading inputs or runs."""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re

from .simple_checkoffs import NETID_PATTERN


def _read(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Examiner export must contain regular files")
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict) or value.get('schema_version') != 1 or value.get('exam') != 3:
        raise ValueError("Unsupported Examiner export format")
    return value


def _timestamp(value):
    if not isinstance(value, str):
        raise ValueError("Missing Examiner export timestamp")
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError("Examiner export timestamp needs a timezone")
    return stamp


def load_reviews(root: Path, netids: set[str]) -> dict[str, dict]:
    """Replay completed batches; the newest exported version of each question wins.

    The configured root is authoritative. Removing all batches retracts reviews.
    Unknown roster members are ignored, but their export identity is still checked.
    """
    if not root.is_dir() or root.is_symlink():
        raise ValueError("Examiner export root must be a readable real directory")
    batches = []
    for folder in root.iterdir():
        if not folder.name.startswith('student-'):
            continue  # Includes Examiner's unfinished .building-* directories.
        if not re.fullmatch(r'student-[0-9a-f]{16}', folder.name) or folder.is_symlink() or not folder.is_dir():
            raise ValueError("Unsafe Examiner export directory")
        manifest = _read(folder / 'manifest.json')
        batches.append((_timestamp(manifest.get('exported_at')), folder, manifest))
    batches.sort(key=lambda batch: (batch[0], batch[1].name))
    reviews, versions = {}, {}
    for stamp, folder, manifest in batches:
        entries = manifest.get('entries')
        if not isinstance(entries, list) or not entries:
            raise ValueError("Examiner manifest needs exported entries")
        expected = {}
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("Invalid Examiner manifest entry")
            identifier, question = entry.get('id'), entry.get('question')
            if not isinstance(identifier, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', identifier):
                raise ValueError("Unsafe Examiner submission ID")
            if not isinstance(question, str) or not re.fullmatch(r'q[1-9][0-9]*', question):
                raise ValueError("Invalid Examiner question ID")
            questions = expected.setdefault(identifier, set())
            if question in questions:
                raise ValueError("Duplicate Examiner manifest entry")
            questions.add(question)
        batch_netids = set()
        for identifier, question_ids in expected.items():
            document = _read(folder / (identifier + '.json'))
            student = document.get('student')
            if not isinstance(student, dict) or student.get('id') != identifier:
                raise ValueError("Examiner submission identity mismatch")
            email = student.get('email')
            if not isinstance(email, str) or not email.lower().endswith('@cornell.edu'):
                raise ValueError("Examiner student needs a Cornell NetID email")
            netid = email.lower().removesuffix('@cornell.edu')
            if not NETID_PATTERN.fullmatch(netid) or netid in batch_netids:
                raise ValueError("Invalid or duplicate Examiner NetID")
            batch_netids.add(netid)
            if _timestamp(document.get('exported_at')) != stamp:
                raise ValueError("Examiner manifest and document timestamps disagree")
            questions = document.get('questions')
            if not isinstance(questions, list) or any(not isinstance(q, dict) for q in questions):
                raise ValueError("Invalid Examiner questions")
            ids = [q.get('id') for q in questions]
            if any(not isinstance(qid, str) for qid in ids) or len(ids) != len(set(ids)) or set(ids) != question_ids:
                raise ValueError("Examiner manifest and document questions disagree")
            for question in questions:
                if question.get('normal_credit') not in ('met', 'not_met', 'blank') or question.get('shiny_credit') not in (None, 'met', 'not_met', 'blank'):
                    raise ValueError("Examiner credit decision is not finalized")
            if netid not in netids:
                continue
            review = reviews.setdefault(netid, {**document, 'questions': []})
            merged = {q['id']: q for q in review['questions']}
            for question in questions:
                key = (netid, question['id'])
                if versions.get(key) == stamp and merged[question['id']] != question:
                    raise ValueError("Conflicting Examiner exports have the same timestamp")
                merged[question['id']] = question
                versions[key] = stamp
            review['questions'] = sorted(merged.values(), key=lambda q: int(q['id'][1:]))
            review['exported_at'] = document['exported_at']
            review['student'] = document['student']
    return reviews
