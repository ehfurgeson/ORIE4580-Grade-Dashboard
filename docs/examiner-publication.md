# Publishing Examiner reviews

## One-time local grades pull

Use `scripts.pull_local_grades` to import completed local exports without polling
Google Sheets or Gradescope or changing the timer. It detects the format from the
manifests; Examiner Exam 3 schema version 1 is the first supported adapter.
Pass the **exports parent directory**, not an individual `student-*` batch.

After installing the updated dashboard code, run:

```sh
cd /opt/orie4580-grade-dashboard
sudo -u orie4580-dashboard -g www-data .venv/bin/python -m scripts.pull_local_grades \
  /var/lib/examiner/exam_03/exports \
  --state /var/lib/orie4580-dashboard/exam-publication.json \
  --output /var/www/html/orie4580_fa26/students \
  --lock-file /var/lib/orie4580-dashboard/refresh.lock \
  --require-hidden
```

Use the same state and lock paths as the scheduled service (older installations
may use `exam2-publication.json`). A missing state is an error, not a reason to
fetch remote grades. The dashboard account needs traversal access to the source
parents and read access to exports and PDFs. Examiner's full setup permission
step grants both to `orie4580-dashboard`; routine `--update` preserves these grants.
No systemd override or service restart is needed for this command.

The pull also copies each exported student's scan from the sibling `pdfs/`
directory into their protected `exam3.pdf`. Use `--pdfs /another/private/pdf-directory`
to override that source. PDF filenames must match exported submission IDs.
Scans are treated as immutable: the same submission ID reuses the published PDF
without hashing, timestamp checks, or copying bytes again. Missing PDFs abort
the staged release. Later scheduled refreshes preserve the imported PDFs.

The command rebuilds the protected student tree from existing collected records
under the normal refresh lock. It preserves both exam visibility settings and
does not write the publication state or advance the overall grade timestamp.
Each imported JSON gets a fresh `published_at`; its `exported_at` still records
when Examiner exported it. `--require-hidden` refuses the import if Exam 3 is
already visible. Omitting it preserves the current setting, including ON.

An invalid/unsupported export or a concurrent refresh aborts without replacing
the live release. An empty source is rejected to catch wrong paths. Each source
is authoritative for its exam: omitted questions survive only if an earlier batch
in that directory contains them. Other local exam files are preserved. To inspect
hidden grades, privately download an imported student JSON and open it in the
local `static/exam3-review.html` viewer; no activation is needed.

## Scheduled collection

The dashboard can pull completed Examiner 03 exports during its existing three-hour
refresh. Every completed `student-*` batch in the configured directory is collected.
Student access defaults to OFF until explicitly enabled with the visibility switch.
This does not run Examiner checks, finalize decisions, or create exports.

Use **Run & export → Create student JSON** in Examiner. The next successful
dashboard refresh reads those immutable batches, maps each student's Cornell email
to their roster NetID, and writes `students/<netid>/exam3.json` inside the same
protected release as `checkoffs.json`. The private manifest never reaches the web
tree. The dashboard refresh timestamp remains the common publication time;
`exported_at` describes source freshness and `published_at` records publication.
No extra timer is needed. To publish early, start `orie4580-checkoffs.service`.
Use `--local-grades /path/to/exports` for the same manifest-based importer during
scheduled refreshes. The existing `--examiner-exports` option remains supported;
both use the shared importer and protected release writer.

Partial exports accumulate by question. The newest timestamp wins for a repeated
student/question, including corrections from correct to incorrect. Skipped and
unselected questions do not erase earlier exports. Conflicting versions with equal
timestamps abort. Students absent from the dashboard roster are not published.
Missing or malformed configured sources fail the refresh and preserve the live
student tree. `.building-*` directories are ignored.

The source directory is authoritative: to retract a question, remove **all** batches
containing it from that directory (archive outside it), then refresh. An empty
configured directory removes every published Exam 3 JSON. Omitting the option
instead preserves existing reviews; it does not retract them. Local rebuilds,
including the Exam 2 visibility switch, also preserve reviews. Manually replacing
a protected `exam3.json` lasts until the next configured pull.

