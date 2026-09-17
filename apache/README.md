# Apache test configuration

These files contain authorization rules only. They contain no grade data.

## Positive course-group test

Copy `course-group-test.htaccess` to the server's existing `auth-test/`
directory as `.htaccess`. It has no user fallback, so access proves that
Shibboleth supplied membership in either `EN-OR-or4580-students` or
`EN-OR-or4580-ta`.

Expected results:

- `ehf38`, as a TA: allowed.
- An enrolled student: allowed.
- An authenticated Cornell user in neither group: denied.
- An unauthenticated browser: sent through Cornell SSO, then evaluated.

A successful `ehf38` test proves only the TA group. Have one enrolled student
open the same harmless endpoint to prove the student group independently.

## Protected fake-grade test

Copy `ehf38-test.htaccess` into `students/me/` as `.htaccess` alongside the
fake generated record. It allows either the specific test user `ehf38` or a
member of the TA group. This models the intended staff override while
preserving the already-proven single-user test.

This is **not** the final multi-student `me` mapping. The final design must
resolve `me` from a trusted authenticated identity, authorize the resolved
student directory, and pass the full own/cross-student/TA matrix.

If Apache returns 500, inspect the error log before changing a rule. A 403 for
an authenticated user outside the listed group or user rule is expected.

## Generated simple-dashboard directories

The simple wide-sheet pipeline generates one directory per validated Cornell
NetID. Each directory has an `.htaccess` containing only:

```apache
AuthType shibboleth
ShibRequestSetting requireSession 1
Require shib-user ehf38
Options -Indexes

<IfModule mod_headers.c>
    Header always set Cache-Control "private, no-store, max-age=0"
</IfModule>
```

There is deliberately no student group, TA group, or `valid-user` fallback.
The HTML and JSON are in the same protected directory, so both require the
matching authenticated NetID. Staff do not receive an override in this
temporary design.

For the first test, generate and deploy only `ehf38`. Verify this matrix before
using `--all-students`:

| User | Resource | Expected |
| --- | --- | --- |
| anonymous | `/students/ehf38/` | SSO challenge, then authorization |
| `ehf38` | `/students/ehf38/` | allow |
| another authenticated user | `/students/ehf38/` | deny |
| `ehf38` | `/students/ehf38/checkoffs.json` | allow, private/no-store |

Copy the generated directory with a dotfile-preserving operation such as
`cp -a`, not `*`. Assign ownership/group so Apache can traverse the directory
and read all three files. If `Options -Indexes` produces a 500, confirm the
server's `AllowOverride Options` policy with IT rather than silently removing
the directory-listing protection.
