/**
 * A minimal CDP driver: open the bowl Atlas at exactly 1280x720, drive the proof lens and
 * click-to-evidence, and retain screenshots plus what was on screen when each was taken.
 *
 * Deliberately no puppeteer: the workspace has none, and everything needed here is four CDP
 * domains over the WebSocket Node already ships.
 */
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { setTimeout as sleep } from 'node:timers/promises';

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const PORT = 9333;
const URL_ = process.env.ATLAS_URL ?? 'http://127.0.0.1:5180/';
const OUT = process.env.OUT_DIR;
if (!OUT) throw new Error('OUT_DIR is required');
mkdirSync(OUT, { recursive: true });

const profile = `${OUT}/.chrome-profile`;
const chrome = spawn(CHROME, [
  '--headless=new',
  `--remote-debugging-port=${PORT}`,
  '--window-size=1280,720',
  '--hide-scrollbars',
  '--no-first-run',
  '--no-default-browser-check',
  '--disable-features=Translate,MediaRouter',
  `--user-data-dir=${profile}`,
  'about:blank',
], { stdio: ['ignore', 'pipe', 'pipe'] });
let chromeLog = '';
chrome.stdout.on('data', (b) => { chromeLog += b.toString(); });
chrome.stderr.on('data', (b) => { chromeLog += b.toString(); });

async function targets() {
  for (let i = 0; i < 60; i += 1) {
    try {
      const res = await fetch(`http://127.0.0.1:${PORT}/json/list`);
      const list = await res.json();
      const page = list.find((t) => t.type === 'page');
      if (page) return page;
    } catch { /* not up yet */ }
    await sleep(250);
  }
  throw new Error(`chrome did not expose a page target\n${chromeLog}`);
}

const page = await targets();
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  ws.addEventListener('open', resolve, { once: true });
  ws.addEventListener('error', reject, { once: true });
});
let nextId = 0;
const pending = new Map();
const events = [];
ws.addEventListener('message', (event) => {
  const message = JSON.parse(event.data);
  if (message.id !== undefined) {
    const slot = pending.get(message.id);
    pending.delete(message.id);
    if (message.error) slot.reject(new Error(JSON.stringify(message.error)));
    else slot.resolve(message.result);
    return;
  }
  events.push(message);
});
function send(method, params = {}) {
  const id = (nextId += 1);
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
    ws.send(JSON.stringify({ id, method, params }));
  });
}
async function evaluate(expression) {
  const result = await send('Runtime.evaluate', {
    expression, returnByValue: true, awaitPromise: true,
  });
  if (result.exceptionDetails) {
    throw new Error(`page threw: ${JSON.stringify(result.exceptionDetails.exception?.description ?? result.exceptionDetails)}`);
  }
  return result.result.value;
}

await send('Page.enable');
await send('Runtime.enable');
await send('Log.enable');
await send('Emulation.setDeviceMetricsOverride', {
  width: 1280, height: 720, deviceScaleFactor: 1, mobile: false,
});

const captures = [];
async function shot(name, note) {
  // The inspector is a scrolling aside. A screenshot of it that stopped at its fold would be a
  // screenshot of the question rather than the answer.
  await evaluate(`(() => {
    const aside = document.querySelector('.reconstruction-inspector');
    const evidence = document.querySelector('.reconstruction-evidence');
    if (aside !== null && !aside.hidden && evidence !== null) {
      aside.scrollTop = Math.max(0, evidence.offsetTop - aside.offsetTop - 56);
    }
    return true;
  })()`);
  await sleep(150);
  const { data } = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
  const file = `${OUT}/${name}.png`;
  writeFileSync(file, Buffer.from(data, 'base64'));
  const state = await evaluate(readState);
  captures.push({ name, file, note, state });
  return state;
}

