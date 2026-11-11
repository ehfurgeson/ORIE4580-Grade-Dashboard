"""Dispatch local grade exports by their manifest format."""
from __future__ import annotations

import json
from pathlib import Path

from .examiner_exports import load_reviews


def load_local_grades(root: Path, netids: set[str], *, allow_empty_exam3=False) -> dict:
    """Return student documents grouped by publication filename.

    Each source directory is authoritative for one exam. New formats belong in
    this adapter table, not in the local pull command or the remote polling code.
    """
    adapters = {(1, 3): ('exam3.json', load_reviews)}
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
                or type(value.get('exam')) is not int):
            raise ValueError("Invalid local grades manifest")
        formats.add((value['schema_version'], value['exam']))
    if not formats and allow_empty_exam3:
        formats.add((1, 3))  # Preserve the legacy --examiner-exports retraction behavior.
    if not formats:
        raise ValueError("No completed exports found; select the exports parent directory")
    if len(formats) != 1 or not formats <= adapters.keys():
        raise ValueError("Unsupported or mixed local grades formats; currently supports Examiner Exam 3, version 1")
    filename, adapter = adapters[next(iter(formats))]
    return {filename: adapter(root, netids)}
