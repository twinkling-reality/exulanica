/**
 * Ask the Companion about a confirmed place in the running app, open what it cites, and keep what
 * a person saw.
 *
 *   node scripts/capture_companion_place_link.mjs --state STATE.json --out DIR
 *
 * STATE.json is the acceptance runtime's state file, for a workspace in which
 * `scripts/measure_companion_place_link.py run` has already confirmed the place through product
 * routes. This script only reads and asks. It opens the app in headless Chrome over the DevTools
 * protocol, with no package beyond Node's own WebSocket, and for each question the pre-registration
 * names (read from the record, never written here):
 *
 *   1. opens the Companion from the World menu and asks the question in the Companion's own field;
 *   2. records the answer as the page drew it: each clause's text, and each name the page restored
 *      or said in words, with the placeholder and entity it stood for; then screenshots it;
 *   3. for the first question, opens the first citation twice. First with the photograph's read
 *      answered 410 by this script through the DevTools Fetch domain, the answer a deleted
 *      photograph gets, because no route deletes one: the page must say the photograph cannot be
 *      shown and draw no picture. The product's server is not asked that time, and the record
 *      says so. Then with nothing intercepted: the page must draw the masked photograph the server
 *      returns. Each face is recorded and screenshotted, and each time it goes back to the answer.
 *
 * It reads no credential: the page holds the synthetic token the runtime's dev server serves.
 * Request headers are never recorded. Exit 0 with evidence.json; any step that fails is recorded
 * with a screenshot of the page at that moment, and the exit is 1.
 */

import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';
import { fileURLToPath } from 'node:url';

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const ROOT = resolve(fileURLToPath(new URL('..', import.meta.url)));
const PREREGISTRATION = 'docs/evaluation/2026-09-23-companion-place-link-preregistration.json';
const VIEWPORT = { width: 1280, height: 860 };

function argument(name) {
  const at = process.argv.indexOf(`--${name}`);
  if (at < 0 || process.argv[at + 1] === undefined) throw new Error(`--${name} is required`);
  return process.argv[at + 1];
}

const state = JSON.parse(readFileSync(resolve(argument('state')), 'utf8'));
const out = resolve(argument('out'));
mkdirSync(join(out, 'screens'), { recursive: true });
const questions = JSON.parse(readFileSync(join(ROOT, PREREGISTRATION), 'utf8')).record.questions;
const appUrl = `http://localhost:${state.ports.vite}/`;

// -- Chrome and the DevTools protocol ---------------------------------------------------------

const profile = join(out, `chrome-profile-${Date.now()}`);
const chrome = spawn(CHROME, [
  '--headless=new', `--remote-debugging-port=${state.ports.browser}`, `--user-data-dir=${profile}`,
  `--window-size=${VIEWPORT.width},${VIEWPORT.height}`, '--no-first-run',
  '--no-default-browser-check', '--disable-extensions', '--disable-background-networking',
  '--disable-sync', '--password-store=basic', '--use-mock-keychain', 'about:blank',
], { stdio: 'ignore', detached: true });
const stopChrome = () => {
  try { process.kill(-chrome.pid, 'SIGTERM'); } catch { /* already gone */ }
};
process.on('exit', stopChrome);

async function pageTarget() {
  for (let attempt = 0; attempt < 60; attempt += 1) {
    try {
      const listed = await (await fetch(`http://127.0.0.1:${state.ports.browser}/json/list`)).json();
      const page = listed.find((target) => target.type === 'page');
      if (page) return page.webSocketDebuggerUrl;
    } catch { /* not listening yet */ }
    await sleep(250);
  }
  throw new Error('headless Chrome exposed no page target');
}

const socket = new WebSocket(await pageTarget());
await new Promise((ok, fail) => { socket.onopen = ok; socket.onerror = fail; });
let nextId = 1;
const pending = new Map();
const listeners = [];
socket.onmessage = (event) => {
  const message = JSON.parse(event.data);
  if (message.id && pending.has(message.id)) {
    const { ok, fail } = pending.get(message.id);
    pending.delete(message.id);
    if (message.error) fail(new Error(message.error.message));
    else ok(message.result);
  } else if (message.method) {
    for (const listener of listeners) listener(message.method, message.params);
  }
};
// A closed socket fails everything still waiting, so a dropped connection ends the run.
socket.onclose = () => {
  for (const [id, { fail }] of pending) {
    pending.delete(id);
    fail(new Error('the DevTools socket closed'));
  }
};
function send(method, params = {}) {
  const id = nextId++;
  socket.send(JSON.stringify({ id, method, params }));
  return new Promise((ok, fail) => pending.set(id, { ok, fail }));
}

