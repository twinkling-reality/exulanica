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
/** A choice's second line (17px at 1.3), and the most lines a choice takes: past two it is cut (D3). */
export const WRAP = 22, ROW_LINES = 2;

/** The widest a choice row runs: up to 48px short of the card, its words wrapping to a second line past that. */
export const rowMost = layout => layout.card.x - 48 - (layout.column + layout.words);

/** Where a choice row's words (and the taken one's Chosen tag) end, where the page cannot measure them. */
export function choiceEnd(layout, words, taken) {
  const width = NUMBER + ROW_GAP + Math.round(String(words).length * CHOICE_CHARACTER) + (taken ? ROW_GAP + TAG : 0);
  return layout.column + layout.words + Math.min(width, rowMost(layout));
}

/** How many lines a choice row takes in the column's width, where the page cannot measure it: one, or two. */
export function choiceLines(layout, words, taken) {
  const width = NUMBER + ROW_GAP + Math.round(String(words).length * CHOICE_CHARACTER) + (taken ? ROW_GAP + TAG : 0);
  return width > rowMost(layout) ? ROW_LINES : 1;
}

/**
 * The flow for `layout` in a window `height` tall (the size's own by default): `count` choices, `taken` the index of the
 * taken one (-1 where none is), `offset` the first row the column shows (null: the window that first shows the taken
 * one), `toldHeight` the told column's height (null or 0 where nothing was told), `takenEnd` the x where the taken row's
 * words end, `headBottom` where the head ends (null: the size's own place for what was told), `lines` each choice's
 * lines, one or two (null: one each).
 *
 * Returns what was told's place (below the head, stopping above the window's foot) and the stored record's (from there
 * to above the keys), the bracket and its line into the ring (null with nothing told), the ring and its words' place,
 * the column's label place, the drawn rows (each its index, y, curve and end dot), the window (offset, home, how many
 * lie above and below), the taken one's lit curve (to its row, or to the column's edge toward it while it is scrolled
 * out of view), the card's place, the line on to the card, and where the down arrow's cap sits.
 */
export function flowLayout(layout, { count, taken = -1, offset = null, toldHeight: told = null, takenEnd = null, height = layout.height, headBottom: headEnd = null, lines = null }) {
  const { card, gap } = layout;
  // Rows are spaced by their own heights (D3): a row of two lines stands a second line taller, and a window holds the
  // rows that fit in the height of the size's most one-line rows, so a column of one-line rows reads as it always did.
  const extra = index => (Math.min(ROW_LINES, Math.max(1, lines?.[index] ?? 1)) - 1) * WRAP;
  const step = index => gap + (extra(index) + extra(index + 1)) / 2;
  const spanOf = (from, rows) => { let span = 0; for (let index = from; index < from + rows - 1; index += 1) span += step(index); return span; };
  const fit = from => { let rows = Math.min(layout.shown, Math.max(0, count - from)); while (rows > 1 && spanOf(from, rows) > (layout.shown - 1) * gap) rows -= 1; return rows; };
  let most = 0, home = 0;
  while (most < count && most + fit(most) < count) most += 1;
  while (taken >= 0 && home < most && taken >= home + fit(home)) home += 1;
  const first = clamp(offset ?? home, 0, most);
  const shown = fit(first);
  const keysTop = height - layout.keys.bottom - CAP;
  const toldTop = headEnd === null ? layout.told.top : Math.max(layout.told.top, Math.ceil(headEnd + HEAD.gap));
  const toldMost = Math.max(120, height - layout.told.foot - toldTop);
  // A short window raises the ring until the lowest row of its tallest window clears the keys; the ring keeps its place
  // while the column scrolls.
  const windows = count ? Array.from({ length: most + 1 }, (_, from) => ({ span: spanOf(from, fit(from)), low: extra(from + fit(from) - 1) })) : [];
  const ringSpan = windows.length ? Math.max(...windows.map(one => one.span)) : (shown - 1) * gap;
  const lowExtra = windows.length ? Math.max(...windows.map(one => one.low)) : 0;
  const ring = { ...layout.ring, y: Math.min(layout.ring.y, Math.floor(keysTop - ABOVE_KEYS - ROW_HALF - lowExtra / 2 - ringSpan / 2)) };
  const top = ring.y - (shown ? spanOf(first, shown) : (shown - 1) * gap) / 2;
  const from = { x: ring.x + ring.r, y: ring.y };
  const rows = [];
  let y = top;
  for (let at = 0; at < shown; at += 1) {
    const index = first + at, lit = index === taken;
    if (at) y += step(index - 1);
    rows.push({ index, y, taken: lit, path: bend(from.x, from.y, layout.column, y, layout.fan.out, layout.fan.into), end: { x: layout.column, y, r: lit ? 4 : 3.5 } });
  }
  const last = shown ? rows[shown - 1].y : top + (shown - 1) * gap;
  const lastEdge = shown ? extra(first + shown - 1) / 2 : 0;
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
  const homeY = taken >= 0 && taken < count ? ring.y - spanOf(home, fit(home)) / 2 + spanOf(home, taken - home + 1) : ring.y;
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
    lit = bend(from.x, from.y, layout.column, taken < first ? top - gap / 2 - extra(first) / 2 : last + gap / 2 + lastEdge, layout.fan.out, layout.fan.into);
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
    down: { x: layout.column + layout.words, y: last + gap / 2 + lastEdge },
  };
}

