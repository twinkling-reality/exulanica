// What a character did on its own page (Teo's day, r06; DESIGN's R-DAY-DECISION build sheet section 1 and "1440 x
// 900"): where the who column, the path and each moment card sit, newest first, at 1920 and at 1440. Pure layout: the
// page (character-page.ts) draws from these numbers and says nothing here; verify-day-rows.mjs holds them to r06.

/** Narrower than this, the page takes its 1440 sizes (History's rule). */
export const NARROW_BELOW = 1700;

/**
 * The page's places in CSS pixels. `left`, `top` and `whoWidth` the who column; `portrait` its round picture and
 * `title` the name's size; `labelX` "What Teo did"; `pathX` the path; `itemX` a card's left edge, `firstTop` the newest
 * card's top and `gap` from one card's top to the next; `picture` a card's picture and `wordsGap` the space before its
 * words; `dotOffset` a dot's centre under its card's top; `pathTop` where the path starts when newer cards are out of
 * view; `keysRight` and `keysBottom` the key row's place; `foot` the band kept clear over the page's foot for the keys.
 * At 1440: margins 80, titles 60, pictures 0.86 of their size, keys 64 in and 32 up, text sizes unchanged.
 */
export const DAY_LAYOUTS = Object.freeze({
  wide: Object.freeze({
    left: 120, top: 84, whoWidth: 600, portrait: 112, title: 72,
    labelX: 860, pathX: 880, itemX: 920, firstTop: 150, gap: 160,
    picture: Object.freeze({ width: 208, height: 118 }), wordsGap: 28, dotOffset: 21, dotRadius: 6, pathTop: 116,
    keysRight: 100, keysBottom: 40, foot: 150,
  }),
  narrow: Object.freeze({
    left: 80, top: 84, whoWidth: 480, portrait: 96, title: 60,
    labelX: 620, pathX: 640, itemX: 680, firstTop: 150, gap: 138,
    picture: Object.freeze({ width: 179, height: 101 }), wordsGap: 28, dotOffset: 18, dotRadius: 6, pathTop: 116,
    keysRight: 64, keysBottom: 32, foot: 120,
  }),
});

/** The layout for a page `width` wide. */
export function dayLayout(width) {
  return width < NARROW_BELOW ? DAY_LAYOUTS.narrow : DAY_LAYOUTS.wide;
}

/** How many cards stand whole between the newest card's top and the band over the page's foot; at least one. */
export function dayCapacity(layout, height) {
  const room = height - layout.foot - layout.picture.height - layout.firstTop;
  return Math.max(1, Math.floor(room / layout.gap) + 1);
}

/**
 * Which of `count` cards are in view, newest first, and where. `chosen` is the chosen card's index (kept in view) or
 * null; `first` the index the view started at in the last draw, kept while the chosen card is still in view, so moving
 * the choice inside the view moves nothing. Each card in view has its `index`, `top` and its dot's centre `dot`. The
 * path runs from the newest card in view to the oldest (from `pathTop` when newer cards are out of view; to the band
 * over the page's foot when older ones are), or is null with no cards. `wordsX` is where a card's words start and
 * `itemWidth` how wide a card may be on a page `width` wide.
 */
export function dayView({ count, chosen = null, first = null, layout, width, height }) {
  const capacity = dayCapacity(layout, height);
  const last = Math.max(0, count - capacity);
  let start = Math.min(Math.max(0, Number.isInteger(first) ? first : 0), last);
  if (Number.isInteger(chosen) && chosen >= 0 && chosen < count) {
    if (chosen < start) start = chosen;
    else if (chosen >= start + capacity) start = chosen - capacity + 1;
  }
  const end = Math.min(count, start + capacity);
  const items = [];
  for (let index = start; index < end; index += 1) {
    const top = layout.firstTop + (index - start) * layout.gap;
    items.push(Object.freeze({ index, top, dot: top + layout.dotOffset }));
  }
  const newer = start > 0, older = end < count;
  const path = items.length
    ? Object.freeze({ x: layout.pathX, from: newer ? layout.pathTop : items[0].top, to: older ? height - layout.foot : items[items.length - 1].dot })
    : null;
  const wordsX = layout.itemX + layout.picture.width + layout.wordsGap;
  return Object.freeze({ first: start, capacity, items: Object.freeze(items), newer, older, path, wordsX, itemWidth: Math.max(0, width - layout.keysRight - layout.itemX) });
}

/**
 * The card the arrows reach from `chosen`: `step` -1 is later (up, newer), 1 earlier (down, older), over the cards a
 * choice may not rest on (`choosable(index)` false: a line heard, T6). The same index where there is none further.
 */
export function stepChoice(count, chosen, step, choosable) {
  let next = (Number.isInteger(chosen) ? chosen : -1) + step;
  while (next >= 0 && next < count && !choosable(next)) next += step;
  return next >= 0 && next < count ? next : chosen;
}
