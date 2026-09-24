"""Refresh combined Google Sheets + Gradescope lab dashboards atomically."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil

from dotenv import load_dotenv

from sync.combined_checkoffs import merge_checkoffs_with_autograders, merge_exam_checkmarks
from sync.google_sheets_api import fetch_first_worksheet_rows
from sync.gradescope_exam import import_exam_soft
from sync.gradescope import (
    GradescopeAdapterError,
    PrivateWebGradescopeSource,
    build_snapshot,
    carry_forward_verified_passes,
    load_config,
    netid_from_email,
    validate_snapshot,
    write_snapshot_atomic,
)
from sync.simple_checkoffs import NETID_PATTERN, rows_to_simple_records
from sync.simple_generate import write_simple_release


def _secret(name: str) -> str:
    """Read one secret from an environment value or a systemd credential file."""
    direct = os.environ.get(name)
    file_name = os.environ.get(f"{name}_FILE")
    if direct and file_name:
        raise ValueError(f"set only one of {name} and {name}_FILE")
    if file_name:
        value = Path(file_name).read_text(encoding="utf-8").strip()
    else:
        value = (direct or "").strip()
    if not value or "\x00" in value or "\n" in value or "\r" in value:
        raise ValueError(f"{name} credential is missing or invalid")
    return value


def _require_private_snapshot(snapshot: Path, output: Path, asset_root: Path | None) -> None:
    resolved_snapshot = snapshot.resolve()
    served_roots = [output.resolve()]
    if asset_root is not None:
        served_roots.append(asset_root.resolve())
    if any(resolved_snapshot == root or root in resolved_snapshot.parents for root in served_roots):
        raise ValueError("Gradescope snapshot must be outside every served dashboard root")


def _selected_netid(explicit: str | None, all_students: bool) -> str | None:
    if all_students:
        return None
    candidate = explicit
    if candidate is None:
        candidate = netid_from_email(os.environ.get("GRADESCOPE_TEST_STUDENT_EMAIL", ""))
        if candidate is None:
            raise ValueError(
                "use --student-id, --all-students, or set a canonical "
                "GRADESCOPE_TEST_STUDENT_EMAIL"
            )
    normalized = candidate.strip().casefold()
    if not NETID_PATTERN.fullmatch(normalized):
        raise ValueError("selected student is not a valid Cornell NetID")
    return normalized


def main() -> None:
    load_dotenv(override=False)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path, help="allowlisted lab-only Gradescope TOML config")
    parser.add_argument("output", type=Path, help="private students directory to replace")
    parser.add_argument("snapshot", type=Path, help="private last-known Gradescope state")
    parser.add_argument("--worksheet-id", type=int, required=True)
    parser.add_argument("--spreadsheet-id", default=os.environ.get("GOOGLE_SHEET_ID"))
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--student-id", help="local canary NetID")
    selection.add_argument(
        "--all-students", action="store_true",
        help="publish every sheet student; use only after access-control tests pass",
    )
    parser.add_argument(
        "--copy-assets-to", type=Path,
        help="local preview only: copy dashboard JS/CSS into this directory",
    )
    args = parser.parse_args()

    if not args.spreadsheet_id:
        parser.error("--spreadsheet-id or GOOGLE_SHEET_ID is required")

    try:
        email = _secret("GRADESCOPE_EMAIL")
        password = _secret("GRADESCOPE_PASSWORD")
        selected_netid = _selected_netid(args.student_id, args.all_students)
        _require_private_snapshot(args.snapshot, args.output, args.copy_assets_to)
        config = load_config(args.config)

        title, rows = fetch_first_worksheet_rows(args.spreadsheet_id, args.worksheet_id)
        timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        if selected_netid is not None:
            # A local canary reads only its selected fake row. Production still
            # validates the full sheet and rejects every duplicate or malformed row.
            selected_rows = [
                row for row in rows
                if str(row.get("NetID", "")).strip().casefold() == selected_netid
            ]
            if len(selected_rows) != 1:
                raise ValueError("selected NetID must match exactly one Google Sheet row")
            records = rows_to_simple_records(
                selected_rows, updated_at=timestamp, worksheet=title
            )
        else:
            records = rows_to_simple_records(rows, updated_at=timestamp, worksheet=title)

        source = PrivateWebGradescopeSource(email, password, config)
        snapshot = build_snapshot(source, config, only_netid=selected_netid)
        if args.all_students and args.snapshot.exists():
            previous = json.loads(args.snapshot.read_text(encoding="utf-8"))
            previous_errors = validate_snapshot(previous)
            if previous_errors:
                raise ValueError("existing Gradescope snapshot is invalid; refusing to publish")
            snapshot = carry_forward_verified_passes(snapshot, previous)

        combined = merge_checkoffs_with_autograders(records, snapshot)
        exam = import_exam_soft(
            source,
            config.exam,
            [record["student"]["netid"] for record in combined],
        )
        combined = merge_exam_checkmarks(combined, exam)

        # All remote reads, normalization, and cross-source validation finish before
        # either persistent artifact changes. The snapshot is private recovery state;
        # the student tree is then swapped as one staged release.
        write_snapshot_atomic(snapshot, args.snapshot)
        paths = write_simple_release(combined, args.output, retain_previous=True)

        if args.copy_assets_to is not None:
            args.copy_assets_to.mkdir(parents=True, exist_ok=True)
            for asset in ("simple-dashboard.js", "simple-style.css"):
                shutil.copy2(Path("static") / asset, args.copy_assets_to / asset)
    except (GradescopeAdapterError, KeyError, OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))

    mode = "all students" if args.all_students else selected_netid
    print(
        f"published combined lab dashboards for {mode}: {len(paths)} protected record(s), "
        f"{len(config.assignments)} lab assignment(s); {exam.message}"
    )


if __name__ == "__main__":
    main()
