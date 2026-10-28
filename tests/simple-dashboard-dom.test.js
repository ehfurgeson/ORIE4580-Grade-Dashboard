"use strict";

const assert = require("assert");
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync("static/simple-dashboard.js", "utf8");

class Element {
  constructor(tag = "div") {
    this.tag = tag;
    this.children = [];
    this.hidden = false;
    this.textContent = "";
    this.className = "";
    this.attributes = {};
    this.dataset = {};
    this.listeners = {};
    this.classList = { add: name => { this.className += ` ${name}`; } };
  }
  append(...children) {
    children.forEach(child => {
      if (child.parent) child.remove();
      child.parent = this;
    });
    this.children.push(...children);
  }
  prepend(...children) { this.children.unshift(...children); }
  setAttribute(name, value) { this.attributes[name] = value; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  remove() { this.parent.children = this.parent.children.filter(child => child !== this); }
  querySelectorAll(selector) {
    const descendants = this.children.flatMap(child => [child, ...child.querySelectorAll('*')]);
    return descendants.filter(child => selector === '*' ||
      (selector === '.staff-private' ? child.className.split(' ').includes('staff-private') : child.tag === selector));
  }
}

function elements() {
  const selectors = [
    "#status", "#dashboard", ".summary-strip span", "#dashboard-description",
    "#completion-note", "#student-netid", "#worksheet", "#updated-at",
    "#unmapped-columns-section", "#unmapped-columns", "#checkmark-overview",
    "#standards", "#earned-total"
  ];
  return Object.fromEntries(selectors.map(selector => [selector, new Element()]));
}

function payload(version, pending) {
  return {
    schema_version: version,
    updated_at: "2026-09-17T12:00:00Z",
    worksheet: "Lab Checkoffs",
    student: { netid: "abc123" },
    unmapped_columns: pending,
    standards: ["S1", "S2", "S3", "S4", "S5", "S6", "S7"].map(id => ({
      id, name: `Standard ${id}`, checkmarks: []
    }))
  };
}

async function run(data, { legacyTemplate = false } = {}) {
  const nodes = elements();
  nodes["#dashboard"].hidden = true;
  nodes["#unmapped-columns-section"].hidden = true;
  if (legacyTemplate) {
    delete nodes["#unmapped-columns-section"];
    delete nodes["#unmapped-columns"];
  }
  const context = {
    window: {},
    document: {
      querySelector(selector) {
        if (selector === '#staff-index') return null;
        if (selector === "#unmapped-columns-section" || selector === "#unmapped-columns") {
          return nodes[selector] || null;
        }
        assert(nodes[selector], `unexpected selector: ${selector}`);
        return nodes[selector];
      },
      createElement(tag) { return new Element(tag); }
    },
    fetch: async () => ({ ok: true, json: async () => data }),
    console,
    setTimeout,
  };
  vm.runInNewContext(source, context, { filename: "simple-dashboard.js" });
  await new Promise(resolve => setImmediate(resolve));
  return nodes;
}

async function checkStaffIndex(withNames = false) {
  const root = new Element();
  const controls = Object.fromEntries([
    '#student-search', '#toggle-checkmarks', '#staff-status', '#student-count', '#no-students'
  ].map(id => [id, new Element()]));
  const headings = ['S1', 'S2'].map(id => {
    const element = new Element('th');
    element.dataset.standard = id;
    element.className = 'staff-private';
    element.hidden = true;
    return element;
  });
  const rows = ['abc123', 'xy99'].map(netid => {
    const row = new Element('tr');
    row.dataset.netid = netid;
    return row;
  });
  if (withNames) {
    rows.forEach((row, index) => {
      row.dataset.firstName = ['Zoe', 'Alice'][index];
      row.dataset.lastName = ['Adams', 'Brown'][index];
      const first = new Element('td');
      first.textContent = row.dataset.firstName;
      const last = new Element('td');
      last.textContent = row.dataset.lastName;
      row.append(first, last);
    });
  }
  const body = new Element('tbody');
  body.append(...rows);
  const allHeaders = [new Element('th'), new Element('th'), new Element('th'), ...headings, new Element('th')];
  if (withNames) {
    const keys = ['netid', 'purple', 'missing', 'S1', 'S2', 'shiny'];
    allHeaders.forEach((header, index) => { header.dataset.sort = keys[index]; });
    const names = ['firstName', 'lastName'].map(key => {
      const header = new Element('th');
      header.dataset.sort = key;
      return header;
    });
    allHeaders.splice(1, 0, ...names);
  }
  root.append(...allHeaders, body);
  root.querySelector = selector => selector === 'tbody' ? body : controls[selector];
  const descendants = root.querySelectorAll.bind(root);
  root.querySelectorAll = selector => selector === 'tbody tr' ? rows
    : selector === '[data-standard]' ? headings
      : selector === 'thead th' ? allHeaders : descendants(selector);
  const doc = new Element();
  doc.querySelector = selector => selector === '#staff-index' ? root : null;
  doc.createElement = tag => new Element(tag);
  const win = new Element();
  const requests = [];
  let finishRequest;
  const waiting = new Promise(resolve => { finishRequest = resolve; });
  const data = payload(6, []);
  data.standards = data.standards.slice(0, 2);
  data.standards[0].checkmarks = ['purple', 'purple', 'purple', 'shiny_purple'].map((kind, index) => ({
    kind, status: 'complete', label: `Question ${index}`, requirements: [{
      id: 'exam_score', source: 'gradescope_exam', status: 'complete'
    }]
  }));
  vm.runInNewContext(source, {
    window: win, document: doc,
    fetch: async url => {
      requests.push(url);
      await waiting;
      return { ok: !url.includes('xy99'), status: 403, json: async () => data };
    }
  });
  assert.strictEqual(requests.length, 0, 'No grade requests before reveal');
  allHeaders[0].children[0].listeners.click();
  assert.strictEqual(body.children[0].dataset.netid, 'xy99', 'NetID descending');
  allHeaders[0].children[0].listeners.click();
  assert.strictEqual(body.children[0].dataset.netid, 'abc123', 'NetID ascending');
  controls['#toggle-checkmarks'].listeners.click();
  assert.strictEqual(requests.length, 2);
  controls['#toggle-checkmarks'].listeners.click();
  finishRequest();
  await new Promise(resolve => setImmediate(resolve));
  assert(root.querySelectorAll('.staff-private').every(cell => cell.hidden),
    'Requests finishing after Hide must stay hidden');
  const cells = rows[0].querySelectorAll('.staff-private');
  assert.strictEqual(cells[0].textContent, '3', 'Two linked purple plus one shiny overflow; extra purple excluded');
  assert.strictEqual(cells[1].textContent, '2', 'Two unfilled S2 boxes');
  assert.match(rows[1].querySelectorAll('.staff-private')[0].textContent, /Unavailable.*403/);
  controls['#toggle-checkmarks'].listeners.click();
  assert.strictEqual(requests.length, 3, 'Only failed rows are retried');
  allHeaders[withNames ? 3 : 1].children[0].listeners.click();
  assert.strictEqual(allHeaders[withNames ? 3 : 1].attributes['aria-sort'], 'descending');
  assert.strictEqual(body.children[0].dataset.netid, 'abc123', 'Unavailable stays last');
  allHeaders[withNames ? 3 : 1].children[0].listeners.click();
  assert.strictEqual(allHeaders[withNames ? 3 : 1].attributes['aria-sort'], 'ascending');
  assert.strictEqual(body.children[0].dataset.netid, 'abc123', 'Unavailable stays last ascending');
  assert.strictEqual(cells[2].children.length, 1, 'Only linked boxes in standard cells');
  doc.listeners.keydown({ key: 'Escape' });
  assert.strictEqual(allHeaders[0].attributes['aria-sort'], 'ascending', 'Hide resets private ordering');
  assert(root.querySelectorAll('.staff-private').every(cell => cell.hidden));
  controls['#student-search'].value = ' ABC ';
  controls['#student-search'].listeners.input();
  assert.strictEqual(rows[0].hidden, false);
  assert.strictEqual(rows[1].hidden, true);
  assert.strictEqual(controls['#student-count'].textContent, '1 of 2 students');
  controls['#toggle-checkmarks'].listeners.click();
  doc.hidden = true;
  doc.listeners.visibilitychange();
  assert(root.querySelectorAll('.staff-private').every(cell => cell.hidden));
  assert.strictEqual(controls['#toggle-checkmarks'].attributes['aria-expanded'], 'false');
  await new Promise(resolve => setImmediate(resolve));
  if (withNames) {
    assert.strictEqual(rows[0].children[0].textContent, 'Zoe', 'Loading preserves name cells');
    allHeaders[1].children[0].listeners.click();
    assert.strictEqual(body.children[0].dataset.netid, 'xy99', 'First name ascending');
    allHeaders[1].children[0].listeners.click();
    assert.strictEqual(body.children[0].dataset.netid, 'abc123', 'First name descending');
    allHeaders[2].children[0].listeners.click();
    assert.strictEqual(body.children[0].dataset.netid, 'abc123', 'Last name ascending');
    controls['#student-search'].value = 'alice brown';
    controls['#student-search'].listeners.input();
    assert.strictEqual(rows[0].hidden, true);
    assert.strictEqual(rows[1].hidden, false);
  }
}

(async () => {
  await checkStaffIndex();
  await checkStaffIndex(true);
  const hostile = "<img src=x onerror=alert(1)>";
  const current = await run(payload(6, [hostile]));
  assert.strictEqual(current["#unmapped-columns-section"].hidden, false);
  assert.strictEqual(current["#unmapped-columns"].children.length, 1);
  assert.strictEqual(current["#unmapped-columns"].children[0].children[0].textContent, hostile);
  assert.strictEqual(current["#earned-total"].textContent, "0 of 0");
  assert.strictEqual(current["#dashboard"].hidden, false);
  assert(!current["#unmapped-columns"].children[0].children.some(
    child => child.className.includes("checkmark")
  ));

  const explanation = current["#completion-note"].textContent;
  assert.match(explanation, /Exam 1 scores over 0\.8/);
  assert.match(explanation, /Q1 at least 4 of 5, Q2 at least 7 of 8, Q3 at least 5 of 6/);
  assert.match(explanation, /Q8 earns one shiny-purple mark for all 4 parts correct/);
  assert.match(explanation, /parts 8\.1 and 8\.2 correct earn one purple mark/);

  const empty = await run(payload(6, []));
  assert.strictEqual(empty["#unmapped-columns-section"].hidden, true);

  const old = await run(payload(5, ["must be ignored"]));
  assert.strictEqual(old["#unmapped-columns-section"].hidden, true);
  assert.strictEqual(old["#unmapped-columns"].children.length, 0);

  const legacyTemplate = await run(payload(5, ["must be ignored"]), { legacyTemplate: true });
  assert.strictEqual(legacyTemplate["#dashboard"].hidden, false);

  const incompatibleTemplate = await run(payload(6, ["Lab 8 - Q1"]), { legacyTemplate: true });
  assert.match(incompatibleTemplate["#status"].textContent, /does not support pending Sheet mappings/);
  assert.strictEqual(incompatibleTemplate["#dashboard"].hidden, true);

  const malformed = await run(payload(6, ["duplicate", "duplicate"]));
  assert.match(malformed["#status"].textContent, /Pending Sheet mappings are malformed/);
  assert.strictEqual(malformed["#dashboard"].hidden, true);
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
