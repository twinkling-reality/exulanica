import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { OPENING_HANDOFF_KEY } from './opening-steps.mjs';

// How the workspace moves (world-motion.css, DESIGN's motion catalog). The opening runs while the world loads on the
// main thread, so what moves there moves by transform, opacity and filter only, which the compositor carries; a
// motion named by the shared sheet keeps to those too, since any page may name it. Pages name motion by its tokens.
const read = (name) => readFileSync(new URL(name, import.meta.url), 'utf8').replace(/\/\*[\s\S]*?\*\//gu, '');
const motion = read('./world-motion.css'), ui = read('./world-ui.css'), door = read('./front-door.css');
const SMOOTH = new Set(['transform', 'opacity', 'filter', 'scale', 'translate']);

/** Each @keyframes block's name and the properties its frames set. */
function keyframes(sheet) {
  const found = new Map();
  for (const [, name, body] of sheet.matchAll(/@keyframes\s+([\w-]+)\s*\{((?:[^{}]*\{[^{}]*\})*)\s*\}/gu)) {
    found.set(name, new Set([...body.matchAll(/([\w-]+)\s*:/gu)].map((one) => one[1])));
  }
  return found;
}
const shared = keyframes(motion);
assert.ok(shared.size >= 6, 'the shared sheet names its motions');
for (const [name, properties] of shared) {
  for (const property of properties) assert.ok(SMOOTH.has(property), `${name} animates ${property}`);
}

// The opening's own rules: every transition moves only what the compositor carries, and every animation is one of the
// shared motions.
const rules = [...ui.matchAll(/([^{}]+)\{([^{}]*)\}/gu)].filter(([, selector]) => selector.includes('.wu-opening'));
assert.ok(rules.length >= 10, 'the opening has its rules');
for (const [, selector, body] of rules) {
  for (const [, value] of body.matchAll(/(?:^|;)\s*transition\s*:([^;]+)/gu)) {
    for (const part of value.split(',')) assert.ok(SMOOTH.has(part.trim().split(/\s+/u)[0]) || part.trim() === 'none', `${selector.trim()} transitions ${part.trim()}`);
  }
  for (const [, value] of body.matchAll(/(?:^|;)\s*animation(?:-name)?\s*:([^;]+)/gu)) {
    const name = value.trim().split(/\s+/u).find((word) => /^wu-/u.test(word));
    if (name !== undefined) assert.ok(shared.has(name), `${selector.trim()} plays ${name}, which the shared sheet does not name`);
  }
}

// Curves come from the tokens: the in-world sheet and the front door write none of their own.
for (const [name, sheet] of [['world-ui.css', ui], ['front-door.css', door]]) {
  assert.deepEqual(sheet.match(/cubic-bezier\([^)]*\)/gu) ?? [], [], `${name} writes its own curve`);
}

// Rule 9: a world's address paints the opening's ground from its first frame (index.html), never the page's own white
// or words, with the picture the front door handed over; the page's script reads that handover by the opening's own key
// and leaves scene previews alone, as the opening does (front-door-routes.mjs).
const page = readFileSync(new URL('../../../web/packages/app/index.html', import.meta.url), 'utf8');
assert.ok(page.includes(`sessionStorage.getItem('${OPENING_HANDOFF_KEY}')`), 'the first frame reads the opening\'s handover');
for (const preview of ["address.get('capture') !== '1'", "address.get('livePreview') !== '1'"]) assert.ok(page.includes(preview), preview);
assert.match(page, /html\[data-opening\] \{ background: #0c1216 /u);
