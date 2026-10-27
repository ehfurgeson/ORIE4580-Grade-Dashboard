import csv
import io
from itertools import product

import pytest

from sync.gradescope_exam2 import (
    EXAM2_OPPORTUNITIES, EXAM2_SOURCE_IDS, import_exam2_soft, parse_exam2_scores_csvs,
)

COUNTS = (5, 8, 6, 5, 3, 2, 2, 4, 1, 1, 1, 6)
LEAVES = [str(q) if n == 1 else f"{q}.{p}" for q, n in enumerate(COUNTS, 1) for p in range(1, n + 1)]
HEADERS = ["Email", "Status", "Submission ID", "Submission Count"] + [f"{leaf}: title (1.0 pts)" for leaf in LEAVES]
SOURCE_IDS = sorted(EXAM2_SOURCE_IDS)


def row(scores=None, *, email="abc123@cornell.edu", missing=False):
    scores = scores or {}
    return [email, "Missing" if missing else "Graded", "" if missing else "12345", "0" if missing else "1"] + [
        "null" if missing else str(scores.get(leaf, "1")) for leaf in LEAVES
    ]


def csv_text(rows, headers=HEADERS):
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(headers)
    writer.writerows(rows)
    return stream.getvalue()


def exports(scores=None):
    return {source: csv_text([row(scores, missing=index != 0)]) for index, source in enumerate(SOURCE_IDS)}


def marks(scores=None):
    result = parse_exam2_scores_csvs(exports(scores), ["abc123"])
    assert result.available
    return result.by_netid["abc123"]


def soft(data, current=frozenset({"abc123"})):
    class Source:
        def exam2_scores_csvs(self):
            return data
    return import_exam2_soft(Source(), ["abc123"], current_gradescope_netids=current)


def test_reviewed_mapping_and_student_payload_privacy():
    result = marks()
    assert len(LEAVES) == 44
    assert [m["standard_id"] for m in result] == ["S1", "S1", "S2", "S3", "S3", "S4", "S4", "S5", "S5", "S1", "S2", "S4"]
    assert [m["kind"] for m in result] == ["purple"] * 7 + ["shiny_purple", "purple"] + ["shiny_purple"] * 3
    assert EXAM2_OPPORTUNITIES[7]["allowed_kinds"] == ("purple", "shiny_purple")
    assert all(set(m) == {"id", "question", "standard_id", "label", "kind", "status"} for m in result)
    assert len({m["id"] for m in result}) == 12
    assert all(m["status"] == "complete" for m in result)


@pytest.mark.parametrize("question,total,threshold", [(1, 5, 4), (2, 8, 7), (3, 6, 5)])
def test_threshold_boundaries_and_partial_credit(question, total, threshold):
    for correct in (threshold - 1, threshold, total):
        scores = {f"{question}.{part}": "1" if part <= correct else "0.999" for part in range(1, total + 1)}
        result = marks(scores)
        assert result[question - 1]["status"] == ("complete" if correct >= threshold else "incomplete")
        assert all(m["status"] == "complete" for m in result if m["question"] != question)


@pytest.mark.parametrize("question", [4, 5, 6, 7, 9, 10, 11, 12])
def test_all_parts_required(question):
    leaf = str(question) if COUNTS[question - 1] == 1 else f"{question}.1"
    assert marks({leaf: "0.99"})[question - 1]["status"] == "incomplete"


@pytest.mark.parametrize("pattern", list(product((0, 1), repeat=4)))
def test_q8_shiny_first_all_binary_patterns(pattern):
    q8 = marks({f"8.{i}": str(score) for i, score in enumerate(pattern, 1)})[7]
    assert q8["id"] == "exam2-q8"
    assert q8["kind"] == ("shiny_purple" if all(pattern) else "purple")
    assert q8["status"] == ("complete" if pattern[:2] == (1, 1) else "incomplete")


@pytest.mark.parametrize("missing", ["", "null", " NULL "])
def test_missing_question_grades_do_not_award_or_fail(missing):
    result = marks({"1.5": missing, "8.4": missing})
    assert result[0]["status"] == result[7]["status"] == "not_graded"
    assert result[7]["kind"] == "purple"
    assert result[1]["status"] == "complete"


def test_placeholder_order_zero_submission_and_identity_normalization():
    data = exports({leaf: "0" for leaf in LEAVES})
    assert all(m["status"] == "incomplete" for m in parse_exam2_scores_csvs(dict(reversed(list(data.items()))), ["abc123"]).by_netid["abc123"])
    data[SOURCE_IDS[0]] = csv_text([row(email=" ABC123@CORNELL.EDU ")])
    assert all(m["status"] == "complete" for m in parse_exam2_scores_csvs(data, ["abc123"]).by_netid["abc123"])
    data = {source: csv_text([row(missing=True)]) for source in SOURCE_IDS}
    assert all(m["status"] == "not_graded" for m in parse_exam2_scores_csvs(data, ["abc123"]).by_netid["abc123"])


