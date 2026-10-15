// The numbers behind the in-world parts (world-ui.ts), kept apart from the DOM so they can be
// checked in Node (verify-world-ui.mjs). Sizes are CSS pixels at the reference viewport; each
// figure is a default a caller may replace.

/** The reference viewport and the scale's bounds (DESIGN's specification, section 2). */
export const UI_SCALE = Object.freeze({ width: 1920, height: 1080, least: 0.78, most: 1.2 });

/** How much every in-world size is multiplied by in a viewport of this size. */
export function uiScale(width, height, bounds = UI_SCALE) {
  if (!(width > 0) || !(height > 0)) return 1;
  const scale = Math.min(width / bounds.width, height / bounds.height);
  return Math.min(bounds.most, Math.max(bounds.least, scale));
}

/** The default inset of anchored parts from the viewport's edge, before scaling. */
export const ANCHOR_INSET = 40;

/**
 * Where a part of `size` goes so that `point` (its top left) stays `inset` inside the viewport.
 * A part larger than the room left keeps its top left at the inset.
 */
export function clampToView(point, size, viewport, inset = ANCHOR_INSET) {
  const room = (at, extent, span) => Math.max(inset, Math.min(span - inset - extent, at));
  return { x: room(point.x, size.width, viewport.width), y: room(point.y, size.height, viewport.height) };
}

/**
 * The side card's placement beside its subject (section 5.6, frame 05), in reference pixels: the
 * gap from the subject's box, the inset from the viewport, and how far below the card's top the
 * connector meets it (level with the title).
 */
export const BESIDE = Object.freeze({ gap: 80, inset: ANCHOR_INSET, meet: 92 });

/**
 * Where a card of `size` sits beside a subject whose screen box is `bounds` ({ left, top, right,
 * bottom, headY, waistY }): `gap` to the right of the box, centred between head and waist, and
 * on the left when the right side would cross the margin. Returns the card's top left, its side,
 * and the connector: from the subject's shoulder, diagonally to the middle of the gap, then level
 * into the card's near edge. `connect` (default `bounds`) is the box the connector starts from: a
 * card beside a carried copy and its spot together points at the copy (DESIGN's ruling L11).
 */
export function placeBeside(bounds, size, viewport, { gap = BESIDE.gap, inset = BESIDE.inset, meet = BESIDE.meet, connect = bounds } = {}) {
  const head = Number.isFinite(bounds.headY) ? bounds.headY : bounds.top;
  const waist = Number.isFinite(bounds.waistY) ? bounds.waistY : (bounds.top + bounds.bottom) / 2;
  const fitsRight = bounds.right + gap + size.width <= viewport.width - inset;
  const fitsLeft = bounds.left - gap - size.width >= inset;
  const side = fitsRight || !fitsLeft ? 'right' : 'left';
  const x = side === 'right' ? bounds.right + gap : bounds.left - gap - size.width;
  const at = clampToView({ x, y: (head + waist) / 2 - size.height / 2 }, size, viewport, inset);
  const towards = side === 'right' ? 1 : -1;
  const fromHead = Number.isFinite(connect.headY) ? connect.headY : connect.top;
  const fromWaist = Number.isFinite(connect.waistY) ? connect.waistY : (connect.top + connect.bottom) / 2;
  const from = { x: side === 'right' ? connect.right : connect.left, y: fromHead + (fromWaist - fromHead) * 0.25 };
  const to = { x: side === 'right' ? at.x : at.x + size.width, y: at.y + Math.min(meet, size.height / 2) };
  const elbow = { x: to.x - towards * Math.min(gap / 2, Math.abs(to.x - from.x)), y: to.y };
  return { x: at.x, y: at.y, side, connector: { from, elbow, to } };
}

/** How long hints stay and come back, and how long a note stays (sections 5.2 and 5.13), in ms. */
export const WORLD_UI_TIMING = Object.freeze({ hintsFadeAfter: 10_000, hintsWake: 6_000, note: 4_000, noteWithPrompt: 8_000, banner: { in: 600, hold: 2_400, out: 800 } });

/**
 * A read the world makes by itself retries quietly (read-backoff.mjs); only after this many failures
 * in a row does the offline note show, and it stays until a read succeeds (DESIGN's ruling L14).
 */
export const OFFLINE_AFTER_FAILED_READS = 3;

/**
 * Whether the hints show at `now`, given the last moment they were woken and how long that wake
 * lasts. `since` is the moment the world view mounted (hints show for `hintsFadeAfter` from it).
 */
export function hintsShown(now, { since, wokenAt = -Infinity, wake = WORLD_UI_TIMING.hintsWake, fadeAfter = WORLD_UI_TIMING.hintsFadeAfter, held = false }) {
  if (held) return true;
  if (now - since < fadeAfter) return true;
  return now - wokenAt < wake;
}

/** How long a note stays, by whether it carries a prompt (Undo). */
export const noteDuration = (withPrompt, timing = WORLD_UI_TIMING) => withPrompt ? timing.noteWithPrompt : timing.note;
