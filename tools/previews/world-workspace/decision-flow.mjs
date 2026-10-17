// A decision's flow on its record page (DESIGN's r10, the R-DAY-DECISION build sheet's section 2 and its 1440 rules),
// read left to right: what the model was told, gathered by a thin bracket into one line; the decision's ring; the
// choices fanned out to a column (at most twelve drawn, more scrolled a whole row at a time); the taken one's line
// running on to the moment's card. Pure numbers and SVG path strings at 1920 by 1080 and 1440 by 900; decision-page.ts
// draws them and verify-decision-flow.mjs holds them.

/** Narrower than this, the page takes its 1440 sizes (History's rule). */
export const NARROW_BELOW = 1700;

/**
 * The two sizes, for windows of their own height; flowLayout fits a shorter or taller one. `headWidth` is the widest the
 * head runs, clear of the card; `told.foot` how far above the window's bottom the told column stops (it scrolls past
 * that); `ring.y` the middle of the column of drawn choices, so the fan opens evenly, raised where a short window would
 * put the rows into the keys; `card.line` how far down the card the taken row's line meets it (r10: 102 of 170);
 * `card.top` the highest the card goes, clear of the head, and `card.block` its picture and words, kept above the keys.
 */
export const FLOW_LAYOUTS = Object.freeze({
  wide: Object.freeze({
    width: 1920, height: 1080, margin: 120, headTop: 84, headWidth: 1220, title: 56,
    told: Object.freeze({ left: 120, top: 300, width: 470, foot: 60 }),
    bracket: Object.freeze({ gap: 22, depth: 8, from: 20, run: 48, out: 26, into: 24 }),
    ring: Object.freeze({ x: 740, y: 614, r: 22, core: 8, caption: 36 }),
    column: 852, words: 16, gap: 44, shown: 12, over: 46,
    fan: Object.freeze({ out: 38, into: 40 }),
    card: Object.freeze({ x: 1380, width: 300, height: 170, line: 102, top: 240, block: 355, orb: 52, text: 330 }),
    keys: Object.freeze({ right: 100, bottom: 40 }),
  }),
  narrow: Object.freeze({
    width: 1440, height: 900, margin: 80, headTop: 84, headWidth: 980, title: 48,
    told: Object.freeze({ left: 80, top: 260, width: 370, foot: 48 }),
    bracket: Object.freeze({ gap: 22, depth: 8, from: 20, run: 48, out: 26, into: 24 }),
    ring: Object.freeze({ x: 600, y: 512, r: 22, core: 8, caption: 36 }),
    column: 712, words: 16, gap: 38, shown: 12, over: 46,
    fan: Object.freeze({ out: 38, into: 40 }),
    card: Object.freeze({ x: 1100, width: 260, height: 148, line: 89, top: 200, block: 335, orb: 46, text: 260 }),
    keys: Object.freeze({ right: 64, bottom: 32 }),
  }),
});

/** The layout for a window this wide. */
export const flowSize = width => (width < NARROW_BELOW ? FLOW_LAYOUTS.narrow : FLOW_LAYOUTS.wide);

const n = value => (Number.isInteger(value) ? String(value) : value.toFixed(1));
const clamp = (value, low, high) => Math.max(low, Math.min(high, value));

/** A curve leaving (x0, y0) level and arriving at (x1, y1) level; `out` and `into` are its handles' lengths. */
export function bend(x0, y0, x1, y1, out, into) {
  return `M ${n(x0)} ${n(y0)} C ${n(x0 + out)} ${n(y0)}, ${n(x1 - into)} ${n(y1)}, ${n(x1)} ${n(y1)}`;
}

/** A straight line. */
export function run(x0, y0, x1, y1) {
  return `M ${n(x0)} ${n(y0)} L ${n(x1)} ${n(y1)}`;
}

/** The told column's type (sheet section 2): its label and the gap under it, a section's gap, name and words. */
export const TOLD = Object.freeze({ label: 13, labelGap: 20, sectionGap: 18, name: 16.9, nameGap: 4, line: 23.2 });
/** IBM Plex Sans's average advance: the told words at 16px, a choice at 17px in 500; the Chosen tag and a row's number. */
const TOLD_CHARACTER = 8, CHOICE_CHARACTER = 8.3, TAG = 55, NUMBER = 12, ROW_GAP = 12;

