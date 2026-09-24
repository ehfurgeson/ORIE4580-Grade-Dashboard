"""Publish a staged simple-dashboard tree protected by one NetID per directory."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any

from .simple_checkoffs import NETID_PATTERN, validate_simple_record


STAFF_USERS = (
    "zivscully",
    "ehf38",
    "jrf298",
    "tm693",
    "as4268",
    "mw2244",
    "zds22",
)
STAFF_REQUIRE_LINES = "\n".join(
    f"    Require shib-user {netid}" for netid in STAFF_USERS
)

STUDENTS_HTACCESS = f"""# Generated protected-index authorization. Do not edit in place.
AuthType shibboleth
ShibRequestSetting requireSession 1
<RequireAny>
{STAFF_REQUIRE_LINES}
    Require shib-attr groups EN-OR-or4580-ta
</RequireAny>
Options -Indexes

<IfModule mod_headers.c>
    Header always set Cache-Control "private, no-store, max-age=0"
</IfModule>
"""

HTACCESS_TEMPLATE = f"""# Generated student/staff authorization. Do not edit in place.
AuthType shibboleth
ShibRequestSetting requireSession 1
AuthMerging Off
<RequireAny>
    Require shib-user {{netid}}
{STAFF_REQUIRE_LINES}
    Require shib-attr groups EN-OR-or4580-ta
</RequireAny>
Options -Indexes

<IfModule mod_headers.c>
    Header always set Cache-Control "private, no-store, max-age=0"
</IfModule>
"""


def _payload(record: dict[str, Any]) -> str:
    return json.dumps(record, indent=2, ensure_ascii=False, allow_nan=False) + "\n"


def _replace_text_atomic(path: Path, payload: str) -> None:
    """Atomically replace one mode-640 generated authorization file."""
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(fd, 0o640)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory_fd = os.open(path.parent, directory_flags)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary.exists():
            temporary.unlink()


def update_authorization_files(output_dir: str | Path) -> list[Path]:
    """Update only generated authorization files without refreshing grade data.

    All directory names are validated before the first write. Per-student rules
    are replaced first; the protected parent-index rule is replaced last.
    """
    output = Path(output_dir)
    if not output.is_dir() or output.is_symlink():
        raise ValueError("students output must be a real directory")
    student_dirs = sorted(path for path in output.iterdir() if path.is_dir())
    if not student_dirs:
        raise ValueError("students output contains no student directories")
    invalid = [
        path.name for path in student_dirs
        if path.is_symlink() or not NETID_PATTERN.fullmatch(path.name)
    ]
    if invalid:
        raise ValueError("students output contains an unsafe directory")

    written: list[Path] = []
    for student_dir in student_dirs:
        path = student_dir / ".htaccess"
        _replace_text_atomic(path, HTACCESS_TEMPLATE.format(netid=student_dir.name))
        written.append(path)
    parent_rule = output / ".htaccess"
    _replace_text_atomic(parent_rule, STUDENTS_HTACCESS)
    written.append(parent_rule)
    return written


def write_simple_release(
    records: list[dict[str, Any]],
    output_dir: str | Path,
    *,
    template_path: str | Path = "templates/simple_student_dashboard.html",
    retain_previous: bool = False,
) -> list[Path]:
    """Validate everything, build a new tree, then replace the prior release.

    When ``retain_previous`` is true, keep the immediately preceding tree in a
    hidden sibling directory for an operator-controlled rollback.
    """
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
        if backup.exists() and not retain_previous:
            shutil.rmtree(backup)
        return [output / relative for relative in written_relative]
    finally:
        if staging.exists():
            shutil.rmtree(staging)
