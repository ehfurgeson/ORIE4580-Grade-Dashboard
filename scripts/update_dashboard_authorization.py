"""Update generated dashboard authorization without fetching grade sources."""
from __future__ import annotations

import argparse
from pathlib import Path

from sync.simple_generate import update_authorization_files


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("students_root", type=Path)
    args = parser.parse_args()
    try:
        paths = update_authorization_files(args.students_root)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(f"updated authorization for {len(paths) - 1} student dashboards and the protected index")


if __name__ == "__main__":
    main()
