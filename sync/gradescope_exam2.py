"""Uncached, optional Exam 2 adapter for the eight reviewed physical versions.

Only canonical question outcomes leave this module; physical provenance and raw
scores are never included in results or diagnostics.
"""
from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation
import io
import re
from typing import Protocol

from .gradescope import GradescopeAdapterError, netid_from_email
from .gradescope_exam import ExamImport

EXAM2_SOURCE_IDS = frozenset({8911573, 8911490, 8911492, 8911493, 8911494, 8911496, 8911497, 8911498})
_PART_COUNTS = (5, 8, 6, 5, 3, 2, 2, 4, 1, 1, 1, 6)
_THRESHOLDS = (4, 7, 5, 5, 3, 2, 2, 4, 1, 1, 1, 6)
_STANDARDS = ("S1", "S1", "S2", "S3", "S3", "S4", "S4", "S5", "S5", "S1", "S2", "S4")
EXAM2_OPPORTUNITIES = tuple(
    {
        "id": f"exam2-q{question}", "question": question,
        "standard_id": standard, "label": f"Exam 2 · Question {question}",
        "kind": "shiny_purple" if question >= 10 else "purple",
        **({"allowed_kinds": ("purple", "shiny_purple")} if question == 8 else {}),
    }
    for question, standard in enumerate(_STANDARDS, 1)
)
_LEAVES = {
    question: tuple(
        str(question) if count == 1 else f"{question}.{part}"
        for part in range(1, count + 1)
    )
    for question, count in enumerate(_PART_COUNTS, 1)
}
_EXPECTED_LEAVES = {leaf for leaves in _LEAVES.values() for leaf in leaves}
_HEADER = re.compile(
    r"^\s*(?P<leaf>[1-9][0-9]*(?:\.[1-9][0-9]*)?)(?:\s*:.*?)?\s*"
    r"\((?P<points>[0-9]+(?:\.[0-9]+)?)\s+pts?\)\s*$", re.IGNORECASE,
)


class Exam2ScoreSource(Protocol):
    def exam2_scores_csvs(self) -> dict[int, str]: ...


def _opportunities(scores: dict[str, Decimal | None] | None = None) -> list[dict]:
    outcomes = []
    for opportunity in EXAM2_OPPORTUNITIES:
        item = {key: value for key, value in opportunity.items() if key != "allowed_kinds"}
        question = item["question"]
        parts = [scores.get(leaf) for leaf in _LEAVES[question]] if scores is not None else []
        item["status"] = "not_graded"
        if parts and all(part is not None for part in parts):
            correct = sum(part == Decimal(1) for part in parts)
            if question == 8:
                if correct == 4:
                    item.update(status="complete", kind="shiny_purple")
                else:
                    item["status"] = "complete" if parts[:2] == [Decimal(1), Decimal(1)] else "incomplete"
            else:
                item["status"] = "complete" if correct >= _THRESHOLDS[question - 1] else "incomplete"
        outcomes.append(item)
    return outcomes


def _score(raw: str) -> Decimal | None:
    raw = raw.strip()
    if raw.casefold() in {"", "null"}:
        return None
    try:
        score = Decimal(raw)
    except InvalidOperation as error:
        raise ValueError("Exam 2 contains a nonnumeric score") from error
    if not score.is_finite() or not 0 <= score <= 1:
        raise ValueError("Exam 2 score is outside 0 to 1")
    return score


