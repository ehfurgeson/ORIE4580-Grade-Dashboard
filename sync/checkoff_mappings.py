"""Explicit syllabus mapping from Google Sheet columns to green checkmarks."""
from __future__ import annotations

import re

LAB_MAPPING_VERSION = "lab-mapping-v1"
MANUAL_SCHEMA_VERSION = 2

STANDARDS = {
    "uniform_samplers": {
        "id": "S1",
        "name": "I can state the defining features of uniform samplers, use them to construct new samplers, and use them to check if a given sampler is valid.",
    },
    "general_1d_sampler": {
        "id": "S2",
        "name": "I can create a sampler for a general one-dimensional probability distribution given its CDF or PDF.",
    },
    "simulation_output_variability": {
        "id": "S3",
        "name": "I can use probabilistic concepts to qualitatively and quantitatively explain the sort of variability one should expect from a simulation's output.",
    },
}

# Each worksheet column belongs to exactly one syllabus checkmark opportunity.
# Multiple columns with the same opportunity ID must all be complete to earn it.
COLUMN_MAPPINGS = {
    "Lab 1 - Q1.3": ("uniform_samplers", "lab1-q1-2", "Lab 1 · Q1–2"),
    "Lab 1 - Q2.3": ("uniform_samplers", "lab1-q1-2", "Lab 1 · Q1–2"),
    "Lab 1 - Q2.4": ("uniform_samplers", "lab1-q1-2", "Lab 1 · Q1–2"),
    "Lab 1 - Q3": ("uniform_samplers", "lab1-q3", "Lab 1 · Q3"),
    "Lab 2 - Q1": ("uniform_samplers", "lab2-q1", "Lab 2 · Q1"),
    "Lab 2 - Q2": ("general_1d_sampler", "lab2-q2", "Lab 2 · Q2"),
    "Lab 2 - Q3": ("general_1d_sampler", "lab2-q3", "Lab 2 · Q3"),
    "Lab 3 - Q1": ("general_1d_sampler", "lab3-q1", "Lab 3 · Q1"),
    "Lab 3 - Q2": ("simulation_output_variability", "lab3-q2", "Lab 3 · Q2.1–2.4"),
    "Lab 3 - Q2.1": ("simulation_output_variability", "lab3-q2", "Lab 3 · Q2.1–2.4"),
    "Lab 3 - Q2.2": ("simulation_output_variability", "lab3-q2", "Lab 3 · Q2.1–2.4"),
    "Lab 3 - Q2.3": ("simulation_output_variability", "lab3-q2", "Lab 3 · Q2.1–2.4"),
    "Lab 3 - Q2.4": ("simulation_output_variability", "lab3-q2", "Lab 3 · Q2.1–2.4"),
    "Lab 3 - Q3": ("simulation_output_variability", "lab3-q3", "Lab 3 · Q3"),
}


OPPORTUNITY_IDS = frozenset(mapping[1] for mapping in COLUMN_MAPPINGS.values())
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
