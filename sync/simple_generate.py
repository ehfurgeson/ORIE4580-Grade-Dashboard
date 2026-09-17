"""Publish a staged simple-dashboard tree protected by one NetID per directory."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any

from .simple_checkoffs import validate_simple_record


STUDENTS_HTACCESS = """# Generated parent rule: do not reveal the NetID directory list.
Options -Indexes
"""

HTACCESS_TEMPLATE = """# Generated student-specific authorization. Do not edit in place.
AuthType shibboleth
ShibRequestSetting requireSession 1
Require shib-user {netid}
Options -Indexes

<IfModule mod_headers.c>
    Header always set Cache-Control "private, no-store, max-age=0"
</IfModule>
"""


def _payload(record: dict[str, Any]) -> str:
    return json.dumps(record, indent=2, ensure_ascii=False, allow_nan=False) + "\n"


def write_simple_release(
    records: list[dict[str, Any]],
    output_dir: str | Path,
    *,
    template_path: str | Path = "templates/simple_student_dashboard.html",
) -> list[Path]:
    """Validate everything, build a new tree, then replace the prior release."""
    if not isinstance(records, list) or not records:
        raise ValueError("records must be a nonempty list")
    errors: list[str] = []
    seen: set[str] = set()
    for index, record in enumerate(records):
        errors.extend(f"student {index}: {error}" for error in validate_simple_record(record))
        student = record.get("student") if isinstance(record, dict) else None
        netid = student.get("netid") if isinstance(student, dict) else None
        if isinstance(netid, str):
            if netid in seen:
                errors.append(f"duplicate NetID: {netid}")
            seen.add(netid)
    if errors:
        raise ValueError("invalid simple records: " + "; ".join(errors))

    template = Path(template_path).read_text(encoding="utf-8")
    output = Path(output_dir)
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}-staging-", dir=output.parent))
    os.chmod(staging, 0o750)
    backup = output.with_name(f".{output.name}-previous")
    written_relative: list[Path] = []
    try:
        (staging / ".htaccess").write_text(STUDENTS_HTACCESS, encoding="utf-8")
        os.chmod(staging / ".htaccess", 0o640)
        for record in records:
            netid = record["student"]["netid"]
            student_dir = staging / netid
            student_dir.mkdir(mode=0o750)
            (student_dir / "index.html").write_text(template, encoding="utf-8")
            (student_dir / "checkoffs.json").write_text(_payload(record), encoding="utf-8")
            (student_dir / ".htaccess").write_text(
                HTACCESS_TEMPLATE.format(netid=netid), encoding="utf-8"
            )
            os.chmod(student_dir / "index.html", 0o640)
            os.chmod(student_dir / "checkoffs.json", 0o640)
            os.chmod(student_dir / ".htaccess", 0o640)
            written_relative.append(Path(netid) / "checkoffs.json")

        if backup.exists():
            shutil.rmtree(backup)
        if output.exists():
            os.replace(output, backup)
        try:
            os.replace(staging, output)
        except BaseException:
            if backup.exists() and not output.exists():
                os.replace(backup, output)
            raise
        if backup.exists():
            shutil.rmtree(backup)
        return [output / relative for relative in written_relative]
    finally:
        if staging.exists():
            shutil.rmtree(staging)
