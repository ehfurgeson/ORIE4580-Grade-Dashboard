"""Fetch a wide checkbox sheet and build NetID-protected simple dashboards."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path

from dotenv import load_dotenv

from sync.google_sheets_api import fetch_first_worksheet_rows
from sync.simple_checkoffs import NETID_PATTERN, rows_to_simple_records
from sync.simple_generate import write_simple_release


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="private staged student-directory root")
    parser.add_argument(
        "--spreadsheet-id",
        default=os.environ.get("GOOGLE_SHEET_ID"),
        help="Google spreadsheet ID; defaults to GOOGLE_SHEET_ID",
    )
    parser.add_argument("--worksheet-id", type=int, required=True)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument(
        "--student-id",
        help="generate only this NetID (required for the initial test)",
    )
    selection.add_argument(
        "--all-students",
        action="store_true",
        help="explicitly generate every student only after authorization testing",
    )
    args = parser.parse_args()
    if not args.spreadsheet_id:
        parser.error("--spreadsheet-id or GOOGLE_SHEET_ID is required")

    requested_netid = None
    if args.student_id:
        requested_netid = args.student_id.strip().lower()
        if not NETID_PATTERN.fullmatch(requested_netid):
            parser.error("--student-id is not a valid Cornell NetID")

    try:
        title, rows = fetch_first_worksheet_rows(args.spreadsheet_id, args.worksheet_id)
        updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        records = rows_to_simple_records(rows, updated_at=updated_at, worksheet=title)
        if requested_netid:
            records = [record for record in records if record["student"]["netid"] == requested_netid]
            if not records:
                raise ValueError("requested NetID was not found in the worksheet")
        paths = write_simple_release(records, args.output)
    except (OSError, RuntimeError, ValueError) as error:
        parser.error(str(error))
    print(
        f"read worksheet {title!r}: {len(rows)} row(s); "
        f"generated {len(paths)} protected dashboard(s)"
    )


if __name__ == "__main__":
    main()