/** The five canonical stages of a decision's execution pipeline (Pillar 1: [X] System telemetry). */
export const PIPELINE_STAGES = Object.freeze([
  Object.freeze({ step: 1, key: 'snapshot', label: '1. World Snapshot' }),
  Object.freeze({ step: 2, key: 'context', label: '2. Context' }),
  Object.freeze({ step: 3, key: 'inference', label: '3. Model Inference' }),
  Object.freeze({ step: 4, key: 'check', label: '4. Engine Check' }),
  Object.freeze({ step: 5, key: 'outcome', label: '5. Outcome' }),
]);

export const PIPELINE_BAR = Object.freeze({ height: 68, aboveKeys: 12 });

const REFUSAL_LABELS = Object.freeze({
  spending_limit_reached: 'Spending limit reached',
  process_budget_spent: 'Process budget spent',
  process_share_spent: 'Process share spent',
  world_hour_spend_spent: 'Hourly spend limit reached',
  no_time_to_ask: 'No time to ask',
  unanswered_in_its_minute: 'Unanswered in minute',
  spending_not_granted: 'Spending not granted',
  spending_revoked: 'Spending revoked',
  spending_expired: 'Spending expired',
  spending_suspended: 'Spending paused',
  spending_unavailable: 'Spending check unavailable',
  spending_scope_missing: 'Spending scope missing',
  request_refused: 'Request refused',
  provider_not_admitted: 'Provider not admitted',
  provider_credential_absent: 'Provider not connected',
  model_no_longer_offered: 'Model no longer offered',
  world_hour_decisions_spent: 'Hourly decision limit reached',
  model_timed_out: 'Timed out',
  answer_not_offered: 'Answer not in offered choices',
  model_call_failed: 'Model call failed',
  model_unavailable: 'Model unavailable',
  provider_configuration_changed: 'Model settings changed',
  decision_context_changed: 'World moved on',
  line_out_of_bounds: 'Spoken line out of bounds',
  no_answer_in_time: 'No answer in time',
  decider_disconnected: 'Decider disconnected',
  place_taken_this_minute: 'Place taken this minute',
  partner_busy: 'Conversation partner busy',
  target_disabled_or_removed: 'Target removed',
});

const cleanText = value => (typeof value === 'string' && value.trim() ? value.trim() : null);

