# Publishing local exam reviews

Exam 3 and Exam Retry use the same import format and publication workflow.
Their caches are private. The dashboard keeps published reviews and full scans
in its protected student tree.

| Exam | Export batches | Source PDFs |
| --- | --- | --- |
| Exam 3 | `/var/cache/examiner-exports` | `/var/lib/examiner/exam_03/pdfs` |
| Exam Retry | `/var/cache/examinator-dashboard/exam_retry/exports` | `/var/cache/examinator-dashboard/exam_retry/pdfs` |

## One-time local pull

From the Grade Dashboard checkout on the server, run the command for the exam
you want to import. It reads the saved dashboard state and uses the same lock
as the scheduled service. It preserves visibility and skips Gradescope and
Google Sheets.

**Exam 3**

```sh
sudo -u orie4580-dashboard -g www-data .venv/bin/python -m scripts.pull_local_grades \
  /var/cache/examiner-exports \
  --pdfs /var/lib/examiner/exam_03/pdfs \
  --state /var/lib/orie4580-dashboard/exam-publication.json \
  --output /var/www/html/orie4580_fa26/students \
  --lock-file /var/lib/orie4580-dashboard/refresh.lock
```

**Exam Retry**

```sh
sudo -u orie4580-dashboard -g www-data .venv/bin/python -m scripts.pull_local_grades \
  /var/cache/examinator-dashboard/exam_retry/exports \
  --state /var/lib/orie4580-dashboard/exam-publication.json \
  --output /var/www/html/orie4580_fa26/students \
  --lock-file /var/lib/orie4580-dashboard/refresh.lock
```

The importer detects the exam from the batch manifests. It looks for PDFs in the
sibling `pdfs/` directory unless you pass `--pdfs`. The manual pull requires a
source PDF or a previously published PDF for each imported submission. Add
`--refresh-pdfs` to replace published scans, or `--require-hidden` to require that
the exam is hidden before importing. An absent or empty export cache is a no-op.
A malformed completed batch or a concurrent refresh aborts the import before
it replaces the live student tree.

## Scheduled collection

The three-hour refresh checks both export caches. Use one `--local-grades EXPORTS`
per exam and `--local-grade-pdfs EXPORTS PDFS` if the PDFs live elsewhere.
It publishes full scans when they are available and reuses already published
scans for the same submission. A missing scan source still permits a scheduled
JSON import, which can display the embedded answer crops.

Both import paths merge partial exports by student and question. A newer
export can change a published grade, including a correction to no credit or
blank. Omitted questions and missing or empty caches preserve previously
published reviews. Older batches cannot roll back published decisions. Reviews
imported by older dashboard versions use their most recent export timestamp
as the fallback for every question until a newer export replaces it.
Incomplete `.building-*` directories are ignored. A malformed completed batch
fails the refresh and leaves the live student tree in place.

You can remove complete batches after verifying their published results. Keep
the grading sources if you need to regenerate exports on a new server.
Retain a backup of the protected reviews if you need to restore the exact
published release. The legacy `--examiner-exports` flag retains its original
replacement behavior. Use `--local-grades` for the scheduled cache workflow.

## Service setup

Give the `orie4580-dashboard` account traversal and read access to both caches
and the PDF sources. Keep the export caches outside the web root. The checked-in
service configures both paths. From the Grade Dashboard checkout, run:

```sh
sudo install -o root -g root -m 0644 deployment/orie4580-checkoffs.service \
  /etc/systemd/system/orie4580-checkoffs.service
sudo systemctl daemon-reload
systemctl --no-pager --full show orie4580-checkoffs.service -p ExecStart -p Environment
```

Remove any old export-source flags from `ORIE4580_REFRESH_FLAGS` in service
drop-ins. The next scheduled run will use the updated service. Use the one-time
local pull above if a review needs to be published before then.

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

## Exam Retry visibility switch

The Retry visibility switch is independent of Exam 3. It defaults to off.
To release Exam Retry after checking the imported reviews, run:

```sh
sudo -u orie4580-dashboard -g www-data .venv/bin/python -m scripts.set_exam_retry_visibility on /var/lib/orie4580-dashboard/exam-publication.json /var/www/html/orie4580_fa26/students --lock-file /var/lib/orie4580-dashboard/refresh.lock
```

`--require-hidden` checks the visibility of the exam being imported. Another exam
in this format is a row in `sync/local_grades.py` `ADAPTERS`, in
`sync/simple_generate.py` `REVIEW_PDFS` (and its page and hidden rule), in
`static/exam3-review.js` `exams` and `static/simple-dashboard.js` sources, plus
its own visibility flag.
