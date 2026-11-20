const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
function run(path, root, {staffIndex = false, status = 403, redirected = false} = {}) {
  const makeLink = () => ({dataset: {}, removeAttribute(name) { delete this[name]; }, setAttribute(name, value) { this[name] = value; }});
  const order = ['dashboard', 'exam3', 'exam_retry', 'calculator'];
  const links = Object.fromEntries(order.map(key => [key, makeLink()]));
  const nav = {dataset: {root}, querySelector: selector => links[selector.match(/"(.*?)"/)[1]],
    prepend: link => { order.unshift(link.dataset.page); links[link.dataset.page] = link; }};
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
  return {links, order, requests};
}
test('navigation preserves the student across exam and calculator pages', () => {
  for (const [path, root] of [['/course/students/abc123/', '../../'], ['/course/students/abc123/exam3/', '../../../'], ['/course/students/abc123/exam_retry/', '../../../'], ['/course/grade_calculator/?student=abc123', '../']]) {
    const {links} = run(path, root);
    assert.equal(links.dashboard.href, 'https://example.org/course/students/abc123/');
    assert.equal(links.exam3.href, 'https://example.org/course/students/abc123/exam3/');
    assert.equal(links.exam_retry.href, 'https://example.org/course/students/abc123/exam_retry/');
    if (path.endsWith('/exam_retry/')) assert.equal(links.exam_retry['aria-current'], 'page');
    assert.equal(links.calculator.href, 'https://example.org/course/grade_calculator/?student=abc123');
  }
});
test('public calculator does not guess an identity or accept arbitrary destinations', () => {
  for (const query of ['', '?student=https://evil.example', '?student=../../staff']) {
    const {links} = run('/course/grade_calculator/' + query, '../');
    assert.equal(links.dashboard.href, undefined);
    assert.equal(links.dashboard['aria-disabled'], 'true');
    assert.equal(links.exam3.href, undefined);
  }
});

test('staff index shows its Index link with disabled exam links even with a student parameter', () => {
  const {links, order, requests} = run('/course/students/?student=abc123', '../', {staffIndex: true});
  assert.equal(links.dashboard.href, undefined);
  assert.equal(links.dashboard['aria-disabled'], 'true');
  assert.equal(links.exam3.href, undefined);
  assert.equal(links.exam_retry.href, undefined);
  assert.equal(links.index['aria-current'], 'page');
  assert.equal(links.index.href, 'https://example.org/course/students/');
  assert.deepEqual(order, ['index', 'dashboard', 'exam3', 'exam_retry', 'calculator']);
  assert.equal(requests.length, 0);
});

test('student dashboard, exam review, and calculator add Index for staff sessions', async () => {
  for (const [path, root] of [['/course/students/abc123/', '../../'], ['/course/students/abc123/exam_retry/', '../../../'], ['/course/grade_calculator/', '../']]) {
    const {links, order, requests} = run(path, root, {status: 200});
    await new Promise(resolve => setImmediate(resolve));
    assert.deepEqual(requests, [{href: 'https://example.org/course/students/', method: 'HEAD',
      credentials: 'same-origin', cache: 'no-store', redirect: 'error'}]);
    assert.equal(links.index.href, 'https://example.org/course/students/');
    assert.equal(links.index.textContent, 'Index');
    assert.deepEqual(order, ['index', 'dashboard', 'exam3', 'exam_retry', 'calculator']);
  }
});

test('denied sessions and sign-in redirects leave the normal header', async () => {
  for (const options of [{status: 403}, {redirected: true}]) {
    const {links} = run('/course/students/abc123/', '../../', options);
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(links.index, undefined);
    assert.equal(links.dashboard.href, 'https://example.org/course/students/abc123/');
    assert.equal(links.exam3.href, 'https://example.org/course/students/abc123/exam3/');
  }
});
