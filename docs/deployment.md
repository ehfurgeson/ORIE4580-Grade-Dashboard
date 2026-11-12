# Ubuntu Deployment

For the current Lab 8/9 release, follow [Lab 8 and Lab 9 activation](#lab-8-and-lab-9-activation) before the first refresh, including private publication-state migration and Gradescope snapshot retirement.

For an existing installation using `exam2-publication.json`, follow the
[shared publication-state rename](exam-publication-migration.md) before restarting refreshes.

For Examiner review exports on the same refresh timer, see [Examiner publication](examiner-publication.md).

This guide covers the shortest safe release procedure for the existing ORIE 4580 Ubuntu server. For source mappings and future dashboard changes, see [`maintenance.md`](maintenance.md).

## 1. Current production layout

| Purpose | Path or unit |
|---|---|
| Application checkout | `/opt/orie4580-grade-dashboard` |
| Protected web root | `/var/www/html/orie4580_fa26` |
| Private Gradescope config | `/etc/orie4580-dashboard/gradescope.toml` |
| Other private credentials | `/etc/orie4580-dashboard/` |
| Private snapshot and positive cache | `/var/lib/orie4580-dashboard/` |
| Refresh service | `orie4580-checkoffs.service` |
| Three-hour timer | `orie4580-checkoffs.timer` |

Real student JSON must never be copied into Git, `static/`, or `public/`.

## Rebuild presentation from saved data

After pulling code, run from `/opt/orie4580-grade-dashboard`:

```sh
sudo sh scripts/rebuild_dashboard.sh
```

This installs all shared assets and the calculator, then regenerates the staff
index, student dashboards, and Exam 3 page shells. It preserves both visibility
settings and existing Exam 3 JSON/PDF files. It holds the normal refresh lock and
refuses to run while a refresh is active. No timer pause is needed.

It does not pull Git, run Examiner exports, import new export batches, or fetch
Google/Gradescope data. Use the normal refresh service to collect new data.
Hard-refresh the browser afterward. Assets and pages are installed sequentially,
so this is a presentation deployment, not an atomic whole-site rollback mechanism.

## 2. Minimal deployment for an existing server

The normal release path is Git plus one production refresh. The publisher builds the full replacement first and swaps it into place only after validation, so a failed refresh preserves the current student tree.

### 2.1 Before connecting to Ubuntu

On the development machine:

```sh
.venv/bin/pytest -q
node --check static/simple-dashboard.js
zola check
git diff --check
git status --short
```

Review, commit, and push the tracked changes:

```sh
git add README.md docs deployment fixtures scripts static sync templates tests
git commit -m "Add Lab 8 and Lab 9 dashboard mappings"
git push origin main
```

### 2.2 Update Ubuntu

Connect to the server:

```sh
ssh en-or-scully.orie.cornell.edu
```

Stop only the timer. This prevents it from starting a refresh halfway through the update:

```sh
sudo systemctl stop orie4580-checkoffs.timer
cd /opt/orie4580-grade-dashboard
git status --short
git pull --ff-only origin main
```

Do not continue if the checkout has unexpected local changes or the pull is not fast-forward.

No dependency changed for Labs 8/9. For a future release that changes `requirements.txt`, run:

```sh
.venv/bin/python -m pip install -r requirements.txt
```

Install the reviewed Gradescope allowlist and the browser assets. These copies are required because student pages load them from the web root; the refresh service replaces `students/` but does not copy root assets. For the schema-6 rollout, install both JavaScript and CSS before the first refresh so the active browser can validate and display `unmapped_columns`.

```sh
sudo install -o root -g root -m 0600 \
  deployment/gradescope.toml.example \
  /etc/orie4580-dashboard/gradescope.toml
sudo install -o root -g www-data -m 0644 \
  static/simple-dashboard.js \
  /var/www/html/orie4580_fa26/simple-dashboard.js
sudo install -o root -g www-data -m 0644 \
  static/simple-style.css \
  /var/www/html/orie4580_fa26/simple-style.css
sudo install -o root -g www-data -m 0644 \
  static/checkmarks.css \
  /var/www/html/orie4580_fa26/checkmarks.css
```

Forward compatibility depends on that order: install schema-6 `simple-dashboard.js`, `simple-style.css`, and its shared `checkmarks.css`, then run the refresh that publishes schema-6 records. The new JavaScript deliberately tolerates schema-3–5 pages whose older HTML has no pending-mapping container during this rollout window. For rollback, use the reverse dependency order: restore the previous schema-3–5 student release first, then restore the previous JavaScript and CSS, and finally roll back the checkout/config as needed. Never serve schema-6 records to an older browser validator.

`load_config` is strict: a hand-edited `gradescope.toml` that omits
`seal_when_closed` on an assignment, or `seal_recheck_hours` under `[cache]`, is
rejected and the refresh fails closed. Re-copy the example file rather than
patching the installed one. Sealing itself is optional and off by default; see
[`maintenance.md`](maintenance.md#25-seal-a-closed-assignment).

Validate the checked-in configuration and source on Ubuntu:

```sh
.venv/bin/python -c \
  'from sync.gradescope import load_config; print(len(load_config("deployment/gradescope.toml.example").assignments))'
.venv/bin/pytest -q
```

For the Lab 5 release, the first command must still print `10`; Lab 5 has no Gradescope assignments. The Lab 6 release added two autograded assignments (`12` total). The current Lab 8/9 release adds Lab 9 Q1, so the first command must print `13`.

When a release changes the Gradescope assignment contract — a new autograded assignment, or a bumped contract version — retire the previous private snapshot before the first refresh. An unknown quarantined column and a mapped manual-only column do not change that contract: they need no Gradescope configuration, and the existing snapshot must not be retired merely because either appeared. The completion cache is invalid after a contract change, so the refresh falls back to `/var/lib/orie4580-dashboard/gradescope-snapshot.json` and aborts with `cannot carry pass evidence across a changed course or assignment contract` if that file still describes the previous contract. Moving it aside lets the full crawl become the new baseline and seed the cache:

```sh
sudo mv /var/lib/orie4580-dashboard/gradescope-snapshot.json \
  /var/lib/orie4580-dashboard/gradescope-snapshot.json.pre-contract-change
```

Lab 5 adds only manual-only columns, so the existing Gradescope snapshot remains compatible. Its mapping-version bump invalidates the positive completion cache, causing the first refresh to revalidate Lab pass history and rebuild that cache; this can take longer than later cached runs. Start one full atomic refresh and follow its progress:

```sh
sudo systemctl reset-failed orie4580-checkoffs.service
sudo systemctl start --no-block orie4580-checkoffs.service
sudo journalctl -fu orie4580-checkoffs.service
```

Press `Ctrl-C` after the completion message. This does not stop the service. Confirm success:

```sh
sudo systemctl show orie4580-checkoffs.service \
  -p ActiveState -p SubState -p Result -p ExecMainStatus
```

A successful oneshot ends with `ActiveState=inactive`, `Result=success`, and `ExecMainStatus=0`.

Check an owner page in the browser. Confirm that Lab 5 Q1, Q2, and Q3 each list only **Manual checkoff**, while the existing autograded opportunities still list **Manual checkoff** and **Autograder**. Review **Pending Sheet mappings** after every refresh. Pending headers must not appear under a standard, affect totals, show a checkmark, or expose raw cell values. Also check that a different student cannot open that page.

Adding a valid Sheet column alone no longer blocks publication. Leave it quarantined until course staff audit and backfill its existing cells, approve the standard and stable opportunity ID, and classify it explicitly as manual-only or autograded. Activating that mapping requires the normal `LAB_MAPPING_VERSION` bump. Only an autograded activation needs a Gradescope contract and its normal contract-version procedure.

Re-enable the schedule only after those checks pass:

```sh
sudo systemctl enable --now orie4580-checkoffs.timer
systemctl list-timers orie4580-checkoffs.timer
```

### One-time standard-ID cache migration

For the removal of descriptive standard keys and categories, the Google Sheet,
Gradescope assignments, production TOML config, and `gradescope-snapshot.json`
need no changes. Keep the snapshot in place. Install the updated
`static/simple-dashboard.js`, `static/simple-style.css`, `static/checkmarks.css`, `static/exam3-review.js`, and `static/exam3-review.css` at the web root before
the first refresh so the browser can read the new record schemas.

After stopping the timer and waiting for any running refresh to finish, update
the checkout and run this migration before starting the service. Use new output
and backup filenames if these already exist:

```sh
cd /opt/orie4580-grade-dashboard
sudo .venv/bin/python -m scripts.migrate_completion_cache \
  /etc/orie4580-dashboard/gradescope.toml \
  /var/lib/orie4580-dashboard/completion-cache.json \
  /var/lib/orie4580-dashboard/completion-cache.migrated.json
sudo cp -p /var/lib/orie4580-dashboard/completion-cache.json \
  /var/lib/orie4580-dashboard/completion-cache.pre-standard-ids.json
sudo install -o orie4580-dashboard -g www-data -m 0600 \
  /var/lib/orie4580-dashboard/completion-cache.migrated.json \
  /var/lib/orie4580-dashboard/completion-cache.json
```

The script makes no network requests. It accepts only the old
`lab-mapping-v2` / `exam1-mapping-v1` format, verifies its fingerprints and exact
contracts against the configured assignments, and writes a separate mode-0600
file. Completions and verification timestamps stay unchanged. If migration
fails, leave the original cache in place and inspect the mismatch before
installing anything. This historical migration applies to the earlier standard-ID
transition; do not use it for the Lab 5 mapping update. Lab 5 intentionally
rebuilds the existing `lab-mapping-v3` cache under `lab-mapping-v4` during the
first full refresh. The Lab 6 release does the same, rebuilding the
`lab-mapping-v4` cache under `lab-mapping-v5`.

Then perform the manual refresh and checks above before re-enabling the timer.
Cached positive Lab results avoid repeated submission-history reads; current
roster checks, uncached submissions, assignment canaries, Google Sheet reads,
and the Exam export still run normally.

### 2.3 If the refresh fails

Read the last service log:

```sh
sudo journalctl -u orie4580-checkoffs.service -n 200 --no-pager
```

Do not weaken a mapping or validation rule to make publication continue. The old student release remains active after a source, contract, validation, or publication failure. Fix the cause, rerun the tests, and start the service again. Re-enable the timer only after a successful manual run.

If the log ends with `cannot carry pass evidence across a changed course or assignment contract` after a full student crawl, the Gradescope crawl succeeded and the old snapshot still has the previous assignment contract. Retire that snapshot as in [2.2](#22-update-ubuntu), then start the service again.


## 3. Deployment checklist

- [ ] Local tests, JavaScript syntax, Zola, and `git diff --check` pass.
- [ ] Tracked changes are committed and pushed.
- [ ] The server checkout is clean and updated with a fast-forward pull.
- [ ] The reviewed Gradescope config and schema-compatible root JavaScript and CSS are installed before refresh.
- [ ] The previous private snapshot was retired only if the Gradescope assignment contract changed, not for an unknown or manual-only Sheet column.
- [ ] The manual production service run succeeds.
- [ ] Lab requirements render correctly; Pending Sheet mappings were reviewed and do not affect marks or totals.
- [ ] Owner, cross-user, and staff authorization checks pass.
- [ ] The timer is active only after validation.


## Grade calculator

The calculator source is `static/grade_calculator/index.html`. It loads shared
checkmark and navigation assets and reads no student data. Its intended public URL is
`https://zivscully.orie.cornell.edu/orie4580_fa26/grade_calculator/`.
The refresh service’s `--copy-assets-to` option and local canary builder copy
this page and its directory-scoped `.htaccess` alongside the dashboard assets.
The student dashboard links to this maintained copy. No separate hosted copy is needed.

Before an explicitly authorized publication, run locally:

```sh
node tests/grade_calculator.test.js
node --test tests/checkmark_geometry.test.cjs
git diff --check
```

After transferring the reviewed source to the server checkout, the following
commands install the calculator and its shared assets. They do not require a student refresh,
timer interruption, or changes to the course-root redirect:

```sh
cd /opt/orie4580-grade-dashboard
sudo install -o root -g www-data -m 0644 \
  static/checkmarks.css static/course-nav.css static/course-nav.js \
  /var/www/html/orie4580_fa26/
sudo install -d -o root -g www-data -m 0755 \
  /var/www/html/orie4580_fa26/grade_calculator
sudo install -o root -g www-data -m 0644 \
  static/grade_calculator/index.html \
  /var/www/html/orie4580_fa26/grade_calculator/index.html
sudo install -o root -g www-data -m 0644 \
  static/grade_calculator/.htaccess \
  /var/www/html/orie4580_fa26/grade_calculator/.htaccess
```

The checked-in `apache/course-root-redirect.conf` matches only the exact course
root, so this subdirectory does not need a redirect exception. Apache should
serve its `index.html` through the existing `DirectoryIndex` configuration.
The calculator’s `.htaccess` disables inherited authentication only in its own
directory, permits public access, and disables directory listing. Apache must
allow these overrides (`AuthConfig`, `Options`, and `Indexes`).
Inspect the active virtual host and any inherited authentication rules before
publication: the calculator should be public, while `students/` retains all
existing authorization rules. Do not loosen course-wide or student rules to
serve the calculator.

After publication, verify an unauthenticated GET returns HTTP 200 and the
calculator HTML at the intended URL, without redirecting to Shibboleth or a
student dashboard. Check that the existing course-root redirect and protected
student URLs still behave as before. No server changes have been made merely
by adding these instructions.

## Exam 2: pre-collect and switch visibility at lecture time

This is separate from publishing grades in Gradescope. Installing the reviewed
`[exam2.sources]` table and updated service enables collection automatically on
normal refreshes. Remove the earlier `publication_enabled` setting if migrating
an unreleased draft configuration; visibility is no longer a TOML setting.
The service passes `--exam-state /var/lib/orie4580-dashboard/exam-publication.json`.
The initial visibility is **OFF**. The private state holds normalized full
combined dashboard records and the current visibility choice, with mode `0600`,
outside all served directories. Raw scores/submission IDs are not stored.

Before lecture, trigger the regular service and inspect its result:

```sh
sudo systemctl start orie4580-checkoffs.service
sudo journalctl -u orie4580-checkoffs.service -n 40 --no-pager
```

Check that the run succeeded, Exam 2 scores loaded, and the collection time is
suitable before showing the results. Do not enable a draft Exam 2 result merely
because a private snapshot exists. The switch does not contact external services
or revalidate grades; it publishes the latest locally collected records.

From `/opt/orie4580-grade-dashboard`, show Exam 2 with:

```sh
sudo -u orie4580-dashboard -g www-data .venv/bin/python -m scripts.set_exam2_visibility on /var/lib/orie4580-dashboard/exam-publication.json /var/www/html/orie4580_fa26/students --lock-file /var/lib/orie4580-dashboard/refresh.lock
```

Hide again using the identical command with `off`. This is the simple on/off
switch; no web-admin endpoint or exposed browser control is added. Both commands
must use the same state, output, and lock as the service. A refresh in progress
causes a lock error rather than racing; retry after it finishes. The switch only
rebuilds the protected local tree, so it avoids network delay but is not literally
zero-time. Later timer refreshes preserve the choice. Open student pages need a
reload; `off` cannot erase information already viewed or saved.

Hiding removes Exam 2 from student payloads and discards the previous generated
student tree so a prior visible copy is not retained as a rollback tree. Do not
restore a visible older release while expecting Exam 2 to remain hidden.
The private desired visibility is saved before local publication; if publication
fails or the process is interrupted, inspect the error and rerun the command.
Do not assume the switch succeeded until it reports successful publication.

Test both directions using fake or local preview data before production. All
preview state, locks, snapshots, and output stay under `local_notes/`; production
state must not be reused for preview. Existing access-control checks still apply.
This feature has not itself been deployed by the development session.

## Lab 7: manual-only activation and publication-state migration

This update maps `Lab 7 - Q1` to S6 and `Lab 7 - Q2` to newly active S7. Both are manual-only; do not add Gradescope assignments. S7 uses the owner-approved (log-)likelihood maximization wording. The active standard count becomes seven, so estimates use fourteen linked boxes and the existing seven-standard thresholds.

Stop the timer and wait for any running refresh before updating code or migrating state. Back up the installed config, existing student release, and private state outside the web root. Preserve the Lab assignment snapshot: its contract is unchanged. Mapping v6 rebuilds the positive Lab cache on the next refresh, so allow time for a full crawl. No manual deletion or migration of the completion cache is needed solely for this update.

After installing the new code, if the deployed private publication snapshot still has the previous S1–S6 catalog, migrate it to a **new private output** while preserving visibility. From the checkout, with timer stopped and no refresh running:

```sh
sudo env PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m scripts.migrate_lab7_publication /var/lib/orie4580-dashboard/exam-publication.json /var/lib/orie4580-dashboard/exam-publication.lab7-migrated.json
sudo cp -p /var/lib/orie4580-dashboard/exam-publication.json /var/lib/orie4580-dashboard/exam-publication.pre-lab7.json
sudo install -o orie4580-dashboard -g www-data -m 0600 /var/lib/orie4580-dashboard/exam-publication.lab7-migrated.json /var/lib/orie4580-dashboard/exam-publication.json
```

Use unique backup/output names if they already exist. Skip migration if there is no Exam 2 publication state, or if it already has the formal S7 wording. The script accepts the previous S1–S6 catalog or the temporary “Standard 7” label; it rejects an already-current catalog rather than silently applying twice. Migration reads no Google/Gradescope data and changes no served student tree. It preserves the current ON/OFF setting, adds empty S7, and removes Lab 7 headers from the pending list; it does not fabricate checkoffs.

Run a successful normal combined refresh before using the Exam 2 visibility switch, so its private combined snapshot includes real Lab 7 results. Verify Q1 under S6 and Q2 under S7, both with only **Manual checkoff**, True earning green and False not earning green. Verify Exam 2 visibility remains as intended, owner/cross-user/staff authorization, and updated grade estimates. Re-enable the timer only after success. Old full-catalog row-import fixtures/releases also need regeneration with S7.

## Exam 3 browser assets

The generated student template and staff index load `exam3-review.js`; student
pages also load `exam3-review.css`. Deploy both alongside the shared dashboard
assets before serving the updated templates. Asset-copy options include them.
The browser expects protected per-student `exam3.json` and `exam3.pdf` files.
File production and preservation across student-tree refreshes are not implemented
in this pass; do not assume that manually placed files survive a refresh.

## Lab 8 and Lab 9 activation

This release activates manual-only `Lab 8 - Q1` → S8 and `Lab 9 - Q2` → S9, plus autograded `Lab 9 - Q1` → S7. The reviewed config now contains **13** Lab assignments, including `9030150` (3 points, three 1-point tests). Mapping v7 rebuilds the completion cache automatically. The catalog has nine standards and eighteen linked boxes; existing grading rules are unchanged.

Follow the normal preflight and update procedure above, with the timer stopped and any running refresh finished. Back up config, private state, and the current student release outside the web root. Install the reviewed Gradescope config and browser assets. Because Lab 9 Q1 changes the assignment set, retire the old `gradescope-snapshot.json` to a unique backup before the first refresh; do not reuse pass evidence from the previous contract. No dependencies changed.

If private publication state has the approved S1–S7 catalog, migrate it **before** refresh; the refresh loads and validates that state before recollection. Run from the updated checkout, using new output and backup filenames:

```sh
sudo env PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m scripts.migrate_lab89_publication /var/lib/orie4580-dashboard/exam-publication.json /var/lib/orie4580-dashboard/exam-publication.lab89-migrated.json
sudo cp -p /var/lib/orie4580-dashboard/exam-publication.json /var/lib/orie4580-dashboard/exam-publication.pre-lab89.json
sudo install -o orie4580-dashboard -g www-data -m 0600 /var/lib/orie4580-dashboard/exam-publication.lab89-migrated.json /var/lib/orie4580-dashboard/exam-publication.json
```

The script reads no network sources and does not change served pages. It preserves Exam 2/3 visibility, collection timestamps, and existing marks, adds empty S8/S9, and removes only the three activated pending headers. It rejects other catalogs, changed wording, and malformed state. Skip migration if no state exists or it already has the current S1–S9 catalog. For a still-pre-Lab-7 deployment, the historical `migrate_lab7_publication` now expands to the current catalog directly; do not run both migrations on the same state.

Run a normal full combined refresh before toggling visibility or rebuilding from saved records. Verify Lab 8 Q1 under S8 and Lab 9 Q2 under S9 each list only **Manual checkoff**, while Lab 9 Q1 under S7 lists **Manual checkoff** and **Autograder**, requiring both for green. Review pending headers, updated grade estimates, preserved exam visibility and Exam 3 files, and owner/cross-user/staff authorization. Re-enable the timer only after a successful refresh and these checks. Old full-catalog row-import releases must also be regenerated with S8/S9.

### Recovering from Lab 8/9 deployment errors

If pytest reports many `PermissionError` failures for
`/var/lib/orie4580-dashboard/student-names.csv`, the tests are trying to read the
server's private staff roster as your login user. `tests/conftest.py` isolates
that path in each test's temporary directory. Update to the code containing this
fixture and rerun `.venv/bin/pytest -q` as your normal user. Do not run pytest as
root, change production roster permissions, or discard the roster to fix tests.
Production still validates the configured private roster and reports access errors.

If the service reports `invalid collected dashboard: unmapped_columns contains a
mapped header; record must contain every currently defined standard`, its saved
publication state has the previous catalog and quarantined Lab headers. The
service validates that state before fetching sources, so repeated starts cannot
repair it. This error is separate from the test roster permissions.

Stop the timer, confirm no refresh is running, and inspect the effective unit:

```sh
sudo systemctl stop orie4580-checkoffs.timer
sudo systemctl show orie4580-checkoffs.service -p ActiveState -p SubState -p ExecStart
```

Use the actual state path shown after `--exam-state` (or its older alias
`--exam2-state`). For an S1–S7 state, run the Lab 8/9 migration commands above
against that file, using unused output and backup names. The migration preserves
existing marks and both exam visibility choices. Do not delete the publication
state; a missing state resets visibility defaults. If the migration rejects the
source catalog, stop and inspect the catalog rather than installing partial output.

Validate the installed state without printing student data (substitute the
actual state path if different):

```sh
sudo -u orie4580-dashboard -g www-data .venv/bin/python -c 'from sync.exam_publication import load_publication_state; s = load_publication_state("/var/lib/orie4580-dashboard/exam-publication.json"); assert s is not None; print("Publication state valid; standards:", len(s["records"][0]["standards"])); print("Exam 2 visible:", s["visible"]); print("Exam 3 visible:", s.get("exam3_visible", False))'
```

Confirm the installed Gradescope config has 13 assignments. If you already moved
the old Gradescope snapshot aside for this release, leave that backup in place;
do not restore it or repeat the move onto an existing backup. Then reset the
failed service and run one manual refresh as above. The service must complete
with `Result=success` and `ExecMainStatus=0` before re-enabling the timer. A failure
at this startup validation step leaves the served student release unchanged.
