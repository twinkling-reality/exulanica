// Headless Chrome and the DevTools protocol for one rehearsal page session. No package beyond
// Node's own WebSocket, on the pattern of scripts/capture_visual_gate.mjs.
//
// One `open()` is one Chrome process with its own profile directory and one page. The rehearsal
// gives every long step group its own page session, because one headless Chrome driven through
// several heavy cycles in a single page has stopped answering mid-run on this machine while the
// page itself kept rendering.
//
// The page's /api/ traffic is recorded (method, path, status, and the body of a JSON response up
// to RESPONSE_BODY_LIMIT_BYTES), never a request header, so the bearer credential the page sends
// is never written anywhere.

import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';

export const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
// The viewport every earlier real-app acceptance on this product used (drive.mjs, the developer
// client's screenshot), wide enough that the app does not show its narrow-screen boundary.
export const VIEWPORT = Object.freeze({ width: 1280, height: 860 });
// A multi-megabyte body over the debugging socket closes Node's WebSocket (measured: a 12.7 MB
// body closed it; 0.56 MB did not), so bodies above this are recorded by size only.
const RESPONSE_BODY_LIMIT_BYTES = 2_000_000;
// Characters of a recorded response body; enough for an answer's clauses and execution block.
const RECORDED_BODY_CHARACTERS = 20_000;
// How long one protocol call may take before the run says so; a screenshot of a busy WebGL page
// is the slowest call this driver makes.
const CALL_TIMEOUT_MS = 120_000;

class Connection {
  constructor(url) {
    this.socket = new WebSocket(url);
    this.next = 1;
    this.pending = new Map();
    this.handlers = [];
    this.closed = null;
    this.socket.addEventListener('message', (event) => {
      const message = JSON.parse(event.data);
      if (message.id !== undefined && this.pending.has(message.id)) {
        const waiter = this.pending.get(message.id);
        this.pending.delete(message.id);
        if (message.error) waiter.reject(new Error(`${waiter.method}: ${message.error.message}`));
        else waiter.resolve(message.result);
      } else if (message.method) {
        for (const handler of this.handlers) handler(message.method, message.params);
      }
    });
    // A closed socket rejects every waiting call with the transport's own reason. Without this a
    // dropped connection reads as a slow call, and the timeout blames the next innocent call.
    const fail = (reason) => {
      this.closed ??= reason;
      for (const [id, waiter] of this.pending) {
        this.pending.delete(id);
        waiter.reject(new Error(`${waiter.method}: ${this.closed}`));
      }
    };
    this.socket.addEventListener('close', (event) => fail(`the DevTools socket closed (code ${event.code})`));
    this.socket.addEventListener('error', () => fail('the DevTools socket reported an error'));
  }

  opened() {
    return new Promise((resolve, reject) => {
      this.socket.addEventListener('open', resolve, { once: true });
      this.socket.addEventListener('error', reject, { once: true });
    });
  }

  send(method, params = {}, timeoutMs = CALL_TIMEOUT_MS) {
    if (this.closed) return Promise.reject(new Error(`${method}: ${this.closed}`));
    const id = this.next++;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`${method} did not answer within ${timeoutMs} ms`));
      }, timeoutMs);
      this.pending.set(id, {
        method,
        resolve: (value) => { clearTimeout(timer); resolve(value); },
        reject: (error) => { clearTimeout(timer); reject(error); },
      });
      this.socket.send(JSON.stringify({ id, method, params }));
    });
  }

  on(handler) { this.handlers.push(handler); }
}

/**
 * One headless Chrome with one page, and the evidence it collects.
 *
 * `appOrigin` is the application's origin, used to write request paths without it. `profile` is a
 * fresh directory for this session only.
 */
