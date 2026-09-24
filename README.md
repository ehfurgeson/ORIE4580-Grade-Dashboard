# ORIE 4580 Grade Dashboard

A small Zola frontend and Python publishing pipeline for the Fall 2026 standards-based grade dashboard. The UI allocates green, purple, and shiny-purple checkmarks to the syllabus checkbox system and shows the first currently satisfied grading threshold.

> **Deployment status:** the combined Google Sheets + Gradescope + Exam 1 pipeline passed a class-scale staging refresh for 174 unique NetIDs and all generated schema-v4 records validated. Deploy one manual Ubuntu refresh and pass the owner/cross-user/TA/`zivscully`/`ehf38` Shibboleth authorization matrix before enabling the production timer.

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

For a real manual export, save the private file under the ignored `imports/` directory and generate only into the ignored `generated/` directory. Never commit either directory. The live API client uses only the `spreadsheets.readonly` OAuth scope. Copy `.env.example` to the ignored `.env`, set `GOOGLE_APPLICATION_CREDENTIALS` to the service-account JSON's absolute path, set `GOOGLE_SHEET_ID`, enable the Google Sheets API in that credential's Cloud project, and share the sheet with the service-account email as Viewer. Then run:

```sh
rm -rf generated/google-api-test
python -m scripts.import_google_sheet_api generated/google-api-test
```

The client discovers the worksheet title from worksheet ID `0`, never logs cell values, sends the rows through the same adapter and validation, and writes only under the ignored output directory.

### Local Gradescope adapter

A read-only, local-only adapter is implemented in `sync/gradescope.py` and `scripts/import_gradescope.py`. It uses pinned `gradescope-tool==0.1.4` to authenticate to Gradescope's unofficial private web interface, then validates the structured `AssignmentSubmissionViewer` properties for every current and historical submission. It does not use free-form autograder output or the package's broken `scores.csv` parser.

Copy `deployment/gradescope.toml.example` to an ignored path such as `imports/gradescope/config.toml`, then configure an explicit course allowlist and one assignment rule per checkmark opportunity. Every rule contains a contract version, expected full score, exact test count, and exact ordered test-maxima vector. The role allowlists and roster minimum must also be confirmed from a live structural probe; the observed student role is `"0"`. Credentials stay in the ignored `.env` file:

```dotenv
GRADESCOPE_EMAIL=staff-account@example.edu
GRADESCOPE_PASSWORD=use-a-secret-store-in-production
```

Run one local canary first. Canary mode requires `--no-carry-forward` and a new output path so it cannot replace a full snapshot:

```sh
python -m scripts.import_gradescope \
  imports/gradescope/config.toml \
  generated/gradescope-canary.json \
  --student-netid abc123 \
  --no-carry-forward
```

The normalized output contains only NetIDs, opportunity IDs, statuses, aggregate submission counts, and minimal pass-evidence provenance. It does not retain emails, member/submission IDs, HTML, source files, scores, cookies, CSRF tokens, or autograder output. A student passes an opportunity only when one individual current or historical submission is processed, has no autograder error, has the configured test count and score contract, and earns full credit on every required test. Tests from different submissions are never combined.

Normal repeated runs should omit `--no-carry-forward`. A prior verified pass is then preserved when the course and assignment contract are unchanged, protecting the “ever passed” rule from later private-history truncation. A changed contract aborts and requires an explicit migration. The adapter enforces timeouts, bounded GET retries, request pacing, request/response/roster/history limits, same-origin redirects, strict schema checks, mode-600 atomic output, and last-known-good preservation on failure.

### Local combined dashboard canary

Schema version 3 combines the normalized Gradescope snapshot with the existing Google Sheet opportunities. Each opportunity displays two independent requirements: **Manual checkoff** and **Autograder**. A green checkmark is complete only when the aggregated manual sheet status is complete and at least one full historical Gradescope submission passed.

