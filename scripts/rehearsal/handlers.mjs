// The rehearsal's browser step handlers, one per runnable browser step of steps.json, by step id.
//
// A handler performs the person's action in the page and reports every observable the step list
// declares for its step, by id, with what it saw: `ctx.observe(id, holds, observed)`. The result
// assembly fails a step that reports less or more than its data declares, so a handler cannot pass
// by checking less. Reads of the saved state go through the API with the run's token, recorded as
// the step's evidence. What a later step needs that only the page knew is kept in `ctx.facts`.
//
// Waiting: every wait names what it waits for and has a bound, so a step that cannot happen fails
// with that name instead of hanging its page session.

import { randomBytes } from 'node:crypto';
import { setTimeout as sleep } from 'node:timers/promises';

import { addUsd } from './usd.mjs';
import {
  BUTTON, OBJECT_PANEL, OPEN_CONFIRM, PLACEHOLDER, TITLE_FIELD, WORLD_READY, chooseMenu, confirm,
  confirmation, focusCanvas, liveObjects, objectRows, objectStatus, open, openObjects, reload,
  savedWorld, waitForWorld,
} from './app.mjs';

// A write the page confirms and the API then holds: the confirmed request and the read after it.
const SETTLE_MS = 30_000;
// A question to the Companion: the route's own timeout for an answer is 180 s (companion-ask-api).
const ANSWER_TIMEOUT_MS = 200_000;
// How often a wait on the API polls.
const POLL_MS = 1_000;
// A range control's step in Customize world is 0.05 (the reviewed style registry); a value read
// back is the one set when it lies within half a step.
const RANGE_TOLERANCE = 0.025;
const TERMINAL_JOB_EVENTS = new Set(['job_succeeded', 'job_failed', 'job_cancelled', 'job_missing', 'job_unavailable']);

const worldQuery = (ctx) => `world_id=${encodeURIComponent(ctx.facts.world_id)}`;
const pick = (value, keys) => (value == null ? value : Object.fromEntries(keys.map((k) => [k, value[k]])));
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

async function until(what, timeoutMs, probe) {
  const deadline = Date.now() + timeoutMs;
  let last;
  while (Date.now() < deadline) {
    last = await probe();
    if (last) return last;
    await sleep(POLL_MS);
  }
  throw new Error(`waited ${timeoutMs} ms for ${what}`);
}

/** The newest recorded response of this step's page traffic whose method and path match. */
async function response(ctx, method, pathPrefix) {
  const traffic = await ctx.page.traffic(ctx.step.id);
  return [...traffic].reverse().find((r) => r.method === method && r.path.startsWith(pathPrefix)) ?? null;
}

async function responses(ctx, method, pathPrefix) {
  return (await ctx.page.traffic(ctx.step.id)).filter((r) => r.method === method && r.path.startsWith(pathPrefix));
}

const usdOf = (execution) => (execution?.calls ?? [])
  .reduce((total, call) => (call.usd == null ? total : addUsd(total, String(call.usd))), '0');

// -- arrival -------------------------------------------------------------------------------------

const TOKEN_FIELD = `document.querySelector('form.credential-gate input[aria-label="Access token"]')`;
const ENTER = `document.querySelector('form.credential-gate button[aria-label="Enter Exulanica"]')`;

async function accessGate(ctx) {
  const { page } = ctx;
  await page.navigate(ctx.runtime.app_url);
  const first = await page.waitFor(`document.querySelector('form.credential-gate') ? 'gate' : (${WORLD_READY} ? 'world' : null)`,
    90_000, 'the credential gate');
  const gate = await page.evaluate(`(() => { const form = document.querySelector('form.credential-gate'); if (!form) return null;
    const account = form.querySelector('button.account-sign-in');
    return { token_field: !!form.querySelector('input[aria-label="Access token"]'),
      account_sign_in: account ? (account.disabled ? 'disabled' : 'enabled') : 'absent' }; })()`);
  ctx.observe('gate-shown', first === 'gate' && gate?.token_field === true && gate?.account_sign_in === 'disabled',
    { first_surface: first, ...gate });
  await ctx.screenshot('gate', 'the credential gate the production build shows on arrival');
  if (first !== 'gate') throw new Error('the application opened without its credential gate');

  // A token this instance was never given: 32 random bytes, made here and used once.
  await page.typeInto(TOKEN_FIELD, randomBytes(32).toString('base64url'));
  await page.click(ENTER, 'Enter Exulanica');
  const refusal = await page.waitFor(`(() => { const p = document.querySelector('form.credential-gate p.gate-failure');
    return p && !p.hidden && p.textContent.trim() ? p.textContent.trim() : null; })()`, 20_000,
  'the gate to answer a token it does not hold').catch(() => null);
  const openedWithWrongToken = await page.evaluate(WORLD_READY);
  ctx.observe('wrong-token-refused', refusal !== null && !openedWithWrongToken, { refusal, world_opened: openedWithWrongToken });
  await ctx.screenshot('wrong-token', 'the gate after a token this instance does not hold');

  await page.typeInto(TOKEN_FIELD, ctx.token);
  await page.click(ENTER, 'Enter Exulanica');
  await waitForWorld(page);
  ctx.observe('token-opens-world', await page.evaluate(WORLD_READY),
    { title_field: await page.evaluate(`${TITLE_FIELD}?.value ?? null`) });
}

async function enterOwnedStarter(ctx) {
  const { page } = ctx;
  if (!await page.evaluate(WORLD_READY)) await open(ctx);
  const surface = await page.evaluate(`(() => {
    const visible = (e) => !!e && e.checkVisibility();
    const start = [...document.querySelectorAll('button.companion-prompt-button')].find(b => b.textContent.trim() === 'Start building');
    return {
      title: document.querySelector('input[aria-label="World title"]')?.value ?? null,
      world_menu: visible(document.querySelector('button.world-open-menu')),
      add_object: visible(document.querySelector('button.world-add-object')),
      add_photos: visible(document.querySelector('button.world-add-photos')),
      canvas: visible(document.getElementById('atlas')),
      visible_forms: [...document.querySelectorAll('#shell form')].filter(f => f.checkVisibility()).map(f => f.className),
      first_use: document.querySelector('.companion-prompt-statement')?.textContent.trim() ?? null,
      start_building: visible(start),
      atlas: { ...document.getElementById('atlas')?.dataset },
    }; })()`);
  // The title form and the Companion's own composer are part of the world; anything else would be
  // an introductory form standing between the person and their world.
  const otherForms = surface.visible_forms
    .filter((name) => !String(name).includes('world-title-form') && !String(name).includes('companion-composer'));
  ctx.observe('starter-opens', surface.title !== null && surface.world_menu && surface.add_object && surface.add_photos
    && surface.canvas && otherForms.length === 0, surface);
  ctx.observe('first-use-card', Boolean(surface.first_use) && surface.start_building,
    { statement: surface.first_use, start_building: surface.start_building });
  ctx.observe('renderer-mounted', Boolean(surface.atlas.engine) && Number(surface.atlas.worldModules) >= 1, surface.atlas);
  await ctx.screenshot('starter', 'the starter world on first entry, with the first-use card');

  const before = await savedWorld(ctx);
  const entry = before.entry;
  ctx.observe('one-authored-starter', before.entries.length === 1 && entry.source_kind === 'authored'
    && entry.availability === 'available' && entry.source_attachments.length === 0
    && entry.authored_scene?.kind === 'authored-starter',
  { entries: before.entries.length, entry: pick(entry, ['entry_id', 'title', 'source_kind', 'availability', 'authored_version_id', 'authored_state_sha256', 'authored_edit_seq', 'style_version_id', 'revision']) });
  if (entry !== null) {
    Object.assign(ctx.facts, { entry_id: entry.entry_id, world_id: entry.world_id, starter_style_version_id: entry.style_version_id });
  }

  await reload(ctx);
  const after = await savedWorld(ctx);
  ctx.observe('same-world-after-reload', after.entries.length === 1 && entry !== null
    && same(pick(after.entry, ['entry_id', 'authored_version_id', 'authored_state_sha256', 'authored_edit_seq']),
      pick(entry, ['entry_id', 'authored_version_id', 'authored_state_sha256', 'authored_edit_seq'])),
  { entries: after.entries.length, entry: pick(after.entry, ['entry_id', 'authored_version_id', 'authored_state_sha256', 'authored_edit_seq']) });
}

