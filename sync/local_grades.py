"""Dispatch local grade exports by their manifest format."""
from __future__ import annotations

from functools import partial
import json
from pathlib import Path

from .examiner_exports import load_reviews

# Examinator's Exam Retry export is Examiner's Exam 3 format with exam 'retry'.
ADAPTERS = {(1, 3): ('exam3.json', load_reviews),
            (1, 'retry'): ('exam_retry.json', partial(load_reviews, exam='retry'))}


def local_format(root: Path, *, allow_empty_exam3=False) -> tuple:
    """The one format (an ``ADAPTERS`` key) of a local grades source."""
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Local grades source must be a real directory")
    formats = set()
    for folder in root.iterdir():
        if not folder.name.startswith('student-'):
            continue
        manifest = folder / 'manifest.json'
        if folder.is_symlink() or not folder.is_dir() or manifest.is_symlink() or not manifest.is_file():
            raise ValueError("Local grades source must contain regular export batches")
        value = json.loads(manifest.read_text(encoding='utf-8'))
        if (not isinstance(value, dict) or type(value.get('schema_version')) is not int
                or type(value.get('exam')) not in (int, str)):
            raise ValueError("Invalid local grades manifest")
        formats.add((value['schema_version'], value['exam']))
    if not formats and allow_empty_exam3:
        formats.add((1, 3))  # Preserve the legacy --examiner-exports retraction behavior.
    if not formats:
        raise ValueError("No completed exports found; select the exports parent directory")
    if len(formats) != 1 or not formats <= ADAPTERS.keys():
        raise ValueError("Unsupported or mixed local exam export formats. Use one supported format per source directory.")
    return next(iter(formats))


def load_local_grades(root: Path, netids: set[str], *, allow_empty_exam3=False) -> dict:
    """Return student documents grouped by publication filename.

    Each source directory is authoritative for one exam. New formats belong in
    this adapter table, not in the local pull command or the remote polling code.
    """
    filename, adapter = ADAPTERS[local_format(root, allow_empty_exam3=allow_empty_exam3)]
    return {filename: adapter(root, netids)}
