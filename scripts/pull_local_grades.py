"""Import completed local grade exports without polling remote grade sources."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from sync.exam_publication import load_publication_state, visible_records
from sync.simple_generate import write_simple_release


def main() -> None:
    from scripts.refresh_combined_dashboard import _acquire_lock, _require_private_state

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, help="private exports directory containing completed batches")
    parser.add_argument('--state', type=Path, required=True, help="same publication state used by scheduled refresh")
    parser.add_argument('--output', type=Path, required=True, help="protected students directory")
    parser.add_argument('--lock-file', type=Path, required=True, help="same lock used by scheduled refresh")
    parser.add_argument('--require-hidden', action='store_true', help="abort if Exam 3 is already visible")
    args = parser.parse_args()
    handle = None
    try:
        for path in (args.source, args.state, args.lock_file):
            _require_private_state(path, args.output, args.output.parent)
        if args.state.resolve() == args.lock_file.resolve():
            raise ValueError("Publication state and lock must be different paths")
        if any(path.resolve().is_relative_to(args.source.resolve()) for path in (args.state, args.lock_file)):
            raise ValueError("Publication state and lock must be outside the exports directory")
        handle = _acquire_lock(args.lock_file)
        state = load_publication_state(args.state)
        if state is None:
            raise ValueError("No collected dashboard state; use the state path from the scheduled refresh")
        exam3_visible = state.get('exam3_visible', False)
        if args.require_hidden and exam3_visible:
            raise ValueError("Exam 3 is visible; hide it with set_exam3_visibility before importing")
        imported_at = datetime.now(timezone.utc).isoformat()
        paths = write_simple_release(visible_records(state['records'], state['visible']), args.output,
                                     local_grades=args.source, local_imported_at=imported_at,
                                     exam3_visible=exam3_visible)
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        parser.error(str(error))
    finally:
        if handle is not None:
            handle.close()
    print(f"Imported local grades at {imported_at}; rebuilt {len(paths)} student dashboard(s). "
          f"Exam 3 visibility remains {'ON' if exam3_visible else 'OFF'}. "
          f"Remote grades remain as of {state['collected_at']}; no remote sources contacted.")


if __name__ == '__main__':
    main()