async function nameWorld(ctx) {
  const { page } = ctx;
  const { title } = ctx.parameters;
  const before = (await savedWorld(ctx)).entry;
  await page.typeInto(TITLE_FIELD, title);
  await page.key('Enter', 'Enter', { text: '\r' });
  const status = await page.waitFor(`(() => { const s = document.querySelector('span.world-title-status')?.textContent.trim();
    return s && !s.startsWith('Saving') ? s : null; })()`, SETTLE_MS, 'the title to save');
  const field = await page.evaluate(`${TITLE_FIELD}.value`);
  ctx.observe('title-saved-shown', field === title && !/could not/i.test(status), { status, field });
  const after = (await ctx.api('GET', `/world-entries/${ctx.facts.entry_id}`)).body;
  ctx.observe('title-held', after?.title === title && after?.revision > before.revision,
    { before: pick(before, ['title', 'revision']), after: pick(after, ['title', 'revision']) });
  ctx.facts.title = title;
  await reload(ctx);
  const reloaded = await page.evaluate(`${TITLE_FIELD}.value`);
  ctx.observe('title-after-reload', reloaded === title, { field: reloaded });
}

async function exploreWalk(ctx) {
  const { page } = ctx;
  const hold = ctx.parameters.hold_milliseconds;
  const focus = await focusCanvas(page);
  ctx.observe('canvas-takes-keys', focus.focused, focus);
  await ctx.screenshot('before-walk', 'the view before walking');
  const moving = () => page.evaluate(`document.querySelector('#shell')?.dataset.moving ?? null`);
  const samples = [];
  await page.keyDown('KeyW', 'w');
  const ends = Date.now() + hold;
  while (Date.now() < ends) {
    samples.push(await moving());
    await sleep(100);
  }
  await page.keyUp('KeyW', 'w');
  await sleep(800);
  const after = await moving();
  ctx.observe('moves-while-held', samples.includes('true'), { samples });
  ctx.observe('stops-when-released', after === 'false', { after });
  await ctx.screenshot('after-walk', 'the view after walking forward');
}

// -- creation ------------------------------------------------------------------------------------

const ROW = `document.querySelector('aside.object-placement li.object-placement-item')`;
const rowButton = (text) => `[...(${ROW})?.querySelectorAll('button') ?? []].find(b => b.textContent.trim() === ${JSON.stringify(text)})`;
const motionWord = (page) => page.evaluate(`(${ROW})?.querySelector('.object-placement-motion')?.textContent.trim() ?? null`);

async function waitForEdit(ctx, beyondSeq, what) {
  return until(what, SETTLE_MS, async () => {
    const read = await savedWorld(ctx);
    return read.version?.edit_seq > beyondSeq ? read : null;
  });
}

async function placeReviewedObject(ctx) {
  const { page } = ctx;
  await openObjects(page);
  const assetSelect = `document.querySelector('select#object-placement-asset')`;
  const choice = await page.evaluate(`(() => { const o = [...${assetSelect}.options].find(o => !o.disabled && o.value);
    return o ? { key: o.value, title: o.text.trim() } : null; })()`);
  if (choice === null) throw new Error('no reviewed object is available to place');
  const before = await savedWorld(ctx);
  await page.setValue(`document.querySelector('select#object-placement-role')`, ctx.parameters.origin_role);
  // A panel refresh resets the asset to the first available one, so it is chosen last.
  await page.setValue(assetSelect, choice.key);
  await page.click(`document.querySelector('button.object-placement-place')`, 'Place before me');
  const said = await confirmation(page, 'placing the object');
  const verdict = await page.waitFor(`(() => { const v = ${OPEN_CONFIRM}?.querySelector('.composition-verdict');
    const s = v?.dataset.state; return s && s !== 'checking' ? { state: s, text: v.innerText.trim() } : null; })()`,
  SETTLE_MS, "the world's check of the placement");
  const structure = await page.evaluate(`({ utterance: !!${OPEN_CONFIRM}.querySelector('blockquote.confirm-utterance'),
    reversible: !!${OPEN_CONFIRM}.querySelector('p.confirm-reversible'),
    confirm_enabled: !(${OPEN_CONFIRM}.querySelector('.confirm-actions button.primary')?.disabled ?? true) })`);
  ctx.observe('confirm-before-write', verdict.state === 'ready' && structure.utterance && structure.reversible
    && structure.confirm_enabled, { confirmation: said, verdict, ...structure });
  await ctx.screenshot('confirm', 'the confirmation before the object is written, with its landing mark');
  await confirm(page, 'placing the object');
  const after = await waitForEdit(ctx, before.version.edit_seq, 'the placed object to be saved');
  await page.waitFor(`document.querySelectorAll('aside.object-placement li.object-placement-item').length > 0`, SETTLE_MS, 'the placed object in the list');
  const rows = await objectRows(page);
  ctx.observe('object-listed', rows.length === 1 && rows[0].title === choice.title && rows[0].motion === 'no motion', rows);
  const objects = liveObjects(after.version);
  const placed = objects[0] ?? null;
  ctx.observe('object-in-version', objects.length === 1 && placed.asset.asset_key === choice.key
    && same(placed.origin, { kind: 'authored', role: ctx.parameters.origin_role })
    && placed.transform.coordinate_space === 'region_local'
    && after.entry.authored_state_sha256 === after.version.state_sha256
    && after.entry.authored_edit_seq === after.version.edit_seq,
  { object: placed, version: pick(after.version, ['version_id', 'state_sha256', 'edit_seq']),
    entry_resume: pick(after.entry, ['authored_state_sha256', 'authored_edit_seq']) });
  if (placed !== null) {
    Object.assign(ctx.facts, { object_id: placed.object_id, asset_key: placed.asset.asset_key, asset_title: choice.title });
  }
  await ctx.screenshot('placed', 'the object on the ground, listed in the objects panel');
}

