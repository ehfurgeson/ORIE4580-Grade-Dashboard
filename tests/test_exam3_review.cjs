const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.textContent = ''; this.attributes = {}; }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children = items; }
  setAttribute(key, value) { this.attributes[key] = value; }
  showModal() { this.open = true; }
  addEventListener(name, callback) { this[name] = callback; }
}
test('local viewer renders answer text safely and clears rejected files', async () => {
  const nodes = Object.fromEntries(['#file', '#status', '#review'].map(id => [id, new Element(id)]));
  const document = {createElement: tag => new Element(tag), createElementNS: (_, tag) => new Element(tag),
    createDocumentFragment: () => new Element('fragment'), querySelector: id => nodes[id]};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/exam3-review.js'), 'utf8'), {document, window: {}});
  const answer = '<script>alert(1)</script> # staff comment';
  const data = {schema_version: 1, exam: 3, student: {id: 'synthetic', first: 'Test', last: 'Student'}, questions: [
    {id: 'q2', title: 'Code', normal_credit: 'met', shiny_credit: 'not_met', answers: [{text: answer}], parts: [
      {label: '2.1', message: null, plots: [{kind: 'cdf', title: 'Test', observed: [[0, 0], [1, 1]], expected: [[0, 0], [1, 1]]}]}
    ]}
  ]};
  const load = value => nodes['#file'].change({target: {files: [{text: async () => JSON.stringify(value)}]}});
  await load(data);
  assert.equal(nodes['#status'].textContent, '');
  const all = node => [node, ...node.children.flatMap(all)];
  assert.ok(all(nodes['#review']).some(node => node.tag === 'pre' && node.textContent === answer));
  assert.ok(all(nodes['#review']).some(node => node.tag === 'svg'));
  assert.ok(!all(nodes['#review']).some(node => node.tag === 'script'));
  assert.equal(all(nodes['#review']).find(node => node.tag === 'details').open, false);
  const marks = () => all(nodes['#review']).filter(node => (node.className || '').startsWith('checkmark '));
  assert.ok(marks().every(node => node.className === 'checkmark purple earned'));
  assert.ok(all(nodes['#review']).some(node => node.textContent === 'Q2.1 · Code output'));
  data.questions[0].shiny_credit = 'met';
  await load(data);
  assert.ok(marks().every(node => node.className === 'checkmark shiny_purple earned'));
  data.questions[0].normal_credit = 'blank';
  await load(data);
  assert.ok(marks().every(node => node.className === 'checkmark empty-box'));
  assert.ok(all(nodes['#review']).some(node => node.textContent === 'Main part: Blank'));
  assert.equal(all(nodes['#review']).find(node => node.tag === 'details').open, false, 'Partly blank starts closed');
  data.questions[0].shiny_credit = 'blank';
  await load(data);
  assert.equal(all(nodes['#review']).find(node => node.tag === 'details').open, false, 'Completely blank starts closed');
  assert.ok(all(nodes['#review']).some(node => node.tag === 'summary'));
  data.questions[0].id = 'q9';
  data.questions[0].normal_credit = 'met';
  data.questions[0].shiny_credit = null;
  data.questions[0].credit_kind = 'shiny_purple';
  await load(data);
  assert.ok(marks().every(node => node.className === 'checkmark shiny_purple earned'));
  await load({schema_version: 99});
  assert.equal(nodes['#review'].children.length, 0);
  assert.match(nodes['#status'].textContent, /Expected an Exam 3/);
});

test('exam3 adapter merges once and distinguishes hidden or missing files from failures', async () => {
  const window = {}, requests = [];
  let response = {status: 404};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/exam3-review.js'), 'utf8'), {
    window, document: {querySelector: () => null},
    fetch: async (url, options) => {requests.push({url, options}); return response;}
  });
  const api = window.Exam3Review;
  assert.equal(await api.load(), null);
  assert.equal(requests[0].url, 'exam3.json');
  assert.equal(requests[0].options.credentials, 'same-origin');
  assert.equal(requests[0].options.cache, 'no-store');
  response = {status: 403, ok: false};
  assert.equal(await api.load(), null);
  response = {status: 500, ok: false};
  await assert.rejects(api.load(), /unavailable/);
  const exam = JSON.parse(fs.readFileSync(path.join(__dirname, '../fixtures/exam3/synthetic-student.json')));
  const original = {standards: ['S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'S7'].map(id => ({id, checkmarks: [{id: 'lab1-q1', kind: 'green', status: 'complete'}]}))};
  const merged = api.merge(original, exam);
  assert.equal(merged.standards.flatMap(s => s.checkmarks).filter(m => m.id.startsWith('exam3-')).length, 9);
  assert.equal(api.merge(merged, exam).standards.flatMap(s => s.checkmarks).length, 16);
  assert.equal(original.standards[0].checkmarks.length, 1);
  assert.equal(merged.standards[2].checkmarks[1].requirements[0].outcome, 'blank');
  assert.equal(merged.standards[6].checkmarks[2].kind, 'shiny_purple');
  const partial = {...exam, questions: exam.questions.slice(0, 1)};
  assert.equal(api.merge(original, partial).standards[1].checkmarks[1].status, 'not_graded');
  assert.equal(api.merge({standards: original.standards.slice(0, 1)}, exam).standards.length, 1);
  exam.questions.push(exam.questions[0]);
  assert.throws(() => api.merge(original, exam), /Invalid/);
});

