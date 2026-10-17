// The Compare page's drawing rules (DESIGN's frame r12, R-DAY-DECISION build sheet section 4 and "1440 x 900"): where
// each moment sits on History's line, which times show, where another model's different answer hangs as History's
// dashed branch, and how a sentence keeps a model's name whole and sets words said apart. Pure, so the page only
// places what these return; verify-compare-line.mjs holds them.
import { LAYOUTS } from './history-rows.mjs';

/** Narrower than this, the page takes its 1440 sizes (History's threshold). */
export const NARROW_BELOW = 1700;

/**
 * The page's fixed places at 1920 and at 1440 (margins 120 and 80 on both sides; the sizes are
 * world-ui-record-compare.css's): the head at `headTop`, the answer in words at `sumTop`, History's line at `lineY`,
 * the picked moment opened at `openTop`, `openWidth` wide, and branches on up to `levels` levels. Where the opened
 * moment and the line's end sit depends on the window's width: compareLayout.
 */
export const COMPARE_LAYOUTS = Object.freeze({
  wide: Object.freeze({ narrow: false, margin: LAYOUTS.wide.margin, headTop: 84, headWidth: 1100, sumTop: 300, lineY: LAYOUTS.wide.lineY, openTop: 300, openWidth: 540, levels: 3 }),
  narrow: Object.freeze({ narrow: true, margin: LAYOUTS.narrow.margin, headTop: 84, headWidth: 1280, sumTop: 260, lineY: LAYOUTS.narrow.lineY, openTop: 260, openWidth: 420, levels: 2 }),
});

/** The line ends this far before the opened moment; the answer in words, this far. */
const LINE_GAP = 80, SUM_GAP = 40;

/**
 * The layout for a page `width` wide: the opened moment always ends a margin from the right edge (1260 at 1920, 1068 at
 * 1728, 940 at 1440), the line ends 80 before it and the answer in words 40 before it, and the head keeps within the
 * margins. Nothing the page draws runs past the window, whose overflow is hidden.
 */
export function compareLayout(width) {
  const base = width < NARROW_BELOW ? COMPARE_LAYOUTS.narrow : COMPARE_LAYOUTS.wide;
  const openLeft = Math.round(width - base.margin - base.openWidth);
  return Object.freeze({
    ...base,
    width,
    openLeft,
    lineTo: Math.max(base.margin + 2 * INSET, openLeft - LINE_GAP),
    sumWidth: Math.max(0, openLeft - SUM_GAP - base.margin),
    headWidth: Math.max(0, Math.min(base.headWidth, width - 2 * base.margin)),
  });
}

/** The first moment sits this far in from the line's start; the newest sits at its end. */
const INSET = 12;
/** A time sits this far above the line; two shown times are at least this far apart. */
export const TIME_ABOVE = 36;
const TIME_GAP = 64;
/** A dot's radius, and the picked one's. */
export const DOT = 6, PICKED_DOT = 7;
/** A branch: its first level this far under the line, each further level this much deeper. */
const FIRST_LEVEL = 92, LEVEL_STEP = 120;
/** Its turn's radius, the run after the turn, and where its words begin, all from the dot; its words' top over the run. */
const TURN = 12, RUN = 20, WORDS_FROM = 26, WORDS_ABOVE = 10;
/** Its words are at least this wide; the model's name in Mono 12 never breaks, so a longer name widens them. */
const WORDS_WIDTH = 120, NAME_SIZE = 12, MONO_ADVANCE = 0.6;
/** Two branches' words on one level stay this far apart; a branch's line passes this far clear of other words. */
const WORDS_GAP = 16, CLEAR = 8;
/** A branch whose words have no room runs this far down alone; the picked moment's answers say it at the right. */
const STUB = 34;

const tenth = value => Math.round(value * 10) / 10;

/** Each moment's x on the line, oldest first: the first 12 in from the line's start, the newest at its end. */
export function momentXs(count, layout) {
  const first = layout.margin + INSET;
  if (count <= 1) return count === 1 ? [first] : [];
  const step = (layout.lineTo - first) / (count - 1);
  return Array.from({ length: count }, (_, index) => tenth(first + index * step));
}

/**
 * Which moments show their time, by index, oldest first: the newest and every third before it (every sixth, ninth,
 * ... where three moments are closer than two times can sit), and the oldest unless it sits beside one shown.
 */
export function timeIndexes(xs) {
  const count = xs.length;
  if (!count) return [];
  const spacing = count > 1 ? (xs[count - 1] - xs[0]) / (count - 1) : Infinity;
  let step = 3;
  while (step * spacing < TIME_GAP) step += 3;
  const shown = [];
  for (let index = count - 1; index >= 0; index -= step) shown.unshift(index);
  if (shown[0] !== 0 && xs[shown[0]] - xs[0] >= TIME_GAP) shown.unshift(0);
  return shown;
}