async function moveObject(ctx) {
  const { page } = ctx;
  await openObjects(page);
  const before = await savedWorld(ctx);
  const was = liveObjects(before.version).find((o) => o.object_id === ctx.facts.object_id);
  await page.click(`(${ROW}).querySelector('button.object-placement-choose')`, 'the placed object in the list');
  for (let press = 0; press < ctx.parameters.presses; press += 1) {
    await page.key(ctx.parameters.key, ctx.parameters.key);
    await sleep(150);
  }
  await page.click(BUTTON('Save this position', OBJECT_PANEL), 'Save this position');
  const said = await confirmation(page, 'the move');
  await confirm(page, 'the move');
  const after = await waitForEdit(ctx, before.version.edit_seq, 'the move to be saved');
  const status = await objectStatus(page);
  ctx.observe('move-confirmed', said.length > 0 && status !== null, { confirmation: said, status });
  const now = liveObjects(after.version).find((o) => o.object_id === ctx.facts.object_id);
  const newest = after.version.edits.at(-1);
  ctx.observe('transform-changed', now !== undefined && !same(now.transform, was.transform)
    && newest.kind === 'move_object' && newest.object_id === ctx.facts.object_id,
  { before: was?.transform, after: now?.transform, newest_edit: pick(newest, ['kind', 'object_id', 'edit_seq']) });
  await ctx.screenshot('moved', 'the object after the saved move');
}

async function inspectObject(ctx) {
  const { page } = ctx;
  if (await page.evaluate(`${OBJECT_PANEL}?.checkVisibility() ?? false`)) {
    await page.click(BUTTON('Close', OBJECT_PANEL), 'Close the objects panel');
  }
  await chooseMenu(page, 'world');
  await page.waitFor(`document.getElementById('world-panel-details')?.checkVisibility() ?? false`, 10_000, 'About this place');
  const inspector = `document.querySelector('details.representation-inspector')`;
  if (!await page.evaluate(`${inspector}?.open ?? false`)) {
    await page.click(`${inspector}.querySelector('summary')`, 'World → data');
  }
  const shown = await page.waitFor(`(${inspector})?.open && (${inspector}).checkVisibility()`, 10_000, 'the World to data inspector').catch(() => false);
  ctx.observe('inspector-shown', shown === true, { open_and_visible: shown });
  const subjects = `${inspector}.querySelector('select[aria-label="Inspect a displayed geometry group"]')`;
  const options = await page.waitFor(`(() => { const s = ${subjects}; if (!s) return null;
    const o = [...s.options].map(x => ({ value: x.value, text: x.text.trim(), disabled: x.disabled }));
    return o.some(x => x.value && !x.disabled) ? o : null; })()`, 15_000, 'a subject to inspect').catch(() => []);
  const target = options.find((o) => o.value && !o.disabled && o.text.startsWith(ctx.facts.asset_key)) ?? null;
  ctx.observe('subject-selectable', target !== null, { options, asset_key: ctx.facts.asset_key });
  if (target === null) throw new Error('the placed object is not offered as a subject to inspect');
  await page.setValue(subjects, target.value);
  const lines = await page.waitFor(`(() => { const items = [...${inspector}.querySelectorAll('ul.representation-availability > li')]
      .map(li => ({ kind: li.dataset.kind ?? null, state: li.dataset.state ?? null, text: li.innerText.trim() }));
    return items.some(i => i.text.startsWith('Provenance') && i.text.includes(${JSON.stringify(ctx.facts.asset_key)})) ? items : null; })()`,
  10_000, "the selected object's availability lines").catch(async () => page.evaluate(`[...${inspector}.querySelectorAll('ul.representation-availability > li')].map(li => ({ kind: li.dataset.kind ?? null, state: li.dataset.state ?? null, text: li.innerText.trim() }))`));
  const description = await page.evaluate(`${inspector}.querySelector('.representation-description')?.innerText.trim() ?? null`);
  const line = (label) => lines.find((l) => l.text.startsWith(`${label}:`)) ?? null;
  const available = (l) => l !== null && /^\w+: available\./.test(l.text);
  const provenance = line('Provenance');
  ctx.observe('geometry-and-origin', available(line('Rendered')) && available(line('Point')) && available(provenance)
    && provenance.text.includes(ctx.facts.asset_key), { lines, description });
  const missing = lines.filter((l) => /^\w+: unavailable\./.test(l.text));
  ctx.observe('missing-explicit', missing.length > 0 && missing.every((l) => /^\w+: unavailable\.\s+\S/.test(l.text)),
    { unavailable: missing });
  await ctx.screenshot('inspector', 'World to data with the placed object selected');
  await page.click(BUTTON('Close', `document.getElementById('world-panel-details')`), 'Close About this place').catch(() => null);
}

async function giveBoundedMotion(ctx) {
  const { page } = ctx;
  await openObjects(page);
  const before = await savedWorld(ctx);
  await page.click(rowButton('Give it motion'), 'Give it motion');
  await page.waitFor(`document.querySelector('div.object-placement-motion-editor')?.checkVisibility() ?? false`, 10_000, 'the motion editor');
  await page.click(BUTTON('Save this motion', OBJECT_PANEL), 'Save this motion');
  const said = await confirmation(page, 'the motion');
  await confirm(page, 'the motion');
  const after = await waitForEdit(ctx, before.version.edit_seq, 'the motion to be saved');
  const word = await page.waitFor(`(() => { const w = (${ROW})?.querySelector('.object-placement-motion')?.textContent.trim();
    return w && w !== 'no motion' ? w : null; })()`, SETTLE_MS, 'the object to show its motion').catch(() => null);
  ctx.observe('motion-confirmed', said.length > 0 && word === 'still, where it was placed', { confirmation: said, motion: word });
  const reviewed = (await ctx.api('GET', '/world/behaviours')).body;
  const held = liveObjects(after.version).find((o) => o.object_id === ctx.facts.object_id)?.behaviour ?? null;
  const entry = reviewed.find((b) => b.behaviour_key === held?.behaviour_key && b.behaviour_version === held?.behaviour_version);
  const within = entry !== undefined && Object.entries(entry.parameters).every(([name, rule]) => {
    const value = held.parameters[name];
    return rule.kind === 'choice' ? rule.choices.includes(value) : Number.isInteger(value) && value >= rule.minimum && value <= rule.maximum;
  });
  ctx.observe('behaviour-held', within, { behaviour: held, reviewed: entry ?? null });
  ctx.facts.behaviour = held;
}

async function triggerStopReset(ctx) {
  const { page } = ctx;
  await openObjects(page);
  const before = (await savedWorld(ctx)).version;
  const press = async (label, word) => {
    await page.click(rowButton(label), label);
    return page.waitFor(`(${ROW})?.querySelector('.object-placement-motion')?.textContent.trim() === ${JSON.stringify(word)}`,
      10_000, `the object to read "${word}"`).then(() => word).catch(async () => motionWord(page));
  };
  const travelling = await press('Start', 'travelling');
  ctx.observe('travelling', travelling === 'travelling', { motion: travelling });
  await ctx.screenshot('travelling', 'the object while its motion runs');
  await sleep(1200);
  const stopped = await press('Stop', 'stopped part-way');
  ctx.observe('stopped-part-way', stopped === 'stopped part-way', { motion: stopped });
  const reset = await press('Reset', 'still, where it was placed');
  ctx.observe('reset-to-rest', reset === 'still, where it was placed', { motion: reset });
  const after = (await savedWorld(ctx)).version;
  ctx.observe('no-write', after.state_sha256 === before.state_sha256 && after.edit_seq === before.edit_seq,
    { before: pick(before, ['state_sha256', 'edit_seq']), after: pick(after, ['state_sha256', 'edit_seq']) });
}