// -- what the page did ------------------------------------------------------------------------

const record = {
  runtime: {
    workspace_id: state.workspace_id, tree: state.tree, ports: state.ports,
    api_imported_exulanica_from: state.api_imported_exulanica_from,
    started_at: new Date().toISOString(),
  },
  viewport: VIEWPORT,
  steps: [],
  console: [],
};
let current = null;
const requests = new Map();
listeners.push((method, params) => {
  if (method === 'Network.requestWillBeSent' && params.request.url.includes('/api/')) {
    requests.set(params.requestId, {
      step: current?.name ?? null,
      method: params.request.method,
      path: new URL(params.request.url).pathname,
      status: null,
    });
  } else if (method === 'Network.responseReceived' && requests.has(params.requestId)) {
    requests.get(params.requestId).status = params.response.status;
  } else if (method === 'Network.loadingFinished' && requests.has(params.requestId)) {
    // What each model call cost, as the answer's own execution block reports the provider's usage.
    // Only the two routes that call a model, and only that block, never a header.
    const entry = requests.get(params.requestId);
    if (!/\/selection\/(ask|appearance)$/.test(entry.path)) return;
    entry.body = send('Network.getResponseBody', { requestId: params.requestId })
      .then((response) => {
        const parsed = JSON.parse(response.body);
        entry.execution = parsed.execution ?? null;
        entry.classification = parsed.classification ?? null;
      })
      .catch((error) => { entry.execution = `unreadable: ${error.message}`; });
  } else if (method === 'Network.loadingFailed' && requests.has(params.requestId)) {
    requests.get(params.requestId).status = `failed: ${params.errorText}`;
  } else if (method === 'Runtime.consoleAPICalled' && ['error', 'warning'].includes(params.type)) {
    record.console.push({
      step: current?.name ?? null,
      type: params.type,
      text: params.args.map((arg) => arg.value ?? arg.description ?? '').join(' ').slice(0, 600),
    });
  } else if (method === 'Runtime.exceptionThrown') {
    record.console.push({
      step: current?.name ?? null,
      type: 'exception',
      text: (params.exceptionDetails.exception?.description ?? params.exceptionDetails.text)
        .slice(0, 600),
    });
  }
});
await send('Network.enable');
await send('Page.enable');
await send('Runtime.enable');
await send('Emulation.setDeviceMetricsOverride', { ...VIEWPORT, deviceScaleFactor: 1, mobile: false });

async function evaluate(expression) {
  const result = await send('Runtime.evaluate', {
    expression, awaitPromise: true, returnByValue: true, userGesture: true,
  });
  if (result.exceptionDetails) {
    throw new Error(result.exceptionDetails.exception?.description ?? result.exceptionDetails.text);
  }
  return result.result.value;
}

async function waitFor(expression, label, timeoutMs = 20_000) {
  const deadline = Date.now() + timeoutMs;
  let last;
  while (Date.now() < deadline) {
    try {
      last = await evaluate(expression);
      if (last) return last;
    } catch (error) {
      last = error.message;
    }
    await sleep(250);
  }
  throw new Error(`timed out after ${timeoutMs} ms waiting for ${label} (last: ${JSON.stringify(last)})`);
}

/** A trusted click at the element's centre, or a programmatic one when something covers it. */
async function click(expression, label) {
  const target = await waitFor(`(() => { const e = ${expression}; if (!e) return null;
    e.scrollIntoView({ block: 'center' }); const r = e.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return null;
    const x = r.left + r.width / 2, y = r.top + r.height / 2; const hit = document.elementFromPoint(x, y);
    return { x, y, covered: hit !== e && !e.contains(hit) }; })()`, label);
  if (target.covered) {
    current?.notes.push(`${label} was covered at its centre, so it was clicked programmatically`);
    await evaluate(`(${expression}).click()`);
    return;
  }
  for (const type of ['mouseMoved', 'mousePressed', 'mouseReleased']) {
    await send('Input.dispatchMouseEvent', { type, x: target.x, y: target.y, button: 'left', clickCount: 1 });
  }
}

