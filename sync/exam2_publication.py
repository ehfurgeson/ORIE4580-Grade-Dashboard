"""Private collected records and the operator-controlled Exam 2 visibility flag."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
import os
from pathlib import Path
import tempfile

from .combined_checkoffs import validate_combined_record
from .gradescope_exam2 import EXAM2_OPPORTUNITIES

_EXAM2_IDS = {item["id"] for item in EXAM2_OPPORTUNITIES}


def _validate_state(state: dict) -> None:
    if not isinstance(state, dict) or set(state) != {"schema_version", "visible", "collected_at", "records"} or type(state.get("schema_version")) is not int or state["schema_version"] != 1:
        raise ValueError("invalid Exam 2 publication state schema")
    if type(state.get("visible")) is not bool:
        raise ValueError("Exam 2 visibility must be a boolean")
    if not isinstance(state.get("collected_at"), str) or not state["collected_at"]:
        raise ValueError("Exam 2 state requires a collection timestamp")
    try:
        timestamp = datetime.fromisoformat(state["collected_at"].replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            raise ValueError("missing timezone")
    except ValueError as error:
        raise ValueError("invalid Exam 2 collection timestamp") from error
    records = state.get("records")
    if not isinstance(records, list) or not records:
        raise ValueError("Exam 2 state requires collected records")
    seen = set()
    metadata = None
    for record in records:
        errors = validate_combined_record(record)
        if errors:
            raise ValueError("invalid collected dashboard: " + "; ".join(errors))
        netid = record["student"]["netid"]
        if netid in seen:
            raise ValueError("duplicate student in Exam 2 state")
        seen.add(netid)
        current_metadata = (record.get("updated_at"), record.get("worksheet"), record.get("unmapped_columns"))
        if metadata is None:
            metadata = current_metadata
        elif current_metadata != metadata:
            raise ValueError("collected records disagree about metadata")
        ids = {mark["id"] for standard in record["standards"] for mark in standard["checkmarks"]}
        if not _EXAM2_IDS <= ids:
            raise ValueError("Exam 2 state requires all collected Exam 2 opportunities")


def load_publication_state(path: str | Path) -> dict | None:
    """Read under the shared refresh lock; a missing state means visibility OFF."""
    path = Path(path)
    if path.is_symlink():
        raise ValueError("Exam 2 state must not be a symlink")
    if not path.exists():
        return None
    state = json.loads(path.read_text(encoding="utf-8"))
    _validate_state(state)
    return state


def write_publication_state(path: str | Path, state: dict) -> None:
    """Atomically save private records; caller holds the shared refresh lock."""
    _validate_state(state)
    path = Path(path)
    if path.is_symlink():
        raise ValueError("Exam 2 state must not be a symlink")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(state, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def visible_records(records: list[dict], visible: bool) -> list[dict]:
    """Filter only Exam 2; never mutate the full private collection."""
    public = deepcopy(records)
    if not visible:
        for record in public:
            for standard in record["standards"]:
                standard["checkmarks"] = [mark for mark in standard["checkmarks"] if mark["id"] not in _EXAM2_IDS]
    return public