async function refuseUnsupportedBehaviour(ctx) {
  const { entry, version } = await savedWorld(ctx);
  const held = ctx.facts.behaviour;
  const reviewed = (await ctx.api('GET', '/world/behaviours')).body
    .filter((b) => b.behaviour_key === held.behaviour_key).map((b) => b.behaviour_version);
  const unlisted = Math.max(...reviewed) + 1;
  const refused = await ctx.api('POST',
    `/world/versions/${version.version_id}/objects/${encodeURIComponent(ctx.facts.object_id)}/behaviour?${worldQuery(ctx)}`, {
      behaviour: { ...held, behaviour_version: unlisted },
      base_state_sha256: version.state_sha256,
      saved_entry: { entry_id: entry.entry_id, base_revision: entry.revision,
        authored_state_sha256: entry.authored_state_sha256, authored_edit_seq: entry.authored_edit_seq },
    });
  const detail = String(refused.body?.detail ?? '');
  ctx.observe('refused-with-reason', refused.status === 422 && /not reviewed/.test(detail),
    { status: refused.status, code: refused.body?.code ?? null, detail, asked_for: `${held.behaviour_key}@${unlisted}` });
  const after = (await savedWorld(ctx)).version;
  ctx.observe('nothing-written', after.state_sha256 === version.state_sha256 && after.edit_seq === version.edit_seq,
    { before: pick(version, ['state_sha256', 'edit_seq']), after: pick(after, ['state_sha256', 'edit_seq']) });
}

async function creationSurvivesReload(ctx) {
  const { page } = ctx;
  const before = await savedWorld(ctx);
  await reload(ctx);
  const after = await savedWorld(ctx);
  ctx.observe('same-version-state', after.version.state_sha256 === before.version.state_sha256
    && after.version.edit_seq === before.version.edit_seq,
  { before: pick(before.version, ['state_sha256', 'edit_seq']), after: pick(after.version, ['state_sha256', 'edit_seq']) });
  const was = liveObjects(before.version).find((o) => o.object_id === ctx.facts.object_id);
  const now = liveObjects(after.version).find((o) => o.object_id === ctx.facts.object_id);
  await openObjects(page);
  const word = await page.waitFor(`(() => { const w = (${ROW})?.querySelector('.object-placement-motion')?.textContent.trim();
    return w === 'still, where it was placed' ? w : null; })()`, SETTLE_MS, 'the object to be drawn at rest with its motion').catch(() => motionWord(page));
  const editLabel = await page.evaluate(`[...(${ROW})?.querySelectorAll('button.object-placement-motion-edit') ?? []].map(b => b.textContent.trim())[0] ?? null`);
  ctx.observe('definition-kept', now !== undefined && same(now.transform, was?.transform) && same(now.behaviour, was?.behaviour)
    && word === 'still, where it was placed' && editLabel === 'Change its motion',
  { transform: now?.transform, behaviour: now?.behaviour, motion: word, motion_control: editLabel });
  const bytes = (await ctx.page.traffic(ctx.step.id)).filter((r) => r.method === 'GET'
    && r.path.startsWith(`/api/world/assets/${ctx.facts.asset_key}/bytes`));
  ctx.observe('object-drawn', bytes.some((r) => r.status === 200), bytes.map((r) => pick(r, ['path', 'status', 'bytes'])));
  await ctx.screenshot('after-reload', 'the object after the reload');
}

async function undoLastChange(ctx) {
  const { page } = ctx;
  await openObjects(page);
  const before = await savedWorld(ctx);
  const newestBefore = before.version.edits.at(-1);
  await page.click(BUTTON('Take back the last change', OBJECT_PANEL), 'Take back the last change');
  const said = await confirmation(page, 'taking back the last change');
  await confirm(page, 'taking back the last change');
  const after = await waitForEdit(ctx, before.version.edit_seq, 'the undo to be saved');
  const status = await objectStatus(page);
  ctx.observe('undo-confirmed', said.length > 0 && status !== null, { confirmation: said, status });
  const newest = after.version.edits.at(-1);
  const now = liveObjects(after.version).find((o) => o.object_id === ctx.facts.object_id);
  ctx.observe('undo-is-an-edit', newest.kind === 'undo' && newest.undone_edit_id === newestBefore.edit_id
    && newestBefore.kind === 'set_object_behaviour' && after.version.edit_seq === before.version.edit_seq + 1
    && now !== undefined && now.behaviour === null,
  { undone: pick(newestBefore, ['edit_id', 'kind']), newest: pick(newest, ['kind', 'undone_edit_id', 'edit_seq']), object: now ?? null });
  await reload(ctx);
  const reloaded = await savedWorld(ctx);
  ctx.observe('undo-kept', reloaded.version.state_sha256 === after.version.state_sha256
    && reloaded.entry.authored_state_sha256 === after.version.state_sha256,
  { version: pick(reloaded.version, ['state_sha256', 'edit_seq']), entry_resume: reloaded.entry.authored_state_sha256 });
}

// -- appearance ----------------------------------------------------------------------------------

const OPTIONS = `document.querySelector('section.options-view')`;
const LIFECYCLE = `document.querySelector('section.options-view p.world-style-lifecycle')`;
const HISTORY = `document.querySelector('section.options-view select[aria-label="World design history"]')`;
const control = (label) => `document.querySelector('section.options-view input[aria-label=${JSON.stringify(label)}]')`;

async function openCustomize(page) {
  if (!await page.evaluate(`${OPTIONS}?.checkVisibility() ?? false`)) await chooseMenu(page, 'options');
  await page.waitFor(`${OPTIONS}?.checkVisibility() ?? false`, 10_000, 'Customize world');
}

async function currentStyle(ctx) {
  const read = await ctx.api('GET', `/world/styles/current?${worldQuery(ctx)}`);
  return read.body?.current ?? null;
}

function changedKeys(before, after) {
  const keys = new Set([...Object.keys(before ?? {}), ...Object.keys(after ?? {})]);
  return [...keys].filter((key) => !same(before?.[key], after?.[key]));
}

async function changeAppearance(ctx) {
  const { page } = ctx;
  const before = await currentStyle(ctx);
  await openCustomize(page);
  const historyBefore = await page.evaluate(`[...(${HISTORY})?.options ?? []].map(o => o.value)`);
  const set = await page.setValue(control(ctx.parameters.control), ctx.parameters.value);
  const lifecycle = await page.waitFor(`(() => { const s = (${LIFECYCLE})?.dataset.state; return s === 'ready' ? { state: s, text: (${LIFECYCLE}).textContent.trim() } : null; })()`,
    SETTLE_MS, 'the preview to be checked').catch(async () => page.evaluate(`({ state: (${LIFECYCLE})?.dataset.state ?? null, text: (${LIFECYCLE})?.textContent.trim() ?? null })`));
  ctx.observe('preview-validated', lifecycle?.state === 'ready', { control: ctx.parameters.control, set_to: set, lifecycle });
  await page.click(`document.querySelector('section.options-view button.world-style-apply')`, 'Apply world design');
  const saved = await page.waitFor(`(() => { const s = (${LIFECYCLE})?.dataset.state; return s === 'saved' ? { state: s, text: (${LIFECYCLE}).textContent.trim() } : null; })()`,
    SETTLE_MS, 'the design to be applied').catch(async () => page.evaluate(`({ state: (${LIFECYCLE})?.dataset.state ?? null, text: (${LIFECYCLE})?.textContent.trim() ?? null })`));
  const historyAfter = await page.evaluate(`[...(${HISTORY})?.options ?? []].map(o => ({ value: o.value, text: o.text.trim() }))`);
  const version = await page.evaluate(`document.querySelector('section.options-view p.world-style-version')?.textContent.trim() ?? null`);
  ctx.observe('applied-as-new-revision', saved?.state === 'saved' && historyAfter.length === historyBefore.length + 1,
    { lifecycle: saved, version, history: historyAfter });
  await ctx.screenshot('applied', 'Customize world after applying the design');
  const after = await currentStyle(ctx);
  const entry = (await savedWorld(ctx)).entry;
  const changed = changedKeys(before?.global_style?.parameters, after?.global_style?.parameters);
  const value = changed.length === 1 ? after.global_style.parameters[changed[0]] : null;
  ctx.observe('new-style-version', after !== null && before !== null && after.version_id !== before.version_id
    && after.revision === before.revision + 1 && changed.length === 1
    && Math.abs(Number(value) - Number(ctx.parameters.value)) <= RANGE_TOLERANCE
    && entry.style_version_id === after.version_id,
  { before: pick(before, ['version_id', 'revision']), after: pick(after, ['version_id', 'revision']), changed, value,
    entry_style_version_id: entry.style_version_id });
  Object.assign(ctx.facts, {
    style_before: { version_id: before?.version_id, parameters: before?.global_style?.parameters ?? null },
    style_applied: { version_id: after?.version_id, control: ctx.parameters.control, value: ctx.parameters.value,
      parameter: changed.length === 1 ? changed[0] : null },
  });
}

