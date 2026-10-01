# Dashboard Maintenance

This guide explains the dashboard data flow and how to add labs, standards, exams, checkmark kinds, or data sources. For releasing reviewed changes to Ubuntu, see [`deployment.md`](deployment.md).

## 1. How lab checkmarks flow through the system

A lab opportunity has up to two independent facts:

1. A Google Sheet checkbox records the staff checkoff.
2. A configured Gradescope assignment records an autograder pass.

An autograded opportunity earns green only when both facts are complete. A declared manual-only opportunity earns green from the Google Sheet checkbox alone.

The main files are:

| File | Responsibility |
|---|---|
| `sync/standards.py` | Shared standard IDs and wording |
| [`standards.md`](standards.md) | Reviewed opportunity mappings and import migration rules |
| `sync/checkoff_mappings.py` | Sheet columns, opportunity IDs, labels, manual-only set, and mapping version |
| `deployment/gradescope.toml.example` | Executable production course and exact autograder contracts |
| `sync/gradescope.py` | Strict Gradescope configuration and submission validation |
| `sync/combined_checkoffs.py` | Merge manual and autograder requirements |
| `sync/completion_cache.py` | Positive-result cache tied to exact contracts and mapping version |
| `static/simple-dashboard.js` | Browser validation and rendering |
| `templates/simple_student_dashboard.html` | Generated student-page shell |
| `tests/` | Mapping, merge, cache, frontend, and deployment behavior |

### 1.1 Lab 4 worked example

