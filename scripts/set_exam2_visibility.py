"""Rebuild protected dashboards from private collected records without source reads."""
from __future__ import annotations

import argparse
from pathlib import Path

from sync.exam2_publication import load_publication_state, visible_records, write_publication_state
from sync.simple_generate import write_simple_release


def main() -> None:
    from scripts.refresh_combined_dashboard import _acquire_lock, _require_private_state

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("visibility", choices=("on", "off"))
    parser.add_argument("state", type=Path)
    parser.add_argument("--lock-file", type=Path, required=True, help="same lock used by scheduled refresh")
    parser.add_argument("output", type=Path, help="protected students directory")
    args = parser.parse_args()
    handle = None
    try:
        _require_private_state(args.state, args.output, args.output.parent)
        _require_private_state(args.lock_file, args.output, args.output.parent)
        if args.state.resolve() == args.lock_file.resolve():
            raise ValueError("publication state and lock must be different paths")
        handle = _acquire_lock(args.lock_file)
        state = load_publication_state(args.state)
        if state is None:
            raise ValueError("no collected Exam 2 state; run the scheduled refresh first")
        state["visible"] = args.visibility == "on"
        write_publication_state(args.state, state)
        paths = write_simple_release(visible_records(state["records"], state["visible"]), args.output, retain_previous=False)
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        parser.error(str(error))
    finally:
        if handle is not None:
            handle.close()
    print(f"Exam 2 visibility {args.visibility}: rebuilt {len(paths)} protected dashboard(s); collected {state['collected_at']}; no source reads")


if __name__ == "__main__":
    main()
