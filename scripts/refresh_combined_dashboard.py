"""Refresh combined Google Sheets + Gradescope lab dashboards atomically."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import shutil
import time

from dotenv import load_dotenv

from sync.combined_checkoffs import merge_checkoffs_with_autograders, merge_exam_checkmarks
from sync.completion_cache import (
    build_completion_cache,
    filter_completion_cache,
    load_completion_cache,
    write_completion_cache_atomic,
)
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


def _require_private_state(path: Path, output: Path, asset_root: Path | None) -> None:
    resolved = path.resolve()
    served_roots = [output.resolve()]
    if asset_root is not None:
        served_roots.append(asset_root.resolve())
    if any(resolved == root or root in resolved.parents for root in served_roots):
        raise ValueError("private state must be outside every served dashboard root")


def _require_private_snapshot(snapshot: Path, output: Path, asset_root: Path | None) -> None:
    """Backward-compatible wrapper used by existing deployment tests."""
    _require_private_state(snapshot, output, asset_root)


def _acquire_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+", encoding="utf-8")
    os.chmod(path, 0o600)
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        handle.close()
        raise ValueError("another dashboard refresh is already running") from error
    return handle


def _lab_statuses(snapshot: dict) -> dict[tuple[str, str], str]:
    """Return only semantic Lab results for cache shadow comparison."""
    return {
        (student["netid"], result["opportunity_id"]): result["status"]
        for student in snapshot["students"]
        for result in student["autograders"]
    }


def _validate_roster_coverage(
    google_netids: set[str], gradescope_netids: set[str], allow_missing: bool
) -> set[str]:
    missing = google_netids - gradescope_netids
    extra = gradescope_netids - google_netids
    if missing and not allow_missing:
        raise ValueError("Google students are missing from Gradescope")
    if extra:
        raise ValueError("Gradescope contains students absent from the Google Sheet")
    return missing


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
    parser.add_argument(
        "--allow-missing-gradescope-students", action="store_true",
        help="allow Google-roster students absent from Gradescope; they receive not_found",
    )
    parser.add_argument("--completion-cache", type=Path, help="private positive-only cache")
    parser.add_argument("--lock-file", type=Path, help="private nonblocking process lock")
    parser.add_argument(
        "--force-full-revalidation", action="store_true",
        help="perform every Lab source check while preserving verified positive results",
    )
    parser.add_argument(
        "--disable-completion-cache", action="store_true",
        help="ignore and do not update the completion cache",
    )
    parser.add_argument(
        "--shadow-cache-comparison", action="store_true",
        help="compare cached Lab results with a forced full revalidation before publishing",
    )
    args = parser.parse_args()

    if not args.spreadsheet_id:
        parser.error("--spreadsheet-id or GOOGLE_SHEET_ID is required")

    lock_handle = None
    try:
        selected_netid = _selected_netid(args.student_id, args.all_students)
        _require_private_state(args.snapshot, args.output, args.copy_assets_to)
        if args.completion_cache is not None:
            _require_private_state(args.completion_cache, args.output, args.copy_assets_to)
        if args.lock_file is not None:
            _require_private_state(args.lock_file, args.output, args.copy_assets_to)
        config = load_config(args.config)
        if config.cache.google_conditional_requests or config.cache.exam_conditional_requests:
            raise ValueError("conditional requests require a successful source capability probe")
        cache_active = config.cache.enabled and not args.disable_completion_cache
        if selected_netid is not None and cache_active:
            raise ValueError("selected-student runs must use --disable-completion-cache")
        if args.all_students and args.lock_file is None:
            raise ValueError("all-student publication requires --lock-file")
        if cache_active and args.completion_cache is None:
            raise ValueError("enabled production caching requires --completion-cache")
        if args.shadow_cache_comparison and not cache_active:
            raise ValueError("shadow comparison requires enabled completion caching")
        if args.lock_file is not None:
            lock_handle = _acquire_lock(args.lock_file)

        email = _secret("GRADESCOPE_EMAIL")
        password = _secret("GRADESCOPE_PASSWORD")
        completion_cache = None
        if cache_active and args.completion_cache is not None:
            completion_cache = load_completion_cache(args.completion_cache, config=config)
            if args.completion_cache.exists() and completion_cache is None:
                print("[cache] Existing cache is invalid; running the full strict path.", flush=True)

        print("[1/6] Reading and validating the Google worksheet...", flush=True)
        title, rows = fetch_first_worksheet_rows(args.spreadsheet_id, args.worksheet_id)
        timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        if selected_netid is not None:
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

        google_netids = {record["student"]["netid"] for record in records}
        prior_lab_passes: frozenset[tuple[str, str]] = frozenset()
        if completion_cache is not None:
            prior_lab_passes, _ = filter_completion_cache(
                completion_cache, config, google_netids
            )
        print(
            f"[1/6] Google worksheet validated: rows={len(rows)}, selected records={len(records)}",
            flush=True,
        )
        print("[2/6] Connecting to the allowlisted Gradescope course...", flush=True)
        source = PrivateWebGradescopeSource(email, password, config)
        print("[3/6] Reading Lab autograder histories...", flush=True)
        crawl_started = time.monotonic()

        def report_progress(completed: int, total: int) -> None:
            if completed == 1 or completed % 10 == 0 or completed == total:
                elapsed = int(time.monotonic() - crawl_started)
                print(
                    f"[3/6] Gradescope students visited: {completed}/{total} "
                    f"(elapsed {elapsed}s)",
                    flush=True,
                )

        lab_metrics: dict[str, int] = {}
        snapshot = build_snapshot(
            source,
            config,
            only_netid=selected_netid,
            prior_passes=prior_lab_passes,
            force_full_revalidation=args.force_full_revalidation,
            metrics=lab_metrics,
            progress=report_progress,
        )
        if args.shadow_cache_comparison:
            if completion_cache is None:
                raise ValueError("shadow comparison requires an existing valid completion cache")
            shadow_metrics: dict[str, int] = {}
            full_snapshot = build_snapshot(
                source,
                config,
                only_netid=selected_netid,
                prior_passes=prior_lab_passes,
                force_full_revalidation=True,
                metrics=shadow_metrics,
            )
            if _lab_statuses(snapshot) != _lab_statuses(full_snapshot):
                raise ValueError("cached and forced-full Lab results differ")
            snapshot = full_snapshot
            print(
                "[3/6] Cache shadow comparison: zero semantic Lab differences; "
                f"forced source checks={shadow_metrics['lab_source_checks']}",
                flush=True,
            )

        if args.all_students and args.snapshot.exists() and (
            not cache_active or completion_cache is None
        ):
            # Migration/fallback precedence: a valid completion cache is the
            # monotone source. Without one, retain the existing validated
            # snapshot behavior, then seed the new cache after publication.
            previous = json.loads(args.snapshot.read_text(encoding="utf-8"))
            previous_errors = validate_snapshot(previous)
            if previous_errors:
                raise ValueError("existing Gradescope snapshot is invalid; refusing to publish")
            snapshot = carry_forward_verified_passes(snapshot, previous)
        print(
            "[3/6] Lab cache: "
            f"candidates={lab_metrics['lab_cache_candidates']}, "
            f"hits={lab_metrics['lab_cache_hits']}, "
            f"source checks={lab_metrics['lab_source_checks']}, "
            f"canary checks={lab_metrics['lab_canary_checks']}",
            flush=True,
        )

        gradescope_netids = {student["netid"] for student in snapshot["students"]}
        missing_gradescope = _validate_roster_coverage(
            google_netids,
            gradescope_netids,
            args.allow_missing_gradescope_students,
        )
        print(
            f"[4/6] Merging Lab sources: Gradescope students={len(gradescope_netids)}, "
            f"Google-only students={len(missing_gradescope)}",
            flush=True,
        )
        combined = merge_checkoffs_with_autograders(
            records,
            snapshot,
            allow_missing_students=bool(missing_gradescope),
        )
        prior_exam_completions: frozenset[tuple[str, str]] = frozenset()
        if completion_cache is not None:
            _, prior_exam_completions = filter_completion_cache(
                completion_cache, config, gradescope_netids
            )
        print("[5/6] Reading optional Exam 1 results...", flush=True)
        exam = import_exam_soft(
            source,
            config.exam,
            [record["student"]["netid"] for record in combined],
            current_gradescope_netids=frozenset(gradescope_netids),
            prior_completions=prior_exam_completions,
        )
        combined = merge_exam_checkmarks(combined, exam)
        print(
            f"[5/6] {exam.message}; completion cache hits={exam.cache_hits}; "
            "conditional export retrieval=unsupported",
            flush=True,
        )
        print("[6/6] Validating and atomically publishing the new release...", flush=True)

        # Publish first. State files follow, and the optimization cache is last.
        # A crash before the cache write causes extra work on the next run, not
        # an incorrectly awarded checkmark.
        paths = write_simple_release(combined, args.output, retain_previous=True)
        write_snapshot_atomic(snapshot, args.snapshot)
        if cache_active and args.completion_cache is not None:
            next_cache = build_completion_cache(
                config, snapshot, exam.verified_completions
            )
            write_completion_cache_atomic(next_cache, args.completion_cache)

        if args.copy_assets_to is not None:
            args.copy_assets_to.mkdir(parents=True, exist_ok=True)
            for asset in ("simple-dashboard.js", "simple-style.css"):
                shutil.copy2(Path("static") / asset, args.copy_assets_to / asset)
    except (GradescopeAdapterError, KeyError, OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))
    finally:
        if lock_handle is not None:
            lock_handle.close()

    mode = "all students" if args.all_students else "selected student"
    print(
        f"published combined lab dashboards for {mode}: {len(paths)} protected record(s), "
        f"{len(config.assignments)} lab assignment(s); "
        f"Gradescope-missing students={len(missing_gradescope)}; {exam.message}"
    )


if __name__ == "__main__":
    main()
