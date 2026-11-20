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
  replaceChildren(...children) { this.children = []; this.append(...children); }
  querySelector(selector) { return this.querySelectorAll('*').find(node => selector.startsWith('#') && node.id === selector.slice(1)) || null; }
  closest(tag) { return this.tag === tag ? this : this.parent?.closest(tag); }
  prepend(...children) { this.children.unshift(...children); }
  setAttribute(name, value) { this.attributes[name] = value; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  remove() { this.parent.children = this.parent.children.filter(child => child !== this); }
  querySelectorAll(selector) {
    const descendants = this.children.flatMap(child => [child, ...child.querySelectorAll('*')]);
    return descendants.filter(child => selector === '*' ||
      (selector.startsWith('.') ? child.className.split(' ').includes(selector.slice(1)) : child.tag === selector));
  }
}

function elements() {
  const selectors = [
    "#status", "#dashboard", ".summary-strip span", "#dashboard-description",
    "#completion-note", "#student-netid", "#worksheet", "#updated-at",
    "#unmapped-columns-section", "#unmapped-columns", "#checkmark-overview",
    "#standards", "#earned-total", "#assignment-overview"
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

async function run(data, { legacyTemplate = false, examData = undefined, retryData = null } = {}) {
  const nodes = elements();
  nodes["#dashboard"].hidden = true;
  nodes["#unmapped-columns-section"].hidden = true;
  if (legacyTemplate) {
    delete nodes["#unmapped-columns-section"];
    delete nodes["#unmapped-columns"];
  }
  if (examData !== undefined) {
    nodes['#exam3-section'] = new Element('details');
    nodes['#exam3-review'] = new Element();
    nodes['#exam3-section'].append(nodes['#exam3-review']);
  }
  const context = {
    window: {},
    document: {
      querySelector(selector) {
        if (selector === '#staff-index' || selector === '#file' || selector === '#exam3-page') return null;
        if (selector === "#unmapped-columns-section" || selector === "#unmapped-columns") {
          return nodes[selector] || null;
        }
        assert(nodes[selector], `unexpected selector: ${selector}`);
        return nodes[selector];
      },
      createElement(tag) { return new Element(tag); },
      createElementNS(ns, tag) { return new Element(tag); },
      createDocumentFragment() { return new Element("fragment"); }
    },
    location: {hash: ''},
    fetch: async url => {
      if (url === 'checkoffs.json') return {ok: true, json: async () => data};
      const review = url === 'exam3.json' ? examData : retryData;
      return review === null ? {ok: false, status: 404} : {ok: true, json: async () => review};
    },
    console,
    setTimeout,
  };
  if (examData !== undefined) vm.runInNewContext(fs.readFileSync("static/exam-review.js", "utf8"), context);
  vm.runInNewContext(source, context, { filename: "simple-dashboard.js" });
  await new Promise(resolve => setImmediate(resolve));
  return nodes;
}

async function checkStaffIndex(withRoster = false, supplementFailure = false) {
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
  if (withRoster) {
    const fields = [['Zoe', 'Adams', '5581'], ['Alice', 'Brown', '4580']];
    rows.forEach((row, rowIndex) => {
      for (const value of fields[rowIndex]) {
        const cell = new Element('td');
        cell.className = 'staff-roster-value';
        cell.textContent = value;
        row.append(cell);
      }
    });
  }
  const body = new Element('tbody');
  body.append(...rows);
  const [netidHeader, purpleHeader, missingHeader, shinyHeader] = ['netid', 'purple', 'missing', 'shiny'].map(key => {
    const header = new Element('th');
    header.dataset.sort = key;
    if (key !== 'netid') header.className = 'staff-private';
    return header;
  });
  const allHeaders = [netidHeader, purpleHeader, missingHeader, ...headings, shinyHeader];
  if (withRoster) {
    const rosterHeaders = ['Given Name', 'Family Name', 'Course Section'].map((label, index) => {
      const header = new Element('th');
      header.textContent = label;
      header.dataset.sort = `roster${index}`;
      header.dataset.rosterColumn = '';
      return header;
    });
    allHeaders.splice(1, 0, ...rosterHeaders);
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
  if (supplementFailure) win.Exam3Review = {load: async () => { throw new Error('Network failure'); }};
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
  assert.equal(root.dataset.checkmarksVisible, 'true', 'Staff layout widens when marks are shown');
  controls['#toggle-checkmarks'].listeners.click();
  finishRequest();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(root.dataset.checkmarksVisible, 'false', 'Staff layout contracts when marks are hidden');
  assert(root.querySelectorAll('.staff-private').every(cell => cell.hidden),
    'Requests finishing after Hide must stay hidden');
  const cells = rows[0].querySelectorAll('.staff-private');
  assert.strictEqual(cells[0].textContent, '3', 'Two linked purple plus one shiny overflow; extra purple excluded');
  assert.strictEqual(cells[1].textContent, '2', 'Two unfilled S2 boxes');
  assert.match(rows[1].querySelectorAll('.staff-private')[0].textContent, /Unavailable.*403/);
  controls['#toggle-checkmarks'].listeners.click();
  assert.strictEqual(requests.length, supplementFailure ? 4 : 3, 'Failed and partial rows are retried');
  if (supplementFailure) assert.match(cells[0].children.at(-1).textContent, /Partial results: Exam 3, Exam Retry unavailable/);
  purpleHeader.children[0].listeners.click();
  assert.strictEqual(purpleHeader.attributes['aria-sort'], 'descending');
  assert.strictEqual(body.children[0].dataset.netid, 'abc123', 'Unavailable stays last');
  purpleHeader.children[0].listeners.click();
  assert.strictEqual(purpleHeader.attributes['aria-sort'], 'ascending');
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
  if (withRoster) {
    assert.strictEqual(rows[0].children[0].textContent, 'Zoe', 'Loading preserves name cells');
    allHeaders[1].children[0].listeners.click();
    assert.strictEqual(body.children[0].dataset.netid, 'xy99', 'First name ascending');
    allHeaders[1].children[0].listeners.click();
    assert.strictEqual(body.children[0].dataset.netid, 'abc123', 'First name descending');
    allHeaders[2].children[0].listeners.click();
    assert.strictEqual(body.children[0].dataset.netid, 'abc123', 'Last name ascending');
    assert.strictEqual(rows[0].children[2].textContent, '5581', 'Loading preserves course section cells');
    allHeaders[3].children[0].listeners.click();
    assert.strictEqual(body.children[0].dataset.netid, 'xy99', 'Course section ascending');
    doc.listeners.keydown({ key: 'Escape' });
    assert.strictEqual(allHeaders[3].attributes['aria-sort'], 'ascending', 'Hide preserves course section sorting');
    allHeaders[3].children[0].listeners.click();
    assert.strictEqual(body.children[0].dataset.netid, 'abc123', 'Course section descending');
    controls['#student-search'].value = 'alice brown';
    controls['#student-search'].listeners.input();
    assert.strictEqual(rows[0].hidden, true);
    assert.strictEqual(rows[1].hidden, false);
    controls['#student-search'].value = '5581';
    controls['#student-search'].listeners.input();
    assert.strictEqual(rows[0].hidden, false, 'Search matches values in a custom CSV column');
    assert.strictEqual(rows[1].hidden, true);
  }
}

(async () => {
  const labs89 = payload(6, []);
  labs89.standards.push(...['S8', 'S9'].map(id => ({id, name: `Standard ${id}`, checkmarks: []})));
  const manual = {id: 'manual', label: 'Manual checkoff', source: 'google_sheet', status: 'complete', details: []};
  for (const [sid, id, autograded] of [['S8', 'lab8-q1', false], ['S7', 'lab9-q1', true], ['S9', 'lab9-q2', false]]) {
    labs89.standards.find(s => s.id === sid).checkmarks.push({
      id, label: id, kind: 'green', status: 'complete', requirements: [manual, ...(autograded ? [{
        id: 'autograder', label: 'Autograder', source: 'gradescope', status: 'passed', details: []
      }] : [])]
    });
  }
  const labs89Nodes = await run(labs89);
  assert.strictEqual(labs89Nodes['#dashboard'].hidden, false);
  assert.strictEqual(labs89Nodes['#standards'].children.length, 9);
  assert.strictEqual(labs89Nodes['#earned-total'].textContent, '3 of 3');
  await checkStaffIndex();
  await checkStaffIndex(true);
  await checkStaffIndex(false, true);
  const examData = JSON.parse(fs.readFileSync('fixtures/exam3/synthetic-student.json'));
  const integrated = await run(payload(6, []), {examData});
  assert.equal(integrated['#earned-total'].textContent, '4 of 9');
  assert.equal(integrated['#exam3-review'].children.length, 0, 'Main dashboard does not embed the review');
  assert.equal(integrated['#assignment-overview'].children[0].children[0].children[0].href, 'exam3/');
  const examSlots = integrated['#assignment-overview'].children[0].children[1].children;
  assert.equal(examSlots.length, 9);
  assert.equal(examSlots[0].href, 'exam3/#q1');
  const assignmentData = payload(6, []);
  const examMark = (id, status, kind = 'purple') => ({
    id, label: id, status, kind,
    requirements: [{ id: 'exam_score', source: 'gradescope_exam', status }]
  });
  assignmentData.standards[0].checkmarks = [
    examMark('exam1-q10', 'complete', 'shiny_purple'),
    examMark('exam1-q3', 'not_graded')
  ];
  assignmentData.standards[1].checkmarks = [examMark('exam1-q2', 'incomplete')];
  const assignments = (await run(assignmentData))['#assignment-overview'];
  assert.strictEqual(assignments.children.length, 1, 'Absent exams must not be manufactured');
  assert.strictEqual(assignments.children[0].children[0].textContent, 'Exam 1');
  const slots = assignments.children[0].children[1].children;
  assert.deepStrictEqual(slots.map(slot => slot.children[0].textContent), ['S2', 'S1', 'S1']);
  assert.deepStrictEqual(slots.map(slot => slot.children[1].textContent), ['–', '?', '✦']);
  assert.strictEqual(slots[0].href, '#standard-S2');

  assignmentData.standards[0].checkmarks.push(examMark('exam2-q1', 'complete'), examMark('exam4-q1', 'complete'), {
    id: 'lab1-q1', label: 'Lab 1 · Question 1', kind: 'green', status: 'complete', requirements: [manual]
  });
  const absentExams = await run(assignmentData, {examData: null});
  const assignmentRows = absentExams['#assignment-overview'].children;
  assert.deepStrictEqual(assignmentRows.map(row => row.children[0].textContent),
    ['Exam 1', 'Exam 2', 'Exam 3', 'Exam Retry', 'Exam 4', 'Lab 1']);
  for (const [row, count] of [[assignmentRows[2], 9], [assignmentRows[3], 7]]) {
    const emptySlots = row.children[1].children;
    assert.equal(emptySlots.length, count);
    assert(emptySlots.every(slot => slot.children[1].textContent === '–' && !slot.href));
  }
  assert.equal(absentExams['#earned-total'].textContent, '4 of 6');

  const retryData = {...examData, exam: 'retry', questions: [examData.questions[0]]};
  const reversedStandards = {...assignmentData, standards: [...assignmentData.standards].reverse()};
  const withRetry = await run(reversedStandards, {examData: null, retryData});
  const retryRow = withRetry['#assignment-overview'].children[3];
  assert.equal(retryRow.children[0].children[0].href, 'exam_retry/');
  assert.equal(retryRow.children[1].children.length, 7);
  assert.equal(retryRow.children[1].children[0].href, 'exam_retry/#q1');

  const retryEligibility = payload(6, []);
  retryEligibility.standards[0].checkmarks = [examMark('exam1-q3', 'complete')];
  retryEligibility.standards[1].checkmarks = [examMark('exam2-q12', 'complete', 'shiny_purple')];
  retryEligibility.standards[3].checkmarks = [examMark('exam4-q1', 'complete')];
  retryEligibility.standards[4].checkmarks = [
    examMark('exam2-q5', 'incomplete'), examMark('exam2-q6', 'not_graded'),
    {id: 'lab5-q1', label: 'Lab 5 · Question 1', kind: 'green', status: 'complete', requirements: [manual]}
  ];
  retryEligibility.standards[6].checkmarks = [
    examMark('exam2-q7', 'complete'), examMark('exam2-q10', 'complete'),
    examMark('exam4-q7', 'complete'), examMark('exam4-q8', 'complete', 'shiny_purple'),
    {id: 'lab7-q1', label: 'Lab 7 · Question 1', kind: 'green', status: 'complete', requirements: [manual]}
  ];
  const metQuestion = number => ({...examData.questions[0], id: `q${number}`, standard: `S${number}`});
  const eligibilityNodes = await run(retryEligibility, {
    examData: {...examData, questions: [metQuestion(3), {...metQuestion(5), normal_credit: 'blank'}]},
    retryData: {...retryData, questions: [1, 2, 3, 4, 5, 6].map(metQuestion)}
  });
  const overviewRows = eligibilityNodes['#checkmark-overview'].children.slice(1, 8);
  assert.deepStrictEqual(overviewRows.map(row => row.children[1].children.map(box => box.textContent)),
    [['✓', '–'], ['✦', '–'], ['✓', '–'], ['✓', '✓'], ['✓', '✓'], ['✓', '–'], ['✓', '✓']]);
  const shinyOverflow = eligibilityNodes['#checkmark-overview'].children.at(-1).children[1];
  assert.equal(shinyOverflow.className, 'checkmark shiny_purple');
  assert.match(shinyOverflow.title, /S7: Counts in shiny pool/);
  const eligibilitySlots = eligibilityNodes['#assignment-overview'].children
    .find(row => row.children[0].children[0]?.href === 'exam_retry/').children[1].children;
  for (const slot of eligibilitySlots.slice(0, 3)) {
    assert.match(slot.title, /already has purple credit from Exams 1–3/);
  }
  for (const slot of eligibilitySlots.slice(3, 6)) {
    assert.match(slot.title, /Counts in standard-linked box/);
  }
  for (const selector of ['#checkmark-overview', '#assignment-overview', '#standards']) {
    const fadedMarks = eligibilityNodes[selector].querySelectorAll('*')
      .filter(node => node.className.split(' ').includes('redundant-mark'));
    assert.equal(fadedMarks.length, 5, `Only redundant marks are faded in ${selector}`);
    assert.equal(fadedMarks.filter(node => node.className.split(' ').includes('purple')).length, 4);
    assert.equal(fadedMarks.filter(node => node.className.split(' ').includes('green')).length, 1);
  }
  const standardDetails = eligibilityNodes['#standards'].querySelectorAll('*');
  const statuses = row => row.querySelectorAll('*')
    .filter(node => ['checkoff-status', 'source-requirement-status'].includes(node.className))
    .map(node => node.textContent);
  const checkoff = label => standardDetails.find(node => node.className === 'checkoff-name' && node.textContent === label).parent.parent;
  assert.deepStrictEqual(statuses(checkoff('Exam Retry · Question 1')), ['Purple checkmark earned, but redundant']);
  assert.deepStrictEqual(statuses(checkoff('exam4-q7')), ['Purple checkmark earned, but redundant']);
  assert.deepStrictEqual(statuses(checkoff('exam4-q8')), ['Shiny purple checkmark earned']);
  assert.deepStrictEqual(statuses(checkoff('Exam 3 · Question 5')), ['Blank']);
  assert.deepStrictEqual(statuses(checkoff('Lab 5 · Question 1')), ['Green checkmark earned', 'Complete']);
  assert.deepStrictEqual(statuses(checkoff('Lab 7 · Question 1')), ['Green checkmark earned, but redundant', 'Complete']);

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
  assert.doesNotMatch(explanation, /Unavailable exam scores do not earn a mark/);

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