async function appearanceSurvivesReload(ctx) {
  const { page } = ctx;
  await reload(ctx);
  await openCustomize(page);
  const applied = ctx.facts.style_applied;
  const shown = await page.evaluate(`${control(applied.control)}?.value ?? null`);
  const entry = (await savedWorld(ctx)).entry;
  const current = await currentStyle(ctx);
  ctx.observe('style-kept', entry.style_version_id === applied.version_id && current?.version_id === applied.version_id
    && Math.abs(Number(shown) - Number(applied.value)) <= RANGE_TOLERANCE,
  { entry_style_version_id: entry.style_version_id, current: current?.version_id, control_value: shown });
  await ctx.screenshot('kept', 'Customize world after the reload');
}

async function restoreOriginalAppearance(ctx) {
  const { page } = ctx;
  await openCustomize(page);
  const original = ctx.facts.style_before;
  const applied = ctx.facts.style_applied;
  const options = await page.evaluate(`[...(${HISTORY})?.options ?? []].map(o => ({ value: o.value, text: o.text.trim() }))`);
  if (!options.some((o) => o.value === original.version_id)) {
    throw new Error(`the history does not offer the authored revision ${original.version_id}`);
  }
  const versionBefore = await page.evaluate(`document.querySelector('section.options-view p.world-style-version')?.textContent.trim() ?? null`);
  await page.setValue(HISTORY, original.version_id);
  await page.click(BUTTON('Restore selected version', OPTIONS), 'Restore selected version');
  const versionAfter = await page.waitFor(`(() => { const t = document.querySelector('section.options-view p.world-style-version')?.textContent.trim();
    return t && t !== ${JSON.stringify(versionBefore)} ? t : null; })()`, SETTLE_MS, 'the restore to be saved').catch(() => null);
  const current = await currentStyle(ctx);
  const shown = await page.evaluate(`${control(applied.control)}?.value ?? null`);
  const authored = applied.parameter === null ? null : original.parameters[applied.parameter];
  ctx.observe('restored-shown', versionAfter !== null && Math.abs(Number(shown) - Number(authored)) <= RANGE_TOLERANCE,
    { version: versionAfter, control_value: shown, authored_value: authored });
  ctx.observe('restored-values', current?.rollback_target_version_id === original.version_id
    && same(current?.global_style?.parameters, original.parameters),
  { current: pick(current, ['version_id', 'revision', 'rollback_target_version_id']) });
  const history = (await ctx.api('GET', `/world/styles/versions?${worldQuery(ctx)}`)).body ?? [];
  ctx.observe('history-kept', history.some((v) => v.version_id === applied.version_id)
    && history.some((v) => v.version_id === original.version_id),
  history.map((v) => pick(v, ['version_id', 'revision', 'rollback_target_version_id'])));
  await ctx.screenshot('restored', 'Customize world after restoring the authored revision');
  await reload(ctx);
  await openCustomize(page);
  const reloaded = await page.evaluate(`${control(applied.control)}?.value ?? null`);
  ctx.observe('restore-kept', Math.abs(Number(reloaded) - Number(authored)) <= RANGE_TOLERANCE, { control_value: reloaded });
  ctx.facts.style_restored_version_id = current?.version_id ?? null;
}

// -- photos --------------------------------------------------------------------------------------

const DRAWER = `document.querySelector('section.photos-drawer')`;
const INTAKE = `document.querySelector('section.personal-intake')`;
const INCLUDE_BOXES = `[...document.querySelectorAll('section.personal-intake input[type=checkbox][aria-label^="Include photograph"]')]`;

async function openDrawer(page) {
  if (!await page.evaluate(`${DRAWER}?.checkVisibility() ?? false`)) {
    await page.click(`document.querySelector('aside.world-identity button.world-add-photos')`, 'Add photos');
  }
  await page.waitFor(`${DRAWER}?.checkVisibility() ?? false`, 10_000, 'the photo drawer');
  // The workflow and its steps are folded; a person unfolds the ones they use.
  await page.evaluate(`(() => { document.querySelectorAll('section.personal-intake details.photo-review-workflow, section.personal-intake details.intake-step').forEach(d => { d.open = true; }); return true; })()`);
}

async function openClosePhotoIntake(ctx) {
  const { page } = ctx;
  await openDrawer(page);
  const inside = await page.evaluate(`({ upload: !!document.querySelector('input[aria-label="Original HEIC or JPEG photographs"]'),
    canvas: document.getElementById('atlas')?.checkVisibility() ?? false, primary: document.querySelector('#shell')?.dataset.primary ?? null })`);
  ctx.observe('drawer-beside-world', inside.upload && inside.canvas, inside);
  await ctx.screenshot('drawer', 'the photo drawer beside the world');
  await page.click(`document.querySelector('button.photos-drawer-close')`, 'Return to world');
  await page.waitFor(`!(${DRAWER}?.checkVisibility() ?? false)`, 10_000, 'the drawer to close');
  const back = await page.evaluate(`({ title: ${TITLE_FIELD}?.value ?? null, primary: document.querySelector('#shell')?.dataset.primary ?? null, ready: ${WORLD_READY} })`);
  const entry = (await savedWorld(ctx)).entry;
  ctx.observe('world-kept', back.ready && back.primary === 'world' && back.title === entry.title && entry.entry_id === ctx.facts.entry_id, back);
}

