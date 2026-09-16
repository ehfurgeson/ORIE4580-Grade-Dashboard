# ORIE 4580 Grade Dashboard

A small Zola frontend and Python publishing pipeline for the Fall 2026 standards-based grade dashboard. The UI allocates green, purple, and shiny-purple checkmarks to the syllabus checkbox system and shows the first currently satisfied grading threshold.

> **Deployment status:** the local MVP and a protected single-user fake-data test work. Do not publish real student data yet. Dynamic per-student Shibboleth authorization and the student/TA access matrix are still pending.

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
- `kind`: `green` for a lab, `purple` for an exam/exam-like opportunity, or `shiny_purple` for a challenging purple problem.
- `status`: `complete`, `incomplete`, `not_graded`, or `excused`.

Only `complete` earns a checkmark. For each standard, two linked boxes are filled in priority order: purple, shiny purple, then green. Extra ordinary purple and green checkmarks do not count. Every shiny purple not selected for a linked box fills an unlimited shiny box. A shiny purple counts in the purple and shiny totals whether it occupies a linked or shiny box, but it occupies only one box. Missing is the number of empty standard-linked boxes.

The grade calculation checks A+ through C in order. Every threshold is interpreted as “at least,” except missing is “at most.” In particular, A+ requires `floor(2n)` purple and `n - 1` shiny purple; A requires `floor(1.5n)` purple and one shiny purple. The displayed result is an estimate, not an official grade, and the syllabus says conditions may be made easier.

Validate and atomically replace each generated JSON file with:

```sh
python -m scripts.sync_grades records.json generated/students
```

The command validates and serializes the whole input batch before it writes. A machine-level I/O failure can still leave a mixed-version batch, so publish from a staged release rather than treating this command as a transactional deployment.

### Google Sheets adapter

`sync.google_sheets.rows_to_records` accepts one standard per row. The required columns are `updated_at`, `course`, `student_id`, `student_name`, and `standard_id`. Rows with an opportunity also use `opportunity_id`, `opportunity_label`, `source`, `kind`, and `status`. Use additional rows when one standard has multiple opportunities; a standard with no opportunity still needs one row with the opportunity columns empty.

Test the complete CSV-export path with fake data:

```sh
rm -rf generated/google-sheet-test
python -m scripts.import_google_sheet_csv \
  fixtures/google-sheet.fake.csv \
  generated/google-sheet-test
```

For a real manual export, save the private file under the ignored `imports/` directory and generate only into the ignored `generated/` directory. Never commit either directory. The next live step is a read-only Google Sheets API client using credentials stored outside the repository; the existing row adapter and downstream validation will remain unchanged.

Gradescope integration is not implemented yet. Prefer a supported CSV export or documented API over an unofficial endpoint, and establish its exact column format with fake or redacted data before adding credentials.

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
