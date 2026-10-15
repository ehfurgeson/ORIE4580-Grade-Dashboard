// Verify the standalone page against the independent Python grading implementation.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {spawnSync} = require('node:child_process');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'static/grade_calculator/index.html'), 'utf8');
const context = vm.createContext({});
vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1], context);
const evaluate = rows => JSON.parse(JSON.stringify(context.evaluate(rows)));
assert.deepEqual(evaluate([{green:0,purple:0,shiny:0}]).totals, [0,0,0,2]);
assert.deepEqual(evaluate([{green:9,purple:3,shiny:4}]).totals, [1,6,4,0]);
assert.deepEqual(evaluate([{green:0,purple:0,shiny:4},{green:0,purple:0,shiny:0}]).totals, [1,4,4,2]);
const scenarios = [
  [{green:0,purple:2,shiny:0},{green:0,purple:1,shiny:0},{green:2,purple:0,shiny:0},{green:1,purple:0,shiny:0},{green:0,purple:0,shiny:0}],
  [{green:0,purple:1,shiny:0},{green:0,purple:1,shiny:0},{green:0,purple:1,shiny:0},{green:2,purple:0,shiny:0},{green:1,purple:0,shiny:0}],
  [{green:0,purple:1,shiny:0},{green:0,purple:1,shiny:0},{green:2,purple:0,shiny:0},{green:2,purple:0,shiny:0},{green:0,purple:0,shiny:0}],
];
// Deterministic varied records, including n=1 and fractional cutoff boundaries.
let seed = 4580;
function random() { seed = (Math.imul(seed,1664525)+1013904223) >>> 0; return seed; }
for (let n = 1; n <= 30; n++) {
  for (let j = 0; j < 80; j++) {
    scenarios.push(Array.from({length:n}, () => ({green:(random() >>> 16)%4,purple:(random() >>> 16)%4,shiny:(random() >>> 16)%4})));
  }
}
const reference = spawnSync('python3', ['-c', `
import json, sys
from sync.grading import summarize
results = []
for rows in json.load(sys.stdin):
    standards = []
    for row in rows:
        opportunities = [{'kind': kind, 'status': 'complete'} for key, kind in [('green', 'green'), ('purple', 'purple'), ('shiny', 'shiny_purple')] for _ in range(row[key])]
        standards.append({'opportunities': opportunities})
    results.append(summarize({'standards': standards}))
json.dump(results, sys.stdout)
`], {cwd:root, input:JSON.stringify(scenarios), encoding:'utf8', maxBuffer:8*1024*1024});
assert.equal(reference.status, 0, reference.stderr);
const grades = new Set();
JSON.parse(reference.stdout).forEach((expected,i) => {
  const actual = evaluate(scenarios[i]);
  assert.deepEqual(actual.totals,[expected.purple_standards,expected.purple,expected.shiny,expected.missing]);
  assert.equal(actual.grade, expected.estimated_grade?.replace('−','-') || 'C- or below — instructor’s discretion');
  grades.add(actual.grade);
});
assert.equal(grades.size, 9, 'Exercise every grade including the fallback');
console.log(`Passed ${scenarios.length} comparisons with Python grading; all grade outcomes covered.`);
