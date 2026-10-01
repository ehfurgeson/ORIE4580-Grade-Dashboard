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
git commit -m "Add Lab 4 dashboard mappings"
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

No dependency changed for Lab 4. For a future release that changes `requirements.txt`, run:

```sh
.venv/bin/python -m pip install -r requirements.txt
```

Install the reviewed Gradescope allowlist and the browser JavaScript. The JavaScript copy is required because student pages load it from the web root; the refresh service replaces `students/` but does not copy root assets.

```sh
sudo install -o root -g root -m 0600 \
  deployment/gradescope.toml.example \
  /etc/orie4580-dashboard/gradescope.toml
sudo install -o root -g www-data -m 0644 \
  static/simple-dashboard.js \
  /var/www/html/orie4580_fa26/simple-dashboard.js
```

Validate the checked-in configuration and source on Ubuntu:

```sh
.venv/bin/python -c \
  'from sync.gradescope import load_config; print(len(load_config("deployment/gradescope.toml.example").assignments))'
.venv/bin/pytest -q
```

For the Lab 4 release, the first command must print `10`.

When this release changes the Gradescope assignment contract — a new autograded assignment, or a bumped contract version — retire the previous private snapshot before the first refresh. A manual-only column does not change that contract. The completion cache is invalid after a contract change, so the refresh falls back to `/var/lib/orie4580-dashboard/gradescope-snapshot.json` and aborts with `cannot carry pass evidence across a changed course or assignment contract` if that file still describes the previous contract. Moving it aside lets the full crawl become the new baseline and seed the cache:

```sh
sudo mv /var/lib/orie4580-dashboard/gradescope-snapshot.json \
  /var/lib/orie4580-dashboard/gradescope-snapshot.json.pre-contract-change
```

Lab 4 adds autograded Q2 and Q3, so it needs this step. The first run also revalidates Lab pass history and can take longer than later cached runs. Start one full atomic refresh and follow its progress:

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

Check an owner page in the browser. Confirm that Lab 4 Q1 lists only **Manual checkoff**, while Q2 and Q3 list **Manual checkoff** and **Autograder**. Also check that a different student cannot open that page.

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
installing anything.

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
- [ ] The reviewed Gradescope config and root JavaScript are installed.
- [ ] If the Gradescope assignment contract changed, the previous private snapshot was retired before the first refresh.
- [ ] The manual production service run succeeds.
- [ ] Lab requirements render correctly.
- [ ] Owner, cross-user, and staff authorization checks pass.
- [ ] The timer is active only after validation.
