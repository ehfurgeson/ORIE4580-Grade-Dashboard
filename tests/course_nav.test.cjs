const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
function run(path, root, {staffIndex = false, status = 403, redirected = false} = {}) {
  const makeLink = () => ({dataset: {}, removeAttribute() {}, setAttribute(name, value) { this[name] = value; }});
  const links = Object.fromEntries(['dashboard', 'calculator', 'exam3', 'exam_retry'].map(key => [key, makeLink()]));
  const nav = {dataset: {root}, querySelector: selector => links[selector.match(/"(.*?)"/)[1]],
    append: link => { links[link.dataset.page] = link; }};
  const url = new URL(path, 'https://example.org');
  const requests = [];
  vm.runInNewContext(fs.readFileSync('static/course-nav.js', 'utf8'), {
    document: {querySelector: selector => selector === '.course-nav' ? nav : staffIndex, createElement: makeLink},
    location: {href: url.href, pathname: url.pathname, search: url.search}, URL, URLSearchParams,
    fetch: async (href, options) => {
      requests.push({href, ...options});
      if (redirected) throw new Error('Redirected to sign-in');
      return {ok: status === 200};
    }
  });
  return {links, requests};
}
test('navigation preserves the student across exam and calculator pages', () => {
  for (const [path, root] of [['/course/students/abc123/', '../../'], ['/course/students/abc123/exam3/', '../../../'], ['/course/students/abc123/exam_retry/', '../../../'], ['/course/grade_calculator/?student=abc123', '../']]) {
    const {links} = run(path, root);
    assert.equal(links.dashboard.href, 'https://example.org/course/');
    assert.equal(links.exam3.href, 'https://example.org/course/students/abc123/exam3/');
    assert.equal(links.exam_retry.href, 'https://example.org/course/students/abc123/exam_retry/');
    if (path.endsWith('/exam_retry/')) assert.equal(links.exam_retry['aria-current'], 'page');
    assert.equal(links.calculator.href, 'https://example.org/course/grade_calculator/?student=abc123');
  }
});
test('public calculator does not guess an identity or accept arbitrary destinations', () => {
  for (const query of ['', '?student=https://evil.example', '?student=../../staff']) {
    assert.equal(run('/course/grade_calculator/' + query, '../').links.exam3.href, undefined);
  }
});

test('staff index shows its Index link with disabled exam links even with a student parameter', () => {
  const {links, requests} = run('/course/students/?student=abc123', '../', {staffIndex: true});
  assert.equal(links.dashboard.href, 'https://example.org/course/');
  assert.equal(links.exam3.href, undefined);
  assert.equal(links.exam_retry.href, undefined);
  assert.equal(links.index['aria-current'], 'page');
  assert.equal(links.index.href, 'https://example.org/course/students/');
  assert.equal(requests.length, 0);
});

test('student dashboard, exam review, and calculator add Index for staff sessions', async () => {
  for (const [path, root] of [['/course/students/abc123/', '../../'], ['/course/students/abc123/exam_retry/', '../../../'], ['/course/grade_calculator/', '../']]) {
    const {links, requests} = run(path, root, {status: 200});
    await new Promise(resolve => setImmediate(resolve));
    assert.deepEqual(requests, [{href: 'https://example.org/course/students/', method: 'HEAD',
      credentials: 'same-origin', cache: 'no-store', redirect: 'error'}]);
    assert.equal(links.index.href, 'https://example.org/course/students/');
    assert.equal(links.index.textContent, 'Index');
  }
});

test('denied sessions and sign-in redirects leave the normal header', async () => {
  for (const options of [{status: 403}, {redirected: true}]) {
    const {links} = run('/course/students/abc123/', '../../', options);
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(links.index, undefined);
    assert.equal(links.exam3.href, 'https://example.org/course/students/abc123/exam3/');
  }
});
