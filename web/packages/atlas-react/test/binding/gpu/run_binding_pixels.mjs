// The binding's GPU pixel scenes, headless, so they queue behind the machine-wide GPU slot.
//
//   node run_binding_pixels.mjs --port <vite port> --worktree <path> [--out <dir>] [--repeat N]
//                               [--only scene,scene] [--plate] [--pin <file> | --check <file>]
//
// --pin writes the scenes' digests, with the browser and renderer they were drawn on, to <file>;
// --check compares this run with <file> and exits 1 when a scene differs, or 3 when the run was
// drawn on another browser or renderer, whose digests the pin cannot speak for. The committed pin
// is pins/digests.json beside this file. CI has no GPU: the check runs by hand, inside gpu-slot.
//
// Serves nothing itself: the app's Vite dev server for <worktree> must be running on <port>. The
// page is a plain document on that origin (the dev server's /@vite/env module), so the app does
// not boot beside the scenes. Prints one JSON document: browser, renderer, and per repeat every
// scene's SHA-256 and drawn pixel count. With --out, also writes each scene's PNG from the first
// repeat. With --plate, also the marker plate sweeps (plateSweeps). Node 22 or later (global
// WebSocket); no packages.
import { spawn } from 'node:child_process';
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';
import zlib from 'node:zlib';

const argument = (name, fallback) => {
  const at = process.argv.indexOf(`--${name}`);
  return at > 0 ? process.argv[at + 1] : fallback;
};
const port = argument('port');
const worktree = argument('worktree');
const out = argument('out');
const repeat = Number(argument('repeat', '1'));
const only = argument('only')?.split(',');
const plates = process.argv.includes('--plate');
const pinTo = argument('pin');
const checkAgainst = argument('check');
if (!port || !worktree) throw new Error('usage: run_binding_pixels.mjs --port <vite port> --worktree <path>');

function crc32(buffer) {
  let c = ~0;
  for (let i = 0; i < buffer.length; i += 1) {
    c ^= buffer[i];
    for (let k = 0; k < 8; k += 1) c = (c >>> 1) ^ (0xedb88320 & -(c & 1));
  }
  return ~c >>> 0;
}
function png(width, height, rgba) {
  const raw = Buffer.alloc((width * 4 + 1) * height);
  for (let y = 0; y < height; y += 1) rgba.copy(raw, y * (width * 4 + 1) + 1, y * width * 4, (y + 1) * width * 4);
  const chunk = (type, data) => {
    const length = Buffer.alloc(4); length.writeUInt32BE(data.length);
    const body = Buffer.concat([Buffer.from(type), data]);
    const crc = Buffer.alloc(4); crc.writeUInt32BE(crc32(body));
    return Buffer.concat([length, body, crc]);
  };
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0); header.writeUInt32BE(height, 4); header[8] = 8; header[9] = 6;
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', header),
    chunk('IDAT', zlib.deflateSync(raw)), chunk('IEND', Buffer.alloc(0))]);
}

const debugPort = 9800 + Math.floor(Math.random() * 180);
const profile = mkdtempSync(join(tmpdir(), 'binding-pixels-'));
const chrome = spawn('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', [
  '--headless=new', `--remote-debugging-port=${debugPort}`, `--user-data-dir=${profile}`,
  '--window-size=1280,800', '--no-first-run', '--no-default-browser-check',
  '--disable-background-timer-throttling', '--disable-renderer-backgrounding', 'about:blank',
], { stdio: 'ignore' });

let socket;
let nextId = 1;
const pending = new Map();
const send = (method, params = {}) => {
  const id = nextId++;
  socket.send(JSON.stringify({ id, method, params }));
  return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
};
async function evaluate(expression) {
  const result = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
  if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails).slice(0, 2000));
  return result.result.value;
}

