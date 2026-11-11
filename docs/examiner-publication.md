# Publishing Examiner reviews

The dashboard pulls completed Examiner 03 exports during its existing three-hour
refresh. Enable this only when exported reviews are ready for students: every
completed `student-*` batch in the configured directory is eligible for publication.
This does not run Examiner checks, finalize decisions, or create exports.

Use **Run & export → Create student JSON** in Examiner. The next successful
dashboard refresh reads those immutable batches, maps each student's Cornell email
to their roster NetID, and writes `students/<netid>/exam3.json` inside the same
protected release as `checkoffs.json`. The private manifest never reaches the web
tree. The dashboard refresh timestamp remains the common publication time;
`exported_at` describes source freshness and `published_at` records publication.
No extra timer is needed. To publish early, start `orie4580-checkoffs.service`.

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

Enable pulling with `sudo systemctl edit orie4580-checkoffs.service`:

```ini
[Service]
Environment="ORIE4580_REFRESH_FLAGS=--examiner-exports /var/lib/examiner/exam3/exports"
```

If `ORIE4580_REFRESH_FLAGS` already has flags, include them in the same value.
Then run:

```sh
sudo systemctl daemon-reload
sudo systemctl start orie4580-checkoffs.service
sudo journalctl -u orie4580-checkoffs.service -n 60 --no-pager
```

First verify this with synthetic export batches and a staging output directory.
Check that the service can read a newly generated batch, that the matching student
can open the review, that another student is denied, and that the ordinary refresh
and Exam 2 visibility switch retain the review. The code has synthetic tests; the
server ACLs, service configuration, and Shibboleth behavior need verification on
your server.
