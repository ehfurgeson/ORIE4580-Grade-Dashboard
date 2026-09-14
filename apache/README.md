# Apache test configuration

`ehf38-test.htaccess` is a temporary, single-user test for the dashboard's
`students/me/grades.json` request. It contains no grade data. Copy it into the
server's `students/me/` directory as `.htaccess` alongside the fake generated
record.

This proves that `ehf38` can load a protected fake record and that another user
cannot load that endpoint. It is **not** the final multi-student `me` mapping.
The final design must resolve `me` from a trusted authenticated identity and
repeat authorization after any internal rewrite.

If Apache returns 500, inspect its error log before changing the rule. Confirm
that the `shib-user` authorization provider is available in the installed
Shibboleth module. A 403 for a different authenticated user is the expected
result.