const readState = `(() => {
  const text = (sel) => { const n = document.querySelector(sel); return n === null ? null : n.textContent; };
  const lens = document.querySelector('.proof-lens');
  const evidence = document.querySelector('.reconstruction-evidence');
  return {
    statusSummaries: [...document.querySelectorAll('.reconstruction-rung > summary')].map((n) => n.textContent),
    proofTiers: [...document.querySelectorAll('.reconstruction-proof-tier')].map((n) => n.dataset.proofTier + ' | ' + n.textContent),
    lensPresent: lens !== null,
    lensState: lens?.dataset.proofLens ?? null,
    lensToggleLabel: text('.proof-lens-toggle'),
    lensLegend: [...document.querySelectorAll('.proof-lens-legend li')].map((n) => n.dataset.proofTier),
    lensLimit: text('.proof-lens-limit'),
    inspectorHidden: document.querySelector('.reconstruction-inspector')?.hidden ?? null,
    inspectorViewId: document.querySelector('.reconstruction-inspector')?.dataset.viewId ?? null,
    inspectorViewLabel: text('.reconstruction-inspector select option:checked'),
    inspectorState: text('.reconstruction-inspector > p[role=status]'),
    evidenceKind: evidence?.dataset.evidence ?? null,
    evidenceState: text('.reconstruction-evidence-state'),
    evidenceDetail: text('.reconstruction-evidence-detail'),
    evidencePhotographs: [...document.querySelectorAll('.reconstruction-evidence-photograph')].map((n) => ({
      captureId: n.dataset.captureId,
      title: n.querySelector('.reconstruction-evidence-title')?.textContent ?? null,
      where: n.querySelector('.reconstruction-evidence-where')?.textContent ?? null,
      consent: n.querySelector('.reconstruction-evidence-consent')?.textContent ?? null,
    })),
    canvasRect: (() => { const r = document.getElementById('atlas')?.getBoundingClientRect(); return r ? { x: r.x, y: r.y, w: r.width, h: r.height } : null; })(),
  };
})()`;

async function click(x, y) {
  for (const type of ['mousePressed', 'mouseReleased']) {
    await send('Input.dispatchMouseEvent', {
      type, x, y, button: 'left', clickCount: 1, buttons: type === 'mousePressed' ? 1 : 0,
    });
  }
}

async function waitFor(expression, label, timeoutMs = 420_000) {
  const started = Date.now();
  for (;;) {
    if (await evaluate(expression) === true) return Date.now() - started;
    if (Date.now() - started > timeoutMs) throw new Error(`timed out waiting for ${label}`);
    await sleep(500);
  }
}

const startedAt = Date.now();
await send('Page.navigate', { url: URL_ });
const mountMs = await waitFor(
  `document.querySelectorAll('.reconstruction-rung').length > 0 && document.querySelector('.reconstruction-loading') === null`,
  'the Atlas to mount and the status panel to render',
);
// Let the trained scene settle into the first photograph's view before anything is captured.
//
// AND THEN HURRY. MEASURED 2026-09-06 and reproduced on the unmodified tree at HEAD 104e415: in
// this headless browser the region's representation drops to its residency stub about thirteen
// seconds after mount and the trained scene stops being drawn until something forces it resident
// again. That is a pre-existing behaviour of the arrival path, not of anything captured here, so
// the world-view pair is taken inside the window and the rest is taken with the inspector open,
// which holds the inspected island resident.
await sleep(2500);

const plan = JSON.parse(process.env.PLAN ?? '{}');
const toggle = async (seconds) => {
  await evaluate(`document.querySelector('.proof-lens-toggle').click(); true`);
  await sleep(seconds * 1000);
};

await shot('lens-off', 'The bowl as it is drawn with the proof lens switched off.');
await toggle(3);
await shot('lens-on', 'The same view with the proof lens on: the trained reconstruction wears the reconstructed tier.');
await toggle(3);
await shot('lens-off-again', 'The lens switched back off, restoring what it found.');
await toggle(0.2);

// Open the inspector on the trained scene: the details block whose substrate is the trained one.
const opened = await evaluate(`(() => {
  for (const details of document.querySelectorAll('.reconstruction-rung')) {
    if (!(details.querySelector('summary')?.textContent ?? '').includes('trained Gaussian')) continue;
    details.open = true;
    const button = [...details.querySelectorAll('button')].find((b) => b.textContent === 'Inspect reconstruction');
    if (button === undefined) return 'no inspect button';
    button.click();
    return details.dataset.sceneId;
  }
  return 'no trained scene listed';
})()`);
await waitFor(`document.querySelector('.reconstruction-inspector')?.hidden === false`, 'the inspector to open');
await shot('inspector-open', `Inspector open on ${opened}, observation graph loading.`);

