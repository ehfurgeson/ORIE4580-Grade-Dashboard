import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sync.staff_roster import load_staff_roster


class StaffRosterTests(unittest.TestCase):
    def test_optional_file_and_csv_names(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'names.csv'
            with patch('sync.staff_roster.STAFF_ROSTER_PATH', path):
                self.assertIsNone(load_staff_roster())
                path.write_text('\ufeffNetID,First Name,Last Name\nABC123,Zoë,"Smith, Jr."\n', encoding='utf-8')
                self.assertEqual(load_staff_roster(), {'abc123': ('Zoë', 'Smith, Jr.')})
                path.write_text('NetID,First Name,Last Name\n', encoding='utf-8')
                self.assertEqual(load_staff_roster(), {})

    def test_bad_roster_fails_instead_of_showing_all_students(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'names.csv'
            with patch('sync.staff_roster.STAFF_ROSTER_PATH', path):
                for contents in (
                    'netid,name\nabc123,Alice\n',
                    'NetID,First Name,Last Name\nabc123,Alice,A\nABC123,Bob,B\n',
                    'NetID,First Name,Last Name\n../unsafe,Alice,A\n',
                    'NetID,First Name,Last Name\nabc123,Alice\n',
                ):
                    with self.subTest(contents=contents):
                        path.write_text(contents, encoding='utf-8')
                        with self.assertRaises(ValueError):
                            load_staff_roster()
