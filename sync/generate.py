"""Generate private per-student JSON without exposing partial files."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any

from .validate import validate_all, validate_record


def _serialize(record: dict[str, Any]) -> str:
    return json.dumps(record, indent=2, ensure_ascii=False, allow_nan=False) + "\n"


def _write_serialized(payload: str, student_id: str, output_dir: str | Path) -> Path:
    destination = Path(output_dir) / student_id / "grades.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=destination.parent, prefix=".grades-", suffix=".tmp", delete=False
        ) as temporary:
            temporary_name = temporary.name
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, destination)
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)
    return destination


def write_record(record: dict[str, Any], output_dir: str | Path) -> Path:
    errors = validate_record(record)
    if errors:
        raise ValueError("invalid record: " + "; ".join(errors))
    return _write_serialized(_serialize(record), record["student"]["id"], output_dir)


def write_records(records: list[dict[str, Any]], output_dir: str | Path) -> list[Path]:
    errors = validate_all(records)
    if errors:
        raise ValueError("invalid records: " + "; ".join(errors))

    # Serialize the complete batch before touching any destination file.
    payloads = [(_serialize(record), record["student"]["id"]) for record in records]
    return [_write_serialized(payload, student_id, output_dir) for payload, student_id in payloads]
