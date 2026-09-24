import pytest

from scripts.refresh_combined_dashboard import (
    _acquire_lock, _lab_statuses, _require_private_snapshot, _require_private_state,
    _secret, _selected_netid, _validate_roster_coverage,
)


def test_local_student_defaults_to_fake_email_in_environment(monkeypatch):
    monkeypatch.setenv("GRADESCOPE_TEST_STUDENT_EMAIL", "ABC123@cornell.edu")
    assert _selected_netid(None, False) == "abc123"


def test_all_students_does_not_use_browser_or_environment_identity(monkeypatch):
    monkeypatch.setenv("GRADESCOPE_TEST_STUDENT_EMAIL", "abc123@cornell.edu")
    assert _selected_netid(None, True) is None


def test_local_student_requires_canonical_cornell_identity(monkeypatch):
    monkeypatch.delenv("GRADESCOPE_TEST_STUDENT_EMAIL", raising=False)
    with pytest.raises(ValueError, match="GRADESCOPE_TEST_STUDENT_EMAIL"):
        _selected_netid(None, False)


def test_snapshot_must_not_be_inside_a_served_root(tmp_path):
    served = tmp_path / "preview"
    with pytest.raises(ValueError, match="outside"):
        _require_private_snapshot(served / "state.json", served / "students", served)
    _require_private_snapshot(tmp_path / "private-state.json", served / "students", served)


def test_secret_can_be_read_from_systemd_credential_file(tmp_path, monkeypatch):
    credential = tmp_path / "password"
    credential.write_text("private-value\n")
    monkeypatch.delenv("GRADESCOPE_PASSWORD", raising=False)
    monkeypatch.setenv("GRADESCOPE_PASSWORD_FILE", str(credential))
    assert _secret("GRADESCOPE_PASSWORD") == "private-value"


def test_secret_rejects_ambiguous_environment_and_file(tmp_path, monkeypatch):
    credential = tmp_path / "password"
    credential.write_text("file-value")
    monkeypatch.setenv("GRADESCOPE_PASSWORD", "environment-value")
    monkeypatch.setenv("GRADESCOPE_PASSWORD_FILE", str(credential))
    with pytest.raises(ValueError, match="only one"):
        _secret("GRADESCOPE_PASSWORD")


def test_service_uses_systemd_credentials_not_secret_environment_file():
    from pathlib import Path
    unit = Path("deployment/orie4580-checkoffs.service").read_text()
    assert "LoadCredential=gradescope-password:" in unit
    assert "GRADESCOPE_PASSWORD_FILE=%d/gradescope-password" in unit
    assert "EnvironmentFile=" not in unit
    assert "GRADESCOPE_PASSWORD=" not in unit


def test_production_allows_any_google_only_mismatch_but_not_gradescope_only():
    google = {"abc123", "xy99", "zz999"}
    assert _validate_roster_coverage(google, {"abc123"}, True) == {"xy99", "zz999"}
    with pytest.raises(ValueError, match="missing from Gradescope"):
        _validate_roster_coverage(google, {"abc123"}, False)
    with pytest.raises(ValueError, match="absent from the Google Sheet"):
        _validate_roster_coverage({"abc123"}, {"abc123", "xy99"}, True)


def test_service_allows_google_students_missing_from_gradescope():
    from pathlib import Path
    unit = Path("deployment/orie4580-checkoffs.service").read_text()
    assert "--allow-missing-gradescope-students" in unit
    assert "--maximum-missing-gradescope-students" not in unit


def test_refresh_progress_is_aggregate_and_journal_ready():
    from pathlib import Path
    script = Path("scripts/refresh_combined_dashboard.py").read_text()
    unit = Path("deployment/orie4580-checkoffs.service").read_text()
    assert "Gradescope students visited: {completed}/{total}" in script
    assert "Lab cache:" in script
    assert "completion cache hits=" in script
    assert 'else "selected student"' in script
    assert "flush=True" in script
    assert "StandardOutput=journal" in unit
    assert "SyslogIdentifier=orie4580-checkoffs" in unit


def test_cache_and_lock_are_private_and_configured_in_systemd(tmp_path):
    served = tmp_path / "served"
    _require_private_state(tmp_path / "state" / "cache.json", served, None)
    with pytest.raises(ValueError, match="outside"):
        _require_private_state(served / "cache.json", served, None)

    from pathlib import Path
    unit = Path("deployment/orie4580-checkoffs.service").read_text()
    assert "--completion-cache /var/lib/orie4580-dashboard/completion-cache.json" in unit
    assert "--lock-file /var/lib/orie4580-dashboard/refresh.lock" in unit
    assert "StateDirectoryMode=0700" in unit
    assert "Environment=ORIE4580_REFRESH_FLAGS=" in unit
    assert "$ORIE4580_REFRESH_FLAGS" in unit


def test_refresh_lock_rejects_a_concurrent_process(tmp_path):
    path = tmp_path / "refresh.lock"
    first = _acquire_lock(path)
    try:
        with pytest.raises(ValueError, match="already running"):
            _acquire_lock(path)
    finally:
        first.close()
    assert path.stat().st_mode & 0o777 == 0o600


def test_publication_precedes_snapshot_and_cache_state_writes():
    from pathlib import Path
    script = Path("scripts/refresh_combined_dashboard.py").read_text()
    publish = script.index("paths = write_simple_release")
    snapshot = script.index("write_snapshot_atomic(snapshot", publish)
    cache = script.index("write_completion_cache_atomic", snapshot)
    assert publish < snapshot < cache


def test_shadow_comparison_uses_only_semantic_lab_statuses():
    snapshot = {
        "students": [{"netid": "abc123", "autograders": [{
            "opportunity_id": "lab1-q1-2", "status": "passed",
            "pass_evidence": "completion_cache", "submissions_observed": 0,
            "submissions_checked": 0,
        }]}]
    }
    changed_provenance = {
        "students": [{"netid": "abc123", "autograders": [{
            "opportunity_id": "lab1-q1-2", "status": "passed",
            "pass_evidence": "current_history", "submissions_observed": 3,
            "submissions_checked": 1,
        }]}]
    }
    assert _lab_statuses(snapshot) == _lab_statuses(changed_provenance)


def test_shadow_mode_and_full_class_lock_are_enforced_in_refresh_source():
    from pathlib import Path
    script = Path("scripts/refresh_combined_dashboard.py").read_text()
    assert "--shadow-cache-comparison" in script
    assert "all-student publication requires --lock-file" in script
    assert "zero semantic Lab differences" in script
