const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('static/checkmarks.js', 'utf8');
test('glints have independent exponential waits and stop when the page is hidden', () => {
  const timers = new Map(), listeners = {}, classes = [new Set(), new Set()];
  let next = 0;
  const marks = classes.map(set => ({isConnected: true,
    classList: {add: value => set.add(value), remove: value => set.delete(value)},
    getBoundingClientRect: () => ({width: 24, height: 24, top: 10, bottom: 34, left: 10, right: 34})}));
  const samples = [0.25, 0.75];
  const document = {hidden: false, documentElement: {}, querySelectorAll: () => marks,
    addEventListener: (event, callback) => {listeners[event] = callback;}};
  vm.runInNewContext(source, {document, window: {addEventListener() {}}, innerHeight: 800, innerWidth: 800,
    matchMedia: () => ({matches: false, addEventListener() {}}),
    MutationObserver: class {observe() {}}, requestAnimationFrame: callback => callback(),
    Math: {log: Math.log, random: () => samples.shift()},
    setTimeout: (callback, delay) => {timers.set(++next, {callback, delay}); return next;},
    clearTimeout: id => timers.delete(id)});
  assert.equal(timers.size, 2);
  assert.equal(timers.get(1).delay, -Math.log(0.75) * 60000);
  assert.equal(timers.get(2).delay, -Math.log(0.25) * 60000);
  const first = timers.get(1); timers.delete(1); first.callback();
  assert.equal(classes[0].has('shimmer'), true);
  assert.equal(classes[1].has('shimmer'), false);
  document.hidden = true; listeners.visibilitychange();
  assert.equal(timers.size, 0);
  assert.ok(classes.every(set => !set.has('shimmer')));
});
test('calculator embeds the shared animation unchanged', () => {
  const html = fs.readFileSync('static/grade_calculator/index.html', 'utf8');
  const embedded = html.match(/<!-- BEGIN SHARED CHECKMARK JS -->\s*<script>\n([\s\S]*?)<\/script>/)[1];
  assert.equal(embedded.trim(), source.trim());
});