The JSON embeds cropped scans. This importer does not publish original PDFs;
previously installed `exam3.pdf` files are preserved by refreshes. Those PDFs must
be placed and removed separately if used by the viewer.

## Server layout and permissions

Keep installed code under `/opt` and mutable exam content under `/var/lib`.
For example, move the **whole** existing exam content root to
`/var/lib/examiner/exam3`, preserving hidden files and permissions, and change
Examiner's `--content-dir` (or its service's configured content path). Stop
Examiner during the copy, retain the old directory until verified, and restart
with the new path. The source path and Examiner runtime account depend on your
installation and are intentionally not guessed here.

Do not disable the dashboard's `ProtectHome=true` or grant it access to raw scans,
grading outputs, or your home directory. Give its service account traversal access
to the parent directories and read access only to `exports`. After migration,
create `exports` as the Examiner runtime account, then apply these ACLs as root
(Ubuntu's `acl` package supplies `setfacl`):

```sh
sudo setfacl -m u:orie4580-dashboard:--x /var/lib/examiner /var/lib/examiner/exam3
sudo setfacl -R -m u:orie4580-dashboard:r-X /var/lib/examiner/exam3/exports
sudo setfacl -m d:u:orie4580-dashboard:r-x /var/lib/examiner/exam3/exports
```

The default ACL is inherited by new batches. The updated Examiner exporter keeps
unfinished batches private, then sets completed directories to `0750` and JSON
files to `0640` before renaming them into place; this also enables the inherited
reader ACL. Existing exports need the recursive ACL command above. The dashboard
gets no write permission to Examiner data. Do not give the web server access to
the export source. Preserve Examiner's own runtime access during migration.

The checked-in `deployment/orie4580-checkoffs.service` includes
`--local-grades /var/lib/examiner/exam_03/exports` directly in `ExecStart`.
Install it to enable local pulls on the regular refresh timer:

```sh
cd /opt/orie4580-grade-dashboard
sudo install -o root -g root -m 0644 deployment/orie4580-checkoffs.service /etc/systemd/system/orie4580-checkoffs.service
sudo systemctl daemon-reload
sudo systemctl enable --now orie4580-checkoffs.timer
systemctl cat orie4580-checkoffs.service
```

If an old drop-in sets `--local-grades` or `--examiner-exports` in
`ORIE4580_REFRESH_FLAGS`, remove that source flag from the drop-in; retain any
unrelated validation flags. No source override is needed for this installation.
To refresh immediately, run `sudo systemctl start orie4580-checkoffs.service`.

First verify this with synthetic export batches and a staging output directory.
Check that the service can read a newly generated batch, that the matching student
can open the review, that another student is denied, and that the ordinary refresh
and Exam 2 visibility switch retain the review. The code has synthetic tests; the
server ACLs, service configuration, and Shibboleth behavior need verification on
your server.

## Exam 3 visibility switch

Exam 3 shares the existing private publication-state file and refresh lock with
Exam 2, but has an independent `exam3_visible` flag. Old state files default to
OFF. Scheduled refreshes preserve both choices. Collection continues while OFF;
Apache denies `exam3.json` and `exam3.pdf`, including direct URLs, for everyone.
The files remain in the protected student tree so switching back ON needs no
source reads. The review HTML contains no grades and remains safe to open.
This requires the same Apache authorization overrides as the existing dashboard;
plain static development servers do not enforce `.htaccess`.

After installing the updated code, hide Exam 3 immediately with:

```sh
cd /opt/orie4580-grade-dashboard
sudo -u orie4580-dashboard -g www-data .venv/bin/python -m scripts.set_exam3_visibility off /var/lib/orie4580-dashboard/exam-publication.json /var/www/html/orie4580_fa26/students --lock-file /var/lib/orie4580-dashboard/refresh.lock
```

Use `on` in place of `off` to release it. The shared file stores both exam visibility choices. A collected state from the normal
refresh must exist first. The command rebuilds the protected release under the
shared lock; it does not change Exam 2 visibility or contact grading sources.
Like the Exam 2 command, it persists the desired choice before rebuilding: if the
rebuild fails, the previous release remains until a successful retry or refresh.
Confirm direct JSON/PDF requests are denied on the deployed Apache server before
relying on the switch; it has not been deployed merely by editing this repository.