const wrapped = (words, width) => Math.max(1, Math.ceil(words.length * TOLD_CHARACTER / width));

/**
 * The told column's height where the page cannot measure it (before layout, or without one): `sections` holds each
 * section's blocks of words, each block starting on its own line and wrapping at `width`. Nothing told is 0.
 */
export function toldHeight(sections, width) {
  if (!sections?.length) return 0;
  let height = TOLD.label + TOLD.labelGap;
  sections.forEach((blocks, at) => {
    const lines = blocks.reduce((sum, block) => sum + wrapped(block, width), 0);
    height += (at ? TOLD.sectionGap : 0) + TOLD.name + TOLD.nameGap + lines * TOLD.line;
  });
  return height;
}

/**
 * The head's type (sheet section 2): the over line (Mono 14, one line), the 14px gap and the title's lines (Sans 200 at
 * the size's title, 1.05, at most two), the 16px gap and the small print (15/1.4, one line); and the least gap between
 * the head and what the model was told.
 */
export const HEAD = Object.freeze({ over: 14, overGap: 14, leading: 1.05, most: 2, byGap: 16, by: 21, gap: 24 });
/** IBM Plex Sans 200's average advance, as a share of its size. */
const TITLE_CHARACTER = 0.47;

/** How many lines the title takes in the head's width, where the page cannot measure it: one or two (it is cut at two). */
export function titleLines(layout, words) {
  const length = String(words ?? '').length;
  if (!length) return 0;
  return Math.min(HEAD.most, Math.ceil(length * TITLE_CHARACTER * layout.title / layout.headWidth));
}

/** Where the head ends: its over line, its title's lines (two at most) and its small print, each only where it is drawn. */
export function headBottom(layout, { over = true, lines = 1, by = true } = {}) {
  return layout.headTop + (over ? HEAD.over : 0) + HEAD.overGap + Math.min(HEAD.most, lines) * layout.title * HEAD.leading + (by ? HEAD.byGap + HEAD.by : 0);
}

/** A key cap's height (History's caps), and the space kept above the key row. */
export const CAP = 21, ABOVE_KEYS = 24;
/** Half a choice row's height. */
const ROW_HALF = 12;

/** The widest a choice row runs: up to 48px short of the card, its words cut with an ellipsis past that. */
export const rowMost = layout => layout.card.x - 48 - (layout.column + layout.words);

/** Where a choice row's words (and the taken one's Chosen tag) end, where the page cannot measure them. */
export function choiceEnd(layout, words, taken) {
  const width = NUMBER + ROW_GAP + Math.round(String(words).length * CHOICE_CHARACTER) + (taken ? ROW_GAP + TAG : 0);
  return layout.column + layout.words + Math.min(width, rowMost(layout));
}

/**
 * The flow for `layout` in a window `height` tall (the size's own by default): `count` choices, `taken` the index of the
 * taken one (-1 where none is), `offset` the first row the column shows (null: the window that first shows the taken
 * one), `toldHeight` the told column's height (null or 0 where nothing was told), `takenEnd` the x where the taken row's
 * words end, `headBottom` where the head ends (null: the size's own place for what was told).
 *
 * Returns what was told's place (below the head, stopping above the window's foot) and the stored record's (from there
 * to above the keys), the bracket and its line into the ring (null with nothing told), the ring and its words' place,
 * the column's label place, the drawn rows (each its index, y, curve and end dot), the window (offset, home, how many
 * lie above and below), the taken one's lit curve (to its row, or to the column's edge toward it while it is scrolled
 * out of view), the card's place, the line on to the card, and where the down arrow's cap sits.
 */
