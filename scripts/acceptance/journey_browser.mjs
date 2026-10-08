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
// look (N1.m), its values shown in Create a world (N1.n) and its look chosen in the Look sheet (N1.o);
// then what the shell states of the look that Use drew (N1.p) and browsing looks live (N1.q); then a
// town made in a look chosen in Create a world (N1.r) and a town kept in an earlier look version (N1.u).
const MAIN_STEPS = ['worlds-first', 'journey-open', 'journey-stall', 'journey-people', 'journey-bench',
  'journey-response', 'journey-why', 'worlds-create', 'worlds-look', 'worlds-values', 'worlds-look-sheet', 'worlds-look-stated',
  'worlds-look-browse', 'worlds-create-look', 'worlds-look-earlier'];
// The people session (a stack with a scripted model): a person's card and its mind changed in two
// clicks (N1.s), then the mark over that person (N1.t).
const PEOPLE_STEPS = ['people-card', 'people-marks'];
// The world the people session opens: the workspace's starter with a stall placed, so its people
// have somewhere to go and stand near where a person arrives (as N1.h prepares it; A-101).
const PEOPLE_STARTER = { title: 'Q10 people' };
const PEOPLE_STALL = { asset: 'cc0.market-stall', subject: 'stall', at: [6000, 0, 0] };
const PEOPLE_SOCIETY = { region_id: 'region:starter', profile: 'exulanica-society/v2' };
// The second saved world N1.l makes through the API, so Your worlds lists two.
const SECOND_WORLD_TITLE = 'Q10 second world';
const SECOND_WORLD_RECIPE = 'small_town';
// Create a world, as Your worlds opens it.
const RECIPES = `document.querySelector('section.world-recipes')`;
// What the shell states of a generated world's look (docs/style-pack-contract.md): the pack asked
// for, whether it was drawn and why not, as JSON.
const WORLD_LOOK = `document.querySelector('#shell')?.getAttribute('data-world-look') ?? null`;
// N1.m (A-65, A-69, A-87): the town opened with no look named, with the tile look and with the toon
// pack, and what the shell states for each, from the contract's words for the team's packs; then, once
// the town's own appearance names the toon pack, opened with no look named. A town is made naming the
// library's default pack (cozy), so with no look named it states that pack chosen by the world.
const LOOKS = [
  { query: '', look: { pack: 'exulanica.cozy-town', source: 'world', drawn: true, reason: null } },
  { query: '?look=today', look: { pack: null, source: 'address', drawn: false, reason: null } },
  { query: '?look=toon', look: { pack: 'exulanica.toon-town', source: 'address', drawn: true, reason: null } },
];
const WORLD_LOOK_CASE = { query: '', look: { pack: 'exulanica.toon-town', source: 'world', drawn: true, reason: null } };
const sameLook = (read, look) => read?.pack === look.pack && read?.source === look.source
  && read?.drawn === look.drawn && read?.reason === look.reason;
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
const STEPS = plan.session.steps ?? MAIN_STEPS;
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
    const openIn = async (query, look, name) => {
      await enter(ctx, () => ctx.page.navigate(`${ctx.runtime.app_url}${query}`), town);
      const stated = await ctx.page.waitFor(WORLD_LOOK, SETTLE_MS * 2, `the town's look for "${query}"`);
      const opened = await ctx.page.evaluate(`document.querySelector('input[aria-label="World title"]')?.value ?? null`);
      const read = JSON.parse(stated);
      seen.push({ query, stated: read, opened });
      ctx.observe(name, sameLook(read, look) && opened === title, { query, stated: read, expected: look, opened, title });
      await ctx.screenshot(name.replace(/[^a-z-]/g, '-'), `the town opened with "${query || 'no look named'}"`);
    };
    for (const { query, look } of LOOKS) await openIn(query, look, `look${query || '-default'}`);
    // The check can tell the looks apart: the three addresses stated three different looks.
    ctx.observe('looks-differ', new Set(seen.map((one) => JSON.stringify([one.stated?.pack, one.stated?.drawn]))).size === LOOKS.length,
      { stated: seen.map((one) => one.stated) });
    // A-69: the town's own appearance names the toon pack, as the library lists it, through a
    // whole-world preview and its apply; opened with no look named, the page draws the world's pack.
    const entry = (await ctx.api('GET', `/world-entries/${town}`)).body;
    const query = `?world_id=${encodeURIComponent(entry?.world_id ?? '')}`;
    const listed = ((await ctx.api('GET', '/world/style-packs')).body?.packs ?? []).find((p) => p.pack_id === 'exulanica.toon-town');
    const current = (await ctx.api('GET', `/world/styles/current${query}`)).body;
    const held = current?.current ?? {};
    const preview = await ctx.api('POST', `/world/styles/previews${query}`, {
      proposal_id: crypto.randomUUID(), origin: 'settings', origin_reference: 'q10-n1m', scope: { kind: 'global' },
      base_style_version_id: held.version_id, base_topology_digest: current?.current_topology_digest,
      profile: { profile_id: held.global_style?.profile_id, profile_version: held.global_style?.profile_version, parameters: held.global_style?.parameters ?? {} },
      style_pack: { pack_id: listed?.pack_id, version: listed?.version, manifest_sha256: listed?.manifest_sha256 },
    });
    // Applied as the page applies it, moving the saved entry to the new version, so the town opens in it.
    const applied = await ctx.api('POST', `/world/styles/previews/${preview.body?.preview_id}/apply${query}`, {
      base_style_version_id: held.version_id, base_topology_digest: current?.current_topology_digest,
      saved_entry: { entry_id: entry?.entry_id, base_revision: entry?.revision, authored_state_sha256: entry?.authored_state_sha256,
        authored_edit_seq: entry?.authored_edit_seq, style_version_id: entry?.style_version_id },
    });
    ctx.observe('town-names-the-toon-pack', preview.status === 201 && applied.status === 200
      && applied.body?.style_pack?.pack_id === 'exulanica.toon-town', { preview: preview.status, apply: applied.status, style_pack: applied.body?.style_pack ?? null });
    await openIn(WORLD_LOOK_CASE.query, WORLD_LOOK_CASE.look, 'look-world');
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
  async 'worlds-look-sheet'(ctx) {
    // N1.o (A-74): in the town, Design opens with O; Change look opens the Look sheet over it.
    const town = ctx.facts.town_entry_id;
    if (!town) throw new Error('N1.l made no town to dress');
    await enter(ctx, () => ctx.page.navigate(ctx.runtime.app_url), town);
    await ctx.page.waitFor(WORLD_LOOK, SETTLE_MS * 2, 'the town drawn in its look');
    const origin = await ctx.page.evaluate('performance.timeOrigin');
    await ctx.page.key('KeyO', 'o', { text: 'o' });
    await ctx.page.click(ACTION('look.open'), 'Change look');
    const SHEET = `document.querySelector('section.look-sheet')`;
    await ctx.page.waitFor(`(${SHEET}?.querySelectorAll('button.look-sheet-card').length ?? 0) > 0 ? true : null`,
      SETTLE_MS, 'the Look sheet to offer its packs');
    const listed = (await ctx.api('GET', '/world/style-packs')).body?.packs ?? [];
    const cards = await ctx.page.evaluate(`[...${SHEET}.querySelectorAll('button.look-sheet-card')].map(b => ({
      pack: b.dataset.packId ?? null, picture: !!b.querySelector('.look-sheet-picture img') }))`);
    ctx.observe('sheet-offers-the-library', same(cards.map((c) => c.pack).sort(), listed.map((p) => p.pack_id).sort())
      && cards.every((c) => c.picture === (listed.find((p) => p.pack_id === c.pack)?.preview_sha256 != null))
      && cards.every((c) => c.picture), { cards, listed: listed.map((p) => [p.pack_id, p.preview_sha256 ?? null]) });
    await ctx.screenshot('look-sheet', 'the Look sheet over the town');
    await ctx.page.click(`${SHEET}.querySelector('button.look-sheet-card[data-pack-id="exulanica.cozy-town"]')`, 'the cozy look');
    await ctx.page.click(ACTION('look.use', SHEET), 'Use this look');
    // A-74 as amended: what a person sees, the sheet's own words for what it drew. The shell's
    // data-world-look is recorded here as it stands; N1.p expects it (A-76).
    const title = listed.find((p) => p.pack_id === 'exulanica.cozy-town')?.title ?? 'exulanica.cozy-town';
    const said = await ctx.page.waitFor(`(() => { const t = ${SHEET}?.querySelector('p.look-sheet-status')?.textContent ?? '';
      return /is now drawn in|could not be drawn now/.test(t) ? t : null; })()`, SETTLE_MS * 4, 'the sheet to say what it drew');
    const unchanged = (await ctx.page.evaluate('performance.timeOrigin')) === origin;
    const attribute = await ctx.page.evaluate(WORLD_LOOK);
    ctx.facts.look_sheet_origin = origin;
    ctx.observe('use-redraws-the-open-town', said.includes(`is now drawn in ${title}`) && unchanged,
      { said, title, same_page: unchanged, data_world_look: attribute === null ? null : JSON.parse(attribute) });
    const entry = (await ctx.api('GET', `/world-entries/${town}`)).body;
    const query = `?world_id=${encodeURIComponent(entry?.world_id ?? '')}`;
    const versions = (await ctx.api('GET', `/world/styles/versions${query}`)).body ?? [];
    const named = versions.find((v) => v.version_id === entry?.style_version_id) ?? null;
    ctx.observe('entry-names-the-cozy-pack', named?.style_pack?.pack_id === 'exulanica.cozy-town',
      { style_version_id: entry?.style_version_id ?? null, style_pack: named?.style_pack ?? null });
    await ctx.screenshot('look-used', 'the town redrawn in the cozy look');
  },
  async 'worlds-look-stated'(ctx) {
    // N1.p (A-76): after N1.o's Use, the shell states the cozy pack drawn by the redraw; once the
    // town is opened again, drawn because the world names it.
    const town = ctx.facts.town_entry_id;
    const settled = async (wanted) => {
      const deadline = Date.now() + SETTLE_MS;
      let read = null;
      while (Date.now() < deadline) {
        const value = await ctx.page.evaluate(WORLD_LOOK);
        read = value === null ? null : JSON.parse(value);
        if (sameLook(read, wanted)) break;
        await sleep(PAGE_SETTLE_MS);
      }
      return read;
    };
    const redrawn = { pack: 'exulanica.cozy-town', source: 'redraw', drawn: true, reason: null };
    const afterUse = await settled(redrawn);
    const unchanged = (await ctx.page.evaluate('performance.timeOrigin')) === ctx.facts.look_sheet_origin;
    ctx.observe('stated-after-use', sameLook(afterUse, redrawn) && unchanged,
      { stated: afterUse, expected: redrawn, same_page: unchanged });
    await enter(ctx, () => ctx.page.navigate(ctx.runtime.app_url), town);
    const named = { pack: 'exulanica.cozy-town', source: 'world', drawn: true, reason: null };
    const reopened = await settled(named);
    ctx.observe('stated-after-reopening', sameLook(reopened, named), { stated: reopened, expected: named });
    await ctx.screenshot('look-stated', 'the town opened again in the look it names');
  },
  async 'worlds-look-browse'(ctx) {
    // N1.q (A-81): the town open in cozy (N1.p reopened it); the Look sheet open and live, resting on
    // the toon card draws the town in toon; Escape closes the sheet and draws the world's own cozy.
    const town = ctx.facts.town_entry_id;
    const SHEET = `document.querySelector('section.look-sheet')`;
    const lookIs = (pack, source) => `(() => { const v = ${WORLD_LOOK}; if (!v) return null;
      const r = JSON.parse(v); return r.pack === ${JSON.stringify(pack)} && r.source === ${JSON.stringify(source)} && r.drawn ? v : null; })()`;
    await ctx.page.key('KeyO', 'o', { text: 'o' });
    await ctx.page.click(ACTION('look.open'), 'Change look');
    const live = await ctx.page.waitFor(`${SHEET}?.dataset.live ?? null`, SETTLE_MS, 'the Look sheet to say whether it is live');
    ctx.observe('sheet-is-live', live === 'true', { live });
    await ctx.page.click(`${SHEET}.querySelector('button.look-sheet-card[data-pack-id="exulanica.toon-town"]')`, 'the toon look');
    const browsed = await ctx.page.waitFor(lookIs('exulanica.toon-town', 'redraw'), SETTLE_MS * 2, 'the town drawn in toon')
      .catch(() => null);
    ctx.observe('resting-draws-the-look', browsed !== null, { stated: browsed === null ? await ctx.page.evaluate(WORLD_LOOK) : JSON.parse(browsed) });
    await ctx.screenshot('browsing-toon', 'the town drawn in toon behind the Look sheet');
    await ctx.page.key('Escape', 'Escape');
    const restored = await ctx.page.waitFor(lookIs('exulanica.cozy-town', 'redraw'), SETTLE_MS * 2, 'the town drawn in its own look again')
      .catch(() => null);
    const closed = await ctx.page.evaluate(`!(${SHEET}?.checkVisibility() ?? false)`);
    ctx.observe('escape-restores-the-world-look', restored !== null && closed,
      { stated: restored === null ? await ctx.page.evaluate(WORLD_LOOK) : JSON.parse(restored), closed });
    const entry = (await ctx.api('GET', `/world-entries/${town}`)).body;
    const query = `?world_id=${encodeURIComponent(entry?.world_id ?? '')}`;
    const versions = (await ctx.api('GET', `/world/styles/versions${query}`)).body ?? [];
    const named = versions.find((v) => v.version_id === entry?.style_version_id) ?? null;
    ctx.observe('entry-still-names-cozy', named?.style_pack?.pack_id === 'exulanica.cozy-town',
      { style_version_id: entry?.style_version_id ?? null, style_pack: named?.style_pack ?? null });
    await ctx.screenshot('browse-closed', 'the town in its own look after Escape');
  },
  async 'worlds-create-look'(ctx) {
    // N1.r (A-95): Create a world shows the host's default look; Change look opens the Look sheet
    // in choosing mode, toon is chosen, the town is made in it and opens stating it.
    const listed = (await ctx.api('GET', '/world/style-packs')).body?.packs ?? [];
    const byId = Object.fromEntries(listed.map((p) => [p.pack_id, p]));
    const fallback = listed.find((p) => p.default) ?? null;
    const before = new Set(((await ctx.api('GET', '/world-entries')).body ?? []).map((e) => e.entry_id));
    // Your worlds through the World menu, as N1.l returns to it (a page load reopens the last world).
    await enter(ctx, () => chooseMenu(ctx.page, 'worlds'), undefined, { choose: false });
    await ctx.page.waitFor(`${SAVED_WORLD_LIST}?.checkVisibility() ? true : null`, SETTLE_MS, 'Your worlds');
    await ctx.page.evaluate(`${SAVED_WORLD_CARDS}[0].focus()`);
    await ctx.page.key('KeyN', 'n', { text: 'n' });
    const ROW = `document.querySelector('section.world-recipes .look-row')`;
    const rowTitle = `(() => { const r = ${ROW}; return r && !r.hidden ? r.querySelector('.look-row-title')?.textContent ?? null : null; })()`;
    const shown = await ctx.page.waitFor(rowTitle, SETTLE_MS, 'the Look row to name the default look');
    ctx.observe('row-names-the-default', fallback !== null && shown === fallback.title, { shown, default: fallback?.pack_id ?? null });
    await ctx.page.click(ACTION('look.change', `document.querySelector('section.world-recipes')`), 'Change look');
    const SHEET = `document.querySelector('section.look-sheet')`;
    await ctx.page.waitFor(`(${SHEET}?.querySelectorAll('button.look-sheet-card').length ?? 0) > 0 ? true : null`,
      SETTLE_MS, 'the Look sheet in choosing mode');
    const words = await ctx.page.evaluate(`${SHEET}.querySelector('button.look-sheet-use span')?.textContent ?? null`);
    await ctx.page.click(`${SHEET}.querySelector('button.look-sheet-card[data-pack-id="exulanica.toon-town"]')`, 'the toon look');
    await ctx.page.click(ACTION('look.use', SHEET), 'Choose this look');
    const toonTitle = byId['exulanica.toon-town']?.title ?? 'exulanica.toon-town';
    const chosen = await ctx.page.waitFor(`(() => { const t = ${rowTitle}; return t === ${JSON.stringify(toonTitle)} ? t : null; })()`,
      SETTLE_MS, 'the Look row to name the chosen look');
    const line = await ctx.page.evaluate(`${ROW}?.querySelector('.look-row-line')?.textContent ?? null`);
    ctx.observe('chosen-in-the-sheet', words === 'Choose this look' && chosen === toonTitle && (line ?? '').startsWith('Your choice'),
      { use_words: words, row: chosen, line });
    await ctx.screenshot('look-chosen', 'Create a world with the toon look chosen');
    await ctx.page.click(`document.querySelector('section.world-recipes button.world-recipes-choice[data-recipe="small_town"]')`, 'the small town');
    await ctx.page.waitFor(`document.querySelector('section.world-recipes button.world-recipes-make')?.hidden === false ? true : null`,
      SETTLE_MS, 'Create this town to be offered');
    await ctx.page.click(`document.querySelector('section.world-recipes button.world-recipes-make')`, 'Create this town');
    const made = await ctx.page.waitFor(`(() => { const v = ${WORLD_LOOK}; if (!v) return null; const r = JSON.parse(v);
      return r.pack === 'exulanica.toon-town' && r.source === 'world' && r.drawn ? v : null; })()`, BAKE_MS, 'the new town drawn in toon')
      .catch(() => null);
    ctx.observe('town-drawn-in-the-chosen-look', made !== null, { stated: made === null ? await ctx.page.evaluate(WORLD_LOOK) : JSON.parse(made) });
    const entries = (await ctx.api('GET', '/world-entries')).body ?? [];
    const fresh = entries.filter((e) => !before.has(e.entry_id));
    const entry = fresh.length === 1 ? (await ctx.api('GET', `/world-entries/${fresh[0].entry_id}`)).body : null;
    const query = `?world_id=${encodeURIComponent(entry?.world_id ?? '')}`;
    const versions = entry === null ? [] : (await ctx.api('GET', `/world/styles/versions${query}`)).body ?? [];
    const named = versions.find((v) => v.version_id === entry?.style_version_id) ?? null;
    ctx.observe('entry-names-toon', fresh.length === 1 && named?.style_pack?.pack_id === 'exulanica.toon-town',
      { made: fresh.map((e) => e.entry_id), style_pack: named?.style_pack ?? null });
    await ctx.screenshot('made-in-toon', 'the town made in the chosen look');
  },
  async 'worlds-look-earlier'(ctx) {
    // N1.u (A-98): a town made (through the API) in the cozy pack's earliest published version; its
    // Look sheet shows that version as Now and offers the current version by number; nothing applied.
    const listed = (await ctx.api('GET', '/world/style-packs')).body?.packs ?? [];
    const cozy = listed.find((p) => p.pack_id === 'exulanica.cozy-town') ?? null;
    const oldest = [...(cozy?.earlier_versions ?? [])].sort((a, b) => a.version - b.version)[0] ?? null;
    if (cozy === null || oldest === null) throw new Error('the library lists no earlier cozy version');
    const binding = { pack_id: cozy.pack_id, version: oldest.version, manifest_sha256: oldest.manifest_sha256 };
    const made = await ctx.api('POST', '/worlds/generated', { recipe: 'small_town', title: 'Q10 earlier look', style_pack: binding });
    ctx.observe('town-made-in-an-earlier-version', made.status === 201, { status: made.status, binding });
    const town = made.body?.entry_id;
    const deadline = Date.now() + BAKE_MS;
    while (Date.now() < deadline) {
      const tiles = (await ctx.api('GET', `/world-entries/${town}`)).body?.generated_ground?.tiles ?? [];
      if (tiles.length > 0 && tiles.every((t) => t.state !== 'baking')) break;
      await sleep(BAKE_LOOK_MS);
    }
    await enter(ctx, () => ctx.page.navigate(ctx.runtime.app_url), town);
    await ctx.page.waitFor(WORLD_LOOK, SETTLE_MS * 2, 'the town drawn in its look');
    await ctx.page.key('KeyO', 'o', { text: 'o' });
    await ctx.page.click(ACTION('look.open'), 'Change look');
    const SHEET = `document.querySelector('section.look-sheet')`;
    await ctx.page.waitFor(`(${SHEET}?.querySelectorAll('button.look-sheet-card').length ?? 0) > 0 ? true : null`,
      SETTLE_MS, 'the Look sheet to offer its packs');
    const read = () => ctx.page.evaluate(`(() => { const s = ${SHEET};
      return { cards: [...s.querySelectorAll('button.look-sheet-card')].map(b => ({ pack: b.dataset.packId ?? null,
        version: b.dataset.version ?? null, caption: b.querySelector('.look-sheet-caption')?.textContent ?? null })),
        use: s.querySelector('button.look-sheet-use')?.hidden ? null : s.querySelector('button.look-sheet-use span')?.textContent ?? null,
        keep: s.querySelector('button.look-sheet-keep span')?.textContent ?? null,
        version_line: s.querySelector('.look-sheet-version')?.textContent ?? null }; })()`);
    const atNow = await read();
    const nowCard = atNow.cards.find((c) => c.version === String(oldest.version)) ?? null;
    const nowIndex = atNow.cards.indexOf(nowCard);
    const next = atNow.cards[nowIndex + 1] ?? null;
    ctx.observe('earlier-version-is-now', nowCard !== null && nowCard.pack === 'exulanica.cozy-town'
      && nowCard.caption === `Now · version ${oldest.version}` && next?.pack === 'exulanica.cozy-town'
      && next?.version === null && next?.caption === `Version ${cozy.version}`
      && atNow.keep === `Keep version ${oldest.version}` && atNow.use === null
      && (atNow.version_line ?? '').includes(`This world is drawn in version ${oldest.version}.`), { read: atNow, oldest: oldest.version, current: cozy.version });
    await ctx.screenshot('earlier-now', 'the Look sheet with the earlier version as Now');
    await ctx.page.click(`${SHEET}.querySelector('button.look-sheet-card[data-pack-id="exulanica.cozy-town"]:not([data-version])')`, 'the current cozy version');
    await sleep(PAGE_SETTLE_MS);
    const atCurrent = await read();
    ctx.observe('current-version-offered-by-number', atCurrent.use === `Use version ${cozy.version}`, { read: atCurrent });
    await ctx.page.key('Escape', 'Escape');
    await sleep(PAGE_SETTLE_MS);
    const entry = (await ctx.api('GET', `/world-entries/${town}`)).body;
    const query = `?world_id=${encodeURIComponent(entry?.world_id ?? '')}`;
    const versions = (await ctx.api('GET', `/world/styles/versions${query}`)).body ?? [];
    const named = versions.find((v) => v.version_id === entry?.style_version_id) ?? null;
    ctx.observe('town-keeps-the-earlier-version', same(named?.style_pack ?? null, binding), { style_pack: named?.style_pack ?? null, binding });
  },
  async 'people-card'(ctx) {
    // N1.s (A-96, A-101): the starter with a stall and its people; a person chosen in the inspector
    // shows their card with their mind; Change then a model changes it in two clicks, said on the
    // card and read from the API.
    const made = await ctx.api('POST', '/world-entries/starter', PEOPLE_STARTER);
    if (made.status !== 200) throw new Error(`the starter answered ${made.status}`);
    const town = made.body.entry_id;
    const read = async () => (await ctx.api('GET', `/world-entries/${town}`)).body;
    let entry = await read();
    const query = `?world_id=${encodeURIComponent(entry.world_id)}`;
    const [x_mm, y_mm, z_mm] = PEOPLE_STALL.at;
    const stall = await ctx.api('POST', `/world/versions/${entry.authored_version_id}/compositions/apply${query}`, {
      base_state_sha256: entry.authored_state_sha256,
      source: { kind: 'reviewed_asset', asset_key: PEOPLE_STALL.asset },
      placement: { subject_id: PEOPLE_STALL.subject, region_id: PEOPLE_SOCIETY.region_id,
        transform: { x_mm, y_mm, z_mm, yaw_microradians: 0, scale_milli: 1000 }, origin_role: 'fictional' },
      saved_entry: { entry_id: entry.entry_id, base_revision: entry.revision,
        authored_state_sha256: entry.authored_state_sha256, authored_edit_seq: entry.authored_edit_seq },
    });
    entry = await read();
    const brought = await ctx.api('POST', `/world/versions/${entry.authored_version_id}/society${query}`, PEOPLE_SOCIETY);
    ctx.observe('people-brought-in', [200, 201].includes(stall.status) && [200, 201].includes(brought.status),
      { stall: stall.status, society: brought.status });
    await enter(ctx, () => ctx.page.navigate(ctx.runtime.app_url), town);
    await openPeopleNearby(ctx.page);
    const nearby = await ctx.page.waitFor(`(() => { const o = [...(${INSPECT})?.options ?? []].map(o => o.value).filter(Boolean);
      return o.length > 0 ? o : null; })()`, SETTLE_MS, 'someone nearby to choose');
    const subject = nearby[0];
    await ctx.page.setValue(INSPECT, subject);
    const CARD = `document.querySelector('section.thing-card[data-subject="${subject}"]')`;
    await ctx.page.waitFor(`${CARD}?.checkVisibility() ? true : null`, SETTLE_MS, "the person's card");
    const mindBefore = await ctx.page.evaluate(`${CARD}.querySelector('.thing-card-mind-name')?.textContent ?? null`);
    await ctx.page.click(`${CARD}.querySelector('[data-action="card.mind.change"]')`, 'Change');
    const key = await ctx.page.waitFor(`(() => { const b = [...${CARD}.querySelectorAll('[data-action="card.mind.choose"]')]
      .find(b => b.dataset.key && b.dataset.key !== 'routine' && !b.hasAttribute('data-now')); return b ? b.dataset.key : null; })()`,
      SETTLE_MS, 'a model the card offers');
    await ctx.page.click(`${CARD}.querySelector('[data-action="card.mind.choose"][data-key=${JSON.stringify(key)}]')`, 'the model');
    const outcome = await ctx.page.waitFor(`${CARD}?.querySelector('.thing-card-outcome')?.textContent || null`, SETTLE_MS, 'the card to say what changed');
    const [provider, ...rest] = key.split(' ');
    const modelId = rest.join(' ');
    entry = await read();
    const roles = (await ctx.api('GET', `/world/versions/${entry.authored_version_id}/models${query}`)).body?.roles ?? [];
    const view = roles.find((r) => r.key === 'society_decision')?.view ?? {};
    const mine = (view.choices ?? []).filter((c) => c.subject_id === subject).sort((a, b) => (b.choice_seq ?? 0) - (a.choice_seq ?? 0))[0] ?? null;
    ctx.observe('mind-changed-in-two-clicks', !!outcome && mine?.model?.provider === provider && mine?.model?.model_id === modelId,
      { subject, before: mindBefore, chosen: key, outcome, recorded: mine?.model ?? null });
    Object.assign(ctx.facts, { people_town: town, people_subject: subject, people_model: key });
    await ctx.screenshot('card-changed', "the person's card after the mind was changed");
  },
  async 'people-marks'(ctx) {
    // N1.t (A-97): the person whose mind is a model carries an AI mark over their head.
    const subject = ctx.facts.people_subject;
    const marked = await ctx.page.waitFor(`(() => { const c = document.querySelector('[data-thing-marks]');
      const pill = document.querySelector('.thing-mark-pill[data-mark="ai"][data-subject="${subject}"]');
      return c && Number(c.dataset.thingMarks) > 0 && pill ? { marks: Number(c.dataset.thingMarks), word: pill.querySelector('.thing-mark-word')?.textContent ?? null } : null; })()`,
      SETTLE_MS * 2, 'the AI mark over the person').catch(() => null);
    ctx.observe('ai-mark-over-the-person', marked !== null, { subject, marked,
      marks: await ctx.page.evaluate(`document.querySelector('[data-thing-marks]')?.dataset.thingMarks ?? null`) });
    await ctx.screenshot('marks', 'the marks over people');
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
