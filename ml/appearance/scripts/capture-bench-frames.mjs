// Render the tile runtime bench's procedural look at the cameras of a structure capture.
//
//   node ml/appearance/scripts/capture-bench-frames.mjs <bench url> <structure capture dir> <out dir>
//
// It drives a throwaway headless Chrome over the DevTools protocol, waits for `window.bench`,
// shows the bench street, and for every camera in the capture's index.json sets the canvas size
// and the pose from that camera's structure record, pumps frames synchronously and saves the
// canvas as <camera name>.png. It edits nothing in the bench; it calls the bench's own automation
// surface (showStreet, resize, pose, pump) exactly as lane 16's evidence scripts do.
import { spawn } from 'node:child_process';
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const [url, captureDir, outDir] = process.argv.slice(2);
if (!url || !captureDir || !outDir) {
  console.error('usage: capture-bench-frames.mjs <bench url> <structure capture dir> <out dir>');
  process.exit(2);
}
mkdirSync(outDir, { recursive: true });
const index = JSON.parse(readFileSync(join(captureDir, 'index.json'), 'utf8'));
const cameras = [
  ...Object.values(index.poses),
  ...index.walk,
].map((entry) => {
  const record = JSON.parse(readFileSync(join(captureDir, 'structures', `${entry.structure_sha256}.json`), 'utf8'));
  const c = record.camera;
  if (c.vertical_fov_degrees !== 70 || c.near_um !== 80000) throw new Error(`${entry.name}: not the bench camera`);
  return { name: entry.name, width: c.width, height: c.height, position: c.position_um.map((v) => v / 1e6), target: c.target_um.map((v) => v / 1e6) };
});

const profile = mkdtempSync(join(tmpdir(), 'appearance-cdp-'));
const port = 9800 + Math.floor(Math.random() * 150);
const chrome = spawn('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', [
  '--headless=new', `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`,
  '--window-size=1440,900', '--hide-scrollbars', '--no-first-run', 'about:blank',
], { stdio: 'ignore' });
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
let targets;
for (let attempt = 0; attempt < 100 && !targets; attempt += 1) {
  try { targets = await (await fetch(`http://127.0.0.1:${port}/json`)).json(); } catch { await sleep(200); }
}
const page = targets.find((target) => target.type === 'page');
const socket = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((resolve) => socket.addEventListener('open', resolve, { once: true }));
let counter = 0;
const pending = new Map();
const logs = [];
socket.addEventListener('message', (event) => {
  const message = JSON.parse(event.data);
  if (message.id !== undefined && pending.has(message.id)) { pending.get(message.id)(message); pending.delete(message.id); }
  if (message.method === 'Runtime.exceptionThrown') logs.push(`EXCEPTION ${message.params.exceptionDetails.text}`);
});
const send = (method, params = {}) => new Promise((resolve) => {
  const id = ++counter; pending.set(id, resolve); socket.send(JSON.stringify({ id, method, params }));
});
const evaluate = async (expression) => {
  const reply = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
  if (reply.result?.exceptionDetails) throw new Error(`${expression.slice(0, 80)}: ${reply.result.exceptionDetails.exception?.description ?? reply.result.exceptionDetails.text}`);
  return reply.result?.result?.value;
};

const written = [];
try {
  await send('Runtime.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await send('Page.enable');
  await send('Page.navigate', { url });
  const deadline = Date.now() + 120000;
  // The canvas has id "bench", so window.bench names the element until the bench replaces it; the
  // page marks itself ready once the bench exists and has drawn its street.
  while (!(await evaluate("['true', 'error'].includes(document.body.dataset.ready)").catch(() => false))) {
    if (Date.now() > deadline) throw new Error('the bench never became ready');
    await sleep(500);
  }
  const failure = await evaluate('window.benchError ?? null');
  if (failure) throw new Error(`bench failed: ${failure}`);
  await evaluate('window.bench.showStreet().then(() => window.bench.drawnSets)');
  for (const camera of cameras) {
    const png = await evaluate(`(() => {
      const b = window.bench;
      b.resize(${camera.width}, ${camera.height});
      b.pose({ position: ${JSON.stringify(camera.position)}, target: ${JSON.stringify(camera.target)} });
      b.pump(4);
      return b.canvas.toDataURL('image/png');
    })()`);
    const file = join(outDir, `${camera.name}.png`);
    writeFileSync(file, Buffer.from(png.slice(png.indexOf(',') + 1), 'base64'));
    written.push(camera.name);
  }
  writeFileSync(join(outDir, 'capture-log.json'), `${JSON.stringify({ url, cameras: written.length, logs }, null, 1)}\n`);
  console.log(`wrote ${written.length} frames to ${outDir}`);
} finally {
  socket.close();
  chrome.kill('SIGTERM');
  await sleep(300);
  rmSync(profile, { recursive: true, force: true });
}