Gradescope Lab titles are mapped by the reviewed convention `Lab N, QN` or `Lab N, QN-N`. In particular, `Lab 1, Q1-2` maps to the one `lab1-q1-2` opportunity that aggregates the three sheet columns `Lab 1 - Q1.3`, `Lab 1 - Q2.3`, and `Lab 1 - Q2.4`. Other recognized titles map one-to-one. Non-Lab assignments are ignored because they are not allowlisted. Malformed, unknown, duplicate, or conflicting Lab mappings fail closed. A reviewed config can set `title_mapping_override = true` as an explicit fallback; there is no fuzzy matching.

The deployment-path refresh command can build a one-student local preview directly. By default it derives the canary NetID from `GRADESCOPE_TEST_STUDENT_EMAIL` in `.env`:

```sh
rm -rf generated/combined-env-preview
python -m scripts.refresh_combined_dashboard \
  imports/gradescope/config.toml \
  generated/combined-env-preview/students \
  generated/combined-env-state.json \
  --worksheet-id 41104109 \
  --spreadsheet-id 1e_5BQpysMUWfKrNw4MS7qg--2TySAno8rCBmuKapiME \
  --copy-assets-to generated/combined-env-preview
python -m http.server 8000 --bind 127.0.0.1 --directory generated/combined-env-preview
```

Open `http://localhost:8000/students/<fake-netid>/`. This path is strict: every current sheet opportunity must have exactly one configured Lab assignment, the selected student must occur in both sources, and any fetch, contract, mapping, or validation error prevents publication. `scripts.build_combined_canary` remains available only for diagnostics where unconfigured opportunities need to be displayed explicitly.

For production, the same command uses `--all-students --allow-missing-gradescope-students`. Google Sheets is the authoritative dashboard roster. Any Google student absent from Gradescope still receives a protected dashboard, but every autograder requirement is `not_found` and earns no checkmark. This one-way mismatch is unbounded so later Gradescope roster removals do not block refreshes. A Gradescope student absent from Google still aborts. The configured minimum canonical Gradescope roster size also remains a separate guard against a severely truncated response.

The supplied systemd service receives the Gradescope login, Google service-account key, and Gradescope config through systemd's per-service credential directory. It keeps normalized pass-history state under `/var/lib/orie4580-dashboard/` and atomically replaces the protected `students/` tree only after the strict Lab sources and merge validate. It retains one hidden previous student tree for manual rollback. systemd prevents concurrent starts of the same oneshot service.

Use the dedicated, non-login `orie4580-dashboard` system account from the unit. This prevents ordinary interactive accounts—including `ehf38`—from reading the short-lived runtime credential files. Root-owned source credentials remain mode `0600`. As with every server-side secret, a user with `root` or unrestricted `sudo` can still retrieve it; Linux cannot hide a service credential from the administrator who controls that service.

### Optional Exam 1 results

Schema version 4 adds the six Exam 1 question results to the same protected dashboard. The checked-in Gradescope config allowlists assignment `Exam_1`. Each question must appear in the Gradescope CSV export as exactly 1 point. A numeric score strictly greater than `0.8` earns its configured purple or shiny-purple checkmark; exactly `0.8` does not. Questions 1, 2, and 6 map to S2. Questions 3, 4, and 5 map to S1. Questions 5 and 6 are shiny purple.

Exam ingestion is deliberately soft-failing while the professor finalizes the rubric. A missing assignment, changed title, missing or non-1-point question column, nonnumeric/out-of-range score, duplicate student, or unavailable export converts all Exam 1 entries to **Not available yet** and does not block the strict Lab refresh. Raw question scores are never written to student JSON. Lab source, contract, roster, and merge errors still fail closed and preserve the prior release.

## Simple NetID-protected checkoff dashboard

