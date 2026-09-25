# Apache configuration

These files contain authentication and authorization rules only. They contain no grade data.

## Authenticated course-root redirect

`course-root-redirect.conf` is a virtual-host snippet for the exact course root. After Shibboleth establishes a session, it validates the trusted `REMOTE_USER` as a lowercase Cornell NetID. The explicit staff users in `sync/simple_generate.py` receive a temporary `302` redirect to the protected `/orie4580_fa26/students/` index; other users go to `/orie4580_fa26/students/<netid>/`. Keep the two staff lists in sync. It never reads identity from JavaScript, a query parameter, or another browser-controlled value.

Install the snippet inside the active HTTPS `<VirtualHost *:443>`, normally with an `Include` directive. Do not put this rule only in `.htaccess`: authentication and rewrite processing occur in different phases. Keep the generated `students/<netid>/.htaccess` rules. The redirect is navigation, not authorization.

Keep `R=302` during testing. Verify the course-root redirect with a named staff account and a student. The generated parent and student `.htaccess` rules remain the authorization boundary.

## Positive course-group test

`course-group-test.htaccess` is a manual diagnostic fixture, not a production
access rule. To test whether Shibboleth supplies either course group, copy it
to the server's existing `auth-test/` directory as `.htaccess`. Remove that
copy after testing. The dashboard's generated authorization does not use
these groups.

## Protected fake-grade test

Copy `ehf38-test.htaccess` into `students/me/` as `.htaccess` alongside the
fake generated record. It allows only the specific test user `ehf38`.

This is **not** the final multi-student `me` mapping. The final design must
resolve `me` from a trusted authenticated identity, authorize the resolved
student directory, and pass the full own/cross-student/staff matrix.

If Apache returns 500, inspect the error log before changing a rule. A 403 for
an authenticated user outside the listed user rule is expected.

## Generated simple-dashboard directories

The simple wide-sheet pipeline generates one directory per validated Cornell
NetID. Each `.htaccess` allows the owner and the six explicit staff users in
`sync/simple_generate.py`. The protected parent index allows those same six
staff users. There is no group or `valid-user` fallback.

For the first test, generate and deploy only `ehf38`. Verify this matrix before
using `--all-students`:

| User | Resource | Expected |
| --- | --- | --- |
| anonymous | `/students/ehf38/` | SSO challenge, then authorization |
| `ehf38` | `/students/ehf38/` | allow |
| another authenticated user outside the staff list | `/students/ehf38/` | deny |
| `ehf38` | `/students/ehf38/checkoffs.json` | allow, private/no-store |

Copy the generated directory with a dotfile-preserving operation such as
`cp -a`, not `*`. Assign ownership/group so Apache can traverse the directory
and read all three files. If `Options -Indexes` produces a 500, confirm the
server's `AllowOverride Options` policy with IT rather than silently removing
the directory-listing protection.
