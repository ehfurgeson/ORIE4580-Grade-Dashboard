import pytest

from scripts.refresh_combined_dashboard import (
    _require_private_snapshot, _secret, _selected_netid, _validate_roster_coverage,
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
