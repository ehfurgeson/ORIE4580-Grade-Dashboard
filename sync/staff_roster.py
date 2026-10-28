"""Read the optional private roster used only by the protected staff index."""
from __future__ import annotations

import csv
from pathlib import Path

from .simple_checkoffs import NETID_PATTERN


STAFF_ROSTER_PATH = Path('/var/lib/orie4580-dashboard/student-names.csv')


def load_staff_roster() -> dict[str, tuple[str, str]] | None:
    """Missing file preserves the NetID-only index; an empty roster lists nobody."""
    try:
        handle = STAFF_ROSTER_PATH.open(encoding='utf-8-sig', newline='')
    except FileNotFoundError:
        return None
    with handle:
        reader = csv.DictReader(handle, strict=True)
        required = {'NetID', 'First Name', 'Last Name'}
        if reader.fieldnames is None or set(reader.fieldnames) != required or len(reader.fieldnames) != 3:
            raise ValueError("Staff roster must have NetID, First Name, and Last Name columns")
        roster = {}
        try:
            for row in reader:
                if None in row or any(value is None for value in row.values()):
                    raise ValueError(f"Staff roster row {reader.line_num} has the wrong number of fields")
                netid = row['NetID'].strip().lower()
                if not NETID_PATTERN.fullmatch(netid) or netid in roster:
                    raise ValueError(f"Staff roster row {reader.line_num} has an invalid or duplicate NetID")
                names = (row['First Name'].strip(), row['Last Name'].strip())
                if any(len(name) > 200 or any(ord(char) < 32 for char in name) for name in names):
                    raise ValueError(f"Staff roster row {reader.line_num} has an invalid name")
                roster[netid] = names
        except csv.Error as error:
            raise ValueError("Staff roster is not valid CSV") from error
        return roster
