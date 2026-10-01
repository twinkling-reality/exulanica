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
  ACTION, OBJECT_PANEL, OPEN_CONFIRM, confirm, confirmation, liveObjects, open, openObjects, savedWorld,
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
// The steps, in order: each one is a person's action in the page.
const STEPS = ['journey-open', 'journey-stall', 'journey-people', 'journey-bench', 'journey-response',
  'journey-why'];

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
