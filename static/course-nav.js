/* Navigation context is only a link destination; Apache still authorizes every student URL. */
(() => {
  const nav = document.querySelector('.course-nav');
  if (!nav) return;
  const root = new URL(nav.dataset.root, location.href);
  const onStaffIndex = Boolean(document.querySelector('#staff-index'));
  const pathMatch = location.pathname.match(/\/students\/([a-z]{2,3}[0-9]+)\/(?:(exam3|exam_retry)\/)?(?:index\.html)?$/);
  const candidate = pathMatch?.[1] || new URLSearchParams(location.search).get('student');
  const student = !onStaffIndex && /^[a-z]{2,3}[0-9]+$/.test(candidate || '') ? candidate : null;
  const dashboard = nav.querySelector('[data-page="dashboard"]');
  if (student) {
    const studentDashboard = new URL(`students/${student}/`, root);
    dashboard.href = studentDashboard.href;
    dashboard.removeAttribute('aria-disabled');
    nav.querySelector('[data-page="calculator"]').href = new URL(`grade_calculator/?student=${student}`, root).href;
    for (const page of ['exam3', 'exam_retry']) {
      const exam = nav.querySelector(`[data-page="${page}"]`);
      if (!exam) continue;
      exam.href = new URL(`${page}/`, studentDashboard).href;
      exam.removeAttribute('aria-disabled');
      exam.removeAttribute('title');
      if (pathMatch?.[2] === page) exam.setAttribute('aria-current', 'page');
    }
  } else {
    dashboard.removeAttribute('href');
    dashboard.setAttribute('aria-disabled', 'true');
  }

  const indexUrl = new URL('students/', root);
  function addIndexLink() {
    const index = document.createElement('a');
    index.dataset.page = 'index';
    index.href = indexUrl.href;
    index.textContent = 'Index';
    if (onStaffIndex) index.setAttribute('aria-current', 'page');
    nav.prepend(index);
  }

  if (onStaffIndex) {
    addIndexLink();
  } else {
    // Check the protected index with the current session without fetching its HTML.
    fetch(indexUrl.href, {method: 'HEAD', credentials: 'same-origin', cache: 'no-store', redirect: 'error'})
      .then(response => { if (response.ok) addIndexLink(); })
      .catch(() => {}); // A missing or expired session leaves the shared links visible.
  }
})();
