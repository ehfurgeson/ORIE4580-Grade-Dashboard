const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
function run(path, root) {
  const links = Object.fromEntries(['dashboard', 'calculator', 'exam3'].map(key => [key, {removeAttribute() {}}]));
  const nav = {dataset: {root}, querySelector: selector => links[selector.match(/"(.*?)"/)[1]]};
  const url = new URL(path, 'https://example.org');
  vm.runInNewContext(fs.readFileSync('static/course-nav.js', 'utf8'), {document: {querySelector: () => nav},
    location: {href: url.href, pathname: url.pathname, search: url.search}, URL, URLSearchParams});
  return links;
}
test('navigation preserves the student across exam and calculator pages', () => {
  for (const [path, root] of [['/course/students/abc123/', '../../'], ['/course/students/abc123/exam3/', '../../../'], ['/course/grade_calculator/?student=abc123', '../']]) {
    const links = run(path, root);
    assert.equal(links.dashboard.href, 'https://example.org/course/');
    assert.equal(links.exam3.href, 'https://example.org/course/students/abc123/exam3/');
    assert.equal(links.calculator.href, 'https://example.org/course/grade_calculator/?student=abc123');
  }
});
test('public calculator does not guess an identity or accept arbitrary destinations', () => {
  for (const query of ['', '?student=https://evil.example', '?student=../../staff']) {
    assert.equal(run('/course/grade_calculator/' + query, '../').exam3.href, undefined);
  }
});

test('staff list and public calculator use the authenticated dashboard redirect', () => {
  for (const path of ['/course/students/', '/course/grade_calculator/']) {
    assert.equal(run(path, '../').dashboard.href, 'https://example.org/course/');
  }
});