export async function open({ port, profile, appOrigin, flags = [] }) {
  mkdirSync(profile, { recursive: true });
  const argv = [
    '--headless=new', `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`,
    `--window-size=${VIEWPORT.width},${VIEWPORT.height}`, '--hide-scrollbars', '--no-first-run',
    '--no-default-browser-check', '--disable-extensions', '--disable-background-networking',
    '--disable-sync', '--password-store=basic', '--use-mock-keychain',
    '--disable-background-timer-throttling', '--disable-renderer-backgrounding',
    '--disable-backgrounding-occluded-windows', ...flags, 'about:blank',
  ];
  const chrome = spawn(CHROME, argv, { stdio: 'ignore', detached: true });
  const stopChrome = () => { try { process.kill(-chrome.pid, 'SIGTERM'); } catch { /* gone */ } };
  process.on('exit', stopChrome);

  let target = null;
  for (let attempt = 0; attempt < 80 && target === null; attempt += 1) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
      target = list.find((entry) => entry.type === 'page')?.webSocketDebuggerUrl ?? null;
    } catch { /* not listening yet */ }
    if (target === null) await sleep(250);
  }
  if (target === null) {
    stopChrome();
    throw new Error(`headless Chrome exposed no page on port ${port}`);
  }
  const connection = new Connection(target);
  await connection.opened();

  const requests = new Map();
  const consoleLines = [];
  let label = null;
  connection.on((method, params) => {
    if (method === 'Network.requestWillBeSent' && params.request.url.includes('/api/')) {
      const url = new URL(params.request.url);
      requests.set(params.requestId, {
        label, method: params.request.method, path: url.pathname + url.search, status: null,
        response_body: null, started: Date.now(),
      });
    } else if (method === 'Network.responseReceived' && requests.has(params.requestId)) {
      const entry = requests.get(params.requestId);
      entry.status = params.response.status;
      entry.mime = params.response.mimeType;
    } else if (method === 'Network.loadingFinished' && requests.has(params.requestId)) {
      const entry = requests.get(params.requestId);
      entry.bytes = params.encodedDataLength;
      if (!String(entry.mime ?? '').includes('json')) return;
      if (params.encodedDataLength > RESPONSE_BODY_LIMIT_BYTES) {
        entry.response_body = `(${params.encodedDataLength} bytes, not read)`;
        return;
      }
      entry.reading = connection.send('Network.getResponseBody', { requestId: params.requestId }, 30_000)
        .then((body) => {
          const text = body.base64Encoded ? '(binary)' : body.body;
          try { entry.response_body = JSON.parse(text); } catch { entry.response_body = text.slice(0, RECORDED_BODY_CHARACTERS); }
        })
        .catch((error) => { entry.response_body = `(unavailable: ${error.message})`; });
    } else if (method === 'Network.loadingFailed' && requests.has(params.requestId)) {
      requests.get(params.requestId).status = `failed: ${params.errorText}`;
    } else if (method === 'Runtime.consoleAPICalled' && ['error', 'warning'].includes(params.type)) {
      consoleLines.push({ label, type: params.type,
        text: params.args.map((a) => a.value ?? a.description ?? '').join(' ').slice(0, 800) });
    } else if (method === 'Runtime.exceptionThrown') {
      consoleLines.push({ label, type: 'exception',
        text: String(params.exceptionDetails.exception?.description ?? params.exceptionDetails.text).slice(0, 800) });
    }
  });
  await connection.send('Network.enable', { maxResourceBufferSize: 20_000_000, maxTotalBufferSize: 100_000_000 });
  await connection.send('Page.enable');
  await connection.send('Runtime.enable');
  await connection.send('DOM.enable');
  await connection.send('Emulation.setDeviceMetricsOverride', {
    width: VIEWPORT.width, height: VIEWPORT.height, deviceScaleFactor: 1, mobile: false,
  });

  const page = {
    connection,
    argv: argv.map((value) => (value.startsWith('--user-data-dir=') ? '--user-data-dir=<session profile>' : value)),
    appOrigin,
    /** Label the traffic and console lines that follow, so a step's evidence is its own. */
    label(name) { label = name; },
    /** The /api/ requests recorded under a label, with their bodies read. */
    async traffic(name) {
      const mine = [...requests.values()].filter((entry) => entry.label === name);
      await Promise.all(mine.map((entry) => entry.reading).filter(Boolean));
      return mine.map(({ reading, label: _label, started: _started, ...entry }) => entry);
    },
    console(name) { return consoleLines.filter((line) => line.label === name); },
    async evaluate(expression, timeoutMs = CALL_TIMEOUT_MS) {
      const reply = await connection.send('Runtime.evaluate', {
        expression, awaitPromise: true, returnByValue: true, userGesture: true,
      }, timeoutMs);
      if (reply.exceptionDetails) {
        throw new Error(`evaluate: ${reply.exceptionDetails.exception?.description ?? reply.exceptionDetails.text}`);
      }
      return reply.result.value;
    },
    async waitFor(expression, timeoutMs, what) {
      const deadline = Date.now() + timeoutMs;
      let last;
      while (Date.now() < deadline) {
        try {
          last = await page.evaluate(expression);
          if (last) return last;
        } catch (error) { last = error.message; }
        await sleep(250);
      }
      throw new Error(`waited ${timeoutMs} ms for ${what}; last saw ${JSON.stringify(last)?.slice(0, 300)}`);
    },
    /**
     * A trusted mouse click at the element's centre. When another element covers that point the
     * click would land on the cover, so the element is clicked programmatically and the returned
     * note says so, naming the cover.
     */
    async click(elementExpression, what, timeoutMs = 15_000) {
      const target = await page.waitFor(`(() => { const e = ${elementExpression}; if (!e) return null;
        e.scrollIntoView({block: 'center', inline: 'center'}); const r = e.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) return null;
        const x = r.left + r.width / 2, y = r.top + r.height / 2; const hit = document.elementFromPoint(x, y);
        return {x, y, disabled: !!e.disabled, covered: hit !== e && !e.contains(hit) ?
          (hit ? (typeof hit.className === 'string' && hit.className ? hit.className : hit.tagName) + ': ' + (hit.textContent || '').trim().slice(0, 60) : 'nothing') : null}; })()`,
      timeoutMs, what);
      if (target.disabled) throw new Error(`${what} is disabled`);
      if (target.covered) {
        await page.evaluate(`(${elementExpression}).click()`);
        return `${what} was under ${target.covered}; clicked programmatically`;
      }
      for (const type of ['mouseMoved', 'mousePressed', 'mouseReleased']) {
        await connection.send('Input.dispatchMouseEvent', { type, x: target.x, y: target.y, button: 'left', clickCount: 1 });
      }
      return null;
    },
    async clickAt(x, y) {
      for (const type of ['mouseMoved', 'mousePressed', 'mouseReleased']) {
        await connection.send('Input.dispatchMouseEvent', { type, x, y, button: 'left', clickCount: 1 });
      }
    },
    /** Focus the element, select what it holds, and type with trusted input. */
    async typeInto(elementExpression, text) {
      await page.evaluate(`(() => { const e = ${elementExpression}; e.focus(); e.select?.(); return true; })()`);
      await connection.send('Input.insertText', { text });
    },
    /** A trusted key press: down, held for `holdMs`, up. `text` is what the key types, if anything. */
    async key(code, key, { holdMs = 0, text } = {}) {
      await page.keyDown(code, key, text);
      if (holdMs > 0) await sleep(holdMs);
      await page.keyUp(code, key);
    },
    async keyDown(code, key, text) {
      await connection.send('Input.dispatchKeyEvent', { type: 'keyDown', ...keyFields(code, key), ...(text ? { text } : {}) });
    },
    async keyUp(code, key) {
      await connection.send('Input.dispatchKeyEvent', { type: 'keyUp', ...keyFields(code, key) });
    },
    /** Set a form control's value the way a person's input does, with input and change events. */
    async setValue(elementExpression, value) {
      return page.evaluate(`(() => { const e = ${elementExpression};
        const proto = e instanceof HTMLSelectElement ? HTMLSelectElement.prototype
          : e instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
        Object.getOwnPropertyDescriptor(proto, 'value').set.call(e, ${JSON.stringify(value)});
        e.dispatchEvent(new Event('input', {bubbles: true})); e.dispatchEvent(new Event('change', {bubbles: true}));
        return e.value; })()`);
    },
    async setFiles(elementExpression, files) {
      const handle = await connection.send('Runtime.evaluate', { expression: `(${elementExpression})` });
      await connection.send('DOM.setFileInputFiles', { files, objectId: handle.result.objectId });
    },
    async navigate(url) {
      await connection.send('Page.navigate', { url });
    },
    async reload() {
      await connection.send('Page.reload', { ignoreCache: true });
    },
    /** A PNG of the viewport after two animation frames, so the page has drawn what it shows. */
    async screenshot(directory, name) {
      await page.evaluate('new Promise(r => requestAnimationFrame(() => requestAnimationFrame(() => r(true))))', 10_000).catch(() => null);
      const shot = await connection.send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
      mkdirSync(directory, { recursive: true });
      const bytes = Buffer.from(shot.data, 'base64');
      const file = join(directory, `${name}.png`);
      writeFileSync(file, bytes);
      return { file, bytes };
    },
    async close() {
      try { await connection.send('Browser.close', {}, 5_000); } catch { /* already closing */ }
      await sleep(300);
      stopChrome();
    },
  };
  return page;
}

// Windows virtual key codes for the named keys the rehearsal presses; a letter's is its capital.
const KEY_CODES = Object.freeze({ Enter: 13, Escape: 27, ArrowUp: 38, ArrowDown: 40, ArrowLeft: 37, ArrowRight: 39 });
const keyFields = (code, key) => ({
  code, key, windowsVirtualKeyCode: key.length === 1 ? key.toUpperCase().charCodeAt(0) : KEY_CODES[key] ?? 0,
});