def parse_exam2_scores_csvs(exports: dict[int, str], netids: list[str]) -> ExamImport:
    """Validate all versions, select one actual submission, and score 12 questions.

    Missing rows are placeholders, not submissions. Blank/null grades on actual
    submissions leave that entire question not graded, including all four Q8 parts.
    Invalid or conflicting evidence raises ValueError without student details.
    """
    if not isinstance(exports, dict) or set(exports) != EXAM2_SOURCE_IDS:
        raise ValueError("Exam 2 requires exactly the eight reviewed sources")
    submissions: dict[str, dict[str, Decimal | None]] = {}
    for text in exports.values():
        if not isinstance(text, str):
            raise ValueError("Exam 2 export must be text")
        reader = csv.reader(io.StringIO(text), strict=True)
        headers = next(reader, [])
        if len(headers) != len(set(headers)):
            raise ValueError("Exam 2 export has duplicate headers")
        if not {"Email", "Status", "Submission ID"} <= set(headers):
            raise ValueError("Exam 2 export lacks submission metadata")
        columns = {}
        for index, header in enumerate(headers):
            match = _HEADER.fullmatch(header)
            if match is None:
                if re.match(r"^\s*[0-9]", header) or re.search(r"\bpts?\)\s*$", header, re.IGNORECASE):
                    raise ValueError("Exam 2 has an unrecognized question header")
                continue
            leaf = match.group("leaf")
            if leaf in columns:
                raise ValueError("Exam 2 has duplicate question identities")
            if Decimal(match.group("points")) != 1:
                raise ValueError("Exam 2 requires one-point leaves")
            columns[leaf] = index
        if set(columns) != _EXPECTED_LEAVES:
            raise ValueError("Exam 2 requires exactly the reviewed 44 leaves")
        seen_netids: set[str] = set()
        for values in reader:
            if not values:
                continue
            if len(values) != len(headers):
                # Gradescope truncates Missing placeholders after Status.
                status_index = headers.index("Status")
                email_index = headers.index("Email")
                submission_index = headers.index("Submission ID")
                missing_placeholder = (
                    max(status_index, email_index) < len(values) < len(headers)
                    and values[status_index].strip().casefold() == "missing"
                    and (submission_index >= len(values) or not values[submission_index].strip())
                )
                if not missing_placeholder:
                    raise ValueError("Exam 2 export has a malformed row")
                values += [""] * (len(headers) - len(values))
            row = dict(zip(headers, values))
            netid = netid_from_email(row["Email"])
            if netid is not None:
                if netid in seen_netids:
                    raise ValueError("Exam 2 export has duplicate student rows")
                seen_netids.add(netid)
            submission_id = row["Submission ID"].strip()
            status = row["Status"].strip().casefold()
            if status == "missing" and not submission_id:
                continue
            if not submission_id or status not in {"graded", "ungraded", "submitted", "partially graded"}:
                raise ValueError("Exam 2 has inconsistent submission metadata")
            if "Submission Count" in row and row["Submission Count"].strip() != "1":
                raise ValueError("Exam 2 requires a single actual submission")
            if netid is None:
                raise ValueError("Exam 2 submitted row lacks a canonical Cornell identity")
            if netid in submissions:
                raise ValueError("Exam 2 has duplicate actual submissions")
            scores = {leaf: _score(values[index]) for leaf, index in columns.items()}
            submissions[netid] = (
                {leaf: None for leaf in columns} if status in {"ungraded", "submitted"} else scores
            )
    return ExamImport(
        {netid: _opportunities(submissions.get(netid)) for netid in netids},
        True, "Exam 2 scores loaded",
    )


def import_exam2_soft(
    source: Exam2ScoreSource,
    netids: list[str],
    *,
    current_gradescope_netids: frozenset[str],
) -> ExamImport:
    """Fail only logical Exam 2; never read or write completion caches."""
    try:
        result = parse_exam2_scores_csvs(source.exam2_scores_csvs(), netids)
    except (GradescopeAdapterError, csv.Error, UnicodeError, ValueError):
        return ExamImport(
            {netid: _opportunities() for netid in netids}, False,
            "Exam 2 scores are not available or do not match the reviewed contract",
        )
    return ExamImport(
        {
            netid: opportunities if netid in current_gradescope_netids else _opportunities()
            for netid, opportunities in result.by_netid.items()
        },
        result.available, result.message,
    )