async function uploadSyntheticPhotographs(ctx) {
  const { page } = ctx;
  const drawn = ctx.runtime.photographs;
  await openDrawer(page);
  await page.setFiles(`document.querySelector('input[aria-label="Original HEIC or JPEG photographs"]')`, drawn.map((p) => p.path));
  await page.click(BUTTON('Upload originals', INTAKE), 'Upload originals');
  const listed = await page.waitFor(`${INCLUDE_BOXES}.length >= ${drawn.length} ? ${INCLUDE_BOXES}.length : null`, 60_000, 'the uploaded originals to be listed').catch(() => 0);
  ctx.observe('originals-listed', listed === drawn.length, { listed, uploaded: drawn.length });
  await ctx.screenshot('uploaded', 'the drawer after the upload');
  const intake = await response(ctx, 'POST', '/api/intake');
  const accepted = intake?.response_body?.accepted ?? [];
  const byName = new Map(accepted.map((a) => [a.filename, a]));
  const captures = drawn.map((p) => ({ ...p, ...(byName.get(p.file) ?? {}) }));
  ctx.observe('captures-accepted', intake?.status === 202 && captures.every((c) => c.capture_id && c.blob_sha256 === c.sha256),
    { status: intake?.status ?? null, accepted: accepted.map((a) => pick(a, ['filename', 'capture_id', 'blob_sha256', 'status'])),
      refused: intake?.response_body?.refused ?? null });
  ctx.facts.captures = captures.map((c) => pick(c, ['file', 'arm', 'capture_id', 'blob_sha256', 'bytes']));
  ctx.facts.job_ids = [intake?.response_body?.queued_job_id].filter(Boolean);
}

