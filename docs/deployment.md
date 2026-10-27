# Ubuntu Deployment

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
git commit -m "Add Lab 5 dashboard mappings"
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

No dependency changed for Lab 5. For a future release that changes `requirements.txt`, run:

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
```

Forward compatibility depends on that order: install schema-6 `simple-dashboard.js` and `simple-style.css`, then run the refresh that publishes schema-6 records. The new JavaScript deliberately tolerates schema-3–5 pages whose older HTML has no pending-mapping container during this rollout window. For rollback, use the reverse dependency order: restore the previous schema-3–5 student release first, then restore the previous JavaScript and CSS, and finally roll back the checkout/config as needed. Never serve schema-6 records to an older browser validator.

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

For the Lab 5 release, the first command must still print `10`; Lab 5 has no Gradescope assignments. The Lab 6 release adds two autograded assignments, so the first command must print `12`.

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
`static/simple-dashboard.js` and `static/simple-style.css` at the web root before
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


## Standalone grade calculator (optional, manual publication)

The calculator source is `static/grade_calculator/index.html`. It contains its
own CSS and JavaScript and reads no student data. Its intended public URL is
`https://zivscully.orie.cornell.edu/orie4580_fa26/grade_calculator/`.
Preparing this file does not publish it. The refresh service and its
`--copy-assets-to` option do not install the calculator.

Before an explicitly authorized publication, run locally:

```sh
node tests/grade_calculator.test.js
git diff --check
```

After transferring the reviewed source to the server checkout, the following
commands install only the calculator. They do not require a student refresh,
timer interruption, or changes to the course-root redirect:

```sh
cd /opt/orie4580-grade-dashboard
sudo install -d -o root -g www-data -m 0755 \
  /var/www/html/orie4580_fa26/grade_calculator
sudo install -o root -g www-data -m 0644 \
  static/grade_calculator/index.html \
  /var/www/html/orie4580_fa26/grade_calculator/index.html
```

The checked-in `apache/course-root-redirect.conf` matches only the exact course
root, so this subdirectory does not need a redirect exception. Apache should
serve its `index.html` through the existing `DirectoryIndex` configuration.
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
The service passes `--exam2-state /var/lib/orie4580-dashboard/exam2-publication.json`.
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
sudo -u orie4580-dashboard -g www-data .venv/bin/python -m scripts.set_exam2_visibility on /var/lib/orie4580-dashboard/exam2-publication.json /var/www/html/orie4580_fa26/students --lock-file /var/lib/orie4580-dashboard/refresh.lock
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