test('dedicated page loads metadata and offers correct page links from zoom overlays', async () => {
  const keys = ['#exam3-page', '#review', '#status', '#student-netid', '#updated-at'];
  const nodes = Object.fromEntries(keys.map(id => [id, new Element(id)]));
  nodes['#exam3-page'].dataset = {source: '../exam3.json', checkoffs: '../checkoffs.json', pdf: '../exam3.pdf'};
  const body = new Element('body');
  const document = {body, querySelector: id => nodes[id], createElement: tag => new Element(tag),
    createElementNS: (_, tag) => new Element(tag), createDocumentFragment: () => new Element('fragment')};
  const exam = JSON.parse(fs.readFileSync(path.join(__dirname, '../fixtures/exam3/synthetic-student.json')));
  exam.questions[0].images[0].page = 4;
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/exam3-review.js'), 'utf8'), {
    document, window: {}, location: {hash: ''}, fetch: async url => ({ok: true, status: 200,
      json: async () => url === '../exam3.json' ? exam : {student: {netid: 'abc123'}, updated_at: exam.exported_at}})
  });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(nodes['#student-netid'].textContent, 'abc123');
  assert.equal(nodes['#updated-at'].dateTime, exam.exported_at);
  assert.equal(nodes['#status'].textContent, '');
  const all = node => [node, ...node.children.flatMap(all)];
  const rendered = all(nodes['#review']);
  assert.ok(rendered.some(node => node.tag === 'a' && node.href === '../exam3.pdf' && node.textContent === 'Open exam PDF'));
  assert.ok(rendered.some(node => node.textContent === '▸ Show details'));
  assert.ok(rendered.some(node => node.textContent === '▾ Hide details'));
  rendered.find(node => node.className === 'scan-button').click();
  assert.ok(all(body).some(node => node.tag === 'a' && node.href === '../exam3.pdf#page=4'));
  assert.equal(body.children.at(-1).children[0].children.at(-1).textContent, 'Close');
  assert.equal(body.children.at(-1).children[0].children.at(-1).autofocus, true);
  rendered.find(node => node.className === 'plot-button').click();
  const plotDialog = body.children.at(-1);
  assert.ok(all(plotDialog).some(node => node.tag === 'svg'));
  assert.ok(!all(plotDialog).some(node => node.tag === 'a'));
  assert.equal(plotDialog.children[0].children.at(-1).textContent, 'Close');
});

for (const unavailableStatus of [403, 404]) test(`direct review URL with JSON status ${unavailableStatus} exposes no exam content, even with a question hash`, async () => {
  const keys = ['#exam3-page', '#review', '#status', '#student-netid', '#updated-at'];
  const nodes = Object.fromEntries(keys.map(id => [id, new Element(id)]));
  nodes['#exam3-page'].dataset = {source: '../exam3.json', checkoffs: '../checkoffs.json', pdf: '../exam3.pdf'};
  const requests = [];
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/exam3-review.js'), 'utf8'), {
    document: {querySelector: id => nodes[id]}, window: {}, location: {hash: '#q2'},
    fetch: async url => {
      requests.push(url);
      if (url === '../exam3.json') return {status: unavailableStatus, ok: false};
      return {status: 200, ok: true, json: async () => ({student: {netid: 'abc123'}, updated_at: '2026-11-11T15:00:00Z'})};
    }
  });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(nodes['#status'].textContent, 'Exam 3 is not available yet.');
  assert.equal(nodes['#review'].children.length, 0, 'No results, scans, plots, question links, or PDF link');
  assert.deepEqual(requests.sort(), ['../checkoffs.json', '../exam3.json']);
});

test('distribution summary has filled bins, step CDFs, axes and explicit titles without tables', () => {
  const window = {};
  const document = {createElement: tag => new Element(tag), createElementNS: (_, tag) => new Element(tag),
    createDocumentFragment: () => new Element('fragment'), querySelector: () => null};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/exam3-review.js'), 'utf8'), {document, window});
  const root = new Element('root');
  window.Exam3Review.render({schema_version: 1, exam: 3, questions: [{id: 'q7', title: 'Synthetic', normal_credit: 'met', answers: [], parts: [
    {label: '7.2', plots: [
      {kind: 'joint', x_labels: ['unused']},
      {id: 'poisson-3-histogram', kind: 'histogram', title: 'Poisson(3)', discrete: true, edges: [-.5, .5, 1.5], density: [.4, .6], expected: [[0, .3], [1, .7]], sample_count: 1000},
      {id: 'poisson-3-cdf', kind: 'cdf', title: 'Poisson(3)', discrete: true, observed: [[0, .4], [1, 1]], expected: [[0, .3], [1, 1]], domain: [0, 1]}
    ]}]}]}, root);
  const all = node => [node, ...node.children.flatMap(all)];
  const nodes = all(root);
  assert.ok(!nodes.some(n => n.tag === 'table'));
  assert.ok(nodes.some(n => n.textContent === 'Poisson(3) · Histogram'));
  assert.ok(nodes.some(n => n.textContent === 'Poisson(3) · CDF'));
  assert.ok(nodes.some(n => n.textContent === 'Cumulative probability · P(X ≤ x)'));
  assert.equal(nodes.filter(n => n.tag === 'rect' && n.attributes.fill === '#2666b5').length, 2);
  const svgs = nodes.filter(n => n.tag === 'svg');
  const curves = all(svgs[1]).filter(n => n.tag === 'path' && ['#2666b5', '#d07822'].includes(n.attributes.stroke) && n.attributes.d.startsWith('M72'));
  assert.equal(curves.length, 2);
  assert.ok(curves.every(n => /H.*V/.test(n.attributes.d) && !n.attributes.d.includes('L')));
});
