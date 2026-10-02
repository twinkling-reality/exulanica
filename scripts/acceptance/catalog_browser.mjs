// Row E4 in the production browser: a character catalog option the host publishes while the page
// is served appears in the page's look editor without the application being built again.
//
//   node scripts/acceptance/catalog_browser.mjs PLAN.json
//
// PLAN.json: { "session": { "id", "budget_seconds" }, "out": <directory>, "label": <the new
// option's label>, "slot": <its control's data-control>, "handshake": { "ready", "published",
// "wait_seconds" }, "runtime": { "app_url", "api_base", "token_file", "browser_port",
// "chrome_flags" } }, written by scripts/acceptance/domain_rows.py (`catalog`).
//
// One headless Chrome, one page, through the product's own controls: the page opens past the
// credential gate, the character studio is opened from the tool rail and its Style step read.
// The runner then writes the handshake's `ready` file and waits for `published`, which the driver
// writes once the new catalog revision is published; the page is reloaded and the same control
// read again. The page reads the served catalogs when a world mounts, so the reload is how a new
// publication reaches an open page; the build itself is never touched. It writes session.json in
// the journey runner's shape after every step.

import { createHash } from 'node:crypto';
import { existsSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { join, relative } from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';

import { open as openBrowser } from '../rehearsal/cdp.mjs';
import { ACTION, BUTTON, open, reload } from '../rehearsal/app.mjs';

const STEPS = ['catalog-before', 'catalog-after'];
// The studio is ready once its people controls are shown and the editor is enabled.
const STUDIO_READY = "(() => { const f = document.querySelector('fieldset.character-editor'); "
  + "const p = document.querySelector('.character-people'); return !!f && !f.disabled && !!p && !p.hidden; })()";
const STYLE_TAB = BUTTON('Style', "document.querySelector('nav.character-tabs')");
const STUDIO_SECONDS = 120;

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
    runtime: plan.runtime,
    token,
    observe(name, ok, observed) {
      observations.push({ id: name, ok: Boolean(ok), observed: observed ?? null });
      return Boolean(ok);
    },
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
      evidence.api.push({ method, path, status: response.status });
      return { status: response.status, body: parsed };
    },
  };
}

/** The labels of the swatches in the studio's control for the plan's slot, once the studio shows it. */
async function studioOptions(ctx) {
  const p = ctx.page;
  await p.click(ACTION('character.open'), 'Character');
  await p.waitFor(STUDIO_READY, STUDIO_SECONDS * 1000, 'the character studio to show its people controls');
  await p.click(STYLE_TAB, 'Style');
  const group = `document.querySelector('[data-control="${plan.slot}"]')`;
  await p.waitFor(`!!${group}`, 30_000, `the ${plan.slot} control`);
  return p.evaluate(`[...${group}.querySelectorAll('button')].map((b) => b.getAttribute('aria-label') || b.textContent.trim())`);
}

/** The page's own recorded catalog reads in this step. */
async function catalogReads(ctx) {
  return (await ctx.page.traffic(ctx.step.id))
    .filter((r) => r.method === 'GET' && r.path.includes('/world/character-catalogs'))
    .map((r) => ({ path: r.path, status: r.status }));
}

const STEP_HANDLERS = {
  async 'catalog-before'(ctx) {
    await open(ctx);
    const options = await studioOptions(ctx);
    ctx.facts.options_before = options;
    ctx.observe('control-shown', options.length >= 2, { options });
    ctx.observe('new-option-not-yet-offered', !options.includes(plan.label), { label: plan.label, options });
    ctx.observe('catalogs-read-by-the-page', (await catalogReads(ctx)).length > 0, { reads: await catalogReads(ctx) });
    await ctx.screenshot('studio-style', 'the look editor before the new revision is published');
    writeFileSync(plan.handshake.ready, new Date().toISOString());
    const deadline = Date.now() + plan.handshake.wait_seconds * 1000;
    while (!existsSync(plan.handshake.published) && Date.now() < deadline) await sleep(500);
    ctx.observe('revision-published', existsSync(plan.handshake.published), {});
    ctx.facts.published = existsSync(plan.handshake.published)
      ? JSON.parse(readFileSync(plan.handshake.published, 'utf8')) : null;
  },
  async 'catalog-after'(ctx) {
    await reload(ctx);
    const options = await studioOptions(ctx);
    const reads = await catalogReads(ctx);
    const digest = ctx.facts.published?.catalog_sha256 ?? '';
    ctx.facts.options_after = options;
    ctx.observe('new-option-offered', options.includes(plan.label), { label: plan.label, options });
    ctx.observe('earlier-options-kept', (ctx.facts.options_before ?? []).every((o) => options.includes(o)),
      { before: ctx.facts.options_before, after: options });
    ctx.observe('new-revision-read-by-the-page', digest !== '' && reads.some((r) => r.path.includes(digest) && r.status === 200),
      { digest, reads });
    await ctx.screenshot('studio-style', 'the look editor after the new revision is published and the page reloaded');
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
  await finish(0, 'an earlier step failed');
} catch (error) {
  await finish(1, `the page session failed: ${String(error?.message ?? error).slice(0, 400)}`);
}
