/* Navigation context is only a link destination; Apache still authorizes every student URL. */
(() => {
  const nav = document.querySelector('.course-nav');
  if (!nav) return;
  const root = new URL(nav.dataset.root, location.href);
  const pathMatch = location.pathname.match(/\/students\/([a-z]{2,3}[0-9]+)\/(?:(exam3|exam_retry)\/)?(?:index\.html)?$/);
  const candidate = pathMatch?.[1] || new URLSearchParams(location.search).get('student');
  const student = /^[a-z]{2,3}[0-9]+$/.test(candidate || '') ? candidate : null;
  nav.querySelector('[data-page="dashboard"]').href = root.href;
  if (student) {
    nav.querySelector('[data-page="calculator"]').href = new URL(`grade_calculator/?student=${student}`, root).href;
    for (const page of ['exam3', 'exam_retry']) {
      const exam = nav.querySelector(`[data-page="${page}"]`);
      if (!exam) continue;
      exam.href = new URL(`students/${student}/${page}/`, root).href;
      exam.removeAttribute('aria-disabled');
      exam.removeAttribute('title');
      if (pathMatch?.[2] === page) exam.setAttribute('aria-current', 'page');
    }
  }
})();