The standards are defined in `sync/standards.py`. The Lab 4 Sheet columns, requirement policies, and Gradescope contracts are recorded in [`standards.md`](standards.md#3-green-lab-mappings). The implementation work was:

- Added the S4 and S5 display text and all three exact Sheet headers.
- Added `MANUAL_ONLY_OPPORTUNITY_IDS` and derived the autograded set from it.
- Bumped `LAB_MAPPING_VERSION` from `lab-mapping-v1` to `lab-mapping-v2`.
- Changed the merger, validator, browser, and cache so a manual-only Lab is first-class and cannot accidentally receive an autograder rule or cached autograder evidence.
- Added the two real Gradescope rules to the deployment config, but deliberately added no Q1 rule.
- Updated the dashboard explanation, README, authoritative [`standards.md`](standards.md) mapping tables, and regression tests.
- Validated the current 174-row Sheet and performed a successful live one-student refresh against all 10 configured Lab assignments.

## 2. Adding a new lab

### 2.1 Collect the facts first

For every green checkmark, record all of the following before editing code:

- Exact Google Sheet column header.
- Display standard ID and authoritative standard wording.
- A stable opportunity ID, such as `lab4-q2`.
- Whether it is manual-only or manual plus autograder.
- Exact Gradescope title and assignment ID when autograded.
- Exact full score, number of autograder tests, and ordered maximum score of each test.

Never guess a standard, assignment ID, or autograder contract. The pipeline intentionally fails closed when one changes.

Put new or revised standard wording in `sync/standards.py`. Record the approved opportunity mapping, policy, and contract in [`standards.md`](standards.md) first. That reviewed document is the opportunity-mapping authority.

### 2.2 Update the source mapping

Mirror the approved mapping from `standards.md` into `sync/checkoff_mappings.py`:

1. Add new standards to `sync/standards.py` only; mappings use their S IDs directly.
2. Add each exact Sheet header to `COLUMN_MAPPINGS`.
3. Use the same opportunity ID for multiple Sheet columns that jointly form one checkmark.
4. Add manual-only IDs to `MANUAL_ONLY_OPPORTUNITY_IDS`.
5. Leave autograded IDs out of that set; `AUTOGRADER_OPPORTUNITY_IDS` is derived automatically.
6. Increment `LAB_MAPPING_VERSION` when the effective mapping changes.

Example shapes:

```python
COLUMN_MAPPINGS = {
    # One checkbox, no autograder.
    "Lab 4 - Q1": ("S3", "lab4-q1", "Lab 4 · Q1"),

    # One checkbox plus one configured Gradescope assignment.
    "Lab 4 - Q2": ("S4", "lab4-q2", "Lab 4 · Q2"),

    # Several checkboxes jointly produce one opportunity.
    "Lab 5 - Q2.1": ("S6", "lab5-q2", "Lab 5 · Q2"),
    "Lab 5 - Q2.2": ("S6", "lab5-q2", "Lab 5 · Q2"),
}

MANUAL_ONLY_OPPORTUNITY_IDS = frozenset({"lab4-q1"})
```

All grouped Sheet columns must be complete before their single manual requirement is complete.

### 2.3 Configure each autograded opportunity

Add one block to `deployment/gradescope.toml.example`. Do not add a block for a manual-only opportunity.

```toml
[assignments."GRADESCOPE_ASSIGNMENT_ID"]
opportunity_id = "lab5-q2"
contract_version = "lab5-q2-v1"
expected_score = "3"
expected_test_count = 3
expected_test_maxima = ["1", "1", "1"]
title_mapping_override = false
```

The Gradescope title should follow `Lab N, QN` or `Lab N, QN-N`. Keep `title_mapping_override = false` unless a reviewed legacy title cannot follow that convention.

Bump `contract_version` whenever the assignment's test contract changes. Update the expected score, count, and maxima at the same time. A version change prevents stale pass evidence from being treated as proof under a different contract.

### 2.4 Update tests and documentation

At minimum:

- Add the new Sheet mapping to `tests/test_simple_checkoffs.py`.
- Test manual-only and two-source behavior in `tests/test_combined_checkoffs.py`.
- Test title/config behavior in `tests/test_gradescope.py`.
- Test cache eligibility in `tests/test_completion_cache.py`.
- Confirm the opportunity mapping still matches [`standards.md`](standards.md) and references IDs in the shared catalog.
- Update user-facing copy only if the requirement types or policy changed.

Run the complete preflight checks in [`deployment.md`](deployment.md#21-before-connecting-to-ubuntu). Then perform a one-student live preview before production:

```sh
rm -rf generated/combined-env-preview
.venv/bin/python -m scripts.refresh_combined_dashboard \
  imports/gradescope/config.toml \
  generated/combined-env-preview/students \
  generated/combined-env-state.json \
  --worksheet-id 41104109 \
  --spreadsheet-id 1e_5BQpysMUWfKrNw4MS7qg--2TySAno8rCBmuKapiME \
  --disable-completion-cache \
  --copy-assets-to generated/combined-env-preview
```

The selected canary comes from `GRADESCOPE_TEST_STUDENT_EMAIL` in the ignored `.env` file.

## 3. Adding or changing an exam

Exam 1 is more specialized than labs. Its mapping is currently explicit in `sync/gradescope_exam.py`, and `sync/gradescope.py` currently validates the finalized six-question Exam 1 contract. A second exam is therefore a code change, not only a TOML addition.

For an Exam 1 mapping change:

1. Update the authoritative exam mapping and earning rule in [`standards.md`](standards.md).
2. Mirror it in `EXAM_OPPORTUNITIES` in `sync/gradescope_exam.py`.
3. Set each opportunity ID, question number, standard ID, label, and kind (`purple` or `shiny_purple`).
4. Increment `EXAM_MAPPING_VERSION`.
5. Update `[exam]` in `deployment/gradescope.toml.example` with the exact assignment ID, human-readable title, rubric version, question count, question maximum, and threshold.
6. Increment `rubric_version` whenever the rubric or earning rule changes.
7. Update `tests/test_gradescope_exam.py`, cache tests, and combined-record tests, then confirm the executable mapping matches `standards.md`.

For Exam 2 or a different exam format, first generalize the singular `[exam]` config and `EXAM_OPPORTUNITIES` model into a list of versioned exam rules. Do not copy Exam 1 and silently reuse its IDs or six-question assumptions. Preserve these properties:

- Raw scores are never written to student dashboard JSON.
- Each question maps explicitly to one catalog standard.
- Purple versus shiny-purple is explicit.
- Threshold comparison is explicit, including equality behavior.
- Rubric drift invalidates cached evidence.
- Optional exam failure remains isolated from strict Lab publication unless course policy intentionally changes.

## 4. Adding another source or checkmark kind

A new source or a new checkmark kind requires a schema change rather than a mapping-only edit. Update, in order:

1. The normalized source adapter and its strict validator.
2. The combined record schema and server-side validation.
3. The browser validator and renderer.
4. Cache policy and versioning, if positive evidence is reusable.
5. Fixtures and end-to-end tests.
6. User-facing legend and explanatory copy.
7. Deployment credentials and systemd sandbox permissions, if the source needs them.

Do not expose raw grades, free-form grader output, credentials, submission IDs, or student emails in generated JSON or logs.

## 5. Maintenance checklist

- [ ] Authoritative mapping and wording recorded.
- [ ] New Sheet headers mapped exactly.
- [ ] Manual-only versus autograded policy explicit.
- [ ] Gradescope IDs and contracts observed, not guessed.
- [ ] Mapping and rubric/contract versions bumped where required.
- [ ] Full tests, JavaScript syntax check, Zola check, and `git diff --check` pass.
- [ ] One-student live preview validates.
- [ ] Changes are ready for the process in [`deployment.md`](deployment.md).
