"""Fetch a Google worksheet read-only and generate private student JSON."""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

from sync.generate import write_records
from sync.google_sheets import rows_to_records
from sync.google_sheets_api import fetch_first_worksheet_rows


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="private generated-data directory")
    parser.add_argument(
        "--spreadsheet-id",
        default=os.environ.get("GOOGLE_SHEET_ID"),
        help="Google spreadsheet ID; defaults to GOOGLE_SHEET_ID",
    )
    parser.add_argument("--worksheet-id", type=int, default=0)
    args = parser.parse_args()
    if not args.spreadsheet_id:
        parser.error("spreadsheet_id or GOOGLE_SHEET_ID is required")

    try:
        title, rows = fetch_first_worksheet_rows(args.spreadsheet_id, args.worksheet_id)
        records = rows_to_records(rows)
        paths = write_records(records, args.output)
    except (OSError, RuntimeError, ValueError) as error:
        parser.error(str(error))
    print(
        f"read worksheet {title!r}: {len(rows)} row(s); "
        f"generated {len(paths)} student file(s)"
    )


if __name__ == "__main__":
    main()
