# Standards and Opportunity Mappings

## 1. Standards catalog

[`sync/standards.py`](../sync/standards.py) is the single source of truth for standard IDs and wording. It defines the currently approved S1–S5 standards. Both the row-based importer and the live Lab/Exam dashboard use this catalog. Change standard wording there; do not maintain a second catalog here or in `sync/checkoff_mappings.py`.

This document records the reviewed opportunity mappings. Mirror mapping changes in `sync/checkoff_mappings.py`, `sync/gradescope_exam.py`, and `deployment/gradescope.toml.example` as applicable.

Lab and Exam mappings refer directly to the catalog IDs, such as `S1`. There are no separate descriptive keys or categories to maintain.

## 2. Old records and imports

The former tentative twelve-standard catalog has been removed. Its P/M IDs are no longer accepted. Its S IDs also had different wording, so there is no automatic translation from that catalog.

For the row-based CSV/API importer, use the current S1–S5 IDs in `standard_id`. Re-export old source data with an explicit, reviewed assignment to the current standards; do not relabel old rows by number. A CSV row with only an S ID cannot identify which catalog it came from. Regenerate old `grades.json` releases after correcting the source; JSON validation rejects obsolete IDs and wording before publication.

The live wide-sheet pipeline now writes records with only `id`, `name`, and `checkmarks` per standard. The schema versions are 5 (manual), 6 (combined Labs), and 7 (combined Labs and Exam 1). The browser also accepts older versions 2–4, so deploy the updated JavaScript before generating new records. Older backend records must be regenerated from the source data.

Lab and Exam opportunity IDs, earning rules, and grading rules are unchanged. No Google Sheet or Gradescope changes are needed for the live pipeline, and existing Gradescope snapshots remain compatible. Mapping versions have advanced because references now use S IDs. Before refreshing, use the [one-time completion-cache migration](deployment.md#one-time-standard-id-cache-migration) to retain verified completions. Without migration, old completion caches are rejected and Gradescope is crawled again. Keep the previous release and cache for rollback.

## 3. Green Lab mappings

Every listed Lab opportunity requires its Google Sheet checkoff. An **Autograded** opportunity additionally requires one full-credit Gradescope submission under the exact configured contract. A **Manual-only** opportunity has no Gradescope assignment and earns green from the recorded checkoff alone.

| Green opportunity | Opportunity ID | Display standard | Google Sheet column(s) | Policy | Gradescope assignment and contract |
|---|---|---|---|---|---|
| Lab 1, Q1–2 | `lab1-q1-2` | `S1` | `Lab 1 - Q1.3`; `Lab 1 - Q2.3`; `Lab 1 - Q2.4` | Autograded | `8532407`; 11 points; 11 × 1-point tests |
| Lab 1, Q3 | `lab1-q3` | `S1` | `Lab 1 - Q3` | Autograded | `8532445`; 1 point; 1 × 1-point test |
| Lab 2, Q1 | `lab2-q1` | `S1` | `Lab 2 - Q1` | Autograded | `8603427`; 6 points; 6 × 1-point tests |
| Lab 2, Q2 | `lab2-q2` | `S2` | `Lab 2 - Q2` | Autograded | `8603442`; 1 point; 1 × 1-point test |
| Lab 2, Q3 | `lab2-q3` | `S2` | `Lab 2 - Q3` | Autograded | `8603445`; 3 points; 3 × 1-point tests |
| Lab 3, Q1 | `lab3-q1` | `S2` | `Lab 3 - Q1` | Autograded | `8693888`; 1 point; 1 × 1-point test |
| Lab 3, Q2.1–2.4 | `lab3-q2` | `S3` | `Lab 3 - Q2`, or milestone columns `Lab 3 - Q2.1`; `Lab 3 - Q2.2`; `Lab 3 - Q2.3`; `Lab 3 - Q2.4` | Autograded | `8693897`; 2 points; 2 × 1-point tests |
| Lab 3, Q3 | `lab3-q3` | `S3` | `Lab 3 - Q3` | Autograded | `8693907`; 1 point; 1 × 1-point test |
| Lab 4, Q1 | `lab4-q1` | `S3` | `Lab 4 - Q1` | **Manual-only** | None |
| Lab 4, Q2 | `lab4-q2` | `S4` | `Lab 4 - Q2` | Autograded | `8757792`; 3 points; 3 × 1-point tests |
| Lab 4, Q3 | `lab4-q3` | `S5` | `Lab 4 - Q3` | Autograded | `8758286`; 2 points; 2 × 1-point tests |

### Grouped manual checkoffs

Lab 1 Q1–2 is one green opportunity, not three. All three listed Sheet milestones must be complete. When the Lab 3 Q2 milestone columns are present, all recorded milestones must be complete for its one green opportunity.

### Lab 4 student-facing requirements

- **S3 / Q1:** complete Q1, then ask for a checkoff. There is no autograded component.
- **S4 / Q2:** complete Q2, pass the Q2 Gradescope autograder, then ask for a checkoff.
- **S5 / Q3:** complete Q3, pass the Q3 Gradescope autograder, then ask for a checkoff.

## 4. Exam 1 mappings

Gradescope assignment `8667062` is the finalized `Exam 1` rubric (`exam1-final-v1`). Each question is out of 1 point. A score strictly greater than `0.8` earns the mapped checkmark; exactly `0.8` does not.

| Exam 1 question | Dashboard opportunity | Display standard | Checkmark kind |
|---|---|---|---|
| Question 1 | `exam1-q1` | `S2` | Purple |
| Question 2 | `exam1-q2` | `S2` | Purple |
| Question 3 | `exam1-q3` | `S1` | Purple |
| Question 4 | `exam1-q4` | `S1` | Purple |
| Question 5 | `exam1-q5` | `S1` | Shiny purple |
| Question 6 | `exam1-q6` | `S2` | Shiny purple |

Exam scores are normalized to completion statuses. Raw question scores are not written to student dashboard JSON.

## 5. Checkmark allocation rules

The opportunity mapping does not alter the rubric allocation rules:

- Each standard has two standard-linked boxes.
- Earned marks fill linked boxes in this order: purple, shiny purple, then green.
- Extra ordinary purple and green marks do not count toward the grade calculation.
- An earned shiny-purple mark not used in a linked box fills an additional shiny box.
- A shiny-purple mark counts toward both purple and shiny totals while occupying only one box.
- “Missing” is the number of empty standard-linked boxes.
- Grade thresholds are minimums except `missing`, which is a maximum.

Student pages show both linked boxes and all earned checkmarks in a compact overview. The shiny pool includes only earned shiny-purple marks left over after linked-box allocation. Each standard also shows its own shiny overflow, and each earned opportunity states whether it fills a linked box, fills the shiny pool, or is an extra mark that does not count toward the grade.

## 6. Change-control rules

When course staff approve a new or changed mapping:

1. Update `sync/standards.py` if standard IDs or wording change.
2. Update this document and `sync/checkoff_mappings.py` for Lab opportunity mappings.
3. Update `sync/gradescope_exam.py` for exam opportunities.
4. Update `deployment/gradescope.toml.example` for exact Gradescope contracts.
5. Increment the relevant mapping, contract, or rubric version.
6. Update mapping, merge, cache, frontend, and end-to-end tests.
7. Run a one-student live preview before following [`deployment.md`](deployment.md).

A Sheet header, standard, Gradescope assignment, or rubric that is not explicitly recorded here must not be guessed or silently mapped.
