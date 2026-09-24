"""Build a local combined Google/Gradescope dashboard canary."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil

from dotenv import load_dotenv

from sync.combined_checkoffs import merge_checkoffs_with_autograders
from sync.google_sheets_api import fetch_first_worksheet_rows
from sync.simple_checkoffs import NETID_PATTERN, rows_to_simple_records
from sync.simple_generate import write_simple_release


def main() -> None:
    load_dotenv(override=False)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="new ignored local preview root")
    parser.add_argument("--gradescope-snapshot", type=Path, required=True)
    parser.add_argument("--student-netid", required=True)
    parser.add_argument("--worksheet-id", type=int, required=True)
    parser.add_argument("--spreadsheet-id", default=os.environ.get("GOOGLE_SHEET_ID"))
    parser.add_argument(
        "--allow-unconfigured",
        action="store_true",
        help="local-only: show unmapped manual opportunities as Not connected yet",
    )
    args = parser.parse_args()
    netid = args.student_netid.strip().casefold()
    if not NETID_PATTERN.fullmatch(netid):
        parser.error("--student-netid is invalid")
    if not args.spreadsheet_id:
        parser.error("--spreadsheet-id or GOOGLE_SHEET_ID is required")
    if args.output.exists():
        parser.error("output already exists; use a new preview path or remove it explicitly")

    try:
        snapshot = json.loads(args.gradescope_snapshot.read_text(encoding="utf-8"))
        title, rows = fetch_first_worksheet_rows(args.spreadsheet_id, args.worksheet_id)
        sheet_updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        records = rows_to_simple_records(
            rows,
            updated_at=sheet_updated_at,
            worksheet=title,
        )
        selected = [record for record in records if record["student"]["netid"] == netid]
        if len(selected) != 1:
            raise ValueError("selected NetID must match exactly one Google Sheet row")
        combined = merge_checkoffs_with_autograders(
            selected,
            snapshot,
            allow_unconfigured=args.allow_unconfigured,
        )
        student_root = args.output / "students"
        paths = write_simple_release(combined, student_root)
        for asset in ("simple-dashboard.js", "simple-style.css"):
            shutil.copy2(Path("static") / asset, args.output / asset)
    except (KeyError, OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))
    print(
        f"built local combined preview for {netid}: {len(paths)} protected record; "
        f"open /students/{netid}/"
    )


if __name__ == "__main__":
    main()
