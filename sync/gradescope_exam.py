"""Optional Exam 1 score adapter.

Exam rubric drift is deliberately soft-failing while the rubric is finalized:
Lab publication continues and all exam opportunities become ``not_graded``.
No raw scores are persisted in dashboard records.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import io
import re
from typing import Protocol

from .gradescope import ExamRule, GradescopeAdapterError, netid_from_email

EXAM_MAPPING_VERSION = "exam1-mapping-v1"
EXAM_OPPORTUNITIES = (
    {"id": "exam1-q1", "question": 1, "standard_key": "general_1d_sampler", "label": "Exam 1 · Question 1", "kind": "purple"},
    {"id": "exam1-q2", "question": 2, "standard_key": "general_1d_sampler", "label": "Exam 1 · Question 2", "kind": "purple"},
    {"id": "exam1-q3", "question": 3, "standard_key": "uniform_samplers", "label": "Exam 1 · Question 3", "kind": "purple"},
    {"id": "exam1-q4", "question": 4, "standard_key": "uniform_samplers", "label": "Exam 1 · Question 4", "kind": "purple"},
    {"id": "exam1-q5", "question": 5, "standard_key": "uniform_samplers", "label": "Exam 1 · Question 5", "kind": "shiny_purple"},
    {"id": "exam1-q6", "question": 6, "standard_key": "general_1d_sampler", "label": "Exam 1 · Question 6", "kind": "shiny_purple"},
)
QUESTION_HEADER = re.compile(
    r"^\s*(?P<number>[1-9][0-9]*)\s*:.*\((?P<points>[0-9]+(?:\.[0-9]+)?)\s+pts?\)\s*$",
    re.IGNORECASE,
)


class ExamScoreSource(Protocol):
    def exam_scores_csv(self) -> str: ...


@dataclass(frozen=True)
class ExamImport:
    by_netid: dict[str, list[dict[str, str]]]
    available: bool
    message: str
    verified_completions: frozenset[tuple[str, str]] = frozenset()
    cache_hits: int = 0


def _unavailable(netids: list[str], message: str) -> ExamImport:
    return ExamImport(
        {
            netid: [
                {**opportunity, "status": "not_graded"}
                for opportunity in EXAM_OPPORTUNITIES
            ]
            for netid in netids
        },
        False,
        message,
    )


def parse_exam_scores_csv(text: str, rule: ExamRule, netids: list[str]) -> ExamImport:
    """Parse the exact normalized six-question Exam 1 export contract."""
    if not isinstance(text, str):
        raise ValueError("Exam 1 export must be text")
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows or not isinstance(rows[0], dict):
        raise ValueError("Exam 1 export has no student rows")
    headers = list(rows[0])
    if "Email" not in headers:
        raise ValueError("Exam 1 export is missing the Email column")

    question_columns: dict[int, str] = {}
    for header in headers:
        match = QUESTION_HEADER.fullmatch(header or "")
        if match is None:
            continue
        number = int(match.group("number"))
        if number not in range(1, rule.expected_question_count + 1):
            continue
        if number in question_columns:
            raise ValueError("Exam 1 export has a duplicate question column")
        try:
            points = Decimal(match.group("points"))
        except InvalidOperation as error:
            raise ValueError("Exam 1 question maximum is invalid") from error
        if points != rule.expected_question_score:
            raise ValueError("Exam 1 questions are not normalized to 1 point yet")
        question_columns[number] = header
    expected = set(range(1, rule.expected_question_count + 1))
    if set(question_columns) != expected:
        raise ValueError("Exam 1 export does not have six normalized question columns")

    wanted = set(netids)
    scores: dict[str, dict[int, str]] = {}
    for row in rows:
        netid = netid_from_email(row.get("Email"))
        if netid is None or netid not in wanted:
            continue
        if netid in scores:
            raise ValueError("Exam 1 export has a duplicate student")
        statuses: dict[int, str] = {}
        for question, column in question_columns.items():
            raw = (row.get(column) or "").strip()
            if not raw:
                statuses[question] = "not_graded"
                continue
            try:
                score = Decimal(raw)
            except InvalidOperation as error:
                raise ValueError("Exam 1 contains a nonnumeric question score") from error
            if not score.is_finite() or score < 0 or score > rule.expected_question_score:
                raise ValueError("Exam 1 question score is outside 0 to 1")
            statuses[question] = "complete" if score > rule.earn_threshold else "incomplete"
        scores[netid] = statuses

    by_netid: dict[str, list[dict[str, str]]] = {}
    for netid in netids:
        statuses = scores.get(netid, {})
        by_netid[netid] = [
            {**opportunity, "status": statuses.get(opportunity["question"], "not_graded")}
            for opportunity in EXAM_OPPORTUNITIES
        ]
    return ExamImport(by_netid, True, "Exam 1 scores loaded")


def _apply_positive_cache(
    result: ExamImport,
    rule: ExamRule,
    current_roster: frozenset[str],
    prior_completions: frozenset[tuple[str, str]],
) -> ExamImport:
    known_ids = {item["id"] for item in EXAM_OPPORTUNITIES}
    reusable = {
        (netid, opportunity)
        for netid, opportunity in prior_completions
        if rule.rubric_finalized and netid in current_roster and opportunity in known_ids
    }
    by_netid = {
        netid: [{**item} for item in opportunities]
        for netid, opportunities in result.by_netid.items()
    }
    hits = 0
    for netid, opportunities in by_netid.items():
        if netid not in current_roster:
            for item in opportunities:
                item["status"] = "not_graded"
            continue
        for item in opportunities:
            key = (netid, item["id"])
            if key in reusable:
                hits += 1
                item["status"] = "complete"
    verified = frozenset(
        (netid, item["id"])
        for netid, opportunities in by_netid.items()
        if rule.rubric_finalized and netid in current_roster
        for item in opportunities
        if item["status"] == "complete"
    )
    return ExamImport(by_netid, result.available, result.message, verified, hits)


def import_exam_soft(
    source: ExamScoreSource,
    rule: ExamRule | None,
    netids: list[str],
    *,
    current_gradescope_netids: frozenset[str] | None = None,
    prior_completions: frozenset[tuple[str, str]] = frozenset(),
) -> ExamImport:
    """Import Exam 1 and reuse only finalized positive results for current students."""
    if rule is None:
        return _unavailable(netids, "Exam 1 is not configured")
    current_roster = (
        frozenset(netids) if current_gradescope_netids is None else current_gradescope_netids
    )
    try:
        result = parse_exam_scores_csv(source.exam_scores_csv(), rule, netids)
    except (GradescopeAdapterError, csv.Error, UnicodeError, ValueError):
        result = _unavailable(netids, "Exam 1 scores are not normalized or available yet")
    return _apply_positive_cache(result, rule, current_roster, prior_completions)
