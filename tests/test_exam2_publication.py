"""Offline Exam 2 visibility switches preserve collection and other opportunities."""
from copy import deepcopy
import json
import sys

import pytest

from sync.exam2_publication import load_publication_state, visible_records, write_publication_state
from sync.simple_generate import write_simple_release
from test_exam2_combined import merged


@pytest.fixture
def state():
    return {"schema_version": 1, "visible": False, "collected_at": "2026-10-27T12:00:00Z", "records": [merged()]}


def test_private_state_round_trip_and_hidden_filter(tmp_path, state):
    path = tmp_path / "private" / "state.json"
    assert load_publication_state(path) is None
    write_publication_state(path, state)
    assert path.stat().st_mode & 0o777 == 0o600
    assert load_publication_state(path) == state
    before = deepcopy(state)
    hidden = visible_records(state["records"], False)
    assert "exam2-q" not in json.dumps(hidden)
    assert state == before
    visible = visible_records(state["records"], True)
    assert visible == state["records"] and visible is not state["records"]
    for full, filtered in zip(state["records"][0]["standards"], hidden[0]["standards"]):
        assert filtered["checkmarks"] == [mark for mark in full["checkmarks"] if not mark["id"].startswith("exam2-q")]


@pytest.mark.parametrize("change", ["timestamp", "timezone", "visible", "extra", "empty", "duplicate", "incomplete"])
def test_invalid_state_is_rejected(tmp_path, state, change):
    if change == "timestamp":
        state["collected_at"] = "bad"
    elif change == "timezone":
        state["collected_at"] = "2026-10-27T12:00:00"
    elif change == "visible":
        state["visible"] = 1
    elif change == "extra":
        state["extra"] = True
    elif change == "empty":
        state["records"] = []
    elif change == "duplicate":
        state["records"] *= 2
    else:
        state["records"] = visible_records(state["records"], False)
    path = tmp_path / "state.json"
    path.write_text(json.dumps(state))
    with pytest.raises(ValueError):
        load_publication_state(path)
    with pytest.raises(ValueError):
        write_publication_state(path, state)


def test_symlink_state_rejected_even_when_dangling(tmp_path, state):
    target = tmp_path / "target.json"
    path = tmp_path / "state.json"
    path.symlink_to(target)
    for exists in (False, True):
        if exists:
            target.write_text(json.dumps(state))
        with pytest.raises(ValueError, match="symlink"):
            load_publication_state(path)
        with pytest.raises(ValueError, match="symlink"):
            write_publication_state(path, state)


def test_offline_cli_on_off_rebuilds_and_removes_previous(tmp_path, monkeypatch, state, capsys):
    import scripts.set_exam2_visibility as switch
    state_path = tmp_path / "private" / "exam2.json"
    output = tmp_path / "served" / "students"
    lock = tmp_path / "private" / "refresh.lock"
    write_publication_state(state_path, state)
    write_simple_release(visible_records(state["records"], False), output)
    for visibility in ("on", "off"):
        monkeypatch.setattr(sys, "argv", ["switch", visibility, str(state_path), str(output), "--lock-file", str(lock)])
        switch.main()
        payload = (output / "abc123" / "checkoffs.json").read_text()
        assert ("exam2-q" in payload) == (visibility == "on")
        collected = load_publication_state(state_path)
        assert collected["visible"] == (visibility == "on")
        assert collected["records"] == state["records"]
        assert not output.with_name(".students-previous").exists()
    assert state["collected_at"] in capsys.readouterr().out


def test_cli_missing_collection_fails_without_publishing(tmp_path, monkeypatch):
    import scripts.set_exam2_visibility as switch
    output = tmp_path / "served" / "students"
    monkeypatch.setattr(sys, "argv", ["switch", "on", str(tmp_path / "private" / "state.json"), str(output), "--lock-file", str(tmp_path / "private" / "refresh.lock")])
    with pytest.raises(SystemExit):
        switch.main()
    assert not output.exists()


def test_cli_writes_desired_state_before_publication(tmp_path, monkeypatch, state):
    import scripts.set_exam2_visibility as switch
    state_path = tmp_path / "private" / "exam2.json"
    output = tmp_path / "served" / "students"
    write_publication_state(state_path, state)
    monkeypatch.setattr(sys, "argv", ["switch", "on", str(state_path), str(output), "--lock-file", str(tmp_path / "private" / "refresh.lock")])
    def failed_publication(records, directory, **kwargs):
        assert load_publication_state(state_path)["visible"] is True
        assert kwargs == {"retain_previous": False}
        raise OSError("fake publication failure")
    monkeypatch.setattr(switch, "write_simple_release", failed_publication)
    with pytest.raises(SystemExit):
        switch.main()
    assert load_publication_state(state_path)["visible"] is True


def test_cli_honors_refresh_lock(tmp_path, monkeypatch, state):
    import scripts.set_exam2_visibility as switch
    from scripts.refresh_combined_dashboard import _acquire_lock
    state_path = tmp_path / "private" / "exam2.json"
    lock = tmp_path / "private" / "refresh.lock"
    write_publication_state(state_path, state)
    handle = _acquire_lock(lock)
    monkeypatch.setattr(sys, "argv", ["switch", "on", str(state_path), str(tmp_path / "served" / "students"), "--lock-file", str(lock)])
    try:
        with pytest.raises(SystemExit):
            switch.main()
    finally:
        handle.close()
    assert load_publication_state(state_path)["visible"] is False
