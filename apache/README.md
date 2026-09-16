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
