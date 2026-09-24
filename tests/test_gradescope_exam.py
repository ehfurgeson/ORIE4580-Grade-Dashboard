from decimal import Decimal

from sync.combined_checkoffs import merge_checkoffs_with_autograders, merge_exam_checkmarks, validate_combined_record
from sync.gradescope import ExamRule, assignment_title_matches
from sync.gradescope_exam import EXAM_OPPORTUNITIES, import_exam_soft, parse_exam_scores_csv
from sync.simple_checkoffs import rows_to_simple_records


RULE = ExamRule(8667062, "Exam 1", 6, Decimal("1"), Decimal("0.8"))
FINAL_RULE = ExamRule(
    8667062, "Exam 1", 6, Decimal("1"), Decimal("0.8"),
    "exam1-final-v1", True,
)
HEADERS = [
    "Email",
    "1: One (1.0 pts)", "2: Two (1.0 pts)", "3: Three (1.0 pts)",
    "4: Four (1.0 pts)", "5: Five (1.0 pts)", "6: Six (1.0 pts)",
]


def exam_csv(scores):
    return ",".join(HEADERS) + "\nabc123@cornell.edu," + ",".join(scores) + "\n"


def lab_record():
    return rows_to_simple_records(
        [{"NetID": "abc123", "Lab 1 - Q1.3": True, "Lab 1 - Q2.3": True, "Lab 1 - Q2.4": True}],
        updated_at="2026-09-24T12:00:00Z",
        worksheet="Lab Checkoffs",
    )[0]


def lab_snapshot():
    return {
        "schema_version": 1, "source": "gradescope_unofficial_read_only", "course_id": 1379687,
        "generated_at": "2026-09-24T12:01:00Z",
        "assignments": [{
            "assignment_id": 8532407, "opportunity_id": "lab1-q1-2",
            "contract_version": "lab1-q1-2-v1", "expected_score": "1",
            "expected_test_count": 1, "expected_test_maxima": ["1"],
            "title_mapping_override": False,
        }],
        "students": [{"netid": "abc123", "autograders": [{
            "opportunity_id": "lab1-q1-2", "status": "passed",
            "pass_evidence": "current_history", "submissions_observed": 1,
            "submissions_checked": 1,
        }]}],
        "unmatched_members": 0,
    }


def test_exam_title_uses_spaces_but_matches_upstream_separator():
    assert RULE.title == "Exam 1"
    assert assignment_title_matches(RULE.title.replace(" ", "_"), RULE.title)
    assert assignment_title_matches("Exam 1", RULE.title)
    assert not assignment_title_matches("Exam 2", RULE.title)


def test_exam_threshold_is_strictly_over_point_eight():
    result = parse_exam_scores_csv(
        exam_csv(["0.81", "0.8", "1", "0", "0.9", ""]), RULE, ["abc123"]
    )
    assert result.available
    assert [item["status"] for item in result.by_netid["abc123"]] == [
        "complete", "incomplete", "complete", "incomplete", "complete", "not_graded"
    ]


def test_exam_mapping_has_the_reviewed_standard_and_color_contract():
    assert [(item["question"], item["standard_key"], item["kind"]) for item in EXAM_OPPORTUNITIES] == [
        (1, "general_1d_sampler", "purple"),
        (2, "general_1d_sampler", "purple"),
        (3, "uniform_samplers", "purple"),
        (4, "uniform_samplers", "purple"),
        (5, "uniform_samplers", "shiny_purple"),
        (6, "general_1d_sampler", "shiny_purple"),
    ]


def test_rubric_drift_soft_fails_to_not_graded_without_blocking_labs():
    class Source:
        def exam_scores_csv(self):
            return exam_csv(["1", "1", "1", "1", "1", "1"]).replace("1.0 pts", "2.0 pts", 1)

    exam = import_exam_soft(Source(), RULE, ["abc123"])
    assert not exam.available
    assert {item["status"] for item in exam.by_netid["abc123"]} == {"not_graded"}

    labs = merge_checkoffs_with_autograders([lab_record()], lab_snapshot())
    combined = merge_exam_checkmarks(labs, exam)[0]
    assert combined["schema_version"] == 4
    assert validate_combined_record(combined) == []
    lab = next(item for standard in combined["standards"] for item in standard["checkmarks"] if item["kind"] == "green")
    assert lab["status"] == "complete"


def test_exam_results_merge_into_s1_and_s2_with_no_raw_scores():
    exam = parse_exam_scores_csv(exam_csv(["1"] * 6), RULE, ["abc123"])
    labs = merge_checkoffs_with_autograders([lab_record()], lab_snapshot())
    record = merge_exam_checkmarks(labs, exam)[0]
    by_standard = {standard["id"]: standard["checkmarks"] for standard in record["standards"]}
    assert [item["id"] for item in by_standard["S1"] if item["kind"] != "green"] == [
        "exam1-q3", "exam1-q4", "exam1-q5"
    ]
    assert [item["id"] for item in by_standard["S2"] if item["kind"] != "green"] == [
        "exam1-q1", "exam1-q2", "exam1-q6"
    ]
    assert "0.8" not in str(record)
    assert validate_combined_record(record) == []


def test_finalized_exam_cache_is_positive_only_and_monotone():
    class Source:
        calls = 0
        def exam_scores_csv(self):
            self.calls += 1
            return exam_csv(["0.8", "1", "", "0", "0.9", ""])

    source = Source()
    prior = frozenset({("abc123", "exam1-q1"), ("abc123", "exam1-q3")})
    result = import_exam_soft(
        source, FINAL_RULE, ["abc123"],
        current_gradescope_netids=frozenset({"abc123"}),
        prior_completions=prior,
    )
    assert source.calls == 1  # ETag behavior is unproven; the export is still checked.
    assert [item["status"] for item in result.by_netid["abc123"]] == [
        "complete", "complete", "complete", "incomplete", "complete", "not_graded",
    ]
    assert ("abc123", "exam1-q1") in result.verified_completions
    assert ("abc123", "exam1-q2") in result.verified_completions
    assert result.cache_hits == 2


def test_exam_soft_failure_reuses_only_current_roster_completions():
    class Source:
        def exam_scores_csv(self):
            raise ValueError("unavailable")

    prior = frozenset({("abc123", "exam1-q1"), ("xy99", "exam1-q1")})
    result = import_exam_soft(
        Source(), FINAL_RULE, ["abc123", "xy99"],
        current_gradescope_netids=frozenset({"abc123"}),
        prior_completions=prior,
    )
    assert not result.available
    assert result.by_netid["abc123"][0]["status"] == "complete"
    assert {item["status"] for item in result.by_netid["xy99"]} == {"not_graded"}
    assert result.verified_completions == frozenset({("abc123", "exam1-q1")})


def test_unfinalized_exam_does_not_reuse_positive_cache():
    class Source:
        def exam_scores_csv(self):
            raise ValueError("unavailable")

    result = import_exam_soft(
        Source(), RULE, ["abc123"],
        current_gradescope_netids=frozenset({"abc123"}),
        prior_completions=frozenset({("abc123", "exam1-q1")}),
    )
    assert {item["status"] for item in result.by_netid["abc123"]} == {"not_graded"}
    assert not result.verified_completions
