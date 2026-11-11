# Rename the shared exam publication state

This migration changes names, not the JSON schema or visibility settings.
`visible` still controls Exam 2; `exam3_visible` controls Exam 3 and defaults to
false in older files. The scripts `set_exam2_visibility` and
`set_exam3_visibility` keep their names. `--exam2-state` remains a compatibility
alias for `--exam-state` during rollout.

## 1. Pause scheduled refreshes

On the server:

```sh
sudo systemctl stop orie4580-checkoffs.timer
sudo systemctl show orie4580-checkoffs.service -p ActiveState -p SubState -p Result
```

If a refresh is running, let it finish before continuing. Do not start manual
refreshes during migration. The live dashboard continues serving its last release.

## 2. Install the reviewed code

Transfer or pull the reviewed changes into `/opt/orie4580-grade-dashboard` using
the normal deployment workflow. Local, uncommitted edits are not available to a
server `git pull`. Do not overwrite unrelated server checkout changes.

Inspect the installed service command and drop-ins with:

```sh
sudo systemctl cat orie4580-checkoffs.service
```

Preserve existing settings, especially `ORIE4580_REFRESH_FLAGS` and Examiner
export paths. The checked-in service now uses `--exam-state` and the new filename.
Any installed `ExecStart` override also needs the new path.

## 3. Back up and rename the state under the refresh lock

First confirm the new destination does not already exist. If it does, stop and
resolve which file is authoritative; do not overwrite either state file.

```sh
sudo ls -l /var/lib/orie4580-dashboard/exam2-publication.json
sudo test ! -e /var/lib/orie4580-dashboard/exam-publication.json
sudo flock -n /var/lib/orie4580-dashboard/refresh.lock sh -eu -c '
  old=/var/lib/orie4580-dashboard/exam2-publication.json
  new=/var/lib/orie4580-dashboard/exam-publication.json
  test -f "$old"
  test ! -L "$old"
  test ! -e "$new"
  test ! -L "$new"
  backup=$(mktemp -d /var/lib/orie4580-dashboard/publication-rename-backup.XXXXXX)
  cp -p "$old" "$backup/exam2-publication.json"
  mv "$old" "$new"
  echo "State backup: $backup"
'
```

Rename preserves ownership and mode. Validate without printing student records:

```sh
cd /opt/orie4580-grade-dashboard
sudo -u orie4580-dashboard -g www-data .venv/bin/python -c 'from sync.exam_publication import load_publication_state; s = load_publication_state("/var/lib/orie4580-dashboard/exam-publication.json"); assert s is not None; print("Exam 2 visible:", s["visible"]); print("Exam 3 visible:", s.get("exam3_visible", False))'
```

## 4. Update the installed service path

Update the effective `ExecStart` to use `--exam-state` and
`/var/lib/orie4580-dashboard/exam-publication.json`. If the base unit matches the
repository unit except for this rename, install the updated unit:

```sh
sudo install -o root -g root -m 0644 deployment/orie4580-checkoffs.service /etc/systemd/system/orie4580-checkoffs.service
sudo systemctl daemon-reload
sudo systemctl show orie4580-checkoffs.service -p ExecStart
```

If the server has customized the base unit or overridden `ExecStart`, preserve
those customizations and update the two names in the effective definition instead.
Do not restart the timer until the effective command points to the new state file.
Update any manual commands/runbooks using the old path too.

## 5. Apply visibility, verify, and resume

To keep Exam 3 hidden now (also rebuilding the Apache denial rules):

```sh
sudo -u orie4580-dashboard -g www-data .venv/bin/python -m scripts.set_exam3_visibility off /var/lib/orie4580-dashboard/exam-publication.json /var/www/html/orie4580_fa26/students --lock-file /var/lib/orie4580-dashboard/refresh.lock
```

Verify authenticated direct Exam 3 JSON/PDF requests are denied. Then run one
manual refresh and confirm it succeeds and preserves the visibility settings:

```sh
sudo systemctl start --no-block orie4580-checkoffs.service
sudo systemctl show orie4580-checkoffs.service -p ActiveState -p SubState -p Result -p ExecMainStatus
```

Wait for completion; inspect the journal if it fails. Only after success:

```sh
sudo systemctl enable --now orie4580-checkoffs.timer
systemctl list-timers orie4580-checkoffs.timer
```

For rollback, stop the timer, wait for any active refresh, and move the current
state back to its old filename under the same lock while restoring the old service
path. Keep one authoritative file; do not leave two independently updated copies.