The protected worksheet dashboard maps each known checkoff column to the standard named in the Lab 1–3 handouts. The mapping lives in `sync/checkoff_mappings.py`; unknown columns fail closed so a new lab cannot be silently assigned to the wrong standard. Multi-column opportunities are aggregated explicitly: the three recorded Lab 1 Q1–2 milestones produce one S1 green checkmark and all must be complete. Generated schema-version-2 records retain the source requirements for auditability.

The handouts’ displayed `S1`/`S2`/`S3` labels conflict with the older tentative category IDs in `sync/standards.py`. The live pipeline therefore joins on stable semantic keys (`uniform_samplers`, `general_1d_sampler`, and `simulation_output_variability`) and uses the handout IDs only for display. See §17 of `notes.md` for the full mapping and the Lab 3 wording note.

Each generated NetID directory contains its own HTML, JSON, and authorization rule. Access is granted to the student owner, the explicit staff users.

```text
students/ehf38/
├── index.html
├── checkoffs.json
└── .htaccess   # owner OR explicit staff list OR EN-OR-or4580-ta
```

Generate only the authorized bottom-row test account from the real `Lab Checkoffs` worksheet:

```sh
rm -rf generated/simple-ehf38
python -m scripts.import_simple_google_sheet_api \
  generated/simple-ehf38/students \
  --spreadsheet-id 1e_5BQpysMUWfKrNw4MS7qg--2TySAno8rCBmuKapiME \
  --worksheet-id 41104109 \
  --student-id ehf38
```

The command validates the entire worksheet but publishes only `ehf38`. Publishing every row requires the explicit `--all-students` flag and must wait until the two-user access matrix passes. Unknown checkbox values, unsafe NetIDs, and duplicate NetIDs fail closed.

For the initial server test, deploy `static/simple-dashboard.js` and `static/simple-style.css` as public assets under the course root, then copy the generated `ehf38` directory—including its dotfile—to the server's private `students/` tree. Open:

```text
https://zivscully.orie.cornell.edu/orie4580_fa26/students/ehf38/
```

Apache must read `.htaccess`, `index.html`, and `checkoffs.json`; the generated files use group-readable modes so deployment must assign the web-server group. Confirm `AllowOverride` permits the auth/header rules and `Options -Indexes`. Do not use a copy glob that drops `.htaccess`. The standards dashboard and its files remain unchanged.

### Production credentials with systemd

The unit requires systemd 247 or newer (`systemd --version`). Create a dedicated non-login account and root-only credential sources:

```sh
sudo useradd --system --no-create-home --home-dir /nonexistent \
  --shell /usr/sbin/nologin --gid www-data orie4580-dashboard
sudo install -d -o root -g root -m 0700 /etc/orie4580-dashboard
sudo install -o root -g root -m 0600 \
  deployment/gradescope.toml.example /etc/orie4580-dashboard/gradescope.toml
sudo install -o root -g root -m 0600 \
  /secure/source/google-service-account.json \
  /etc/orie4580-dashboard/google-service-account.json
```

Enter the Gradescope login without placing the password in shell history:

```sh
read -r -p 'Gradescope email: ' GS_EMAIL
read -r -s -p 'Gradescope password: ' GS_PASSWORD; echo
printf '%s\n' "$GS_EMAIL" | sudo tee /etc/orie4580-dashboard/gradescope-email >/dev/null
printf '%s\n' "$GS_PASSWORD" | sudo tee /etc/orie4580-dashboard/gradescope-password >/dev/null
unset GS_EMAIL GS_PASSWORD
sudo chown root:root /etc/orie4580-dashboard/gradescope-email \
  /etc/orie4580-dashboard/gradescope-password
sudo chmod 0600 /etc/orie4580-dashboard/gradescope-email \
  /etc/orie4580-dashboard/gradescope-password
```

`LoadCredential=` copies these files into a private, read-only credential directory only for the service invocation. The Python process reads the email and password from files, not environment values. Do not use `Environment=GRADESCOPE_PASSWORD=...`, an environment file containing the password, command-line arguments, Git, or the journal.