// The lens pair again from a recovered camera. The inspector holds its island resident, so this
// pair is not racing the representation pressure controller the way the world-view pair is.
await sleep(3000);
await shot('inspector-lens-on', 'The lens on, from the first photograph\'s own recovered camera.');
await toggle(3);
await shot('inspector-lens-off', 'The same recovered camera with the lens off.');
await toggle(3);

const readyMs = await waitFor(
  `document.querySelector('.reconstruction-evidence')?.dataset.evidence === 'ready'`,
  'the recorded observation graph to load',
);
await sleep(1500);
if (plan.viewIndex !== undefined) {
  await evaluate(`(() => {
    const select = document.querySelector('.reconstruction-inspector select');
    select.selectedIndex = ${plan.viewIndex};
    select.dispatchEvent(new Event('change'));
    return true;
  })()`);
  await sleep(3000);
}
await shot('evidence-ready', 'The observation graph loaded; nothing clicked yet.');

const rect = await evaluate(`(() => { const r = document.getElementById('atlas').getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height }; })()`);
const points = plan.clicks ?? (() => {
  const grid = [];
  for (let gy = 0.2; gy < 0.85; gy += 0.1) for (let gx = 0.28; gx < 0.75; gx += 0.06) grid.push([gx, gy]);
  return grid;
})();
const attempts = [];
let tookHit = false;
let tookMiss = false;
for (const [index, [fx, fy]] of points.entries()) {
  const x = rect.x + fx * rect.w;
  const y = rect.y + fy * rect.h;
  await click(x, y);
  await sleep(500);
  const state = await evaluate(readState);
  attempts.push({
    index, fractionX: Number(fx.toFixed(4)), fractionY: Number(fy.toFixed(4)),
    clientX: Math.round(x), clientY: Math.round(y),
    kind: state.evidenceKind, state: state.evidenceState,
    photographs: state.evidencePhotographs.length,
  });
  if (plan.clicks !== undefined) {
    const label = plan.labels?.[index] ?? `click-${String(index)}`;
    await shot(label, `A click at (${x.toFixed(0)}, ${y.toFixed(0)}): ${String(state.evidenceKind)}.`);
    continue;
  }
  if (state.evidenceKind === 'hit' && !tookHit) {
    tookHit = true;
    await shot('evidence-hit', `A click at (${x.toFixed(0)}, ${y.toFixed(0)}) resolved to the photographs that observed that point.`);
  } else if (state.evidenceKind === 'miss' && !tookMiss) {
    tookMiss = true;
    await shot('evidence-miss', `A click at (${x.toFixed(0)}, ${y.toFixed(0)}) reached no recorded observation, shown as the answer it is.`);
  }
  if (tookHit && tookMiss) break;
}

// The keyboard-reachable equivalent, since the world canvas is aria-hidden.
await evaluate(`document.querySelector('.reconstruction-evidence-resolve').click(); true`);
await sleep(700);
await shot('evidence-centre-button', 'The same question asked from the button, for anyone not using a pointer.');

const consoleErrors = events
  .filter((e) => e.method === 'Log.entryAdded' && e.params.entry.level === 'error')
  .map((e) => e.params.entry.text);

writeFileSync(`${OUT}/run.json`, `${JSON.stringify({
  url: URL_,
  viewport: '1280x720 css px, deviceScaleFactor 1',
  mountMs,
  observationGraphReadyMs: readyMs,
  totalMs: Date.now() - startedAt,
  inspectorSceneId: opened,
  canvasRect: rect,
  attempts,
  consoleErrors,
  captures,
}, null, 2)}\n`);

ws.close();
chrome.kill();
console.log(JSON.stringify({ mountMs, readyMs, attempts, consoleErrors: consoleErrors.slice(0, 5) }, null, 2));