const base = `/@fs${worktree}/web`;
const MODULE = `${base}/packages/atlas-react/test/binding/gpu/binding-pixels.ts`;
let code = 0;
try {
  let page;
  for (let attempt = 0; attempt < 80 && page === undefined; attempt += 1) {
    try {
      const targets = await (await fetch(`http://127.0.0.1:${debugPort}/json/list`)).json();
      page = targets.find((target) => target.type === 'page');
    } catch { /* not listening yet */ }
    if (page === undefined) await sleep(250);
  }
  if (page === undefined) throw new Error('Chrome exposed no page');
  const version = await (await fetch(`http://127.0.0.1:${debugPort}/json/version`)).json();
  socket = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve) => socket.addEventListener('open', resolve, { once: true }));
  socket.addEventListener('message', (event) => {
    const message = JSON.parse(event.data);
    if (!message.id || !pending.has(message.id)) return;
    const { resolve, reject } = pending.get(message.id);
    pending.delete(message.id);
    if (message.error) reject(new Error(JSON.stringify(message.error))); else resolve(message.result);
  });
  socket.addEventListener('close', () => {
    for (const { reject } of pending.values()) reject(new Error('the CDP socket closed'));
    pending.clear();
  });
  await send('Page.enable');
  await send('Page.navigate', { url: `http://localhost:${port}/@vite/env` });
  await sleep(1500);
  const renderer = await evaluate(`(() => { const gl = document.createElement('canvas').getContext('webgl2');
    const info = gl.getExtension('WEBGL_debug_renderer_info'); return gl.getParameter(info.UNMASKED_RENDERER_WEBGL); })()`);
  const runs = [];
  for (let index = 0; index < repeat; index += 1) {
    runs.push(await evaluate(`(async () => {
      const module = await import(${JSON.stringify(MODULE)});
      return module.renderBindingScenes(${JSON.stringify(base)}, ${JSON.stringify(only ?? null)} ?? undefined);
    })()`));
  }
  if (out !== undefined) {
    mkdirSync(out, { recursive: true });
    const names = runs[0].map((digest) => digest.scene);
    for (const name of names) {
      const shot = await evaluate(`(async () => {
        const module = await import(${JSON.stringify(MODULE)});
        const opm = (await import(${JSON.stringify(`${base}/packages/atlas-react/src/playcanvas/opm.ts`)}))
          .decodeOpm(await (await fetch(${JSON.stringify(`${base}/packages/atlas-react/test/fixtures/python-writer.opm`)})).arrayBuffer());
        const scene = module.PIXEL_SCENES.find((s) => s.name === ${JSON.stringify(name)});
        const drawn = await module.renderScene(scene, ${JSON.stringify(base)}, opm);
        let binary = '';
        for (let i = 0; i < drawn.pixels.length; i += 32768) binary += String.fromCharCode.apply(null, drawn.pixels.subarray(i, i + 32768));
        return { width: drawn.width, height: drawn.height, data: btoa(binary) };
      })()`);
      writeFileSync(join(out, `${name}.png`), png(shot.width, shot.height, Buffer.from(shot.data, 'base64')));
    }
  }
  const identical = runs.every((run) => JSON.stringify(run) === JSON.stringify(runs[0]));
  const plateSweeps = plates ? await evaluate(`(async () => {
    const module = await import(${JSON.stringify(MODULE)});
    return module.plateSweeps(${JSON.stringify(base)});
  })()`) : null;
  process.stdout.write(`${JSON.stringify({ port, worktree, browser: version.Browser, renderer, repeats: repeat,
    identical_across_repeats: identical, scenes: runs[0], plate_sweeps: plateSweeps, runs }, null, 1)}\n`);
  const digests = runs[0].map(({ scene, sha256, drawnPixels, skyColours }) => ({ scene, sha256, drawnPixels, skyColours }));
  if (pinTo !== undefined) {
    if (!identical) throw new Error('the repeats differ, so there is no one digest per scene to pin');
    writeFileSync(pinTo, `${JSON.stringify({ browser: version.Browser, renderer, width: runs[0][0]?.width,
      height: runs[0][0]?.height, scenes: digests }, null, 1)}\n`);
  }
  if (checkAgainst !== undefined) {
    const pin = JSON.parse(readFileSync(checkAgainst, 'utf8'));
    if (pin.browser !== version.Browser || pin.renderer !== renderer) {
      process.stderr.write(`not comparable: pinned on ${pin.browser} / ${pin.renderer}, drawn on ${version.Browser} / ${renderer}\n`);
      code = 3;
    } else {
      const pinned = new Map(pin.scenes.map((scene) => [scene.scene, scene]));
      const differing = digests.filter((scene) => JSON.stringify(pinned.get(scene.scene)) !== JSON.stringify(scene))
        .map((scene) => scene.scene);
      const missing = [...pinned.keys()].filter((name) => !digests.some((scene) => scene.scene === name));
      if (differing.length > 0 || missing.length > 0 || !identical) {
        process.stderr.write(`differs from the pin: ${[...differing, ...missing.map((name) => `${name} (not drawn)`)].join(', ') || 'repeats differ'}\n`);
        code = 1;
      } else {
        process.stderr.write(`${digests.length} scenes match the pin\n`);
      }
    }
  }
} catch (error) {
  code = 1;
  process.stderr.write(`${error.stack ?? error}\n`);
} finally {
  try { socket?.close(); } catch { /* already closed */ }
  chrome.kill('SIGKILL');
  await sleep(500);
  rmSync(profile, { recursive: true, force: true });
  process.exit(code);
}
