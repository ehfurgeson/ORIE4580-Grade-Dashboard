 Plan: Quarantine Unmapped Google Sheet Columns

 │ Corrected implementation plan. The repository changes described below are implemented with this update.

 1. Goal

 Allow new Google Sheet columns to appear without breaking the synchronization service.

 An unknown column should:

 - Be accepted by the importer.
 - Appear in the dashboard as Pending mapping.
 - Never earn a green checkmark.
 - Never affect grade allocation.
 - Never require a Gradescope assignment.
 - Become a normal opportunity automatically after its mapping is added to the repository.

 The repository should remain authoritative for:

 - Standard assignment.
 - Opportunity ID.
 - Display label.
 - Manual-only versus autograded policy.
 - Gradescope assignment and contract.

 2. Behavior change

 Current behavior

 sync/simple_checkoffs.py rejects every Sheet header not present in COLUMN_MAPPINGS.

 This is the current failure:

   unmapped checkoff column(s): ...

 The refresh then preserves the previous dashboard release.

 Proposed behavior

 For an unknown header such as:

   Lab 6 - Q1

 the importer would produce a record containing:

   {
     "unmapped_columns": [
       "Lab 6 - Q1"
     ]
   }

 The dashboard would show:

 │ Lab 6 - Q1 — Pending course-staff mapping. This column does not earn a checkmark.

 The column would not appear under S1–S5 and would not be included in earned or available checkmark totals.

 3. Proposed data model

 Add an unmapped_columns field to internal manual records and published combined records.
 Internal manual records remain unversioned. Published combined records use schema version 6.
 The following abbreviated fragment shows only the new field; valid records still contain the full S1–S5 standards structure:

   {
     "schema_version": 6,
     "updated_at": "...",
     "worksheet": "Lab Checkoffs",
     "student": {
       "netid": "abc123"
     },
     "unmapped_columns": [
       "Lab 6 - Q1",
       "Lab 6 - Q2"
     ],
     "standards": ["... all S1–S5 standard objects ..."]
   }

 Recommended rules:

 - Store only column names, not raw cell values.
 - Require each name to be a nonempty string.
 - Reuse the existing 200-Unicode-code-point header limit in Python and JavaScript.
 - Reject ASCII control characters and Unicode bidi-control characters in every checkoff header.
 - Bound the number of checkoff headers to the A:ZZ transport limit (702 total columns, including NetID).
 - Preserve the worksheet column order.
 - Use an empty list when all columns are mapped.
 - Do not assign unknown columns to a standard.
 - Do not assign them an opportunity ID.
 - Do not interpret their cell contents before the mapping is approved.

 This means an arbitrary extra column cannot leak raw cell values or break the refresh because of a non-boolean value. The validated header name itself is intentionally published as pending metadata.

 4. Files to modify

 sync/simple_checkoffs.py

 rows_to_simple_records

 Change the current unmapped-column rejection:

   unmapped = [header for header in item_headers if header not in COLUMN_MAPPINGS]
   if unmapped:
       raise ValueError(...)

 to:

 1. Validate header names and lengths as today.
 2. Split headers into:
     - mapped headers;
     - unmapped headers.
 3. Run checkbox normalization only for mapped headers.
 4. Store unmapped header names in unmapped_columns.
 5. Continue generating normal S1–S5 records from mapped headers.

 Unknown column values should not be parsed until the column has an approved mapping.

 validate_manual_record

 Update the expected schema to include:

   "unmapped_columns"

 Validate that:

 - It is a list.
 - Every item is a valid bounded string.
 - There are no duplicate names.
 - It does not contain any currently mapped Sheet column.
 - The existing standard and checkmark validation remains unchanged.

 sync/combined_checkoffs.py

 Schema version

 Change:

   SCHEMA_VERSION = 5

 to:

   SCHEMA_VERSION = 6

 merge_checkoffs_with_autograders

 Carry unmapped_columns through unchanged.

 Do not add unknown columns to:

 - available_opportunities;
 - AUTOGRADER_OPPORTUNITY_IDS;
 - manual checkoff requirements;
 - green checkmark allocation.

 The existing strict Gradescope checks should continue to apply only to known mapped opportunities.

 validate_combined_record

 Require and validate unmapped_columns.

 For schema version 6:

 - Require the new field.
 - Validate its structure.
 - Confirm that no unmapped name is also present in COLUMN_MAPPINGS.

 Validation across the importer, merge, and combined-record validator should continue rejecting:

 - malformed or non-authoritative known opportunities;
 - unknown Gradescope mappings;
 - missing Gradescope rules for explicitly autograded opportunities;
 - invalid known checkbox values.

 validate_manual_record and validate_combined_record must verify that each green opportunity ID, standard, display label, and complete manual detail-header group agrees with COLUMN_MAPPINGS, OPPORTUNITY_HEADER_GROUPS, and the explicit policy sets. Gradescope snapshot/config relationships remain merge/config responsibilities rather than combined-record-only checks.

 sync/simple_generate.py

 No major logic change should be needed because it already delegates record validation to validate_combined_record.

 Verify that it publishes the new field unchanged, require every record in a publication batch to carry the same ordered worksheet-wide list, and add regression tests for successful publication and inconsistent-list rejection.

 static/simple-dashboard.js

 Schema support

 Accept schema version 6:

   [3, 4, 5, 6]

 For schema version 6, validate:

   unmapped_columns

 as an array of bounded strings.

 For older schema versions, treat the field as an empty array for backward compatibility.

 Rendering

 Add a visible section such as:

   Pending Sheet mappings

 Each item should state:

   Lab 6 - Q1
   Awaiting course-staff mapping. This column does not earn a checkmark.

 Important behavior:

 - Do not render a green, purple, or shiny-purple mark.
 - Do not include pending columns in the earned total.
 - Do not include them in standard-linked box allocation.
 - Do not render raw cell values.
 - Use textContent and the existing safe DOM helpers.
 - Hide the section when the list is empty.

 templates/simple_student_dashboard.html

 Add a container for pending mappings, for example:

   <section id="unmapped-columns-section" hidden>
     <h2>Pending Sheet mappings</h2>
     <div id="unmapped-columns"></div>
   </section>

 The JavaScript can populate and show this section only when needed.

 static/simple-style.css

 Add a visually distinct non-checkmark pending style with safe wrapping for long headers.

 tests/test_simple_checkoffs.py

 Update the existing Lab 6 - Q1 unmapped-column rejection case so it expects quarantine rather than rejection.

 Add tests covering:

 1. Unknown columns are accepted.
 2. Unknown headers appear in unmapped_columns.
 3. Unknown values are not parsed or published.
 4. Known columns still require valid boolean checkbox values.
 5. Mapped columns do not appear in unmapped_columns.
 6. Duplicate or malformed unmapped metadata is rejected.
 7. Existing mapped opportunities still behave exactly as before.

 tests/test_combined_checkoffs.py

 Add tests confirming that:

 1. Unmapped columns survive the manual-to-combined merge.
 2. Unmapped columns do not create checkmarks.
 3. Unmapped columns do not affect the earned total.
 4. Unmapped columns do not require Gradescope assignments.
 5. A combined record with only unmapped columns passes record validation if the normal S1–S5 structure is present. This is a schema-validator case, not a promise that a production merge with unrelated configured Gradescope assignments can publish a Sheet missing every known mapped column.
 6. A mapped autograded opportunity still requires both Google and Gradescope requirements.

 tests/test_simple_checkoffs.py and a dedicated executable frontend test

 Add executable DOM-level checks, with source-level safety checks as a supplement, confirming that:

 - Schema version 6 is supported.
 - The pending mapping section exists.
 - Pending mappings are rendered with safe DOM methods.
 - innerHTML is not introduced.
 - Pending mappings are not passed into allocation logic.

 tests/test_gradescope_exam.py

 Update schema-version assertions and verify that Exam merging preserves unmapped_columns.

 tests/test_refresh_combined_dashboard.py

 Test that the aggregate warning counts unique headers and never logs header names, NetIDs, or raw cell values.

 tests/test_completion_cache.py

 Confirm that quarantined columns create no cache entries and do not change mapping or contract fingerprints.

 tests/test_documentation.py

 Add documentation checks confirming that:

 - The maintenance documentation describes quarantine behavior.
 - The README describes pending unmapped columns.
 - The schema/version documentation mentions schema version 6.
 - The documentation does not claim that every unknown column aborts publication.

 README.md

 Update the current statement that unknown columns fail closed.

 Document that:

 - Unknown Sheet columns are quarantined.
 - They are shown as pending mappings.
 - They cannot earn marks.
 - Repository mappings are still authoritative.
 - Unknown values are not published.

 Also update the data model section to mention schema version 6 and unmapped_columns.

 docs/maintenance.md

 Add a section such as:

   ### Quarantining new Sheet columns

 Document:

 1. Staff may add a new Sheet column before the code change.
 2. The next refresh will publish it as pending.
 3. The pending column cannot earn a checkmark.
 4. Staff must add the approved mapping to sync/checkoff_mappings.py.
 5. Manual-only opportunities require only the mapping and manual-only declaration.
 6. Autograded opportunities additionally require the Gradescope contract.
 7. A mapping change requires the normal mapping-version update.

 Clarify that the system must never infer a standard or Gradescope policy from a column name.

 docs/standards.md

 Add a policy note stating:

 - The table remains the authoritative mapping.
 - Columns absent from the table are quarantined.
 - Quarantined columns do not count toward grades.
 - A new mapped opportunity must be explicitly classified as manual-only or autograded.

 The Lab opportunity table itself should not list temporary unknown columns.

 docs/deployment.md

 Update deployment guidance to explain:

 - Adding a Sheet column alone no longer blocks publication.
 - The dashboard will show pending mappings.
 - Operators should review the pending section after each refresh.
 - No Gradescope configuration change is needed for an unmapped or manual-only column.
 - A later mapping change may require the normal mapping-version/cache procedure.
 - A Gradescope snapshot should not be retired merely because an unknown manual Sheet column appeared.
 - Install the schema-6 JavaScript (and CSS, if changed) before publishing schema-6 JSON. The new JavaScript must tolerate schema-3–5 pages whose old HTML lacks the pending container during that rollout window. On rollback, restore compatible JSON before rolling back the browser asset.

 scripts/refresh_combined_dashboard.py

 Add an aggregate warning after Sheet normalization, such as:

   [1/6] Warning: unmapped Sheet columns=2

 Do not log:

 - student identities;
 - checkbox values;
 - student-specific details;
 - raw Sheet contents.

 The count should be based on unique column names, not student rows.

 No cache entries should be created for quarantined columns.

 sync/checkoff_mappings.py

 No automatic mapping should be added here.

 Replace the derived autograder complement with two explicit policy sets:

 - MANUAL_ONLY_OPPORTUNITY_IDS;
 - AUTOGRADER_OPPORTUNITY_IDS.

 Validate at import time and in tests that the sets are disjoint and that their union is exactly OPPORTUNITY_IDS. A mapped opportunity in neither set, or in both sets, is a configuration error. Nothing defaults to manual-only or autograded.

 Add OPPORTUNITY_HEADER_GROUPS as the explicit allowed Sheet-header set or alternative sets for every opportunity. Validators must require an exact approved group so a grouped opportunity cannot earn a mark after one of its required columns is dropped. The existing Lab 3 Q2 aggregate header and four-milestone form remain two approved alternatives.

 This file remains the explicit approval point. When staff approve a column:

 1. Add it to COLUMN_MAPPINGS.
 2. Assign its standard ID and opportunity ID.
 3. Add its opportunity ID to exactly one explicit policy set.
 4. If autograded, add the Gradescope rule separately.
 5. Increment LAB_MAPPING_VERSION.

 5. Gradescope behavior

 Manual-only opportunity

 The workflow would be:

 1. Add Sheet column.
 2. Column appears as pending.
 3. Audit/backfill the existing column so every value is a valid checkbox.
 4. Add the mapping.
 5. Add the opportunity to MANUAL_ONLY_OPPORTUNITY_IDS.
 6. Deploy.

 No Gradescope change is needed.

 Autograded opportunity

 The workflow would be:

 1. Add Sheet column.
 2. Column appears as pending.
 3. Audit/backfill the existing column so every value is a valid checkbox.
 4. Add the approved mapping.
 5. Add the opportunity to AUTOGRADER_OPPORTUNITY_IDS.
 6. Add the Gradescope assignment contract.
 7. Increment the mapping/contract versions as required.
 8. Deploy and perform a full validation.

 The system must not automatically assume that a newly mapped opportunity is autograded or manual-only. Every mapped opportunity must belong to exactly one explicit policy set.

 6. Versioning and compatibility

 Use schema version 6 for records containing unmapped_columns.

 Backward compatibility:

 - The browser should continue accepting schemas 3–5.
 - Old records should behave as though unmapped_columns is empty.
 - New backend output should use schema 6.
 - No completion-cache entries should be created for unmapped columns.
 - Adding an unknown column alone should not require a mapping-version bump.
 - Adding the approved mapping later should follow the existing mapping-version rules.

 7. Security and failure policy

 The change should preserve fail-closed behavior for malformed or dangerous data.

 The service should still abort for:

 - invalid NetIDs;
 - duplicate NetIDs;
 - malformed mapped checkbox values;
 - invalid mapped standards;
 - invalid Gradescope contracts;
 - Gradescope-only roster students;
 - malformed records;
 - invalid headers;
 - duplicate unmapped metadata.

 It should not abort solely because a valid-looking new Sheet header is not yet mapped.

 8. Acceptance criteria

 The update is complete when all of the following pass:

 - A new column such as Lab 6 - Q1 does not abort the Sheet import.
 - The dashboard displays it under Pending Sheet mappings.
 - It does not earn a checkmark.
 - It does not affect standard allocation or totals.
 - It does not require a Gradescope rule.
 - Invalid values in existing mapped columns still fail closed.
 - Adding the approved mapping causes existing Sheet data to appear under the correct standard.
 - Manual-only mappings require no Gradescope configuration.
 - Autograded mappings still require exact Gradescope configuration.
 - Existing Lab 1–5 behavior remains unchanged.
 - All Python tests pass.
 - JavaScript syntax checks pass.
 - zola check passes.
 - git diff --check passes.
 - A local canary visibly confirms the pending section.
 - A production refresh logs only an aggregate unmapped-column warning and publishes successfully.