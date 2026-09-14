"""Validate normalized records and generate private per-student JSON files."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sync.generate import write_records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="JSON record or list of records")
    parser.add_argument("output", type=Path, help="private output directory")
    args = parser.parse_args()

    try:
        records = json.loads(args.input.read_text(encoding="utf-8"))
        records = records if isinstance(records, list) else [records]
        paths = write_records(records, args.output)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        parser.error(str(error))
    print(f"generated {len(paths)} student file(s)")


if __name__ == "__main__":
    main()
