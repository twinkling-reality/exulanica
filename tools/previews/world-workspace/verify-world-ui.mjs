import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { UI_SCALE, WORLD_UI_TIMING, clampToView, hintsShown, noteDuration, placeBeside, uiScale } from './world-ui-layout.mjs';

// The scale is 1 at the reference viewport, follows the tighter side, and stays within its bounds.
assert.equal(uiScale(1920, 1080), 1);
assert.equal(uiScale(1440, 900), 0.78);
assert.equal(uiScale(1728, 1117), 0.9);
assert.equal(uiScale(3840, 2160), UI_SCALE.most);
assert.equal(uiScale(800, 1080), UI_SCALE.least);
assert.equal(uiScale(0, 0), 1);
assert.equal(uiScale(3840, 2160, { ...UI_SCALE, most: 2 }), 2);

// Anchored parts stay 40 px inside the viewport on every side.
const viewport = { width: 1920, height: 1080 };
assert.deepEqual(clampToView({ x: 900, y: 400 }, { width: 100, height: 50 }, viewport), { x: 900, y: 400 });
assert.deepEqual(clampToView({ x: -30, y: 1070 }, { width: 100, height: 50 }, viewport), { x: 40, y: 990 });
assert.deepEqual(clampToView({ x: 1900, y: 5 }, { width: 100, height: 50 }, viewport), { x: 1780, y: 40 });
assert.deepEqual(clampToView({ x: 1900, y: 5 }, { width: 100, height: 50 }, viewport, 20), { x: 1800, y: 20 });

// The side card sits 80 px right of its subject, centred between head and waist, with the connector
// from the shoulder diagonally to the middle of the gap, then level into the card at its title; at
// the right margin it takes the left side.
const card = { width: 388, height: 300 };
const middle = placeBeside({ left: 900, top: 300, right: 980, bottom: 700, headY: 320, waistY: 520 }, card, viewport);
assert.equal(middle.side, 'right');
assert.equal(middle.x, 1060);
assert.equal(middle.y, 270);
assert.deepEqual(middle.connector.from, { x: 980, y: 370 });
assert.deepEqual(middle.connector.elbow, { x: 1020, y: 362 });
assert.deepEqual(middle.connector.to, { x: 1060, y: 362 });
const nearRight = placeBeside({ left: 1500, top: 300, right: 1580, bottom: 700, headY: 320, waistY: 520 }, card, viewport);
assert.equal(nearRight.side, 'left');
assert.equal(nearRight.x, 1500 - 80 - 388);
assert.equal(nearRight.connector.to.x, nearRight.x + 388);
assert.equal(nearRight.connector.elbow.x, nearRight.x + 388 + 40);
// With no room either side it keeps the right and is held inside the margin.
const wide = placeBeside({ left: 60, top: 300, right: 1860, bottom: 700 }, card, viewport);
assert.equal(wide.side, 'right');
assert.equal(wide.x, 1920 - 40 - 388);
// A tall card near the top is held 40 px down.
assert.equal(placeBeside({ left: 900, top: 0, right: 980, bottom: 200, headY: 10, waistY: 100 }, card, viewport).y, 40);

// Hints show for ten seconds after the world opens, then only for six seconds after a hinted key
// or while held (Tab).
assert.equal(hintsShown(9_999, { since: 0 }), true);
assert.equal(hintsShown(10_000, { since: 0 }), false);
assert.equal(hintsShown(20_000, { since: 0, wokenAt: 15_000 }), true);
assert.equal(hintsShown(21_000, { since: 0, wokenAt: 15_000 }), false);
assert.equal(hintsShown(60_000, { since: 0, held: true }), true);
assert.equal(hintsShown(12_000, { since: 0, fadeAfter: 20_000 }), true);
assert.equal(noteDuration(false), WORLD_UI_TIMING.note);
assert.equal(noteDuration(true), WORLD_UI_TIMING.noteWithPrompt);

// The stylesheet holds the design's tokens once, every part under .wu-root, and no em dash.
const css = readFileSync(new URL('world-ui.css', import.meta.url), 'utf8');
for (const token of ['--ink: #ffffff', '--wash: #a8cbd2', '--live: #bfe9f0', '--refused: #ff8f7e', '--glass-fill: rgba(13, 20, 27, .68)']) {
  assert.equal(css.split(token).length - 1, 1, token);
}
assert.match(css, /prefers-reduced-motion: reduce/u);
assert.match(css, /prefers-reduced-transparency: reduce/u);
assert.match(css, /prefers-contrast: more/u);
assert.doesNotMatch(css, /text-transform:\s*uppercase/u);
for (const file of ['world-ui.css', 'world-ui.ts', 'world-ui-layout.mjs', 'world-ui-parts.ts', 'world-ui-parts.html']) {
  assert.doesNotMatch(readFileSync(new URL(file, import.meta.url), 'utf8'), /\u2014/u, file);
}
// Text under 16 px never scales below 12 px, except a key cap's glyph (DESIGN's ruling L5).
assert.match(css, /\.wu-key \{[^}]*font: 500 max\(9px, calc\(13 \* var\(--u\)\)\)/u);
for (const [, size] of css.matchAll(/(?:font:\s*\d+\s+|font-size:\s*)calc\((\d+(?:\.\d+)?) \* var\(--u\)\)/gu)) {
  assert.ok(Number(size) >= 16, `a ${size} px text scales below 12 px; wrap it in max(12px, ...)`);
}

export default true;
