"""Expand private S1–S7 publication state for Labs 8/9 without inferring credit.

Run with the refresh timer stopped and no active refresh. Use a new private
output path, then install it and perform a normal combined refresh.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path

from sync.exam_publication import _validate_state, write_publication_state
from sync.standards import STANDARDS

ACTIVATED_HEADERS = {"Lab 8 - Q1", "Lab 9 - Q1", "Lab 9 - Q2"}


def migrate_lab89_state(state: dict) -> dict:
    migrated = deepcopy(state)
    records = migrated.get("records")
    if not isinstance(records, list) or not records:
        raise ValueError("publication state requires records")
    previous = list(STANDARDS)[:7]
    for record in records:
        standards = record.get("standards", [])
        if [item.get("id") for item in standards] != previous or any(
            item.get("name") != STANDARDS[item["id"]] for item in standards
        ):
            raise ValueError("migration requires the approved S1–S7 catalog")
        record["standards"].extend(
            {"id": sid, "name": STANDARDS[sid], "checkmarks": []}
            for sid in ("S8", "S9")
        )
        record["unmapped_columns"] = [
            header for header in record["unmapped_columns"]
            if header not in ACTIVATED_HEADERS
        ]
    _validate_state(migrated)
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
        state = migrate_lab89_state(json.loads(args.source.read_text()))
        write_publication_state(args.output, state)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        parser.error(str(error))
    print("Migrated private state; visibility preserved. Run a full refresh to collect Labs 8/9.")


if __name__ == "__main__":
    main()
