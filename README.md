# ORIE 4580 Grade Dashboard

A small Zola frontend and Python publishing pipeline for the Fall 2026 standards-based grade dashboard. The UI shows green lab checkmarks, purple exam or exam-like checkmarks, progress toward two checkmarks per standard, and the first currently satisfied threshold in the tentative syllabus scale.

> **Deployment status:** local fake-data MVP. Do not publish real student data yet. Per-student Shibboleth authorization and the student/TA access matrix are still pending.

## Requirements

- Python 3.11 or newer
- [Zola](https://www.getzola.org/) 0.23

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m pytest -q
zola check
```

## Local demo

The `static/students/` tree is ignored because anything under `static/` is copied into the public build. Use only the fake fixture there during local development:

```sh
mkdir -p static/students/me
cp fixtures/grades.json static/students/me/grades.json
zola serve
```

Remove it before a production build:

```sh
rm -rf static/students
zola build
```

The browser requests the relative URL `students/me/grades.json`, so local and staging builds do not contact the production site.

## Data model and grading rules

`fixtures/grades.json` is the canonical example. `fixtures/ehf38-grades.fake.json` is clearly labeled fake data for the first authenticated server test. Each record contains:

- `course`: `ORIE 4580`, `ORIE 5580`, or `ORIE 5581`.
- `standards`: all 12 syllabus standards for 4580/5580, or an evaluated subset for 5581.
- `kind`: `green` for a lab or `purple` for an exam/exam-like opportunity.
- `status`: `complete`, `incomplete`, `not_graded`, or `excused`.

Only `complete` earns a checkmark. `not_graded` and `excused` remain visible but do not count. “Missing” is `sum(max(0, 2 - earned checkmarks))` across evaluated standards. The displayed grade estimate checks the syllabus rules from A+ through C in order and uses the required floor operations. It is labeled tentative and is not an official grade.

Validate and atomically replace each generated JSON file with:

```sh
python -m scripts.sync_grades records.json generated/students
```

The command validates and serializes the whole input batch before it writes. A machine-level I/O failure can still leave a mixed-version batch, so publish from a staged release rather than treating this command as a transactional deployment.

### Google Sheets adapter

`sync.google_sheets.rows_to_records` accepts one standard per row. The required columns are `updated_at`, `course`, `student_id`, `student_name`, and `standard_id`. Rows with an opportunity also use `opportunity_id`, `opportunity_label`, `source`, `kind`, and `status`. The API client and credentials are intentionally outside this repository. Gradescope integration is not implemented yet.

## Production security gate

Grades are FERPA-sensitive. Zola must own presentation, Python must own data, and Apache/Shibboleth must own authentication and authorization. Never place real grade JSON in `static/`, `public/`, or Git.

The previously tested rule below proves login only; it does **not** provide per-student privacy:

```apache
AuthType shibboleth
ShibRequestSetting requireSession 1
Require valid-user
```

Before real deployment, the server configuration must:

1. Map `students/me/grades.json` to the authenticated, trusted `REMOTE_USER`/NetID.
2. Deny direct access to another student's predictable path.
3. Allow authorized course staff through a separate rule.
4. Send `Cache-Control: private, no-store` for grade JSON.
5. Keep generated data outside the Zola output and publish it with restrictive ownership and permissions.
6. Pass this server-side test matrix: anonymous denied; student A→A allowed; A→B denied; B→A denied; TA→A/B allowed.

Do not infer authorization in JavaScript. A course-wide AD group is useful for site access, but it is not enough to protect individual grades.

## Repository layout

```text
apache/               Temporary fake-data authorization test configuration
config.toml           Canonical Zola configuration (`zola.toml` is a compatibility symlink)
content/              Zola content entry point
templates/            Dashboard HTML
static/               Public CSS and JavaScript only
fixtures/              Fake grade record
sync/                  Validation, grading, adapters, and generation
scripts/sync_grades.py JSON generation CLI
tests/                 Python tests
```

Run `python -m pytest -q && zola check` before sharing or deploying changes.