function reasonWords(code) {
  const key = cleanText(code);
  if (!key) return null;
  if (Object.hasOwn(REFUSAL_LABELS, key)) return REFUSAL_LABELS[key];
  const spaced = key.replaceAll('_', ' ');
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

function formatUsd(value, known = true) {
  if (value === null || value === undefined || value === '') return null;
  const num = Number(value);
  if (!Number.isFinite(num) || num < 0) return null;
  if (num === 0) return known ? '$0' : 'at most $0';
  const digits = num < 0.0001 ? 6 : 4;
  const text = num.toFixed(digits).replace(/0+$/u, '').replace(/\.$/u, '');
  return `${known ? '' : 'at most '}$${text}`;
}

function formatLatency(ms) {
  if (!Number.isFinite(ms) || ms < 0) return null;
  const rounded = Math.round(ms);
  const seconds = ms < 100 ? '<0.1 s' : `${(ms / 1000).toFixed(1)} s`;
  return `${rounded} ms (${seconds})`;
}

function parseDoneMetrics(done) {
  const text = cleanText(done);
  if (!text) return { latencyMs: null, costUsd: null, costKnown: true };
  const secMatch = /(\d+(?:\.\d+)?)\s*s\b/iu.exec(text);
  const underMatch = /under\s+0\.1\s*s/iu.test(text);
  const costMatch = /\$([0-9]+(?:\.[0-9]+)?)/u.exec(text);
  const atMost = /at most/iu.test(text);
  return {
    latencyMs: secMatch ? Math.round(Number(secMatch[1]) * 1000) : underMatch ? 50 : null,
    costUsd: costMatch ? costMatch[1] : null,
    costKnown: !atMost,
  };
}

function snapshotNearbyCounts(context, told) {
  const surroundings = context?.surroundings;
  if (surroundings && typeof surroundings === 'object') {
    const beings = (Array.isArray(surroundings.beings) ? surroundings.beings.length : 0)
      + (Number.isSafeInteger(surroundings.more_beings) ? surroundings.more_beings : 0);
    const objects = (Array.isArray(surroundings.things) ? surroundings.things.length : 0)
      + (Number.isSafeInteger(surroundings.more_things) ? surroundings.more_things : 0);
    return { beings, objects };
  }
  const nearbySection = Array.isArray(told) ? told.find(section => section?.label === 'Nearby') : null;
  if (!nearbySection || !Array.isArray(nearbySection.lines)) return { beings: 0, objects: 0 };
  let beings = 0, objects = 0;
  for (const raw of nearbySection.lines) {
    const line = cleanText(raw);
    if (!line) continue;
    const moreMatch = /^And (\d+) more farther away\.$/iu.exec(line);
    if (moreMatch) { beings += Number(moreMatch[1]); continue; }
    if (/^The\s+/u.test(line)) objects += 1;
    else beings += 1;
  }
  return { beings, objects };
}

function contextSectionNames(context, told) {
  if (Array.isArray(told) && told.length) {
    return told.map(section => cleanText(section?.label)).filter(Boolean);
  }
  if (!context || typeof context !== 'object') return [];
  const names = [];
  if (context.character && (cleanText(context.character.name) || cleanText(context.character.about))) names.push('Personality');
  if (cleanText(context.here) || cleanText(context.surroundings?.at?.words) || context.clock || context.world_clock || Number.isSafeInteger(context.tick)) {
    names.push('Location & Time');
  }
  if ((Array.isArray(context.needs) && context.needs.length) || Number.isFinite(context.need_milli) || (Array.isArray(context.holding) && context.holding.length)) {
    names.push('Status');
  }
  const near = snapshotNearbyCounts(context, null);
  if (near.beings + near.objects > 0) names.push('Nearby');
  if (Array.isArray(context.heard) && context.heard.some(item => cleanText(item?.line))) names.push('Heard');
  const rem = context.remembers;
  if (rem && ((Array.isArray(rem.beings) && rem.beings.length) || (Array.isArray(rem.places) && rem.places.length) || (Array.isArray(rem.handed) && rem.handed.length))) {
    names.push('Remembers');
  }
  return names;
}

function normalizeStagePercents(rawWeights) {
  const total = rawWeights.reduce((sum, w) => sum + w, 0) || 100;
  const percents = rawWeights.map(w => Math.max(10, Math.round((w * 100) / total)));
  const diff = 100 - percents.reduce((sum, p) => sum + p, 0);
  // Adjust the largest stage (typically Model Inference) so percents sum to exactly 100.
  let maxIndex = 2;
  for (let i = 0; i < percents.length; i += 1) {
    if (percents[i] > percents[maxIndex]) maxIndex = i;
  }
  percents[maxIndex] += diff;
  return percents;
}

/**
 * Computes the 5-stage visual execution pipeline and proportional timing/status breakdown from a recorded decision
 * receipt (`detail` = `{ request, decision }`) and/or a `DecisionPageState` object.
 */
export function executionPipeline(input = {}) {
  const detail = input?.detail ?? (input?.request || input?.decision ? input : null);
  const request = detail?.request ?? input?.request ?? null;
  const receipt = detail?.decision ?? input?.decision ?? null;
  const context = request?.context ?? input?.context ?? null;
  const config = request?.provider_config ?? null;
  const provider = receipt?.provider ?? null;
  const proposal = receipt?.proposal ?? null;

  // Stage 1: World Snapshot (tick, state digest prefix, nearby beings/objects count)
  const tick = Number.isSafeInteger(request?.base_tick) ? request.base_tick
    : Number.isSafeInteger(context?.tick) ? context.tick : null;
  const rawDigest = cleanText(request?.state_sha256) ?? cleanText(context?.state_sha256)
    ?? cleanText(request?.document_sha256) ?? cleanText(receipt?.request_sha256);
  const digest = rawDigest && rawDigest.length >= 8 ? rawDigest.slice(0, 8) : null;
  const { beings, objects } = snapshotNearbyCounts(context, input?.told);
  const overParts = cleanText(input?.over)?.split(' · ').slice(0, 2).join(' · ') ?? null;
  const snapshotParts = [
    tick !== null ? `Tick ${tick}` : overParts ?? 'Snapshot',
    digest ? `#${digest}` : null,
  ].filter(Boolean);
  const snapshotDetail = `${beings} ${beings === 1 ? 'being' : 'beings'}, ${objects} ${objects === 1 ? 'object' : 'objects'}`;

  // Stage 2: Context (sections assembled: Location & Time, Status, Nearby, Heard, Remembers + offered choices count)
  const sections = contextSectionNames(context, input?.told);
  const choicesCount = Array.isArray(input?.choices) ? input.choices.length
    : Array.isArray(context?.options) ? context.options.length : 0;
  const contextSummary = `${sections.length} ${sections.length === 1 ? 'section' : 'sections'} · ${choicesCount} ${choicesCount === 1 ? 'choice' : 'choices'}`;
  const contextDetail = sections.length ? sections.join(' · ') : 'Direct options';

  // Stage 3: Model Inference (model name, provider/local, latency in ms/s, token/dollar spend)
  const origin = config?.provider ? 'model' : config?.kind ?? null;
  const decider = input?.decider ?? (origin === 'model' || origin === 'person' || origin === 'external' ? origin : input?.model ? 'model' : null);
  const parsedDone = parseDoneMetrics(input?.done);
  const unanswered = input?.unanswered ?? null;
  const answered = input?.answered ?? null;
  const modelName = cleanText(input?.model) ?? cleanText(provider?.served_model_id) ?? cleanText(config?.model_id)
    ?? (decider === 'person' ? 'Person playing' : decider === 'agent' ? 'Outside AI agent' : decider === 'external' ? 'Outside program' : 'Model');
  const isLocal = Boolean(config?.local || provider?.local || config?.provider === 'local' || provider?.provider === 'local' || decider === 'person');
  const rawProvider = cleanText(config?.provider) ?? cleanText(provider?.provider) ?? cleanText(config?.bridge);
  const providerLabel = isLocal ? 'Local'
    : rawProvider ? rawProvider.replaceAll('_', ' ')
      : decider === 'agent' || decider === 'external' ? 'Door bridge' : 'Hosted';
  const latencyMs = Number.isFinite(provider?.latency_ms) ? provider.latency_ms
    : Number.isFinite(answered?.latencyMs) ? answered.latencyMs
      : Number.isFinite(unanswered?.latencyMs) ? unanswered.latencyMs
        : parsedDone.latencyMs;
  const promptTokens = Number.isSafeInteger(provider?.prompt_tokens) ? provider.prompt_tokens : null;
  const completionTokens = Number.isSafeInteger(provider?.completion_tokens) ? provider.completion_tokens : null;
  const totalTokens = promptTokens !== null && completionTokens !== null ? promptTokens + completionTokens : null;
  const rawCost = provider?.cost_usd ?? answered?.costUsd ?? unanswered?.costUsd ?? parsedDone.costUsd ?? null;
  const costKnown = provider?.cost_known !== undefined ? Boolean(provider.cost_known)
    : answered?.costKnown !== undefined ? Boolean(answered.costKnown)
      : unanswered?.costKnown !== undefined ? Boolean(unanswered.costKnown)
        : parsedDone.costKnown;
  const costText = decider === 'person' || decider === 'external' || decider === 'agent' ? null : formatUsd(rawCost, costKnown);
  const latencyText = formatLatency(latencyMs);
  const notCalled = Boolean(unanswered && unanswered.asks < 1);
  const inferenceSummary = [modelName, notCalled ? 'not called' : latencyText].filter(Boolean).join(' · ');
  const inferenceDetail = [
    providerLabel,
    totalTokens !== null ? `${totalTokens} tok (${promptTokens} in / ${completionTokens} out)` : null,
    costText,
  ].filter(Boolean).join(' · ');
  const inferenceStatus = notCalled ? 'warn'
    : (unanswered || receipt?.status === 'unavailable' || receipt?.status === 'rejected') ? 'fallback' : 'ok';

  // Stage 4: Engine Check (Applied vs specific refusal reason / Not Applied / Routine Fallback)
  const receiptStatus = cleanText(receipt?.status);
  const disposition = cleanText(detail?.disposition ?? input?.disposition);
  const rawReason = cleanText(unanswered?.reason ?? receipt?.reason ?? detail?.disposition_reason);
  const reasonLabel = reasonWords(rawReason);
  const isLate = Boolean(input?.late || disposition === 'stale' || receiptStatus === 'stale');
  const isNotApplied = Boolean(disposition === 'rejected' || disposition === 'superseded');
  const isFallback = Boolean(unanswered || receiptStatus === 'rejected' || receiptStatus === 'unavailable');
  const isPending = Boolean(!isLate && !isNotApplied && !isFallback && (cleanText(input?.verdict) || detail?.status === 'in_progress'));

  let checkStatus = 'ok';
  let checkVerdict = 'Applied';
  let checkSummary = 'Applied';
  let checkDetail = 'Proposal validated';

  if (isLate) {
    checkStatus = 'warn';
    checkVerdict = 'Not Applied';
    checkSummary = 'Not Applied · Routine Fallback';
    checkDetail = reasonLabel ? `${reasonLabel} · Routine Fallback` : 'World moved on before commit · Routine Fallback';
  } else if (isNotApplied) {
    checkStatus = 'warn';
    checkVerdict = 'Not Applied';
    checkSummary = 'Not Applied · Routine Fallback';
    checkDetail = reasonLabel ? `${reasonLabel} · Routine Fallback` : 'Superseded at commit · Routine Fallback';
  } else if (isFallback) {
    checkStatus = 'fallback';
    checkVerdict = 'Routine Fallback';
    checkSummary = reasonLabel ? `${reasonLabel} · Routine Fallback` : 'Routine Fallback';
    checkDetail = cleanText(input?.why) ?? (reasonLabel ? `Refused (${reasonLabel})` : 'No usable proposal; routine acted');
  } else if (isPending) {
    checkStatus = 'pending';
    checkVerdict = 'Pending';
    checkSummary = 'Accepted · Pending';
    checkDetail = cleanText(input?.verdict) ?? 'Validated option; awaiting minute commit';
  } else {
    const takenIndex = Array.isArray(input?.choices) ? input.choices.findIndex(choice => choice?.chosen) : -1;
    const optionNum = takenIndex >= 0 ? (input.choices[takenIndex]?.number ?? takenIndex + 1)
      : proposal?.label && Array.isArray(context?.options)
        ? context.options.findIndex(option => option?.label === proposal.label) + 1 : 0;
    checkDetail = optionNum > 0 ? `Option #${optionNum} verified` : 'Proposal validated';
  }

  // Stage 5: Outcome (world state commit / spoken line / movement target)
  const spokenLine = cleanText(input?.said) ?? (cleanText(proposal?.line) ? `“${cleanText(proposal.line)}”` : null);
  const actionTarget = isLate || isNotApplied || isFallback
    ? (cleanText(input?.action) ?? cleanText(input?.title) ?? cleanText(input?.decided) ?? cleanText(proposal?.label))
    : (cleanText(input?.action) ?? cleanText(input?.decided) ?? cleanText(input?.title) ?? cleanText(proposal?.label));
  const outcomeStatus = checkStatus;
  let outcomeKind = 'commit';
  let outcomeSummary = actionTarget ?? 'State committed';
  let outcomeDetail = 'World state commit';

  if (isLate || isNotApplied || isFallback) {
    outcomeKind = 'fallback';
    outcomeSummary = actionTarget ?? 'Routine continuation';
    outcomeDetail = 'Routine fallback committed to world state';
  } else if (spokenLine) {
    outcomeKind = 'speech';
    outcomeSummary = spokenLine;
    outcomeDetail = tick !== null ? `Spoken line committed · Tick ${tick}` : 'Spoken line committed to world state';
  } else if (isPending) {
    outcomeKind = 'pending';
    outcomeSummary = actionTarget ?? 'Pending action';
    outcomeDetail = 'Awaiting minute state commit';
  } else {
    outcomeKind = 'movement';
    outcomeSummary = actionTarget ?? 'Action applied';
    outcomeDetail = tick !== null ? `Movement / action committed · Tick ${tick}` : 'Movement / action committed to world state';
  }

  // Proportional timing/weight shares across the 5 stages
  const rawWeights = [
    14,
    14 + Math.min(8, sections.length + Math.floor(choicesCount / 4)),
    notCalled ? 14 : latencyMs !== null && latencyMs > 0 ? Math.min(52, Math.max(24, Math.round(16 + Math.log10(Math.max(10, latencyMs)) * 10))) : 24,
    15,
    15,
  ];
  const percents = normalizeStagePercents(rawWeights);

  const stages = [
    {
      ...PIPELINE_STAGES[0],
      status: 'ok',
      percent: percents[0],
      share: Number((percents[0] / 100).toFixed(2)),
      summary: snapshotParts.join(' · '),
      detail: snapshotDetail,
      metrics: { tick, digest, beings, objects },
    },
    {
      ...PIPELINE_STAGES[1],
      status: 'ok',
      percent: percents[1],
      share: Number((percents[1] / 100).toFixed(2)),
      summary: contextSummary,
      detail: contextDetail,
      metrics: { sections, choices: choicesCount },
    },
    {
      ...PIPELINE_STAGES[2],
      status: inferenceStatus,
      percent: percents[2],
      share: Number((percents[2] / 100).toFixed(2)),
      summary: inferenceSummary,
      detail: inferenceDetail,
      metrics: {
        model: modelName,
        provider: providerLabel,
        local: isLocal,
        latencyMs,
        tokens: totalTokens,
        promptTokens,
        completionTokens,
        costUsd: rawCost !== null ? String(rawCost) : null,
        costKnown,
      },
    },
    {
      ...PIPELINE_STAGES[3],
      status: checkStatus,
      percent: percents[3],
      share: Number((percents[3] / 100).toFixed(2)),
      summary: checkSummary,
      detail: checkDetail,
      metrics: {
        verdict: checkVerdict,
        reason: rawReason,
        applied: checkVerdict === 'Applied',
        fallback: isFallback || isLate || isNotApplied,
      },
    },
    {
      ...PIPELINE_STAGES[4],
      status: outcomeStatus,
      percent: percents[4],
      share: Number((percents[4] / 100).toFixed(2)),
      summary: outcomeSummary,
      detail: outcomeDetail,
      metrics: {
        kind: outcomeKind,
        text: outcomeSummary,
        committed: !isPending,
      },
    },
  ];

  return {
    stages,
    totalLatencyMs: latencyMs,
    verdict: checkVerdict,
  };
}

export const decisionPipeline = executionPipeline;

/**
 * Places the 5-stage execution pipeline strip along the lower telemetry rail of the decision page, clear of the keys,
 * and computes proportional pixel widths for each stage segment.
 */
export function pipelineLayout(layout, height = layout.height, stages = null) {
  const width = layout.width - 2 * layout.margin;
  const keysTop = height - layout.keys.bottom - CAP;
  const top = Math.max(layout.told.top, keysTop - ABOVE_KEYS - PIPELINE_BAR.height);
  const list = Array.isArray(stages) && stages.length === PIPELINE_STAGES.length
    ? stages
    : PIPELINE_STAGES.map(stage => ({ ...stage, percent: 20, share: 0.2 }));
  let x = 0;
  const segments = list.map((stage, index) => {
    const segWidth = index === list.length - 1 ? width - x : Math.round((width * (stage.percent ?? 20)) / 100);
    const segment = { key: stage.key, step: stage.step, x, width: segWidth, percent: stage.percent ?? 20 };
    x += segWidth;
    return segment;
  });
  return { left: layout.margin, top, width, height: PIPELINE_BAR.height, segments };
}
