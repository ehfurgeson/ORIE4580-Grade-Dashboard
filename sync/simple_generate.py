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
from .examiner_exports import merge_review
from .local_grades import load_local_grades


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


# Deny the actual files, including guessed URLs; collecting them is still allowed.
EXAM3_HIDDEN_RULE = '\n<FilesMatch "^exam3\\.(json|pdf)$">\n    Require all denied\n</FilesMatch>\n'
EXAM_RETRY_HIDDEN_RULE = EXAM3_HIDDEN_RULE.replace('exam3', 'exam_retry')
# Each exam review's JSON and its scan; both are preserved across rebuilds.
REVIEW_PDFS = {'exam3.json': 'exam3.pdf', 'exam_retry.json': 'exam_retry.pdf'}

def render_staff_index(netids: list[str]) -> str:
    """Render a protected staff index from validated canonical NetIDs."""
    if not netids or any(not NETID_PATTERN.fullmatch(netid) for netid in netids):
        raise ValueError("staff index requires validated Cornell NetIDs")
    if len(netids) != len(set(netids)):
        raise ValueError("staff index NetIDs must be unique")
    roster = load_staff_roster()
    roster_headings = ''
    if roster is not None:
        netids = [netid for netid in netids if netid in roster.rows]
        roster_headings = ''.join(
            f'<th scope="col" data-sort="roster{index}" data-roster-column>{escape(label)}</th>'
            for index, label in enumerate(roster.columns)
        )
    headings = ''.join(
        f'<th scope="col" class="staff-private" data-standard="{standard_id}" hidden '
        f'title="{escape(name, quote=True)}">{standard_id}</th>'
        for standard_id, name in STANDARDS.items()
    )
    rows = []
    for netid in sorted(netids):
        fields = roster.rows[netid] if roster is not None else ()
        cells = ''.join(f'<td class="staff-roster-value">{escape(value)}</td>' for value in fields)
        rows.append(
            f'<tr data-netid="{netid}">'
            f'<td class="staff-line-number"></td><th scope="row"><a href="./{netid}/">{netid}</a></th>'
            f'{cells}</tr>'
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
  <link rel="stylesheet" href="../course-nav.css">
  <script src="../course-nav.js" defer></script>
</head>
<body>
  <main class="course-page simple-container staff-container" id="staff-index">
    <header class="course-header">
      <p class="eyebrow">ORIE 4580</p>
      <h1>Student dashboards</h1>
      <nav class="course-nav" aria-label="Course" data-root="../">
        <a data-page="dashboard" aria-disabled="true">Dashboard</a>
        <a data-page="exam3" aria-disabled="true" title="Open a student dashboard to view Exam 3">Exam 3</a>
        <a data-page="exam_retry" aria-disabled="true" title="Open a student dashboard to view Exam Retry">Exam Retry</a>
        <a data-page="calculator" href="../grade_calculator/">Grade calculator</a>
      </nav>
    </header>
    <p class="page-intro">Protected staff index. Select a NetID to open that student's dashboard.</p>
    <section aria-labelledby="student-list-title">
      <h2 id="student-list-title">Students ({len(netids)})</h2>
      <div class="staff-controls">
        <label for="student-search">Search students
          <input id="student-search" type="search" autocomplete="off" spellcheck="false" placeholder="e.g. abc123">
        </label>
        <button id="toggle-checkmarks" type="button" aria-expanded="false" aria-controls="student-table" disabled>Show checkmarks</button>
      </div>
      <p id="staff-status" class="note">Checkmarks start hidden. Click Show/Hide checkmarks to toggle them; Escape or switching tabs hides them.</p>
      <noscript><p>Enable JavaScript to search and show checkmarks.</p></noscript>
      <div class="staff-table-scroll" role="region" aria-label="Student summaries">
      <table id="student-table" class="staff-table">
        <caption class="note">Student dashboards — <span id="student-count">{len(netids)} students</span></caption>
        <thead><tr><th class="staff-line-number" scope="col" aria-label="Line number"></th><th scope="col" data-sort="netid">NetID</th>
          {roster_headings}
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
  <script src="../exam-review.js" defer></script>
  <script src="../simple-dashboard.js?v=roster-columns-2" defer></script>
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
        existing = path.read_text()
        hidden_rules = ''.join(rule for rule in (EXAM3_HIDDEN_RULE, EXAM_RETRY_HIDDEN_RULE) if rule in existing)
        _replace_text_atomic(path, HTACCESS_TEMPLATE.format(netid=student_dir.name) + hidden_rules)
        written.append(path)
    _replace_text_atomic(
        output / "index.html",
        index_html,
    )
    parent_rule = output / ".htaccess"
    _replace_text_atomic(parent_rule, STUDENTS_HTACCESS)
    written.append(parent_rule)
    return written


def _exam_pdfs(root: Path) -> dict[str, Path]:
    if root.is_symlink():
        raise ValueError("Exam PDFs must come from a real directory")
    try:
        files = list(root.iterdir())
    except FileNotFoundError:
        return {}
    except NotADirectoryError:
        raise ValueError("Exam PDFs must come from a real directory") from None
    pdfs = {}
    for path in files:
        if path.suffix.lower() == '.pdf':
            if path.is_symlink() or not path.is_file() or path.stem in pdfs:
                raise ValueError("Exam PDFs must have unique submission filenames and be regular files")
            pdfs[path.stem] = path
    return pdfs


def _stage_exam_review(previous: Path, target: Path, review: str, pdf: str,
                       incoming: dict | None, pdf_sources: dict[str, Path], *,
                       published_at: str, replace: bool, require_pdf: bool, refresh_pdf: bool) -> None:
    old_review, old_pdf = previous / review, previous / pdf
    for path in (old_review, old_pdf):
        if path.is_symlink() or (path.exists() and (previous.is_symlink() or not path.is_file())):
            raise ValueError("Existing exam review must be a regular protected file")
    target_review, target_pdf = target / review, target / pdf
    if incoming is None:
        if old_review.is_file():
            shutil.copyfile(old_review, target_review)
            target_review.chmod(0o640)
        if old_pdf.is_file():
            os.link(old_pdf, target_pdf)
            target_pdf.chmod(0o640)
        return

    saved = json.loads(old_review.read_text(encoding='utf-8')) if old_review.is_file() else None
    document = merge_review(saved, incoming) if saved is not None and not replace else incoming
    if document is saved:
        shutil.copyfile(old_review, target_review)
    else:
        target_review.write_text(_payload({**document, 'published_at': published_at}), encoding='utf-8')
    target_review.chmod(0o640)

    identifier = document['student']['id']
    if old_pdf.is_file() and saved is not None and saved.get('student', {}).get('id') == identifier and not refresh_pdf:
        os.link(old_pdf, target_pdf)
        target_pdf.chmod(0o640)
    elif identifier in pdf_sources:
        shutil.copyfile(pdf_sources[identifier], target_pdf)
        target_pdf.chmod(0o640)
    elif require_pdf:
        raise ValueError(f"Missing exam PDF for submission {identifier}")


def write_simple_release(
    records: list[dict[str, Any]],
    output_dir: str | Path,
    *,
    template_path: str | Path = "templates/simple_student_dashboard.html",
    retain_previous: bool = False,
    examiner_exports: str | Path | None = None,
    exam3_visible: bool = False,
    exam_retry_visible: bool = False,
    local_grades: str | Path | None = None,
    local_grade_sources: dict[Path, Path] | None = None,
    examiner_pdfs: str | Path | None = None,
    refresh_examiner_pdfs: bool = False,
    local_imported_at: str | None = None,
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

    if sum(source is not None for source in (local_grades, examiner_exports, local_grade_sources)) > 1:
        raise ValueError("Choose one local grades import mode")
    local_documents = {}
    pdf_sources = {}
    source_path = local_grades if local_grades is not None else examiner_exports
    if refresh_examiner_pdfs and examiner_pdfs is None:
        raise ValueError("Refreshing PDFs requires an exam PDF directory")
    if examiner_pdfs is not None and source_path is None:
        raise ValueError("PDF import requires a local grades source")
    sources: dict[Path, Path | None] = dict(local_grade_sources or {})
    if source_path is not None:
        sources[Path(source_path)] = Path(examiner_pdfs) if examiner_pdfs is not None else None
    destination = Path(output_dir).resolve()
    legacy = examiner_exports is not None
    for source, pdf_root in sources.items():
        for path in (p.resolve() for p in (source, pdf_root) if p is not None):
            if path.is_relative_to(destination) or destination.is_relative_to(path):
                raise ValueError("Local exam sources and student output must be separate trees")
        documents = load_local_grades(source, seen, allow_empty_exam3=legacy, optional=not legacy)
        if local_documents.keys() & documents.keys():
            raise ValueError("Configure one local grades source per exam")
        local_documents.update(documents)
        if pdf_root is not None and documents:
            pdf_sources[next(iter(documents))] = _exam_pdfs(pdf_root)

    template = Path(template_path).read_text(encoding="utf-8")
    exam_template = (Path(__file__).resolve().parents[1] / "templates" / "exam3_student_review.html").read_text(encoding="utf-8")
    # Exam Retry's page is Exam 3's, pointed at its own files.
    retry_template = (exam_template.replace('data-exam="3"', 'data-exam="retry"')
                      .replace('exam3.json', 'exam_retry.json').replace('exam3.pdf', 'exam_retry.pdf')
                      .replace('<title>Exam 3', '<title>Exam Retry')
                      .replace('<h1>Exam 3</h1>', '<h1>Exam Retry</h1>'))
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
            for review, pdf in REVIEW_PDFS.items():
                incoming = local_documents.get(review, {}).get(netid)
                if legacy and review in local_documents and incoming is None:
                    continue
                _stage_exam_review(output / netid, student_dir, review, pdf, incoming,
                                   pdf_sources.get(review, {}), published_at=local_imported_at or record['updated_at'],
                                   replace=legacy, require_pdf=examiner_pdfs is not None,
                                   refresh_pdf=refresh_examiner_pdfs)
            (student_dir / "index.html").write_text(template, encoding="utf-8")
            for exam_dir, page in ((student_dir / "exam3", exam_template), (student_dir / "exam_retry", retry_template)):
                exam_dir.mkdir(mode=0o750)
                (exam_dir / "index.html").write_text(page, encoding="utf-8")
                os.chmod(exam_dir / "index.html", 0o640)
            (student_dir / "checkoffs.json").write_text(_payload(record), encoding="utf-8")
            (student_dir / ".htaccess").write_text(
                HTACCESS_TEMPLATE.format(netid=netid) + ("" if exam3_visible else EXAM3_HIDDEN_RULE)
                + ("" if exam_retry_visible else EXAM_RETRY_HIDDEN_RULE), encoding="utf-8"
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
