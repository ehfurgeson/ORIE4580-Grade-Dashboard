"""Embed the shared grade-mark stylesheet in the standalone calculator."""
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
START = '<!-- BEGIN SHARED CHECKMARK CSS -->'
END = '<!-- END SHARED CHECKMARK CSS -->'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help="fail if the embedded copy is stale")
    args = parser.parse_args()
    target = ROOT / 'static/grade_calculator/index.html'
    source = (ROOT / 'static/checkmarks.css').read_text(encoding='utf-8')
    text = target.read_text(encoding='utf-8')
    start, end = text.index(START), text.index(END) + len(END)
    replacement = START + '\n<style>\n' + source.rstrip() + '\n</style>\n' + END
    updated = text[:start] + replacement + text[end:]
    if args.check:
        if text != updated:
            parser.exit(1, "Calculator checkmarks are stale; run scripts/sync_calculator_checkmarks.py.\n")
    else:
        target.write_text(updated, encoding='utf-8')


if __name__ == '__main__':
    main()
