"""Import a private Google Sheets CSV export and generate student JSON."""
from __future__ import annotations

import argparse
from pathlib import Path

from sync.generate import write_records
from sync.google_sheets import load_csv, rows_to_records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="private CSV export")
    parser.add_argument("output", type=Path, help="private generated-data directory")
    args = parser.parse_args()

    try:
        rows = load_csv(args.input)
        records = rows_to_records(rows)
        paths = write_records(records, args.output)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(f"loaded {len(rows)} sheet row(s); generated {len(paths)} student file(s)")


if __name__ == "__main__":
    main()
