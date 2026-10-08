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
    this.classList = { add: name => { this.className += ` ${name}`; } };
  }
  append(...children) { this.children.push(...children); }
  prepend(...children) { this.children.unshift(...children); }
  setAttribute(name, value) { this.attributes[name] = value; }
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
    standards: ["S1", "S2", "S3", "S4", "S5"].map(id => ({
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

(async () => {
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

  const empty = await run(payload(6, []));
  assert.strictEqual(empty["#unmapped-columns-section"].hidden, true);

  const old = await run(payload(5, ["must be ignored"]));
  assert.strictEqual(old["#unmapped-columns-section"].hidden, true);
  assert.strictEqual(old["#unmapped-columns"].children.length, 0);

  const legacyTemplate = await run(payload(5, ["must be ignored"]), { legacyTemplate: true });
  assert.strictEqual(legacyTemplate["#dashboard"].hidden, false);

  const incompatibleTemplate = await run(payload(6, ["Lab 6 - Q1"]), { legacyTemplate: true });
  assert.match(incompatibleTemplate["#status"].textContent, /does not support pending Sheet mappings/);
  assert.strictEqual(incompatibleTemplate["#dashboard"].hidden, true);

  const malformed = await run(payload(6, ["duplicate", "duplicate"]));
  assert.match(malformed["#status"].textContent, /Pending Sheet mappings are malformed/);
  assert.strictEqual(malformed["#dashboard"].hidden, true);
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
