# Publishing local exam reviews

## One-time local grades pull

Use `scripts.pull_local_grades` to import completed local exports without polling
Google Sheets or Gradescope or changing the timer. It detects the exam and format
from the manifests. Pass the **exports parent directory** that contains the
`student-*` batches.

After installing the updated dashboard code, run this with the exports directory
for the exam you want to import. The example uses Exam 3.

```sh
cd /opt/orie4580-grade-dashboard
sudo -u orie4580-dashboard -g www-data .venv/bin/python -m scripts.pull_local_grades \
  /var/cache/examiner-exports \
  --pdfs /var/lib/examiner/exam_03/pdfs \
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

The pull also copies each exported student's scan into their protected exam PDF.
With a separate export cache, pass the scan directory using `--pdfs`. For a
bundle with `exports/` and `pdfs/` side by side, the sibling `pdfs/` is the
default. PDF filenames must match exported submission IDs.
Scans are treated as immutable: the same submission ID reuses the published PDF
without hashing, timestamp checks, or copying bytes again. Missing PDFs abort
the staged release. Later scheduled refreshes preserve the imported PDFs.

If source scans were corrected, rerun the same command with `--refresh-pdfs`
to replace cached PDFs even when submission IDs have not changed. This copies
the source PDFs as-is; it does not remove pages or change PDF page references.

The command rebuilds the protected student tree from existing collected records
under the normal refresh lock. It preserves exam visibility settings and the
overall grade timestamp.
Each imported JSON gets a fresh `published_at`; its `exported_at` still records
the original export time. `--require-hidden` refuses the import if that exam is
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

The source directory is authoritative. To retract a question, remove every batch
containing it from that directory, then refresh. If `--local-grades` points to
an empty directory, the refresh fails and preserves the previous release.
The legacy `--examiner-exports` flag treats an empty directory as a retraction
of all Exam 3 reviews. Refreshes with neither flag preserve the published
reviews, as do local rebuilds including the Exam 2 visibility switch.

The JSON embeds cropped scans. This importer does not publish original PDFs;
previously installed `exam3.pdf` files are preserved by refreshes. Those PDFs must
be placed and removed separately if used by the viewer.

## Server layout and permissions

The default Examiner installation writes export batches to
`/var/cache/examiner-exports` and keeps scans in `/var/lib/examiner/exam_03/pdfs`.
Examiner's setup grants the dashboard service account read-only access to the
export cache, including future batches. The one-time pull also needs read access
to the source PDFs. The scheduled import reads the export cache alone. Keep the
cache private and outside the web root.

The checked-in `deployment/orie4580-checkoffs.service` includes
`--local-grades /var/cache/examiner-exports` directly in `ExecStart`.
For an existing installation, populate the cache with the completed Exam 3
batches from the former `exports/` directory before switching the service.
Partial batches can each contain unique student/question pairs. Keep the former
directory until a refresh from the new location succeeds and coverage is verified.
Install the updated unit. If a refresh is already running, let it finish before
starting the verification run.

```sh
cd /opt/orie4580-grade-dashboard
sudo install -o root -g root -m 0644 deployment/orie4580-checkoffs.service /etc/systemd/system/orie4580-checkoffs.service
sudo systemctl daemon-reload
systemctl show orie4580-checkoffs.service -p ExecStart -p Environment
```

If an old drop-in sets `--local-grades` or `--examiner-exports` in
`ORIE4580_REFRESH_FLAGS`, remove that source flag from the drop-in; retain any
unrelated validation flags. Once the effective service points to the cache,
run `sudo systemctl start orie4580-checkoffs.service` and check its result.
Resume the timer with `sudo systemctl start orie4580-checkoffs.timer` if it was
paused for the cutover.

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

Use `on` in place of `off` to release it. The shared file stores exam visibility choices. A collected state from the normal
refresh must exist first. The command rebuilds the protected release under the
shared lock; it does not change Exam 2 visibility or contact grading sources.
Like the Exam 2 command, it persists the desired choice before rebuilding: if the
rebuild fails, the previous release remains until a successful retry or refresh.
Confirm direct JSON/PDF requests are denied on the deployed Apache server before
relying on the switch; it has not been deployed merely by editing this repository.

## Exam Retry (Examinator)

Examinator's `deploy/export-dashboard.py` writes the same format with exam
`'retry'` (questions `q1`-`q7`, one per standard S1-S7). The Retry bundle is at
`/var/cache/examinator-dashboard/exam_retry/`. The import reads `exports/` and
its sibling `pdfs/` from that directory and publishes `exam_retry.json` and
`exam_retry.pdf` in each student's protected directory.

```sh
cd /opt/orie4580-grade-dashboard
sudo -u orie4580-dashboard -g www-data .venv/bin/python -m scripts.pull_local_grades \
  /var/cache/examinator-dashboard/exam_retry/exports \
  --state /var/lib/orie4580-dashboard/exam-publication.json \
  --output /var/www/html/orie4580_fa26/students \
  --lock-file /var/lib/orie4580-dashboard/refresh.lock \
  --require-hidden
```

Release Exam Retry after the import succeeds.

```sh
sudo -u orie4580-dashboard -g www-data .venv/bin/python -m scripts.set_exam_retry_visibility on /var/lib/orie4580-dashboard/exam-publication.json /var/www/html/orie4580_fa26/students --lock-file /var/lib/orie4580-dashboard/refresh.lock
```

`--require-hidden` checks the visibility of the exam being imported. Another exam
in this format is a row in `sync/local_grades.py` `ADAPTERS`, in
`sync/simple_generate.py` `REVIEW_PDFS` (and its page and hidden rule), in
`static/exam3-review.js` `exams` and `static/simple-dashboard.js` sources, plus
its own visibility flag.
