// The connected journey (matrix row N1.j) in the production browser, through the rehearsal's own
// page machinery: one headless Chrome, one page, the person's actions through the product's
// controls, and the server's answers read from the page's own recorded /api/ traffic.
//
//   node scripts/acceptance/journey_browser.mjs PLAN.json
//
// PLAN.json: { "session": { "id", "budget_seconds" }, "out": <directory>, "runtime": { "app_url",
// "api_base", "token_file", "browser_port", "chrome_flags", "page_deadlines_ms" } }, written by
// scripts/acceptance/foundation.py from a stack scripts/acceptance/launch.py started with
// --production --society-playback. It writes session.json in the rehearsal's shape (session,
// started_at, finished_at, chrome_argv, facts, outcomes, unreached) after every step.
//
// It registers nothing in the rehearsal's step list: S9's steps and handlers stay as they are, and
// this runner only imports the helpers they export. Every action is a control in the page; direct
// API reads with the run's token are only reads, recorded as each step's evidence. The placed
// objects are followed by the ids the server gave them (`facts`), never by a label.

import { createHash } from 'node:crypto';
import { readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import { setTimeout as sleep } from 'node:timers/promises';

import { open as openBrowser } from '../rehearsal/cdp.mjs';
import {
  ACTION, OBJECT_PANEL, OPEN_CONFIRM, SAVED_WORLD_CARDS, SAVED_WORLD_LIST, WORLD_READY, chooseMenu,
  chooseSavedWorld, confirm, confirmation, enter, liveObjects, open, openObjects, savedWorld,
} from '../rehearsal/app.mjs';
import {
  INSPECT, INSPECTOR, PEOPLE, ROW, inspectorSeen, openPeopleNearby, societyPath, waitForEdit,
} from '../rehearsal/handlers.mjs';

const REPOSITORY = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
// A write the page confirms and the API then holds.
const SETTLE_MS = 30_000;
// After a panel changes, time for the page to draw what it read.
const PAGE_SETTLE_MS = 1_500;
// How many simulated minutes the journey may advance before the response is declared not seen.
const MINUTES_MOST = 60;
// The stall is moved this far aside before the bench is placed, so the two do not share a spot.
const MOVE_PRESSES = 8;
const MOVE_KEY = 'ArrowRight';
// The steps, in order: each one is a person's action in the page. Your worlds comes first after
// signing in (N1.k), the journey follows (N1.j), and Your worlds with two worlds and Create a world
// close it (N1.l), so neither changes the world the journey uses. N1.l's town is then opened in each
// look (N1.m) and its values shown in Create a world (N1.n).
const STEPS = ['worlds-first', 'journey-open', 'journey-stall', 'journey-people', 'journey-bench',
  'journey-response', 'journey-why', 'worlds-create', 'worlds-look', 'worlds-values'];
// The second saved world N1.l makes through the API, so Your worlds lists two.
const SECOND_WORLD_TITLE = 'Q10 second world';
const SECOND_WORLD_RECIPE = 'small_town';
// Create a world, as Your worlds opens it.
const RECIPES = `document.querySelector('section.world-recipes')`;
// What the shell states of a generated world's look (docs/style-pack-contract.md): the pack asked
// for, whether it was drawn and why not, as JSON.
const WORLD_LOOK = `document.querySelector('#shell')?.getAttribute('data-world-look') ?? null`;
// N1.m (A-65): the town opened with no look named, with the tile look and with the toon pack, and
// what the shell states for each, from the contract's words for the team's packs.
const LOOKS = [
  { query: '', look: { pack: 'exulanica.cozy-town', drawn: true, reason: null } },
  { query: '?look=today', look: { pack: null, drawn: false, reason: null } },
  { query: '?look=toon', look: { pack: 'exulanica.toon-town', drawn: true, reason: null } },
];
// How long the town's tiles may take to bake before the page can draw it, and how often to look.
const BAKE_MS = 600_000;
const BAKE_LOOK_MS = 5_000;

const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

/** What Your worlds shows: its variant, the chosen world, its cards in order and its actions. */
const yourWorlds = (page) => page.evaluate(`(() => { const gate = ${SAVED_WORLD_LIST}; if (!gate) return null;
  return { variant: gate.dataset.variant ?? null,
    primary: gate.querySelector('.your-worlds-actions')?.dataset.primary ?? null,
    heading: gate.querySelector('.your-worlds-title')?.textContent ?? null,
    cards: ${SAVED_WORLD_CARDS}.map(b => ({ entry_id: b.dataset.entryId ?? null,
      title: b.querySelector('.world-entry-choice-title')?.textContent ?? null,
      current: b.getAttribute('aria-current') })),
    create_card: !!gate.querySelector('[data-action="worlds.create-card"]'),
    create_action: !!gate.querySelector('[data-action="worlds.create"]') }; })()`);

/** The words the inspector's why-button reads, from the catalog the page draws them from. */
function whyWords() {
  const catalog = JSON.parse(readFileSync(join(REPOSITORY, 'assets', 'catalogs', 'society-words',
    'society-inhabitant-words.v1.json'), 'utf8'));
  const entry = catalog.entries.find((e) => e.code === 'ask_why');
  if (entry === undefined) throw new Error('the society words catalog has no ask_why entry');
  return entry.words;
}

const plan = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const out = plan.out;
const token = readFileSync(plan.runtime.token_file, 'utf8').trim();
const report = {
  session: plan.session.id,
  started_at: new Date().toISOString(),
  finished_at: null,
  chrome_argv: null,
  facts: {},
  outcomes: {},
  unreached: {},
};
let page = null;
let current = null;

function write() {
  writeFileSync(join(out, 'session.json'), `${JSON.stringify(report, null, 2)}\n`);
}

async function finish(code, reason) {
  for (const id of STEPS) {
    if (!(id in report.outcomes)) report.unreached[id] = id === current ? `${reason} (during this step)` : reason;
  }
  report.finished_at = new Date().toISOString();
  write();
  if (page !== null) await page.close().catch(() => null);
  rmSync(join(out, 'chrome-profile'), { recursive: true, force: true });
  process.exit(code);
}

setTimeout(() => {
  void finish(124, `the session's time allowance of ${plan.session.budget_seconds} s ran out`);
}, plan.session.budget_seconds * 1000).unref();
process.on('SIGTERM', () => { void finish(143, 'the run was stopped'); });

function context(id, evidence, observations) {
  const sha256 = (bytes) => createHash('sha256').update(bytes).digest('hex');
  return {
    page,
    step: { id },
    facts: report.facts,
    parameters: {},
    runtime: plan.runtime,
    token,
    observe(name, ok, observed) {
      observations.push({ id: name, ok: Boolean(ok), observed: observed ?? null });
      return Boolean(ok);
    },
    note(text) { evidence.notes.push(text); },
    async screenshot(name, scope) {
      const index = String(Object.keys(report.outcomes).length + 1).padStart(2, '0');
      const shot = await page.screenshot(join(out, 'screens'), `${plan.session.id}-${index}-${id}-${name}`);
      evidence.screenshots.push({ file: relative(out, shot.file), sha256: sha256(shot.bytes), scope });
      return shot;
    },
    async api(method, path, body) {
      const response = await fetch(`${plan.runtime.api_base}${path}`, {
        method,
        headers: { Authorization: `Bearer ${token}`, Accept: 'application/json',
          ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
      const text = await response.text();
      let parsed = text;
      try { parsed = JSON.parse(text); } catch { /* not JSON */ }
      evidence.api.push({ method, path, request_body: body ?? null, status: response.status,
        response_body: typeof parsed === 'string' ? parsed.slice(0, 4000) : parsed });
      return { status: response.status, body: parsed };
    },
  };
}

/** This step's recorded page requests whose method and path match. */
async function traffic(ctx, method, pathPart) {
  return (await ctx.page.traffic(ctx.step.id)).filter((r) => r.method === method && r.path.includes(pathPart));
}

/** Place a reviewed asset through the objects panel, its check and its confirmation. */
async function place(ctx, assetKey) {
  const { page: p } = ctx;
  await openObjects(p);
  const before = await savedWorld(ctx);
  await p.setValue(`document.querySelector('select#object-placement-role')`, 'fictional');
  await p.setValue(`document.querySelector('select#object-placement-asset')`, assetKey);
  await p.click(`document.querySelector('button.object-placement-place')`, 'Place before me');
  const said = await confirmation(p, `placing ${assetKey}`);
  const verdict = await p.waitFor(`(() => { const v = ${OPEN_CONFIRM}?.querySelector('.composition-verdict');
    const s = v?.dataset.state; return s && s !== 'checking' ? { state: s, text: v.innerText.trim() } : null; })()`,
  SETTLE_MS, `the world's check of ${assetKey}`);
  await ctx.screenshot('confirm', `the confirmation before ${assetKey} is written`);
  const unwritten = (await savedWorld(ctx)).version.edit_seq === before.version.edit_seq;
  await confirm(p, `placing ${assetKey}`);
  const after = await waitForEdit(ctx, before.version.edit_seq, `${assetKey} to be saved`);
  const placed = liveObjects(after.version).find((o) => o.asset.asset_key === assetKey
    && !liveObjects(before.version).some((b) => b.object_id === o.object_id)) ?? null;
  const previews = await traffic(ctx, 'POST', '/compositions/preview');
  const applies = await traffic(ctx, 'POST', '/compositions/apply');
  ctx.observe(`${assetKey}-confirmed-before-write`, verdict.state === 'ready' && unwritten,
    { confirmation: said, verdict, unwritten_before_confirm: unwritten });
  ctx.observe(`${assetKey}-preview-then-apply`, previews.some((r) => r.status === 200)
    && applies.length === 1 && applies[0].status === 201,
  { previews: previews.map((r) => r.status), applies: applies.map((r) => r.status) });
  ctx.observe(`${assetKey}-in-version`, placed !== null, { object: placed });
  await ctx.screenshot('placed', `${assetKey} placed`);
  return { placed, edit: after.version.edits.at(-1) };
}

const STEP_HANDLERS = {
  async 'worlds-first'(ctx) {
    const surface = await enter(ctx, () => ctx.page.navigate(plan.runtime.app_url), undefined, { choose: false });
    const seen = await yourWorlds(ctx.page);
    const { entries, entry } = await savedWorld(ctx);
    ctx.observe('your-worlds-first', surface === 'list' && entries.length === 1 && seen?.cards.length === 1
      && seen.cards[0].entry_id === entry?.entry_id && seen.cards[0].title === entry?.title
      && seen.create_card && seen.create_action,
    { surface, seen, entries: entries.map((e) => [e.entry_id, e.title, e.authored_edit_seq]) });
    // The untouched starter is not yet a world of the person's own: Create is the action asked for.
    ctx.observe('untouched-starter-asks-to-create', entry?.authored_edit_seq === 0
      && seen?.variant === 'first' && seen?.primary === 'create',
    { edit_seq: entry?.authored_edit_seq ?? null, variant: seen?.variant ?? null, primary: seen?.primary ?? null });
    await ctx.screenshot('your-worlds', 'Your worlds, the first screen after the credential gate');
    await chooseSavedWorld(ctx);
    const title = await ctx.page.evaluate(`document.querySelector('input[aria-label="World title"]')?.value ?? null`);
    ctx.observe('card-opens-its-world', await ctx.page.evaluate(WORLD_READY) && title === entry?.title,
      { title, entry_title: entry?.title ?? null });
  },
  async 'worlds-create'(ctx) {
    // A workspace holds one starter, so the second world is a town from the smallest recipe. It is
    // the newest card; the journey's starter, second, is the one opened, so no tile need be baked.
    const made = await ctx.api('POST', '/worlds/generated', { recipe: SECOND_WORLD_RECIPE, title: SECOND_WORLD_TITLE });
    ctx.observe('second-world-saved', made.status === 201, { status: made.status, entry_id: made.body?.entry_id ?? null });
    ctx.facts.town_entry_id = made.body?.entry_id ?? null;
    const surface = await enter(ctx, () => ctx.page.reload(), undefined, { choose: false });
    const listed = (await ctx.api('GET', '/world-entries')).body ?? [];
    const newestFirst = [...listed].sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at)).map((e) => e.entry_id);
    const seen = await yourWorlds(ctx.page);
    ctx.observe('worlds-newest-first', surface === 'list' && listed.length === 2
      && same(seen?.cards.map((c) => c.entry_id), newestFirst) && seen?.variant === 'worlds' && seen?.primary === 'open',
    { surface, cards: seen?.cards ?? null, newest_first: newestFirst, variant: seen?.variant ?? null, primary: seen?.primary ?? null });
    await ctx.screenshot('two-worlds', 'Your worlds with two saved worlds');
    // Arrows choose and Enter opens: from the first card, one step right chooses the second.
    await ctx.page.evaluate(`${SAVED_WORLD_CARDS}[0].focus()`);
    await ctx.page.key('ArrowRight', 'ArrowRight');
    await sleep(PAGE_SETTLE_MS);
    const chose = await yourWorlds(ctx.page);
    const second = listed.find((e) => e.entry_id === newestFirst[1]) ?? null;
    ctx.observe('arrow-chooses', chose?.cards[1]?.current === 'true' && chose?.heading === second?.title,
      { cards: chose?.cards ?? null, heading: chose?.heading ?? null, second: second?.title ?? null });
    // Enter on the focused card is the card's own press, which a key types as a carriage return.
    await ctx.page.key('Enter', 'Enter', { text: '\r' });
    await ctx.page.waitFor(WORLD_READY, SETTLE_MS * 3, 'the chosen world to open');
    const title = await ctx.page.evaluate(`document.querySelector('input[aria-label="World title"]')?.value ?? null`);
    ctx.observe('enter-opens-the-chosen-world', title === second?.title, { title, chosen: second?.title ?? null });
    // The World menu's Your worlds comes back to the list.
    const back = await enter(ctx, () => chooseMenu(ctx.page, 'worlds'), undefined, { choose: false });
    ctx.observe('world-menu-returns-to-your-worlds', back !== null && !!await ctx.page.evaluate(SAVED_WORLD_LIST),
      { surface: back });
    // N creates: Create a world opens with describing the town first, then the served recipes.
    await ctx.page.evaluate(`${SAVED_WORLD_CARDS}[0].focus()`);
    await ctx.page.key('KeyN', 'n', { text: 'n' });
    await ctx.page.waitFor(`${RECIPES}?.querySelectorAll('button.world-recipes-choice').length > 0 ? true : null`,
      SETTLE_MS, 'Create a world to show its recipes');
    const served = ((await ctx.api('GET', '/worlds/specification')).body?.presets ?? []).map((p) => p.key).sort();
    const sheet = await ctx.page.evaluate(`(() => { const r = ${RECIPES}; const d = document.querySelector('section.world-description');
      return { visible: !!r && r.checkVisibility(), presets: [...r.querySelectorAll('button.world-recipes-choice')].map(b => b.dataset.recipe),
        description_first: !!d && d.checkVisibility() && !!(d.compareDocumentPosition(r.querySelector('button.world-recipes-choice')) & Node.DOCUMENT_POSITION_FOLLOWING) }; })()`);
    ctx.observe('n-opens-create-a-world', sheet.visible && same([...sheet.presets].sort(), served) && sheet.description_first,
      { sheet, served });
    await ctx.screenshot('create-a-world', 'Create a world, opened from Your worlds with N');
    await ctx.page.key('Escape', 'Escape');
    await sleep(PAGE_SETTLE_MS);
    const closed = await ctx.page.evaluate(`!(${RECIPES}?.checkVisibility() ?? false) && !!${SAVED_WORLD_LIST}?.checkVisibility()`);
    ctx.observe('escape-returns-to-your-worlds', closed, { closed });
  },
  async 'worlds-look'(ctx) {
    // N1.m: the town's tiles are baked first, read from its entry, so the page draws rather than waits.
    const town = ctx.facts.town_entry_id;
    if (!town) throw new Error('N1.l made no town to open');
    const deadline = Date.now() + BAKE_MS;
    let tiles = [];
    while (Date.now() < deadline) {
      tiles = (await ctx.api('GET', `/world-entries/${town}`)).body?.generated_ground?.tiles ?? [];
      if (tiles.length > 0 && tiles.every((t) => t.state !== 'baking')) break;
      await sleep(BAKE_LOOK_MS);
    }
    ctx.observe('town-tiles-baked', tiles.length > 0 && tiles.every((t) => t.state === 'baked'),
      { states: tiles.map((t) => t.state) });
    const title = (await ctx.api('GET', `/world-entries/${town}`)).body?.title ?? null;
    const seen = [];
    for (const { query, look } of LOOKS) {
      await enter(ctx, () => ctx.page.navigate(`${ctx.runtime.app_url}${query}`), town);
      const stated = await ctx.page.waitFor(WORLD_LOOK, SETTLE_MS * 2, `the town's look for "${query}"`);
      const opened = await ctx.page.evaluate(`document.querySelector('input[aria-label="World title"]')?.value ?? null`);
      const read = JSON.parse(stated);
      seen.push({ query, stated: read, opened });
      ctx.observe(`look${query || '-default'}`, read?.pack === look.pack && read?.drawn === look.drawn && read?.reason === look.reason && opened === title, { query, stated: read, expected: look, opened, title });
      await ctx.screenshot(`look${query.replace(/[^a-z]/g, '-') || '-default'}`, `the town opened with "${query || 'no look named'}"`);
    }
    // The check can tell the looks apart: the three addresses stated three different looks.
    ctx.observe('looks-differ', new Set(seen.map((one) => JSON.stringify([one.stated?.pack, one.stated?.drawn]))).size === LOOKS.length,
      { stated: seen.map((one) => one.stated) });
    ctx.facts.town_looks = seen;
  },
  async 'worlds-values'(ctx) {
    // N1.n: View values on the town opens Create a world with the town's own values.
    const town = ctx.facts.town_entry_id;
    if (!town) throw new Error('N1.l made no town to show');
    const before = (await ctx.api('GET', `/world-entries/${town}`)).body;
    const values = before?.generated_ground?.values ?? null;
    ctx.observe('town-states-its-values', values !== null && Object.keys(values).length > 0,
      { recipe_key: before?.generated_ground?.recipe_key ?? null, keys: values === null ? null : Object.keys(values).length });
    const surface = await enter(ctx, () => ctx.page.navigate(ctx.runtime.app_url), undefined, { choose: false });
    if (surface !== 'list' && surface !== 'gate') throw new Error(`the page opened on ${surface}, not Your worlds`);
    // Choose the town's card with the arrows, as N1.l does, then press View values.
    const ids = await ctx.page.evaluate(`${SAVED_WORLD_CARDS}.map(b => b.dataset.entryId ?? null)`);
    const index = ids.indexOf(town);
    if (index < 0) throw new Error('Your worlds does not list the town');
    await ctx.page.evaluate(`${SAVED_WORLD_CARDS}[0].focus()`);
    for (let i = 0; i < index; i += 1) await ctx.page.key('ArrowRight', 'ArrowRight');
    await sleep(PAGE_SETTLE_MS);
    const current = await ctx.page.evaluate(`${SAVED_WORLD_CARDS}.find(b => b.getAttribute('aria-current') === 'true')?.dataset.entryId ?? null`);
    ctx.observe('town-chosen', current === town, { current, town });
    await ctx.page.click(`document.querySelector('main.world-entry-gate [data-action="worlds.values"]')`, 'View values');
    await ctx.page.waitFor(`(${RECIPES}?.querySelectorAll('[data-parameter]').length ?? 0) > 0
      && !(document.querySelector('p.world-recipes-origin')?.hidden ?? true) ? true : null`, SETTLE_MS, 'Create a world with the town\'s values');
    await sleep(PAGE_SETTLE_MS);
    const shown = await ctx.page.evaluate(`(() => { const r = ${RECIPES};
      return { visible: !!r && r.checkVisibility(), origin: r.querySelector('p.world-recipes-origin')?.textContent ?? null,
        controls: [...r.querySelectorAll('[data-parameter]')].map(i => ({ key: i.dataset.parameter, kind: i.tagName.toLowerCase(),
          value: i.value, step: i.getAttribute('step') })) }; })()`);
    // A range is drawn snapped to its step, so it holds the value within half a step; a choice exactly.
    const held = (control, from = values) => {
      const wanted = from?.[control.key];
      if (control.kind === 'select') return control.value === String(wanted);
      return typeof wanted === 'number' && Math.abs(Number(control.value) - wanted) <= Number(control.step ?? 1) / 2;
    };
    const mismatched = shown.controls.filter((c) => !held(c)).map((c) => ({ ...c, wanted: values?.[c.key] ?? null }));
    ctx.observe('values-from-the-town', shown.visible && (shown.origin ?? '').includes(before?.title ?? '\u0000')
      && same(shown.controls.map((c) => c.key).sort(), Object.keys(values ?? {}).sort()) && mismatched.length === 0,
    { origin: shown.origin, title: before?.title ?? null, controls: shown.controls.length, keys: Object.keys(values ?? {}).length, mismatched });
    // The comparison can fail: against the town's values with the first control's value altered
    // (a range moved ten steps, a choice renamed) that control does not hold.
    const first = shown.controls[0];
    const altered = first === undefined ? null : { ...values, [first.key]: first.kind === 'select'
      ? `${values?.[first.key]}-altered` : Number(values?.[first.key]) + 10 * Number(first.step ?? 1) };
    ctx.observe('altered-values-not-held', altered !== null && !held(first, altered), { key: first?.key ?? null });
    await ctx.screenshot('values', 'Create a world holding the town\'s own values');
    await ctx.page.key('Escape', 'Escape');
    await sleep(PAGE_SETTLE_MS);
    const closed = await ctx.page.evaluate(`!(${RECIPES}?.checkVisibility() ?? false) && !!${SAVED_WORLD_LIST}?.checkVisibility()`);
    const after = (await ctx.api('GET', `/world-entries/${town}`)).body;
    ctx.observe('escape-returns-to-your-worlds', closed, { closed });
    ctx.observe('town-unchanged', same(after, before), { changed: !same(after, before) });
  },
  async 'journey-open'(ctx) {
    await open(ctx);
    const { entries, entry } = await savedWorld(ctx);
    ctx.observe('starter-open', entries.length === 1 && entry?.source_kind === 'authored', { entries: entries.length, entry_id: entry?.entry_id });
    Object.assign(ctx.facts, { entry_id: entry.entry_id, world_id: entry.world_id, version_id: entry.authored_version_id });
    await ctx.screenshot('open', 'the starter world, open in the production build');
  },
  async 'journey-stall'(ctx) {
    const { placed } = await place(ctx, 'cc0.market-stall');
    ctx.facts.stall_object_id = placed?.object_id ?? null;
    // Move the stall aside, through the same panel, so the bench gets a spot of its own.
    const before = await savedWorld(ctx);
    await ctx.page.click(`(${ROW}).querySelector('button.object-placement-choose')`, 'the stall in the list');
    for (let press = 0; press < MOVE_PRESSES; press += 1) {
      await ctx.page.key(MOVE_KEY, MOVE_KEY);
      await sleep(150);
    }
    await ctx.page.click(ACTION('objects.save-move', OBJECT_PANEL), 'Save position');
    await confirmation(ctx.page, 'the move');
    await confirm(ctx.page, 'the move');
    const after = await waitForEdit(ctx, before.version.edit_seq, 'the move to be saved');
    ctx.observe('stall-moved-aside', after.version.edits.at(-1)?.kind === 'move_object',
      { newest_edit: after.version.edits.at(-1) });
    await ctx.page.click(ACTION('panel.close', OBJECT_PANEL), 'Close the objects panel').catch(() => null);
  },
  async 'journey-people'(ctx) {
    await openPeopleNearby(ctx.page);
    await ctx.page.waitFor(`['absent', 'present'].includes(${PEOPLE}?.dataset.state)`, SETTLE_MS, 'People nearby to read the society');
    await ctx.page.click(ACTION('people.bring-in', PEOPLE), 'Bring people in');
    await ctx.page.waitFor(`${PEOPLE}?.dataset.state === 'present'`, SETTLE_MS, 'the inhabitants to be present');
    const { entry } = await savedWorld(ctx);
    const society = (await ctx.api('GET', societyPath(entry))).body;
    const created = await traffic(ctx, 'POST', '/society');
    ctx.observe('people-brought-in', (society?.state?.inhabitants ?? []).length > 0
      && created.some((r) => r.status === 200),
    { population: society?.population_size ?? null, requests: created.map((r) => [r.path, r.status]) });
    await ctx.screenshot('people', 'People here after Bring people in');
  },
  async 'journey-bench'(ctx) {
    const { placed, edit } = await place(ctx, 'cc0.bench');
    Object.assign(ctx.facts, { bench_object_id: placed?.object_id ?? null, bench_edit_id: edit?.edit_id ?? null,
      bench_edit_seq: edit?.edit_seq ?? null });
    await ctx.page.click(ACTION('panel.close', OBJECT_PANEL), 'Close the objects panel').catch(() => null);
  },
  async 'journey-response'(ctx) {
    await openPeopleNearby(ctx.page);
    const { entry } = await savedWorld(ctx);
    let rest = null;
    let minutes = 0;
    while (rest === null && minutes < MINUTES_MOST) {
      await ctx.page.waitFor(`(() => { const b = ${ACTION('clock.advance', PEOPLE)}; return !!b && !b.disabled; })()`,
        SETTLE_MS, 'Next minute to be offered');
      await ctx.page.click(ACTION('clock.advance', PEOPLE), 'Next minute');
      minutes += 1;
      await sleep(PAGE_SETTLE_MS);
      const events = (await ctx.api('GET', societyPath(entry, '/events', '&limit=256'))).body?.events ?? [];
      rest = events.find((e) => e.event_kind === 'action_completed'
        && (e.document?.target ?? {}).object_id === ctx.facts.bench_object_id) ?? null;
    }
    const stepped = await traffic(ctx, 'POST', '/society');
    ctx.observe('page-advanced-minutes', stepped.filter((r) => r.status === 200).length >= minutes,
      { minutes, posts: stepped.map((r) => [r.path, r.status]).slice(-5) });
    ctx.observe('rest-at-the-bench', rest !== null,
      rest === null ? { minutes } : { subject: rest.subject_id, tick: rest.tick, input_seq: rest.document.input_seq, minutes });
    if (rest !== null) Object.assign(ctx.facts, { rested_subject: rest.subject_id, rest_input_seq: rest.document.input_seq });
    await ctx.screenshot('response', 'People nearby once someone has rested at the bench');
  },
  async 'journey-why'(ctx) {
    await openPeopleNearby(ctx.page);
    const subject = ctx.facts.rested_subject;
    const nearby = await ctx.page.evaluate(`[...(${INSPECT})?.options ?? []].map(o => o.value).filter(Boolean)`);
    ctx.observe('rested-person-nearby', nearby.includes(subject), { subject, nearby: nearby.length });
    await ctx.page.setValue(INSPECT, subject);
    await ctx.page.waitFor(`${INSPECTOR}?.checkVisibility() ?? false`, 10_000, 'the inspector');
    await sleep(PAGE_SETTLE_MS);
    const seen = await inspectorSeen(ctx.page);
    const words = whyWords();
    const button = `[...document.querySelectorAll('button.world-inhabitants-ask')].find(b => b.textContent.trim() === ${JSON.stringify(words)} && b.checkVisibility())`;
    await ctx.page.click(button, words);
    const deadline = Object.values(plan.runtime.page_deadlines_ms ?? {}).reduce((t, ms) => t + ms, 0) + 15_000;
    // This question's own reply, as the rehearsal's ask waits for it: the route's response first,
    // then the answer drawn. A speech face an earlier step left is already on the page.
    const until = Date.now() + deadline;
    let posted = [];
    while (Date.now() < until) {
      posted = (await traffic(ctx, 'POST', '/selection/ask')).filter((r) => r.status !== null);
      if (posted.length > 0) break;
      await sleep(250);
    }
    const asked = posted.length > 0 && await ctx.page.waitFor(
      `['answer', 'failed'].includes(document.querySelector('aside.companion-encounter .companion-speech')?.dataset.mode)
        && document.querySelector('aside.companion-encounter')?.dataset.answering !== 'asking'`,
      30_000, 'the Companion to draw its reply').catch(() => false);
    const last = posted.at(-1) ?? null;
    const body = last?.request_body ?? {};
    const citations = Object.values(last?.response_body?.simulation ?? {});
    const atBench = citations.filter((c) => c.object_id === ctx.facts.bench_object_id);
    ctx.observe('why-asked-from-the-inspector', seen?.subject === subject && last?.status === 200
      && body?.plan?.intent === 'society' && body?.plan?.society?.aspect === 'why'
      && body?.society_context?.inhabitant_id === subject,
    { inspector: seen, status: last?.status ?? null, plan: body?.plan ?? null, society_context: body?.society_context ?? null });
    ctx.observe('answer-cites-the-bench-and-its-edit', atBench.length > 0 && atBench.every((c) =>
      c.result_kind === 'simulation_event' && c.input_seq != null
      && c.edit_id === ctx.facts.bench_edit_id && c.edit_seq === ctx.facts.bench_edit_seq),
    { bench: ctx.facts.bench_object_id, edit: [ctx.facts.bench_edit_id, ctx.facts.bench_edit_seq], citations: atBench });
    ctx.observe('answer-drawn', asked === true, { drawn: asked === true });
    await ctx.screenshot('why', 'the Companion answering why the person went to the bench');
  },
};

try {
  page = await openBrowser({
    port: plan.runtime.browser_port,
    profile: join(out, 'chrome-profile'),
    appOrigin: new URL(plan.runtime.app_url).origin,
    flags: plan.runtime.chrome_flags,
  });
  report.chrome_argv = page.argv;
  for (const id of STEPS) {
    current = id;
    const evidence = { screenshots: [], api: [], network: [], console: [], notes: [] };
    const observations = [];
    const started = new Date().toISOString();
    page.label(id);
    let status = 'passed';
    let failure = null;
    const ctx = context(id, evidence, observations);
    try {
      await STEP_HANDLERS[id](ctx);
      const broken = observations.filter((o) => !o.ok).map((o) => o.id);
      if (broken.length > 0) { status = 'failed'; failure = `did not hold: ${broken.join(', ')}`; }
    } catch (error) {
      status = 'failed';
      failure = String(error?.stack ?? error).split('\n').slice(0, 4).join(' | ');
    }
    if (status === 'failed') {
      await ctx.screenshot('at-failure', 'the page when the step failed').catch(() => null);
    } else if (evidence.screenshots.length === 0) {
      await ctx.screenshot('end', 'the page when the step ended').catch(() => null);
    }
    if (evidence.screenshots.length === 0) {
      status = 'failed';
      failure = failure ? `${failure}; no screenshot was captured` : 'no screenshot was captured';
    }
    evidence.network = await page.traffic(id);
    evidence.console = page.console(id);
    report.outcomes[id] = { status, reason: failure, observations, evidence, started_at: started,
      finished_at: new Date().toISOString() };
    write();
    console.log(`${status.toUpperCase()} ${id}${failure ? `: ${failure.slice(0, 300)}` : ''}`);
    if (status === 'failed') break;
  }
  current = null;
  await finish(0, 'an earlier step of the journey failed');
} catch (error) {
  await finish(1, `the page session failed: ${String(error?.message ?? error).slice(0, 400)}`);
}
