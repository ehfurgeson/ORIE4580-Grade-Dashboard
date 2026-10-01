# Standards and Opportunity Mappings

This document is the human-readable source of truth for course-standard wording and dashboard opportunity mappings. Update this document first when course staff approve a new standard or mapping, then update the executable mirrors in `sync/checkoff_mappings.py`, `sync/gradescope_exam.py`, and `deployment/gradescope.toml.example` in the same change.

## 1. Two standard namespaces

The course materials currently contain two different identifier systems:

1. The rubric catalog uses category IDs such as `P1`, `S1`, and `M1`.
2. The Lab handouts use one sequential display namespace, currently `S1` through `S5`.

These IDs are not interchangeable. For example, handout **S1** is rubric **P1**, while rubric **S2** appears as dashboard **S4**. The dashboard therefore joins records with stable semantic keys and uses the sequential handout ID only for display.

Never join data using a bare display ID such as `S1`. Use the semantic key.

## 2. Rubric standard catalog

| Rubric ID | Category | Standard wording | Current handout/dashboard mapping |
|---|---|---|---|
| P1 | Probability | I can state the defining features of uniform samplers, use them to construct new samplers, and use them to check if a given sampler is valid. | S1 / `uniform_samplers` |
| P2 | Probability | I can state the defining features of Poisson samplers, use them to construct new samplers, and use them to check if a given sampler is valid. | Not mapped yet |
| P3 | Probability | I can state the defining features of Gaussian samplers, use them to construct new samplers, and use them to check if a given sampler is valid. | Not mapped yet |
| P4 | Probability | I can create a sampler for a general one-dimensional probability distribution given its CDF or PDF. | S2 / `general_1d_sampler` |
| P5 | Probability | I can list different ways in which a stochastic process might be unstable and assess whether each is occurring in a given simulation. | Not mapped exactly; do not substitute for handout S3 |
| S1 | Statistics | I can explain how different histogram parameters impact the resulting plot and choose appropriate parameters for a given dataset. | Not mapped yet |
| S2 | Statistics | I can apply the formal definition of confidence intervals to derive confidence interval procedures for both traditional and novel parameter estimation tasks. | S4 / `histogram_parameters` |
| S3 | Statistics | I can apply confidence intervals in practical situations, handling concerns such as non-independence, multiple hypotheses, and multiple stages of study. | S5 / `confidence_interval_procedures` |
| S4 | Statistics | I can write an expression for the log-likelihood of a candidate parameterized model. | Not mapped yet |
| S5 | Statistics | I can implement a variance reduction technique, explain in what sense it reduces variance, and explain the tradeoffs of the technique. | Not mapped yet |
| M1 | Modeling | I can model a scenario as a Markov chain or event-driven simulation by specifying what the system state is and how the state changes over time. | Not mapped yet |
| M2 | Modeling | I can combine multiple sources of evidence and my own reasoning to make practical decisions about how to model or optimize a process. | Not mapped yet |

## 3. Active handout/dashboard standards

Only standards with a confirmed dashboard opportunity belong in this active table.

| Display ID | Semantic key | Authoritative display wording | Rubric crosswalk |
|---|---|---|---|
| S1 | `uniform_samplers` | I can state the defining features of uniform samplers, use them to construct new samplers, and use them to check if a given sampler is valid. | P1 |
| S2 | `general_1d_sampler` | I can create a sampler for a general one-dimensional probability distribution given its CDF or PDF. | P4 |
| S3 | `simulation_output_variability` | I can use probabilistic concepts to qualitatively and quantitatively explain the sort of variability one should expect from a simulation's output. | No exact rubric equivalent |
| S4 | `histogram_parameters` | I can apply the formal definition of confidence intervals to derive confidence interval procedures for both traditional and novel parameter estimation tasks. | Rubric S2 |
| S5 | `confidence_interval_procedures` | I can apply confidence intervals in practical situations, handling concerns such as non-independence, multiple hypotheses, and multiple stages of study. | Rubric S3 |

The active display wording reflects the course staff update of October 1, 2026. S3 is related to rubric P5, but is not equivalent. The existing S4 and S5 keys are retained for compatibility with stored records and opportunity mappings; their names reflect earlier wording. Use the authoritative display wording above.

## 4. Green Lab mappings

Every listed Lab opportunity requires its Google Sheet checkoff. An **Autograded** opportunity additionally requires one full-credit Gradescope submission under the exact configured contract. A **Manual-only** opportunity has no Gradescope assignment and earns green from the recorded checkoff alone.