export function flowLayout(layout, { count, taken = -1, offset = null, toldHeight: told = null, takenEnd = null, height = layout.height, headBottom: headEnd = null }) {
  const { card, gap } = layout;
  const shown = Math.min(Math.max(0, count), layout.shown);
  const most = Math.max(0, count - layout.shown);
  const home = taken >= layout.shown ? Math.min(most, taken - layout.shown + 1) : 0;
  const first = clamp(offset ?? home, 0, most);
  const keysTop = height - layout.keys.bottom - CAP;
  const toldTop = headEnd === null ? layout.told.top : Math.max(layout.told.top, Math.ceil(headEnd + HEAD.gap));
  const toldMost = Math.max(120, height - layout.told.foot - toldTop);
  // A short window raises the ring until its lowest row clears the keys.
  const ring = { ...layout.ring, y: Math.min(layout.ring.y, Math.floor(keysTop - ABOVE_KEYS - ROW_HALF - (shown - 1) * gap / 2)) };
  const top = ring.y - (shown - 1) * gap / 2;
  const from = { x: ring.x + ring.r, y: ring.y };
  const rows = [];
  for (let at = 0; at < shown; at += 1) {
    const index = first + at, y = top + at * gap, lit = index === taken;
    rows.push({ index, y, taken: lit, path: bend(from.x, from.y, layout.column, y, layout.fan.out, layout.fan.into), end: { x: layout.column, y, r: lit ? 4 : 3.5 } });
  }
  const last = top + (shown - 1) * gap;
  const seen = rows.find(row => row.taken) ?? null;

  let bracket = null;
  if (told && told > 0) {
    const tip = layout.told.left + layout.told.width + layout.bracket.gap, spine = tip + layout.bracket.depth;
    const high = toldTop + layout.bracket.from;
    const low = Math.max(high + 24, toldTop + Math.min(told, toldMost) - 2);
    const middle = (high + low) / 2, straight = spine + layout.bracket.run;
    bracket = {
      path: `M ${n(tip)} ${n(high)} L ${n(spine)} ${n(high)} L ${n(spine)} ${n(low)} L ${n(tip)} ${n(low)}`,
      into: `M ${n(spine)} ${n(middle)} L ${n(straight)} ${n(middle)} C ${n(straight + layout.bracket.out)} ${n(middle)}, ${n(ring.x - ring.r - layout.bracket.into)} ${n(ring.y)}, ${n(ring.x - ring.r)} ${n(ring.y)}`,
    };
  }

  // The card keeps the place the taken row first had, so scrolling the column never moves it.
  const homeY = taken >= 0 && taken < count ? top + (taken - home) * gap : ring.y;
  const lowest = Math.max(card.top, keysTop - ABOVE_KEYS - card.block);
  const cardTop = clamp(homeY - card.line, card.top, lowest);
  const meet = y => clamp(y, cardTop + 16, cardTop + card.height - 16);
  const onTo = (x, y) => (meet(y) === y ? run(x, y, card.x, y) : bend(x, y, card.x, meet(y), (card.x - x) / 2, (card.x - x) / 2));

  let lit = null, onward = null;
  if (seen) {
    lit = seen.path;
    const end = Math.min(takenEnd ?? choiceEnd(layout, '', true), layout.column + layout.words + rowMost(layout));
    onward = onTo(Math.round(end), seen.y);
  } else if (taken >= 0 && taken < count && shown) {
    // Scrolled out of view: the lit curve points to the column's edge on the taken one's side.
    lit = bend(from.x, from.y, layout.column, taken < first ? top - gap / 2 : last + gap / 2, layout.fan.out, layout.fan.into);
  } else if (!count) {
    // No choices recorded: the decision's own line runs on to the card.
    onward = onTo(from.x, from.y);
  }

  return {
    told: { left: layout.told.left, top: toldTop, width: layout.told.width, most: toldMost },
    record: { left: layout.margin, top: toldTop, width: layout.width - 2 * layout.margin, height: Math.max(120, keysTop - ABOVE_KEYS - toldTop) },
    bracket,
    ring: { x: ring.x, y: ring.y, r: ring.r, core: ring.core },
    caption: { x: ring.x, y: ring.y + ring.caption },
    over: { x: layout.column + layout.words, y: top - layout.over },
    rows,
    offset: first, home, above: first, below: Math.max(0, count - first - shown),
    lit, onward,
    card: { x: card.x, top: cardTop, width: card.width, height: card.height, text: card.text, orb: card.orb },
    down: { x: layout.column + layout.words, y: last + gap / 2 },
  };
}
