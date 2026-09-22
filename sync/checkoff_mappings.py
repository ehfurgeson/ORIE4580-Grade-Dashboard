"""Explicit syllabus mapping from Google Sheet columns to green checkmarks."""
from __future__ import annotations

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
