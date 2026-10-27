"""Migrate pre-Lab-7 or temporary-S7 state to the approved catalog.

Does not fetch or infer Lab 7 checkoffs. Run a normal refresh after migration.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path

from sync.exam2_publication import write_publication_state
from sync.standards import STANDARDS


def migrate_lab7_state(state: dict) -> dict:
    migrated = deepcopy(state)
    records = migrated.get("records")
    if not isinstance(records, list) or not records:
        raise ValueError("publication state requires records")
    for record in records:
        standards = record.get("standards", [])
        ids = [s.get("id") for s in standards]
        if ids == list(STANDARDS)[:-1]:
            record["standards"].append({"id":"S7", "name":STANDARDS["S7"], "checkmarks":[]})
        elif ids == list(STANDARDS) and standards[-1].get("name") == "Standard 7":
            standards[-1]["name"] = STANDARDS["S7"]
        else:
            raise ValueError("migration requires S1–S6 or the temporary S7 label")
        record["unmapped_columns"] = [name for name in record["unmapped_columns"] if name not in {"Lab 7 - Q1", "Lab 7 - Q2"}]
    return migrated


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        if args.source.is_symlink() or args.output.exists() or args.output.is_symlink():
            raise ValueError("use a real source and a new separate output path")
        if args.output.resolve().is_relative_to(Path("/var/www").resolve()):
            raise ValueError("migration output must not be under the web root")
        state = migrate_lab7_state(json.loads(args.source.read_text()))
        write_publication_state(args.output, state)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.error(str(error))
    print("Migrated private state; visibility preserved. Run a full refresh to collect Lab 7.")


if __name__ == "__main__":
    main()