function localDateTime(offsetDays) {
  const end = new Date(Date.now() + offsetDays * 24 * 3600 * 1000);
  return new Date(end.getTime() - end.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

async function authorizeAdmissionInApp(ctx) {
  const { page } = ctx;
  await openDrawer(page);
  await page.setValue(`document.querySelector('input[aria-label="Purpose of this use"]')`, ctx.parameters.purpose);
  await page.setValue(`document.querySelector('input[aria-label="Your account authority basis"]')`, ctx.parameters.authority_basis);
  await page.setValue(`document.querySelector('input[aria-label="Authority valid until"]')`, localDateTime(ctx.parameters.valid_days));
  await page.click(BUTTON('Authorize personal admission and request detection', INTAKE), 'Authorize personal admission');
  const posted = await until('the admission to be answered', SETTLE_MS, async () => {
    const r = await response(ctx, 'POST', '/api/personal-admission');
    return r?.status ? r : null;
  });
  await sleep(1000);
  const said = await page.evaluate(`${INTAKE}.innerText`);
  ctx.observe('receipts-recorded', posted.status === 202 && /receipt/i.test(said),
    { status: posted.status, drawer_mentions_receipts: /receipt/i.test(said) });
  await ctx.screenshot('admitted', 'the drawer after authorizing admission');
  const status = (await ctx.api('GET', '/personal-admission')).body;
  const sources = new Set((status?.sources ?? []).map((s) => s.capture_id));
  ctx.observe('admitted-for-detection', ctx.facts.captures.every((c) => sources.has(c.capture_id)),
    { sources: status?.sources?.map((s) => pick(s, ['capture_id', 'eligibility_state', 'screening_kind'])) ?? null });
  const job = posted.response_body?.queued_job_id;
  if (job) ctx.facts.job_ids = [...(ctx.facts.job_ids ?? []), job];
}

async function grantModelRightsByRoute(ctx) {
  const now = Date.now();
  const at = new Date(now - 60_000).toISOString();
  const validUntil = new Date(now + ctx.parameters.valid_days * 24 * 3600 * 1000).toISOString();
  const granted = await ctx.api('POST', '/personal-admission', {
    members: ctx.facts.captures.map((c) => ({ capture_id: c.capture_id, sha256: c.blob_sha256, bytes: c.bytes,
      review: 'not-reviewed', edits: [] })),
    purpose: ctx.parameters.purpose,
    authority: { account_authority_basis: ctx.parameters.authority_basis, authorized_at: at, valid_until: validUntil },
    recorded_at: at,
    operation: 'detect',
    model_rights: ctx.parameters.roles.map((role) => ({ role, valid_until: validUntil })),
  });
  const receipts = granted.body?.receipts ?? [];
  const rolesOf = (receipt) => new Set((receipt.model_rights ?? []).filter((r) => !r.withdrawn).map((r) => r.model.role));
  ctx.observe('rights-recorded', granted.status === 202 && receipts.length === ctx.facts.captures.length
    && receipts.every((r) => ctx.parameters.roles.every((role) => rolesOf(r).has(role))),
  { status: granted.status, detail: granted.body?.detail ?? null,
    rights: receipts.map((r) => ({ capture_id: r.capture_id, roles: [...rolesOf(r)] })) });
  const jobs = [...(ctx.facts.job_ids ?? []), granted.body?.queued_job_id].filter(Boolean);
  const terminal = {};
  await until('every derivative job to end', ctx.parameters.job_wait_seconds * 1000, async () => {
    for (const job of jobs) {
      if (terminal[job]) continue;
      const events = (await ctx.api('GET', `/operations/derivative-jobs/${job}/events`)).body ?? [];
      const end = events.find((e) => TERMINAL_JOB_EVENTS.has(e.event_type));
      if (end) terminal[job] = end.event_type;
    }
    return jobs.every((job) => terminal[job]);
  }).catch(() => null);
  const metrics = (await ctx.api('GET', '/operations/derivative-jobs')).body;
  ctx.spend(String(metrics?.cost?.usd_estimate ?? '0'));
  ctx.observe('vision-ran', jobs.length > 0 && jobs.every((job) => terminal[job] === 'job_succeeded') && metrics?.cost?.model_calls > 0,
    { jobs: terminal, cost: metrics?.cost ?? null });
  const graph = (await ctx.api('GET', '/graph')).body;
  const places = (graph?.occurrences ?? []).filter((o) => o.occurrence_class === 'place');
  const expected = new Set(ctx.facts.captures.filter((c) => c.arm === 'positive').map((c) => c.capture_id));
  const found = new Set(places.map((o) => o.capture_id));
  ctx.observe('place-proposed', expected.size > 0 && same([...expected].sort(), [...found].sort()),
    { expected: [...expected], place_occurrences: places.map((o) => pick(o, ['occurrence_id', 'capture_id', 'entity_id'])) });
  ctx.facts.place_occurrences = places.map((o) => pick(o, ['occurrence_id', 'capture_id']));
}

async function confirmProposedPlace(ctx) {
  const { page } = ctx;
  const [first, ...rest] = ctx.facts.place_occurrences ?? [];
  if (first === undefined) throw new Error('no place occurrence was proposed');
  const named = await ctx.api('POST', '/identity/name', { occurrence_id: first.occurrence_id, display_name: ctx.parameters.display_name });
  const confirmed = [];
  for (const occurrence of rest) {
    confirmed.push(await ctx.api('POST', '/identity/confirm', { occurrence_id: occurrence.occurrence_id, entity_id: named.body?.entity_id }));
  }
  const graph = (await ctx.api('GET', '/graph')).body;
  const linked = (graph?.occurrences ?? []).filter((o) => o.occurrence_class === 'place');
  ctx.observe('place-named', named.status === 200 && confirmed.every((c) => c.status === 200)
    && linked.every((o) => o.entity_id === named.body?.entity_id && o.link_state === 'confirmed'),
  { named: named.status, entity_id: named.body?.entity_id ?? null, confirmed: confirmed.map((c) => c.status),
    links: linked.map((o) => pick(o, ['occurrence_id', 'entity_id', 'link_state'])) });
  ctx.facts.place_entity_id = named.body?.entity_id ?? null;
  ctx.facts.place_name = ctx.parameters.display_name;
  // The page read the graph when it opened; a person sees the new name after the next load.
  await reload(ctx);
  await chooseMenu(page, 'index');
  const text = await page.waitFor(`(() => { const t = document.body.innerText; return t.toLowerCase().includes(${JSON.stringify(ctx.parameters.display_name.toLowerCase())}) ? t : null; })()`,
    15_000, 'the Library to show the place').catch(async () => page.evaluate('document.body.innerText'));
  const count = new RegExp(`${linked.length} occurrences?`).test(text);
  ctx.observe('library-lists-place', text.toLowerCase().includes(ctx.parameters.display_name.toLowerCase()) && count,
    { lists_name: text.toLowerCase().includes(ctx.parameters.display_name.toLowerCase()), occurrences_stated: count,
      excerpt: text.slice(0, 600) });
  await ctx.screenshot('library', 'the Library after the place was confirmed');
  await page.key('Escape', 'Escape');
}

// -- companion -----------------------------------------------------------------------------------

const SPEECH = `document.querySelector('aside.companion-encounter .companion-speech')`;
// A placeholder the composer wrote without its brackets, as "place A" or "PLACE A" (measured on the
// Companion lane's runs); "place I" is left alone because it is also English ("the place I saw").
const BARE_PLACEHOLDER = /\b(?:place|Place|PLACE|person|Person|PERSON) (?!I\b)[A-Z]\b/;
const COMPOSER = `[...document.querySelectorAll('aside.companion-encounter form.companion-composer input')].find(i => i.checkVisibility())`;

async function openCompanion(page) {
  if (await page.evaluate(`document.querySelector('aside.companion-encounter')?.dataset.state === 'open'`)) return;
  await chooseMenu(page, 'companion');
  await page.waitFor(`document.querySelector('aside.companion-encounter')?.dataset.state === 'open'`, 10_000, 'the Companion to open');
}

/** Ask in words through the Companion's own composer and wait for the answer face to settle. */
async function ask(ctx, question) {
  const { page } = ctx;
  await openCompanion(page);
  if (!await page.evaluate(`!!(${COMPOSER})`)) {
    // A pending turn keeps the composer behind "Other…", which is how a person asks their own question.
    await page.click(`document.querySelector('aside.companion-encounter button.companion-other-reveal')`, 'Other…');
  }
  await page.waitFor(`!!(${COMPOSER})`, 10_000, 'the question field');
  const asksBefore = (await responses(ctx, 'POST', '/api/selection/ask')).length;
  const appearanceBefore = (await responses(ctx, 'POST', '/api/selection/appearance')).length;
  await page.typeInto(COMPOSER, question);
  await page.key('Enter', 'Enter', { text: '\r' });
  // This question's own reply, not the face an earlier question left: an answer from the answer
  // route, or an appearance proposal (or a refusal of one) from the proposal route.
  await until('the Companion to answer or fail', ANSWER_TIMEOUT_MS, async () => {
    const asked = (await responses(ctx, 'POST', '/api/selection/ask')).slice(asksBefore).filter((r) => r.status !== null);
    const classified = (await responses(ctx, 'POST', '/api/selection/appearance')).slice(appearanceBefore)
      .filter((r) => r.status !== null && (r.status !== 200 || r.response_body?.classification === 'appearance'));
    return asked.length > 0 || classified.length > 0;
  });
  await page.waitFor(`['answer', 'failed'].includes((${SPEECH})?.dataset.mode) && document.querySelector('aside.companion-encounter')?.dataset.answering !== 'asking'`,
    30_000, 'the Companion to draw its reply');
  // The answer may be drawn before its packet is read; the chips follow the packet.
  await sleep(1500);
  // The answer is its clauses; the speech also echoes the question, which must not count as an answer.
  const face = await page.evaluate(`(() => { const s = ${SPEECH};
    return { mode: s?.dataset.mode ?? null, abstained: s?.hasAttribute('data-abstained') ?? false,
      text: s?.innerText.trim() ?? '',
      clauses: [...(s?.querySelectorAll('p.companion-utterance') ?? [])].map(p => p.textContent.trim()),
      provenance: s?.querySelector('p.companion-provenance')?.textContent.trim() ?? null,
      chips: [...document.querySelectorAll('aside.companion-encounter button.companion-evidence-chip')].map(b => ({ text: b.textContent.trim(), disabled: b.disabled })) }; })()`);
  const asked = (await responses(ctx, 'POST', '/api/selection/ask')).slice(asksBefore);
  const classified = (await responses(ctx, 'POST', '/api/selection/appearance')).slice(appearanceBefore);
  const answer = asked.at(-1)?.response_body ?? null;
  const classification = classified.at(-1)?.response_body ?? null;
  ctx.spend(addUsd(usdOf(answer?.execution), usdOf(classification?.execution)));
  return { face, answer, answer_status: asked.at(-1)?.status ?? null, classification, classification_status: classified.at(-1)?.status ?? null };
}

async function askGroundedQuestion(ctx) {
  const { face, answer, answer_status: status, classification } = await ask(ctx, ctx.parameters.question);
  const text = face.clauses.join(' ');
  const expected = ctx.parameters.expected_words.every((word) => text.toUpperCase().includes(word));
  ctx.observe('answer-shown', face.mode === 'answer' && !face.abstained && expected,
    { mode: face.mode, abstained: face.abstained, clauses: face.clauses, expected_words: ctx.parameters.expected_words });
  const placeholder = text.match(PLACEHOLDER)?.[0] ?? text.match(BARE_PLACEHOLDER)?.[0] ?? null;
  ctx.observe('names-restored', placeholder === null, { placeholder, saved_name: ctx.facts.place_name ?? null });
  const reasoning = (answer?.execution?.calls ?? []).filter((c) => String(c.role).startsWith('reasoning_'));
  const served = reasoning.at(-1)?.served_model ?? null;
  ctx.observe('executed-model-shown', face.provenance !== null && served !== null && face.provenance.includes(served),
    { provenance: face.provenance, served_model: served });
  ctx.observe('citation-offered', face.chips.some((c) => !c.disabled), face.chips);
  const clauses = answer?.answer?.clauses ?? [];
  const calls = answer?.execution?.calls ?? [];
  const composed = reasoning.at(-1) ?? null;
  const unserved = calls.filter((c) => !c.served_model).map((c) => c.role);
  if (unserved.length > 0) ctx.note(`calls recorded without a served model: ${unserved.join(', ')}`);
  ctx.observe('grounded-execution', status === 200 && clauses.some((c) => (c.citations ?? []).length > 0)
    && composed !== null && Boolean(composed.served_model) && composed.usd != null
    && calls.every((c) => c.role && c.requested_model && c.usd != null),
  { status, clauses, execution: answer?.execution ?? null, classification: classification?.classification ?? null });
  await ctx.screenshot('answer', "the Companion's answer with its citation");
}

async function openCitedPhotograph(ctx) {
  const { page } = ctx;
  await page.click(`[...document.querySelectorAll('aside.companion-encounter button.companion-evidence-chip')].find(b => !b.disabled)`, 'the first citation');
  const evidence = await page.waitFor(`(() => { const e = document.querySelector('aside.companion-encounter section.companion-evidence');
    const state = e?.dataset.evidence; if (!state || state === 'opening') return null;
    const img = e.querySelector('figure.companion-evidence-figure img');
    return { state, drawn: !!img && img.complete && img.naturalWidth > 0, width: img?.naturalWidth ?? 0 }; })()`,
  20_000, 'the cited photograph').catch(() => ({ state: 'nothing drawn', drawn: false }));
  ctx.observe('photograph-shown', evidence.state === 'shown' && evidence.drawn, evidence);
  await ctx.screenshot('evidence', 'the Companion after the citation was opened');
  const read = (await ctx.page.traffic(ctx.step.id)).filter((r) => r.method === 'GET' && /^\/api\/evidence\/[^/]+\/masked/.test(r.path));
  ctx.observe('evidence-served', read.some((r) => r.status === 200 && String(r.mime).startsWith('image/')),
    read.map((r) => pick(r, ['path', 'status', 'mime', 'bytes'])));
  const back = `[...document.querySelectorAll('aside.companion-encounter button')].find(b => b.classList.contains('companion-evidence-back') || b.classList.contains('companion-answer-back'))`;
  if (await page.evaluate(`!!(${back})`)) await page.click(back, 'back to the answer');
}

async function unanswerableQuestionAbstains(ctx) {
  const { face, answer } = await ask(ctx, ctx.parameters.question);
  const clauses = answer?.answer?.clauses ?? [];
  const cited = clauses.filter((c) => (c.citations ?? []).length > 0);
  ctx.observe('missing-said', face.mode === 'answer' && (face.abstained || face.chips.length === 0),
    { mode: face.mode, abstained: face.abstained, chips: face.chips, text: face.text });
  ctx.observe('nothing-cited-for-absent-place', answer !== null && cited.length === 0, { cited_clauses: cited, clauses });
  await ctx.screenshot('abstained', 'the Companion asked about a place no photograph shows');
}

async function companionProposesAppearanceChange(ctx) {
  const { page } = ctx;
  const { face, classification, classification_status: status } = await ask(ctx, ctx.parameters.utterance);
  const proposal = classification?.proposal ?? null;
  ctx.observe('proposal-drafted', status === 200 && classification?.classification === 'appearance' && proposal !== null,
    { status, classification: classification?.classification ?? null, refusal: classification?.refusal ?? null,
      proposal: proposal === null ? null : pick(proposal, ['model_id', 'prompt_version', 'spoken']) });
  ctx.observe('proposal-offered', proposal !== null && face.text.includes(proposal.spoken), { mode: face.mode, text: face.text });
  await ctx.screenshot('proposal', "the Companion's reply to the appearance request");
  await page.key('Escape', 'Escape');
  await openCustomize(page);
  const review = await page.evaluate(`({ review: document.querySelector('section.options-view div.world-style-proposal-review')?.textContent.trim() ?? null,
    lifecycle: (${LIFECYCLE})?.dataset.state ?? null })`);
  ctx.observe('proposal-ready-in-customize', /companion/i.test(review.review ?? '') && review.lifecycle === 'ready', review);
}

// -- return --------------------------------------------------------------------------------------

async function returningUserReopens(ctx) {
  const { page } = ctx;
  await open(ctx);
  const { entries, entry, version } = await savedWorld(ctx);
  const title = await page.evaluate(`${TITLE_FIELD}.value`);
  ctx.observe('saved-world-opens', entries.length === 1 && entry.entry_id === ctx.facts.entry_id && title === entry.title,
    { entries: entries.length, title_field: title, saved_title: entry?.title ?? null });
  await openObjects(page);
  const saved = liveObjects(version);
  const rows = await page.waitFor(`document.querySelectorAll('aside.object-placement li.object-placement-item').length === ${saved.length}
    ? [...document.querySelectorAll('aside.object-placement li.object-placement-item .object-placement-choose strong')].map(s => s.textContent.trim()) : null`,
  SETTLE_MS, 'the saved objects in the list').catch(async () => (await objectRows(page)).map((r) => r.title));
  const client = ctx.facts.client_object_id ? saved.find((o) => o.object_id === ctx.facts.client_object_id) : null;
  const bytes = (await ctx.page.traffic(ctx.step.id)).filter((r) => r.method === 'GET' && r.path.includes('/api/world/assets/') && r.path.endsWith('/bytes'));
  ctx.observe('objects-as-saved', rows.length === saved.length
    && (ctx.facts.client_object_id === undefined || (client !== undefined && client !== null
      && bytes.some((r) => r.path.includes(`/assets/${client.asset.asset_key}/bytes`) && r.status === 200))),
  { listed: rows, saved: saved.map((o) => pick(o, ['object_id', 'behaviour'])), client_object: ctx.facts.client_object_id ?? null,
    asset_reads: bytes.map((r) => pick(r, ['path', 'status'])) });
  await ctx.screenshot('objects', 'the saved world reopened, with its objects listed');
  await page.click(BUTTON('Close', OBJECT_PANEL), 'Close the objects panel');
  await openCustomize(page);
  const shown = await page.evaluate(`document.querySelector('section.options-view p.world-style-version')?.textContent.trim() ?? null`);
  const current = await currentStyle(ctx);
  const revision = Number(shown?.match(/(\d+)/)?.[1]);
  ctx.observe('appearance-as-saved', entry.style_version_id === current?.version_id && revision === current?.revision,
    { shown, entry_style_version_id: entry.style_version_id, current: pick(current, ['version_id', 'revision']) });
  ctx.observe('resume-point-current', entry.authored_state_sha256 === version.state_sha256 && entry.authored_edit_seq === version.edit_seq,
    { entry: pick(entry, ['authored_state_sha256', 'authored_edit_seq']), version: pick(version, ['state_sha256', 'edit_seq']) });
}

/**
 * A step that acts in the world: a page session starts on a blank page, so the first such step of
 * a session opens the application and passes its gate, the way the person arrives.
 */
const inWorld = (handler) => async (ctx) => {
  if (!await ctx.page.evaluate(`document.readyState === 'complete' && ${WORLD_READY}`).catch(() => false)) await open(ctx);
  return handler(ctx);
};

/** Every runnable browser step of steps.json, by id; tests/test_rehearsal_steps.py holds the two to each other. */
export const HANDLERS = Object.freeze({
  // These two load the application themselves: the gate and the returning person's arrival are
  // what they observe.
  'access-gate': accessGate,
  'returning-user-reopens': returningUserReopens,
  'enter-owned-starter': inWorld(enterOwnedStarter),
  'name-world': inWorld(nameWorld),
  'explore-walk': inWorld(exploreWalk),
  'place-reviewed-object': inWorld(placeReviewedObject),
  'move-object': inWorld(moveObject),
  'inspect-object': inWorld(inspectObject),
  'give-bounded-motion': inWorld(giveBoundedMotion),
  'trigger-stop-reset': inWorld(triggerStopReset),
  'refuse-unsupported-behaviour': inWorld(refuseUnsupportedBehaviour),
  'creation-survives-reload': inWorld(creationSurvivesReload),
  'undo-last-change': inWorld(undoLastChange),
  'change-appearance': inWorld(changeAppearance),
  'appearance-survives-reload': inWorld(appearanceSurvivesReload),
  'restore-original-appearance': inWorld(restoreOriginalAppearance),
  'open-close-photo-intake': inWorld(openClosePhotoIntake),
  'upload-synthetic-photographs': inWorld(uploadSyntheticPhotographs),
  'authorize-admission-in-app': inWorld(authorizeAdmissionInApp),
  'grant-model-rights-by-route': inWorld(grantModelRightsByRoute),
  'confirm-proposed-place': inWorld(confirmProposedPlace),
  'ask-grounded-question': inWorld(askGroundedQuestion),
  'open-cited-photograph': inWorld(openCitedPhotograph),
  'unanswerable-question-abstains': inWorld(unanswerableQuestionAbstains),
  'companion-proposes-appearance-change': inWorld(companionProposesAppearanceChange),
});