async function screenshot(name, shows) {
  await evaluate('new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => r(true))))');
  await sleep(400);
  const shot = await send('Page.captureScreenshot', { format: 'png' });
  const bytes = Buffer.from(shot.data, 'base64');
  const file = `${String(record.steps.length + 1).padStart(2, '0')}-${name}.png`;
  writeFileSync(join(out, 'screens', file), bytes);
  current?.screenshots.push({ file, shows, sha256: createHash('sha256').update(bytes).digest('hex') });
}

async function step(name, body) {
  current = { name, ok: null, error: null, notes: [], seen: {}, screenshots: [], requests: [] };
  const before = new Set(requests.keys());
  try {
    await body(current);
    current.ok = true;
  } catch (error) {
    current.ok = false;
    current.error = String(error.stack ?? error);
    try { await screenshot('failure', 'the page when the step failed'); } catch { /* nothing to show */ }
  }
  await sleep(300);
  const mine = [...requests.entries()].filter(([id]) => !before.has(id)).map(([, r]) => r);
  await Promise.all(mine.map((entry) => entry.body).filter(Boolean));
  current.requests = mine.map(({ body, ...entry }) => entry);
  record.steps.push(current);
  console.log(`${current.ok ? 'PASS' : 'FAIL'} ${name}${current.ok ? '' : `: ${(current.error ?? '').split('\n')[0]}`}`);
  writeFileSync(join(out, 'evidence.json'), `${JSON.stringify(record, null, 2)}\n`);
  current = null;
}

// -- the Companion ------------------------------------------------------------------------------

const FIELD = `document.querySelector('.companion-encounter .companion-composer textarea, .companion-encounter .companion-composer input')`;
const SPEECH = `document.querySelector('.companion-encounter .companion-speech')`;

/** The answer as drawn: each clause, and each name restored or said in words. */
const DRAWN = `(() => {
  const speech = ${SPEECH};
  return {
    mode: speech?.dataset.mode ?? null,
    question: speech?.querySelector('.companion-question-echo')?.textContent ?? null,
    clauses: [...(speech?.querySelectorAll('.companion-utterance') ?? [])].map((p) => p.textContent),
    names: [...(speech?.querySelectorAll('.companion-name') ?? [])].map((span) => ({
      text: span.textContent,
      placeholder: span.dataset.placeholder ?? null,
      entity_id: span.dataset.entityId ?? null,
      unresolved: span.dataset.unresolved ?? null,
    })),
    brackets_left: /\\[(person|voice|place|object|conversation|event) [A-Z]+\\]/i
      .test(speech?.textContent ?? ''),
    provenance: speech?.querySelector('.companion-provenance')?.textContent ?? null,
    chips: [...document.querySelectorAll('.companion-encounter .companion-evidence-chip')]
      .map((chip) => ({ text: chip.textContent.trim(), disabled: chip.disabled })),
  };
})()`;

/** The photograph face as drawn: its title, the picture or the sentence, and the way back. */
const VIEW = `(() => { const v = document.querySelector('.companion-evidence');
  const image = v.querySelector('img');
  return {
    title: v.querySelector('.companion-evidence-title')?.textContent ?? null,
    caption: v.querySelector('.companion-evidence-caption')?.textContent ?? null,
    unavailable: v.querySelector('.companion-evidence-unavailable')?.textContent ?? null,
    unavailable_detail: v.querySelector('.companion-evidence-unavailable-detail')?.textContent ?? null,
    image: image === null ? null : {
      scheme: image.currentSrc.split(':')[0], width: image.naturalWidth, height: image.naturalHeight,
    },
    back: v.querySelector('.companion-evidence-back')?.textContent.trim() ?? null,
    focused: document.activeElement?.classList.contains('companion-evidence-back') ?? false,
  };
})()`;

async function openCompanion(seen) {
  await click(`document.querySelector('button[aria-label="Open World menu"]')`, 'the World menu');
  await click(`[...document.querySelectorAll('.world-menu button, .world-menu [role=menuitem]')]
    .find((item) => item.textContent.includes('Companion'))`, 'the Companion entry');
  await waitFor(`document.querySelector('.companion-encounter')?.dataset.state === 'open'`, 'the open Companion');
  const field = await evaluate(`!!(${FIELD}) && (${FIELD}).getClientRects().length > 0`);
  if (!field) {
    // An open turn keeps the question field behind "Other…", which is how a person asks their own.
    await click(`[...document.querySelectorAll('.companion-encounter button')]
      .find((b) => b.textContent.includes('Other') && b.getClientRects().length > 0)`, 'Other…');
    seen.revealed_through_other = true;
  }
}

