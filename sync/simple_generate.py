"""Publish a staged simple-dashboard tree protected by one NetID per directory."""
from __future__ import annotations

import json
from html import escape
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any

from .combined_checkoffs import validate_combined_record
from .simple_checkoffs import NETID_PATTERN
from .standards import STANDARDS
from .staff_roster import load_staff_roster


STAFF_USERS = (
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
</RequireAny>
Options -Indexes

<IfModule mod_headers.c>
    Header always set Cache-Control "private, no-store, max-age=0"
    Header always set X-Robots-Tag "noindex, nofollow, noarchive"
</IfModule>
"""

HTACCESS_TEMPLATE = f"""# Generated student/staff authorization. Do not edit in place.
AuthType shibboleth
ShibRequestSetting requireSession 1
AuthMerging Off
<RequireAny>
    Require shib-user {{netid}}
{STAFF_REQUIRE_LINES}
</RequireAny>
Options -Indexes

<IfModule mod_headers.c>
    Header always set Cache-Control "private, no-store, max-age=0"
</IfModule>
"""


def render_staff_index(netids: list[str]) -> str:
    """Render a protected staff index from validated canonical NetIDs."""
    if not netids or any(not NETID_PATTERN.fullmatch(netid) for netid in netids):
        raise ValueError("staff index requires validated Cornell NetIDs")
    if len(netids) != len(set(netids)):
        raise ValueError("staff index NetIDs must be unique")
    roster = load_staff_roster()
    if roster is not None:
        netids = [netid for netid in netids if netid in roster]
    headings = ''.join(
        f'<th scope="col" class="staff-private" data-standard="{standard_id}" hidden '
        f'title="{escape(name, quote=True)}">{standard_id}</th>'
        for standard_id, name in STANDARDS.items()
    )
    rows = []
    for netid in sorted(netids):
        first, last = (escape(name, quote=True) for name in (roster or {}).get(netid, ('', '')))
        rows.append(
            f'<tr data-netid="{netid}" data-first-name="{first}" data-last-name="{last}">'
            f'<td class="staff-line-number"></td><th scope="row"><a href="./{netid}/">{netid}</a></th>'
            f'<td class="staff-name">{first}</td><td class="staff-name">{last}</td></tr>'
        )
    links = "\n".join(rows)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex, nofollow, noarchive">
  <title>ORIE 4580 Staff Dashboard Index</title>
  <link rel="stylesheet" href="../simple-style.css">
</head>
<body>
  <main class="simple-container staff-container" id="staff-index">
    <header>
      <p class="eyebrow">ORIE 4580</p>
      <h1>Student dashboards</h1>
      <p>Protected staff index. Select a NetID to open that student's dashboard.</p>
    </header>
    <section aria-labelledby="student-list-title">
      <h2 id="student-list-title">Students ({len(netids)})</h2>
      <div class="staff-controls">
        <label for="student-search">Search by NetID or name
          <input id="student-search" type="search" autocomplete="off" spellcheck="false" placeholder="e.g. abc123">
        </label>
        <button id="toggle-checkmarks" type="button" aria-expanded="false" aria-controls="student-table" disabled>Show checkmarks</button>
      </div>
      <p id="staff-status" class="note">Checkmarks start hidden. Click Show/Hide checkmarks to toggle them; Escape or switching tabs hides them.</p>
      <noscript><p>Enable JavaScript to search and show checkmarks.</p></noscript>
      <div class="staff-table-scroll" tabindex="0" role="region" aria-label="Student summaries">
      <table id="student-table" class="staff-table">
        <caption class="note">Student dashboards — <span id="student-count">{len(netids)} students</span></caption>
        <thead><tr><th class="staff-line-number" scope="col" aria-label="Line number"></th><th scope="col" data-sort="netid">NetID</th>
          <th scope="col" data-sort="firstName">First Name</th>
          <th scope="col" data-sort="lastName">Last Name</th>
          <th scope="col" data-sort="purple" class="staff-private" hidden>Total purple</th>
          <th scope="col" data-sort="missing" class="staff-private" hidden>Total missing</th>
          {headings}
          <th scope="col" data-sort="shiny" class="staff-private" hidden>Shiny overflow</th>
        </tr></thead>
        <tbody>
{links}
        </tbody>
      </table>
      </div>
      <p id="no-students" class="note" hidden>No matching students.</p>
    </section>
  </main>
  <script src="../simple-dashboard.js" defer></script>
</body>
</html>
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
    index_html = render_staff_index([student_dir.name for student_dir in student_dirs])

    written: list[Path] = []
    for student_dir in student_dirs:
        path = student_dir / ".htaccess"
        _replace_text_atomic(path, HTACCESS_TEMPLATE.format(netid=student_dir.name))
        written.append(path)
    _replace_text_atomic(
        output / "index.html",
        index_html,
    )
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
    expected_unmapped: tuple[str, ...] | None = None
    for index, record in enumerate(records):
        errors.extend(f"student {index}: {error}" for error in validate_combined_record(record))
        student = record.get("student") if isinstance(record, dict) else None
        netid = student.get("netid") if isinstance(student, dict) else None
        if isinstance(netid, str):
            if netid in seen:
                errors.append(f"duplicate NetID: {netid}")
            seen.add(netid)
        unmapped = record.get("unmapped_columns") if isinstance(record, dict) else None
        if isinstance(unmapped, list) and all(isinstance(item, str) for item in unmapped):
            current_unmapped = tuple(unmapped)
            if expected_unmapped is None:
                expected_unmapped = current_unmapped
            elif current_unmapped != expected_unmapped:
                errors.append("records disagree about unmapped Sheet columns")
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
        (staging / "index.html").write_text(
            render_staff_index([record["student"]["netid"] for record in records]),
            encoding="utf-8",
        )
        os.chmod(staging / "index.html", 0o640)
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