Prepare the existing site root for atomic replacement by the dedicated publisher while keeping Apache read access:

```sh
SITE=/var/www/html/orie4580_fa26
sudo chown orie4580-dashboard:www-data "$SITE"
sudo chmod 2750 "$SITE"
# The publisher must be able to retain and later remove the previous release.
sudo chown -R orie4580-dashboard:www-data "$SITE/students"
if [ -d /var/lib/orie4580-dashboard ]; then
  sudo chown -R orie4580-dashboard:www-data /var/lib/orie4580-dashboard
  sudo chmod 0700 /var/lib/orie4580-dashboard
fi
```

Copy the reviewed unit, reload systemd, and test one manual run before touching the timer:

```sh
sudo install -o root -g root -m 0644 deployment/orie4580-checkoffs.service \
  /etc/systemd/system/orie4580-checkoffs.service
sudo install -o root -g root -m 0644 deployment/orie4580-checkoffs.timer \
  /etc/systemd/system/orie4580-checkoffs.timer
sudo systemctl daemon-reload
sudo systemctl start --no-block orie4580-checkoffs.service
sudo journalctl -fu orie4580-checkoffs.service
```

`--no-block` returns control immediately. The journal reports each phase, then aggregate progress after student 1, every 10 students, and the final student. It never logs NetIDs, emails, scores, or submission identifiers. Press `Ctrl-C` to stop following the journal; this does not stop the service. In another shell, check the current state with:

```sh
sudo systemctl status orie4580-checkoffs.service
sudo systemctl show orie4580-checkoffs.service -p ActiveState -p SubState -p Result -p ExecMainStatus
```

A full run can take several minutes because requests are paced and historical submissions are checked. `activating (start)` is normal during the crawl. Success ends as an inactive oneshot with `Result=success` and `ExecMainStatus=0`.

Inspect one owner page and repeat the authorization matrix: owner allowed; another student denied; a member of `EN-OR-or4580-ta` allowed; each explicit staff user (`zivscully`, `ehf38`, `jrf298`, `tm693`, `as4268`, `mw2244`, and `zds22`) allowed; and an authenticated user in none of those categories denied. The TA test also confirms that Shibboleth is actually releasing the `groups` attribute to this service provider. Only then enable the schedule:

```sh
sudo systemctl enable --now orie4580-checkoffs.timer
```

### Authorization-only update

Staff authorization can be updated without fetching Google Sheets or Gradescope and without changing any HTML or JSON:

```sh
sudo -u orie4580-dashboard \
  /opt/orie4580-grade-dashboard/.venv/bin/python \
  -m scripts.update_dashboard_authorization \
  /var/www/html/orie4580_fa26/students
```

The command validates all student directory names before writing, atomically replaces each per-student `.htaccess`, and updates the protected parent index rule last. It is intended for narrow authorization changes; normal refreshes continue to generate the same rules automatically.

### Scheduled refresh

After the owner/staff authorization tests pass and the full simple site replaces the old document root, Ubuntu can refresh the sheet with the supplied systemd unit and timer:

```text
deployment/orie4580-checkoffs.service
deployment/orie4580-checkoffs.timer
```

The timer runs every three hours with a randomized delay and persistent catch-up after downtime. The service uses `--all-students --allow-missing-gradescope-students`; enable it only after the successful manual run and authorization matrix. There is no NetID-entry landing page. Install `apache/course-root-redirect.conf` inside the active HTTPS virtual host so Shibboleth authenticates the course-root request and Apache redirects from trusted `REMOTE_USER` to the matching generated student directory. Keep the per-student `.htaccess` authorization in place.

The importer fetches and validates the complete sheet before replacing the generated tree. A fetch or validation failure leaves the previous release intact. Check runs with:

```sh
sudo systemctl status orie4580-checkoffs.service
sudo journalctl -u orie4580-checkoffs.service
systemctl list-timers orie4580-checkoffs.timer
```

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
