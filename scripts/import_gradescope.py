"""Fetch an allowlisted Gradescope snapshot without changing the dashboard."""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from sync.gradescope import (
    GradescopeAdapterError,
    PrivateWebGradescopeSource,
    build_snapshot,
    carry_forward_verified_passes,
    load_config,
    validate_snapshot,
    write_snapshot_atomic,
)


def _safe_output(path: Path) -> Path:
    resolved = path.resolve()
    repository = Path(__file__).resolve().parents[1]
    for public_name in ("static", "public"):
        public_root = (repository / public_name).resolve()
        if resolved == public_root or public_root in resolved.parents:
            raise ValueError("Gradescope output must not be written under static/ or public/")
    return resolved


def _validate_canary_mode(student_netid: str | None, no_carry_forward: bool, output: Path) -> None:
    if student_netid is None:
        return
    if not no_carry_forward:
        raise ValueError("--student-netid requires --no-carry-forward")
    if output.exists():
        raise ValueError("canary output already exists; use a new path or remove it explicitly")


def main() -> None:
    load_dotenv(override=False)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path, help="allowlisted Gradescope TOML config")
    parser.add_argument("output", type=Path, help="private normalized JSON output")
    parser.add_argument(
        "--student-netid",
        help="local canary only: fetch one canonical NetID while validating the full roster",
    )
    parser.add_argument(
        "--no-carry-forward",
        action="store_true",
        help="do not preserve prior verified passes (local diagnostics only)",
    )
    args = parser.parse_args()

    email = os.environ.get("GRADESCOPE_EMAIL", "")
    password = os.environ.get("GRADESCOPE_PASSWORD", "")
    if not email or not password:
        parser.error("GRADESCOPE_EMAIL and GRADESCOPE_PASSWORD are required")

    try:
        output = _safe_output(args.output)
        _validate_canary_mode(args.student_netid, args.no_carry_forward, output)
        config = load_config(args.config)
        source = PrivateWebGradescopeSource(email, password, config)
        snapshot = build_snapshot(source, config, only_netid=args.student_netid)
        if output.exists() and not args.no_carry_forward:
            previous = json.loads(output.read_text(encoding="utf-8"))
            previous_errors = validate_snapshot(previous)
            if previous_errors:
                raise ValueError("existing snapshot is invalid; refusing to replace it")
            snapshot = carry_forward_verified_passes(snapshot, previous)
        write_snapshot_atomic(snapshot, output)
    except (GradescopeAdapterError, OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))

    statuses = Counter(
        result["status"]
        for student in snapshot["students"]
        for result in student["autograders"]
    )
    summary = ", ".join(f"{name}={statuses[name]}" for name in sorted(statuses))
    print(
        f"wrote normalized Gradescope snapshot for {len(snapshot['students'])} student(s), "
        f"{len(snapshot['assignments'])} assignment(s): {summary}"
    )


if __name__ == "__main__":
    main()
