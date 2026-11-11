const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const css = fs.readFileSync(path.join(root, 'static/checkmarks.css'), 'utf8');

test('tick and sparkle use centered vector geometry at every display size', () => {
  const symbols = [...css.matchAll(/--mark-symbol: url\("([^"\n]+)"\)/g)].map(match => decodeURIComponent(match[1]));
  assert.equal(symbols.length, 2);
  for (const symbol of symbols) {
    assert.match(symbol, /viewBox='0 0 24 24'/);
    const d = symbol.match(/d='([^']+)'/)[1];
    const coordinates = d.match(/\d+(?:\.\d+)?/g).map(Number);
    const xs = coordinates.filter((_, index) => index % 2 === 0);
    const ys = coordinates.filter((_, index) => index % 2 === 1);
    for (const size of [20, 21.6, 24, 28, 60.8]) {
      assert.equal((Math.min(...xs) + Math.max(...xs)) / 2 / 24 * size, size / 2);
      assert.equal((Math.min(...ys) + Math.max(...ys)) / 2 / 24 * size, size / 2);
    }
  }
  assert.match(css, /mask: var\(--mark-symbol\) center \/ 100% 100% no-repeat/);
  assert.match(css, /border: calc\(var\(--checkmark-size\)/, 'Earned marks retain their colored rim');
  assert.match(symbols[1], /[CQ]/, 'Sparkle has softly curved sides');
  assert.doesNotMatch(css, /animation:|@keyframes/, 'Marks remain static');
});

test('standalone calculator embeds exactly the same styles without an external stylesheet', () => {
  const html = fs.readFileSync(path.join(root, 'static/grade_calculator/index.html'), 'utf8');
  const embedded = html.match(/<!-- BEGIN SHARED CHECKMARK CSS -->\s*<style>\n([\s\S]*?)<\/style>/)[1];
  assert.equal(embedded.trim(), css.trim());
  assert.doesNotMatch(html, /<link[^>]+rel=["']stylesheet/);
  assert.doesNotMatch(html, /<svg/, 'Calculator must not retain its old independent sparkle');
});