| Green opportunity | Opportunity ID | Display standard | Semantic key | Google Sheet column(s) | Policy | Gradescope assignment and contract |
|---|---|---|---|---|---|---|
| Lab 1, Q1–2 | `lab1-q1-2` | S1 | `uniform_samplers` | `Lab 1 - Q1.3`; `Lab 1 - Q2.3`; `Lab 1 - Q2.4` | Autograded | `8532407`; 11 points; 11 × 1-point tests |
| Lab 1, Q3 | `lab1-q3` | S1 | `uniform_samplers` | `Lab 1 - Q3` | Autograded | `8532445`; 1 point; 1 × 1-point test |
| Lab 2, Q1 | `lab2-q1` | S1 | `uniform_samplers` | `Lab 2 - Q1` | Autograded | `8603427`; 6 points; 6 × 1-point tests |
| Lab 2, Q2 | `lab2-q2` | S2 | `general_1d_sampler` | `Lab 2 - Q2` | Autograded | `8603442`; 1 point; 1 × 1-point test |
| Lab 2, Q3 | `lab2-q3` | S2 | `general_1d_sampler` | `Lab 2 - Q3` | Autograded | `8603445`; 3 points; 3 × 1-point tests |
| Lab 3, Q1 | `lab3-q1` | S2 | `general_1d_sampler` | `Lab 3 - Q1` | Autograded | `8693888`; 1 point; 1 × 1-point test |
| Lab 3, Q2.1–2.4 | `lab3-q2` | S3 | `simulation_output_variability` | `Lab 3 - Q2`, or milestone columns `Lab 3 - Q2.1`; `Lab 3 - Q2.2`; `Lab 3 - Q2.3`; `Lab 3 - Q2.4` | Autograded | `8693897`; 2 points; 2 × 1-point tests |
| Lab 3, Q3 | `lab3-q3` | S3 | `simulation_output_variability` | `Lab 3 - Q3` | Autograded | `8693907`; 1 point; 1 × 1-point test |
| Lab 4, Q1 | `lab4-q1` | S3 | `simulation_output_variability` | `Lab 4 - Q1` | **Manual-only** | None |
| Lab 4, Q2 | `lab4-q2` | S4 | `histogram_parameters` | `Lab 4 - Q2` | Autograded | `8757792`; 3 points; 3 × 1-point tests |
| Lab 4, Q3 | `lab4-q3` | S5 | `confidence_interval_procedures` | `Lab 4 - Q3` | Autograded | `8758286`; 2 points; 2 × 1-point tests |

### Grouped manual checkoffs

Lab 1 Q1–2 is one green opportunity, not three. All three listed Sheet milestones must be complete. When the Lab 3 Q2 milestone columns are present, all recorded milestones must be complete for its one green opportunity.

### Lab 4 student-facing requirements

- **S3 / Q1:** complete Q1, then ask for a checkoff. There is no autograded component.
- **S4 / Q2:** complete Q2, pass the Q2 Gradescope autograder, then ask for a checkoff.
- **S5 / Q3:** complete Q3, pass the Q3 Gradescope autograder, then ask for a checkoff.

## 5. Exam 1 mappings

Gradescope assignment `8667062` is the finalized `Exam 1` rubric (`exam1-final-v1`). Each question is out of 1 point. A score strictly greater than `0.8` earns the mapped checkmark; exactly `0.8` does not.

| Exam 1 question | Dashboard opportunity | Display standard | Semantic key | Checkmark kind |
|---|---|---|---|---|
| Question 1 | `exam1-q1` | S2 | `general_1d_sampler` | Purple |
| Question 2 | `exam1-q2` | S2 | `general_1d_sampler` | Purple |
| Question 3 | `exam1-q3` | S1 | `uniform_samplers` | Purple |
| Question 4 | `exam1-q4` | S1 | `uniform_samplers` | Purple |
| Question 5 | `exam1-q5` | S1 | `uniform_samplers` | Shiny purple |
| Question 6 | `exam1-q6` | S2 | `general_1d_sampler` | Shiny purple |

Exam scores are normalized to completion statuses. Raw question scores are not written to student dashboard JSON.

## 6. Checkmark allocation rules

The opportunity mapping does not alter the rubric allocation rules:

- Each standard has two standard-linked boxes.
- Earned marks fill linked boxes in this order: purple, shiny purple, then green.
- Extra ordinary purple and green marks do not count toward the grade calculation.
- An earned shiny-purple mark not used in a linked box fills an additional shiny box.
- A shiny-purple mark counts toward both purple and shiny totals while occupying only one box.
- “Missing” is the number of empty standard-linked boxes.
- Grade thresholds are minimums except `missing`, which is a maximum.

Student pages show both linked boxes and all earned checkmarks in a compact overview. The shiny pool includes only earned shiny-purple marks left over after linked-box allocation. Each standard also shows its own shiny overflow, and each earned opportunity states whether it fills a linked box, fills the shiny pool, or is an extra mark that does not count toward the grade.

## 7. Change-control rules

When course staff approve a new or changed mapping:

1. Update the wording and mapping in this document.
2. Update `sync/checkoff_mappings.py` for standards and Lab opportunities.
3. Update `sync/gradescope_exam.py` for exam opportunities.
4. Update `deployment/gradescope.toml.example` for exact Gradescope contracts.
5. Increment the relevant mapping, contract, or rubric version.
6. Update mapping, merge, cache, frontend, and end-to-end tests.
7. Run a one-student live preview before following [`deployment.md`](deployment.md).

A Sheet header, standard, Gradescope assignment, or rubric that is not explicitly recorded here must not be guessed or silently mapped.
