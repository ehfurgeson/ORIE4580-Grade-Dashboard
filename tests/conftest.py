"""Keep tests independent of private production files installed on the host."""
import pytest

from sync import staff_roster


@pytest.fixture(autouse=True)
def isolated_staff_roster(tmp_path, monkeypatch):
    # An absent optional roster exercises the NetID-only index. Roster-specific
    # tests can override this path with their own synthetic CSVs.
    monkeypatch.setattr(staff_roster, 'STAFF_ROSTER_PATH', tmp_path / 'student-names.csv')