async function ask(question) {
  await waitFor(`!!(${FIELD}) && (${FIELD}).getClientRects().length > 0`, 'the question field');
  await evaluate(`(() => { const e = ${FIELD}; e.focus(); e.select?.(); return true; })()`);
  await send('Input.insertText', { text: question });
  const key = { key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 };
  await send('Input.dispatchKeyEvent', { type: 'keyDown', ...key, text: '\r' });
  await send('Input.dispatchKeyEvent', { type: 'keyUp', ...key });
  await waitFor(`['answer', 'failed'].includes(${SPEECH}?.dataset.mode) && ${SPEECH}?.querySelector('.companion-question-echo')?.textContent === ${JSON.stringify(question)}`, 'an answer', 180_000);
  await sleep(600);
}

await step('open the app', async (seen) => {
  await send('Page.navigate', { url: appUrl });
  await waitFor(`document.readyState === 'complete' && !!document.querySelector('button[aria-label="Open World menu"]')
    && !document.querySelector('#shell')?.hasAttribute('aria-busy')`, 'the world chrome', 60_000);
  await sleep(1500);
  seen.title = await evaluate('document.title');
});

for (const [position, question] of questions.entries()) {
  await step(`ask ${question.id}`, async (seen) => {
    if (position === 0) await openCompanion(seen);
    else {
      // The answer face keeps its own question field revealed; the next question goes there.
      await waitFor(`${SPEECH}?.dataset.mode === 'answer'`, 'the previous answer');
    }
    await ask(question.text);
    seen.drawn = await evaluate(DRAWN);
    await screenshot(`answer-${question.id}`, `the Companion's answer to "${question.text}"`);
  });

  if (position !== 0) continue;
  await step(`open the photograph ${question.id} cites, its read answered 410 by this script`, async (seen) => {
    const refused = [];
    listeners.push((method, params) => {
      if (method !== 'Fetch.requestPaused') return;
      refused.push(new URL(params.request.url).pathname);
      void send('Fetch.fulfillRequest', {
        requestId: params.requestId,
        responseCode: 410,
        responseHeaders: [{ name: 'Content-Type', value: 'application/json' }],
        body: Buffer.from(JSON.stringify({ detail: 'deleted' })).toString('base64'),
      });
    });
    await send('Fetch.enable', { patterns: [{ urlPattern: '*/api/evidence/*/masked', requestStage: 'Request' }] });
    try {
      await click(`document.querySelector('.companion-encounter .companion-evidence-chip:not([disabled])')`, 'the first citation');
      seen.evidence = await waitFor(`(() => { const v = document.querySelector('.companion-evidence');
        return v && v.dataset.evidence !== 'opening' ? v.dataset.evidence : null; })()`, 'the stated absence', 30_000);
      seen.view = await evaluate(VIEW);
      seen.injected = { status: 410, by: 'this script, through the DevTools Fetch domain', paths: refused };
      await screenshot(`photograph-refused-${question.id}`, 'a photograph whose read was answered 410, said in words with no picture');
    } finally {
      await send('Fetch.disable');
      listeners.pop();
    }
    await click(`document.querySelector('.companion-evidence-back')`, 'Back to the answer');
    await waitFor(`${SPEECH}?.dataset.mode === 'answer'`, 'the answer again');
  });

  await step(`open the photograph ${question.id} cites`, async (seen) => {
    await click(`document.querySelector('.companion-encounter .companion-evidence-chip:not([disabled])')`, 'the first citation');
    const face = await waitFor(`(() => { const v = document.querySelector('.companion-evidence');
      return v && v.dataset.evidence !== 'opening' ? v.dataset.evidence : null; })()`, 'the photograph or its stated absence', 30_000);
    seen.evidence = face;
    seen.view = await evaluate(VIEW);
    await screenshot(`photograph-${question.id}`, 'the cited photograph, drawn inside the Companion');
    await click(`document.querySelector('.companion-evidence-back')`, 'Back to the answer');
    await waitFor(`${SPEECH}?.dataset.mode === 'answer'`, 'the answer again');
    seen.back = await evaluate(DRAWN);
  });
}

record.finished_at = new Date().toISOString();
writeFileSync(join(out, 'evidence.json'), `${JSON.stringify(record, null, 2)}\n`);
stopChrome();
process.exit(record.steps.every((entry) => entry.ok) ? 0 : 1);