@pytest.mark.parametrize("same_source", [False, True])
def test_duplicate_actual_submissions_reject_logical_exam(same_source):
    data = exports()
    target = SOURCE_IDS[0] if same_source else SOURCE_IDS[1]
    data[target] = csv_text([row(), row()]) if same_source else csv_text([row()])
    result = soft(data)
    assert not result.available
    assert all(m["status"] == "not_graded" for m in result.by_netid["abc123"])
    assert "abc123" not in result.message and "12345" not in result.message


@pytest.mark.parametrize("bad", ["garbage", "NaN", "Infinity", "-0.1", "1.1"])
def test_invalid_scores_soft_fail(bad):
    assert not soft(exports({"1.1": bad})).available


@pytest.mark.parametrize("change", ["missing_source", "parent", "missing_leaf", "extra_leaf", "duplicate_header", "duplicate_identity", "max", "malformed_header", "malformed_row"])
def test_exact_source_and_leaf_contract(change):
    data = exports()
    headers = list(HEADERS)
    values = row()
    if change == "missing_source":
        data.pop(SOURCE_IDS[-1])
    elif change == "parent":
        data[422404] = csv_text([values])
    else:
        if change == "missing_leaf":
            headers.pop(); values.pop()
        elif change == "extra_leaf":
            headers.append("13 (1.0 pts)"); values.append("1")
        elif change == "duplicate_header":
            headers.append(headers[-1]); values.append("1")
        elif change == "duplicate_identity":
            headers.append("12.6: other (1 pts)"); values.append("1")
        elif change == "max":
            headers[-1] = headers[-1].replace("1.0 pts", "2.0 pts")
        elif change == "malformed_header":
            headers[-1] = "12.6 nonsense"
        elif change == "malformed_row":
            values.pop()
        data[SOURCE_IDS[-1]] = csv_text([values], headers)
    assert not soft(data).available


@pytest.mark.parametrize("index,value", [(1, "Missing"), (2, ""), (3, "2"), (0, "abc123@example.com")])
def test_inconsistent_submission_metadata(index, value):
    data = exports()
    values = row()
    values[index] = value
    data[SOURCE_IDS[0]] = csv_text([values])
    assert not soft(data).available


def test_roster_gate_and_no_cache_reuse_or_verified_completions():
    assert all(m["status"] == "not_graded" for m in soft(exports(), frozenset()).by_netid["abc123"])
    before = soft(exports({"8.4": "0"}))
    after = soft(exports())
    assert before.by_netid["abc123"][7]["kind"] == "purple"
    assert after.by_netid["abc123"][7]["kind"] == "shiny_purple"
    assert not after.verified_completions and after.cache_hits == 0
    assert soft(exports({"8.1": "0"})).by_netid["abc123"][7]["status"] == "incomplete"


def test_unavailable_source_is_soft_and_private():
    class Source:
        def exam2_scores_csvs(self):
            raise ValueError("private upstream details")
    result = import_exam2_soft(Source(), ["abc123"], current_gradescope_netids=frozenset({"abc123"}))
    assert not result.available
    assert "private" not in result.message
    assert all(m["status"] == "not_graded" for m in result.by_netid["abc123"])


@pytest.mark.parametrize("status", ["Ungraded", "Submitted"])
def test_ungraded_submission_scores_are_not_final_evidence(status):
    data = exports()
    values = row({leaf: "0" for leaf in LEAVES})
    values[1] = status
    data[SOURCE_IDS[0]] = csv_text([values])
    result = soft(data)
    assert result.available
    assert all(m["status"] == "not_graded" for m in result.by_netid["abc123"])


def test_duplicate_placeholders_within_one_export_are_rejected():
    data = exports()
    data[SOURCE_IDS[-1]] = csv_text([row(missing=True), row(missing=True)])
    assert not soft(data).available


def test_partially_graded_status_uses_only_complete_question_evidence():
    data = exports()
    values = row({"8.4": "null"})
    values[1] = "Partially Graded"
    data[SOURCE_IDS[0]] = csv_text([values])
    result = soft(data)
    assert result.available
    assert result.by_netid["abc123"][7]["status"] == "not_graded"
    assert result.by_netid["abc123"][0]["status"] == "complete"


def test_live_eight_cell_missing_placeholder_is_accepted_and_deduplicated():
    headers = ["First Name", "Last Name", "SID", "Email", "Sections", "Total Score", "Max Points", "Status", "Submission ID"] + HEADERS[4:]
    missing = ["", "", "", "abc123@cornell.edu", "", "null", "44.0", "Missing"]
    data = exports()
    data[SOURCE_IDS[-1]] = csv_text([missing], headers)
    assert soft(data).available
    data[SOURCE_IDS[-1]] = csv_text([missing, missing], headers)
    assert not soft(data).available
    missing[7] = "Graded"
    data[SOURCE_IDS[-1]] = csv_text([missing], headers)
    assert not soft(data).available
