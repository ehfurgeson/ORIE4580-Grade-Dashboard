#!/bin/sh
# Reinstall presentation assets and rebuild pages from private saved data.
set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "Run with sudo: sudo sh scripts/rebuild_dashboard.sh" >&2
    exit 1
fi
cd "$(dirname "$0")/.."

# Same lock as the refresh service; fail immediately if a refresh is running.
exec 9>/var/lib/orie4580-dashboard/refresh.lock
if ! flock -n 9; then
    echo "A dashboard refresh is running. Wait for it to finish, then retry." >&2
    exit 1
fi

# Validate the saved state before changing served files. Print no student data.
sudo -u orie4580-dashboard -g www-data env PYTHONDONTWRITEBYTECODE=1 .venv/bin/python - <<'PY'
from sync.exam_publication import load_publication_state
state = load_publication_state('/var/lib/orie4580-dashboard/exam-publication.json')
if state is None:
    raise SystemExit('No saved publication state; run a normal refresh first.')
PY

web_root=/var/www/html/orie4580_fa26
install -o root -g www-data -m 0644 \
    static/simple-dashboard.js static/simple-style.css static/checkmarks.css \
    static/course-nav.css static/course-nav.js \
    static/exam3-review.js static/exam3-review.css "$web_root/"
install -d -o root -g www-data -m 0755 "$web_root/grade_calculator"
install -o root -g www-data -m 0644 \
    static/grade_calculator/index.html static/grade_calculator/.htaccess \
    "$web_root/grade_calculator/"

# The parent shell holds the refresh lock throughout both operations.
sudo -u orie4580-dashboard -g www-data env PYTHONDONTWRITEBYTECODE=1 .venv/bin/python - <<'PY'
from sync.exam_publication import load_publication_state, visible_records
from sync.simple_generate import write_simple_release
state = load_publication_state('/var/lib/orie4580-dashboard/exam-publication.json')
paths = write_simple_release(
    visible_records(state['records'], state['visible']),
    '/var/www/html/orie4580_fa26/students',
    exam3_visible=state.get('exam3_visible', False),
)
print(f'Rebuilt {len(paths)} student dashboards, staff index, Exam 3 pages, and shared assets.')
print('Visibility settings and existing Exam 3 JSON/PDF files preserved. No source refresh performed.')
PY
