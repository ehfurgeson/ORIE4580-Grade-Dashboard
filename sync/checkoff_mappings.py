"""Executable Lab mapping mirrored from the reviewed ``docs/standards.md`` tables."""
from __future__ import annotations

import re

LAB_MAPPING_VERSION = "lab-mapping-v4"

# Each worksheet column belongs to exactly one syllabus checkmark opportunity.
# Multiple columns with the same opportunity ID must all be complete to earn it.
COLUMN_MAPPINGS = {
    "Lab 1 - Q1.3": ('S1', "lab1-q1-2", "Lab 1 · Q1–2"),
    "Lab 1 - Q2.3": ('S1', "lab1-q1-2", "Lab 1 · Q1–2"),
    "Lab 1 - Q2.4": ('S1', "lab1-q1-2", "Lab 1 · Q1–2"),
    "Lab 1 - Q3": ('S1', "lab1-q3", "Lab 1 · Q3"),
    "Lab 2 - Q1": ('S1', "lab2-q1", "Lab 2 · Q1"),
    "Lab 2 - Q2": ('S2', "lab2-q2", "Lab 2 · Q2"),
    "Lab 2 - Q3": ('S2', "lab2-q3", "Lab 2 · Q3"),
    "Lab 3 - Q1": ('S2', "lab3-q1", "Lab 3 · Q1"),
    "Lab 3 - Q2": ('S3', "lab3-q2", "Lab 3 · Q2.1–2.4"),
    "Lab 3 - Q2.1": ('S3', "lab3-q2", "Lab 3 · Q2.1–2.4"),
    "Lab 3 - Q2.2": ('S3', "lab3-q2", "Lab 3 · Q2.1–2.4"),
    "Lab 3 - Q2.3": ('S3', "lab3-q2", "Lab 3 · Q2.1–2.4"),
    "Lab 3 - Q2.4": ('S3', "lab3-q2", "Lab 3 · Q2.1–2.4"),
    "Lab 3 - Q3": ('S3', "lab3-q3", "Lab 3 · Q3"),
    "Lab 4 - Q1": ('S3', "lab4-q1", "Lab 4 · Q1"),
    "Lab 4 - Q2": ('S4', "lab4-q2", "Lab 4 · Q2"),
    "Lab 4 - Q3": ('S5', "lab4-q3", "Lab 4 · Q3"),
    "Lab 5 - Q1": ('S3', "lab5-q1", "Lab 5 · Q1"),
    "Lab 5 - Q2": ('S4', "lab5-q2", "Lab 5 · Q2"),
    "Lab 5 - Q3": ('S5', "lab5-q3", "Lab 5 · Q3"),
}

# Each mapped opportunity must use exactly one approved Sheet-header group.
# Lab 3 Q2 supports either its legacy aggregate checkbox or all four milestones.
OPPORTUNITY_HEADER_GROUPS = {
    "lab1-q1-2": (frozenset({"Lab 1 - Q1.3", "Lab 1 - Q2.3", "Lab 1 - Q2.4"}),),
    "lab1-q3": (frozenset({"Lab 1 - Q3"}),),
    "lab2-q1": (frozenset({"Lab 2 - Q1"}),),
    "lab2-q2": (frozenset({"Lab 2 - Q2"}),),
    "lab2-q3": (frozenset({"Lab 2 - Q3"}),),
    "lab3-q1": (frozenset({"Lab 3 - Q1"}),),
    "lab3-q2": (
        frozenset({"Lab 3 - Q2"}),
        frozenset({"Lab 3 - Q2.1", "Lab 3 - Q2.2", "Lab 3 - Q2.3", "Lab 3 - Q2.4"}),
        frozenset({
            "Lab 3 - Q2", "Lab 3 - Q2.1", "Lab 3 - Q2.2",
            "Lab 3 - Q2.3", "Lab 3 - Q2.4",
        }),
    ),
    "lab3-q3": (frozenset({"Lab 3 - Q3"}),),
    "lab4-q1": (frozenset({"Lab 4 - Q1"}),),
    "lab4-q2": (frozenset({"Lab 4 - Q2"}),),
    "lab4-q3": (frozenset({"Lab 4 - Q3"}),),
    "lab5-q1": (frozenset({"Lab 5 - Q1"}),),
    "lab5-q2": (frozenset({"Lab 5 - Q2"}),),
    "lab5-q3": (frozenset({"Lab 5 - Q3"}),),
}


OPPORTUNITY_IDS = frozenset(mapping[1] for mapping in COLUMN_MAPPINGS.values())
MANUAL_ONLY_OPPORTUNITY_IDS = frozenset({
    "lab4-q1", "lab5-q1", "lab5-q2", "lab5-q3",
})
AUTOGRADER_OPPORTUNITY_IDS = frozenset({
    "lab1-q1-2", "lab1-q3", "lab2-q1", "lab2-q2", "lab2-q3",
    "lab3-q1", "lab3-q2", "lab3-q3", "lab4-q2", "lab4-q3",
})

if MANUAL_ONLY_OPPORTUNITY_IDS & AUTOGRADER_OPPORTUNITY_IDS:
    raise RuntimeError("manual-only and autograded opportunity policies overlap")
if MANUAL_ONLY_OPPORTUNITY_IDS | AUTOGRADER_OPPORTUNITY_IDS != OPPORTUNITY_IDS:
    raise RuntimeError("every mapped opportunity must have exactly one explicit policy")
if set(OPPORTUNITY_HEADER_GROUPS) != OPPORTUNITY_IDS:
    raise RuntimeError("every mapped opportunity must have approved Sheet-header groups")
for _opportunity_id, _groups in OPPORTUNITY_HEADER_GROUPS.items():
    _mapped_headers = {
        column for column, mapping in COLUMN_MAPPINGS.items()
        if mapping[1] == _opportunity_id
    }
    if not _groups or any(not group for group in _groups) or set().union(*_groups) != _mapped_headers:
        raise RuntimeError("approved Sheet-header groups do not match COLUMN_MAPPINGS")
LAB_ASSIGNMENT_PATTERN = re.compile(
    r"^\s*Lab\s*(?P<lab>[0-9]+)\s*[,;:\-]\s*Q\s*"
    r"(?P<start>[0-9]+)(?:\s*[-–—]\s*(?P<end>[0-9]+))?\s*$",
    re.IGNORECASE,
)


def opportunity_from_assignment_title(title: object) -> str | None:
    """Map an exact Lab N, QN[-N] convention to a known sheet opportunity.

    Non-lab assignments return None. A title containing "Lab" that does not
    match the convention or maps to no sheet opportunity raises ValueError so
    quizzes/exams are ignored while malformed labs fail closed.
    """
    if not isinstance(title, str) or not title.strip():
        raise ValueError("Gradescope assignment title is missing")
    if not re.search(r"\blab\b", title, re.IGNORECASE):
        return None
    match = LAB_ASSIGNMENT_PATTERN.fullmatch(title)
    if not match:
        raise ValueError(f"Lab assignment title does not match the required convention: {title!r}")
    question = match.group("start")
    if match.group("end"):
        question += f"-{match.group('end')}"
    opportunity_id = f"lab{int(match.group('lab'))}-q{question}"
    if opportunity_id not in OPPORTUNITY_IDS:
        raise ValueError(f"Lab assignment has no Google Sheet opportunity mapping: {title!r}")
    return opportunity_id
