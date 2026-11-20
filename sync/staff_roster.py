"""Read the optional private roster used only by the protected staff index."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from .simple_checkoffs import NETID_PATTERN


STAFF_ROSTER_PATH = Path('/var/lib/orie4580-dashboard/student-names.csv')


@dataclass
class StaffRoster:
    columns: tuple[str, ...]
    rows: dict[str, tuple[str, ...]]


def load_staff_roster() -> StaffRoster | None:
    """Missing file preserves the NetID-only index; an empty roster lists nobody."""
    try:
        handle = STAFF_ROSTER_PATH.open(encoding='utf-8-sig', newline='')
    except FileNotFoundError:
        return None
    with handle:
        reader = csv.reader(handle, strict=True)
        try:
            headers = [header.strip() for header in next(reader, [])]
            if 'NetID' not in headers or '' in headers or len(set(headers)) != len(headers):
                raise ValueError("Staff roster must have a NetID column and unique, nonempty headers")
            netid_index = headers.index('NetID')
            columns = tuple(header for header in headers if header != 'NetID')
            rows = {}
            for values in reader:
                if not values:
                    continue
                if len(values) != len(headers):
                    raise ValueError(f"Staff roster row {reader.line_num} has the wrong number of fields")
                netid = values.pop(netid_index).strip().lower()
                if not NETID_PATTERN.fullmatch(netid) or netid in rows:
                    raise ValueError(f"Staff roster row {reader.line_num} has an invalid or duplicate NetID")
                rows[netid] = tuple(value.strip() for value in values)
        except csv.Error as error:
            raise ValueError("Staff roster is not valid CSV") from error
        return StaffRoster(columns, rows)