/** How wide a branch's words are with this model's name over them. */
export const branchWidth = name => Math.max(WORDS_WIDTH, Math.ceil(String(name ?? '').length * NAME_SIZE * MONO_ADVANCE));

/** The y of a branch level's run. */
const levelY = (layout, level) => layout.lineY + FIRST_LEVEL + level * LEVEL_STEP;

/** What a placed branch covers on its level: from its dot to its words' far edge. */
const box = (x, side, width) => side === 'right' ? [x, x + WORDS_FROM + width] : [x - WORDS_FROM - width, x];
const covers = ([left, right], x) => left - CLEAR <= x && x <= right + CLEAR;
const overlaps = ([a0, a1], [b0, b1]) => a0 < b1 + WORDS_GAP && b0 < a1 + WORDS_GAP;

/**
 * Where each different answer hangs, as History's dashed branch from its moment's dot: down, a turn, a short run, then
 * the model's name over the answer. `branches` are `{ index, x, width }`. Each is placed newest first, at the shallowest
 * level with room: on the first level its words always read rightwards from its moment; deeper, they may hang left
 * (as near the line's end). Words stay within the line's span, never meet other words on their level, and never sit
 * across another branch's line; a branch with no room runs a short way down alone (`level` null). The order is the
 * moments', so moving the picked moment never moves a branch.
 */
export function branchPlaces(branches, layout) {
  const placed = [];
  const sides = level => level === 0 ? ['right'] : ['right', 'left'];
  for (const branch of [...branches].sort((a, b) => b.index - a.index)) {
    let place = null;
    for (let level = 0; level < layout.levels && !place; level += 1) {
      for (const side of sides(level)) {
        const span = box(branch.x, side, branch.width);
        if (span[0] < layout.margin || span[1] > layout.lineTo) continue;
        const clash = placed.some(other => other.level !== null && (
          (other.level === level && overlaps(other.box, span))
          || (other.level > level && covers(span, other.x))
          || (other.level < level && covers(other.box, branch.x))));
        if (!clash) { place = { level, side, box: span }; break; }
      }
    }
    placed.push({ index: branch.index, x: branch.x, width: branch.width, level: place?.level ?? null, side: place?.side ?? null, box: place?.box ?? null });
  }
  const top = layout.lineY + DOT + 1;
  return placed.sort((a, b) => a.index - b.index).map(({ index, x, width, level, side }) => {
    if (level === null) return { index, x, level, side, path: `M ${x} ${top} L ${x} ${top + STUB}`, left: null, top: null, width };
    const y = levelY(layout, level), towards = side === 'right' ? 1 : -1;
    const path = `M ${x} ${top} L ${x} ${y - TURN} Q ${x} ${y} ${tenth(x + towards * TURN)} ${y} L ${tenth(x + towards * RUN)} ${y}`;
    const left = side === 'right' ? tenth(x + WORDS_FROM) : tenth(x - WORDS_FROM - width);
    return { index, x, level, side, path, left, top: y - WORDS_ABOVE, width };
  });
}

/**
 * A sentence's parts with each model's name kept whole: "Qwen3 235B Instruct chose as Nemotron 3 Nano 30B did ..." is
 * `[{ model: 'Qwen3 235B Instruct' }, ' chose as ', { model: 'Nemotron 3 Nano 30B' }, ' did ...']`. The longest name
 * wins where one starts another ("Nemotron 3 Nano 30B, again").
 */
export function nameParts(text, names) {
  const known = [...new Set(names.filter(name => typeof name === 'string' && name))].sort((a, b) => b.length - a.length);
  const parts = [];
  let rest = String(text ?? '');
  while (rest) {
    let at = -1, name = '';
    for (const candidate of known) {
      const found = rest.indexOf(candidate);
      if (found !== -1 && (at === -1 || found < at)) { at = found; name = candidate; }
    }
    if (at === -1) { parts.push(rest); break; }
    if (at > 0) parts.push(rest.slice(0, at));
    parts.push({ model: name });
    rest = rest.slice(at + name.length);
  }
  return parts;
}

/** An answer's parts, words said apart: "Said to Ines: “Calm water today, Ines.”" is the plain lead, then the quote. */
export function saidParts(words) {
  const parts = [];
  let last = 0;
  for (const match of String(words ?? '').matchAll(/“[^”]*”/gu)) {
    if (match.index > last) parts.push({ words: words.slice(last, match.index), said: false });
    parts.push({ words: match[0], said: true });
    last = match.index + match[0].length;
  }
  if (last < String(words ?? '').length) parts.push({ words: String(words).slice(last), said: false });
  return parts;
}
