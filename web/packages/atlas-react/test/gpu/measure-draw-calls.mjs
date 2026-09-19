/**
 * WHERE A FRAME'S DRAW CALLS GO, AND WHAT EACH OF THEM RASTERISES.
 *
 *   node web/packages/atlas-react/test/gpu/measure-draw-calls.mjs \
 *     --url 'http://127.0.0.1:5345/?preview=1&city=<seed>&tile_x=2&tile_y=0&pose_x_mm=...' \
 *     --seconds 4 --settle-seconds 10
 *
 * The visual gate's `practicalBrowserBudget` decides on `maxDrawCalls`, which the product's own
 * recorder takes from `app.stats.drawCalls.total`. In PlayCanvas 2.21.4 that field is assigned
 * `device._drawCallsPerFrame`, which is incremented at EVERY GL draw: the forward pass, every
 * shadow cascade, a depth prepass, and each post effect quad. So one number covers a world's
 * geometry and a look's passes together, and nothing in it says which moved.
 *
 * This says which. It counts every draw by the RENDER TARGET bound at that moment, which is the
 * pass that made it, and counts the triangles each draw submits beside it, BECAUSE A DRAW CALL IS
 * NOT A TRIANGLE: merging batches removes draws and adds geometry to the ones that remain, and
 * only the second column says so. It defines no new number: the per-frame total it reports is the
 * same field the gate reads, and it is checked against it.
 *
 * Four arms over one page, each restored before the next and the set run twice, so a figure that
 * moved because the page moved is visible as a disagreement between the two:
 *
 *   whole          the frame as the product draws it
 *   noTileShadows  every batch under the environment root stops casting: the cascades' share
 *   worldHidden    those batches are disabled: everything the frame costs with no world in it
 *   oneCascade     the sun's cascades cut to one, which prices the look's own choice
 *
 * Two headings, the page's own and the reverse of it, because culling is what a per-tile batching
 * buys and the reverse heading is where a world-wide batching would lose it.
 *
 * It waits for the same condition the gate waits on before reading anything, and then settles:
 * a page that has mounted a world is not a page that has finished arriving, and arms measured
 * across the arrival are arms measured on different scenes.
 *
 * TEST-ONLY. It reads a running dev server and writes nothing to the product.
 */
import { spawn } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const VIEWPORT = { width: 1440, height: 900 };
const ARMS = ['whole', 'noTileShadows', 'worldHidden', 'oneCascade', 'whole'];

const argument = (name, fallback) => {
  const at = process.argv.indexOf(`--${name}`);
  return at >= 0 && process.argv[at + 1] !== undefined ? process.argv[at + 1] : fallback;
};
const url = argument('url', null);
if (url === null) throw new Error('--url is required: the page to measure, with its stated pose');
const seconds = Number(argument('seconds', '4'));
const settleMs = Number(argument('settle-seconds', '10')) * 1000;
const port = Number(argument('cdp-port', String(9600 + Math.floor(Math.random() * 300))));

class Session {
  #socket; #id = 0; #pending = new Map();
  constructor(socket) {
    this.#socket = socket;
    socket.addEventListener('message', (event) => {
      const message = JSON.parse(event.data);
      const waiter = this.#pending.get(message.id);
      if (waiter === undefined) return;
      this.#pending.delete(message.id);
      if (message.error) waiter.reject(new Error(message.error.message));
      else waiter.resolve(message.result);
    });
  }
  send(method, params = {}) {
    const id = ++this.#id;
    this.#socket.send(JSON.stringify({ id, method, params }));
    return new Promise((resolve, reject) => this.#pending.set(id, { resolve, reject }));
  }
  async evaluate(expression) {
    const result = await this.send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
    if (result.exceptionDetails) {
      throw new Error(result.exceptionDetails.exception?.description ?? result.exceptionDetails.text);
    }
    return result.result.value;
  }
}

/** The condition `scripts/capture_visual_gate.mjs` waits on, so this reads a page the gate would score. */
const MOUNTED = `(() => {
  if (document.querySelector('.credential-gate')) return 'the product showed its credential gate';
  if (document.querySelector('[data-empty-world]')) return 'the product showed its empty world';
  if (document.getElementById('shell')?.getAttribute('data-world-state') === 'error') return 'the product failed to start';
  const canvas = document.getElementById('atlas');
  return canvas instanceof HTMLCanvasElement && canvas.dataset.worldTopology !== undefined &&
    document.querySelector('#shell .reticle') !== null &&
    document.querySelector('.reconstruction-loading') === null;
})()`;

/** What the page is drawing, read from the scene rather than from anything this file states. */
const ATTACH = `(async () => {
  for (let i = 0; i < 240; i += 1) {
    const names = performance.getEntriesByType('resource').map(e => e.name);
    const bindingUrl = names.filter(n => n.includes('/playcanvas/atlas-binding.ts')).pop();
    const pcUrl = names.find(n => n.includes('/node_modules/.vite/deps/playcanvas.js'));
    if (bindingUrl && pcUrl) {
      const m = await import(bindingUrl);
      const pc = await import(pcUrl);
      const app = pc.AppBase.getApplication();
      if (app) {
        const original = m.AtlasBinding.prototype.update;
        if (!original.__measure) {
          const patched = function (...rest) { window.__binding = this; return original.apply(this, rest); };
          patched.__measure = true;
          m.AtlasBinding.prototype.update = patched;
        }
        window.__pc = pc;
        try { app.update(1 / 60); } catch { /* the app may still be starting */ }
        await new Promise(r => setTimeout(r, 500));
        if (window.__binding) {
          const binding = window.__binding;
          const gl = binding.device.gl;
          const info = gl.getExtension('WEBGL_debug_renderer_info');
          const root = binding.app.root.findByName('geographic-environment');
          if (root === null) throw new Error('the page has no geographic-environment root');
          const roots = root.children.map((child) => {
            const batches = [];
            for (const render of child.findComponents('render')) {
              for (const instance of render.meshInstances) {
                batches.push({ entity: render.entity.name, castShadows: render.castShadows,
                  triangles: instance.mesh.primitive[0].count / 3 });
              }
            }
            return { root: child.name, batches: batches.length,
              casting: batches.filter(one => one.castShadows).length,
              triangles: batches.reduce((total, one) => total + one.triangles, 0),
              keys: batches.map(one => one.entity) };
          });
          return {
            renderer: gl.getParameter(info.UNMASKED_RENDERER_WEBGL),
            canvas: [binding.device.width, binding.device.height],
            title: document.title,
            roots,
            lights: binding.app.root.findComponents('light')
              .filter(light => light.enabled && light.entity.enabled)
              .map(light => ({ name: light.entity.name, type: light.type, castShadows: light.castShadows,
                cascades: light.numCascades, shadowDistance: light.shadowDistance })),
          };
        }
      }
    }
    await new Promise(r => setTimeout(r, 500));
  }
  throw new Error('the page never exposed a binding: ' + JSON.stringify({ title: document.title,
    resources: performance.getEntriesByType('resource').length }));
})()`;

/**
 * One arm. The device's own draw entry point is wrapped once and counts by the bound render target;
 * the first two frames after a change are discarded because `Stats.updateBasic` runs at the START of
 * a tick, so `app.stats.drawCalls.total` read at `frameend` is the PREVIOUS tick's count.
 */
const MEASURE = (arm, yaw, ms) => `(async () => {
  const binding = window.__binding;
  const app = binding.app;
  const pc = window.__pc;
  const root = app.root.findByName('geographic-environment');
  const components = [];
  for (const child of root.children) for (const render of child.findComponents('render')) components.push(render);
  window.__saved ??= components.map(render => ({ render, castShadows: render.castShadows, enabled: render.entity.enabled }));
  const restore = () => {
    for (const one of window.__saved) { one.render.castShadows = one.castShadows; one.render.entity.enabled = one.enabled; }
  };
  restore();
  const sun = app.root.findComponents('light').find(light => light.enabled && light.entity.enabled && light.castShadows);
  window.__cascades ??= sun ? sun.numCascades : null;
  if (sun) sun.numCascades = window.__cascades;
  if ('${arm}' === 'noTileShadows') for (const one of window.__saved) one.render.castShadows = false;
  if ('${arm}' === 'worldHidden') for (const one of window.__saved) one.render.entity.enabled = false;
  if ('${arm}' === 'oneCascade' && sun) sun.numCascades = 1;
  if (${yaw} !== null) binding.controls.state.yaw = ${yaw};

  const device = app.graphicsDevice;
  if (!device.draw.__counted) {
    const original = device.draw.bind(device);
    const counted = function (...rest) {
      const target = device.renderTarget;
      const name = target === null || target === undefined ? 'backbuffer' : (target.name ?? 'unnamed');
      window.__drawsPerTarget[name] = (window.__drawsPerTarget[name] ?? 0) + 1;
      window.__draws += 1;
      const primitive = rest[0];
      if (primitive && primitive.type === pc.PRIMITIVE_TRIANGLES) {
        window.__trianglesPerTarget[name] = (window.__trianglesPerTarget[name] ?? 0) + primitive.count / 3;
        window.__triangles += primitive.count / 3;
      }
      return original(...rest);
    };
    counted.__counted = true;
    device.draw = counted;
  }
  const clear = () => { window.__drawsPerTarget = {}; window.__draws = 0; window.__trianglesPerTarget = {}; window.__triangles = 0; };
  clear();
  const totals = [];
  const frames = [];
  let seen = 0;
  const onEnd = () => {
    seen += 1;
    if (seen > 2) {
      totals.push(app.stats.drawCalls.total);
      frames.push({ draws: window.__draws, drawsPerTarget: window.__drawsPerTarget,
        triangles: window.__triangles, trianglesPerTarget: window.__trianglesPerTarget });
    }
    clear();
  };
  app.on('frameend', onEnd);
  const started = performance.now();
  await new Promise(resolve => {
    const wait = () => (performance.now() - started >= ${ms} ? resolve() : requestAnimationFrame(wait));
    requestAnimationFrame(wait);
  });
  app.off('frameend', onEnd);
  restore();
  if (sun) sun.numCascades = window.__cascades;

  const sorted = [...totals].sort((x, y) => x - y);
  const busiest = frames.reduce((best, one) => (best === null || one.draws > best.draws ? one : best), null);
  const at = binding.camera.getPosition();
  return { arm: '${arm}', frames: sorted.length, yaw: ${yaw},
    // The gate's own field, and this file's own count of the same frame. They must agree.
    statsMax: sorted[sorted.length - 1] ?? null,
    countedMax: frames.reduce((most, one) => Math.max(most, one.draws), 0),
    busiestFrame: busiest,
    camera: [at.x, at.y, at.z], cameraYaw: binding.controls.state.yaw };
})()`;

async function main() {
  const profile = mkdtempSync(join(tmpdir(), 'measure-draw-calls-'));
  const chrome = spawn(CHROME, [
    '--headless=new', `--remote-debugging-port=${port}`,
    `--window-size=${VIEWPORT.width},${VIEWPORT.height}`, '--force-device-scale-factor=1',
    '--hide-scrollbars', '--no-first-run', '--no-default-browser-check',
    '--disable-background-timer-throttling', '--disable-renderer-backgrounding',
    '--disable-backgrounding-occluded-windows', '--disable-features=Translate,MediaRouter',
    `--user-data-dir=${profile}`, 'about:blank',
  ], { stdio: ['ignore', 'ignore', 'ignore'] });
  try {
    let page;
    for (let attempt = 0; attempt < 120 && page === undefined; attempt += 1) {
      try {
        const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
        page = targets.find((target) => target.type === 'page');
      } catch { /* not listening yet */ }
      if (page === undefined) await sleep(250);
    }
    if (page === undefined) throw new Error('Chrome exposed no page');
    const version = await (await fetch(`http://127.0.0.1:${port}/json/version`)).json();
    const socket = new WebSocket(page.webSocketDebuggerUrl);
    await new Promise((resolve, reject) => {
      socket.addEventListener('open', resolve, { once: true });
      socket.addEventListener('error', reject, { once: true });
    });
    const session = new Session(socket);
    await session.send('Emulation.setDeviceMetricsOverride', { ...VIEWPORT, deviceScaleFactor: 1, mobile: false });
    await session.send('Page.enable');
    await session.send('Page.addScriptToEvaluateOnNewDocument', {
      source: 'performance.setResourceTimingBufferSize(100000);',
    });
    await session.send('Page.navigate', { url });
    const startedAt = Date.now();
    let mounted = false;
    while (Date.now() - startedAt < 300_000) {
      const answer = await session.evaluate(MOUNTED);
      if (answer === true) { mounted = true; break; }
      if (typeof answer === 'string') throw new Error(answer);
      await sleep(1000);
    }
    if (!mounted) throw new Error('the product shell never mounted a world');
    const mountMs = Date.now() - startedAt;
    process.stderr.write(`the shell mounted a world after ${mountMs} ms\n`);
    await sleep(settleMs);
    const attached = await session.evaluate(ATTACH);
    process.stderr.write(`${attached.roots.length} roots, ${attached.lights.length} lights\n`);
    const runs = [];
    const stated = await session.evaluate('window.__binding.controls.state.yaw');
    for (const [pose, yaw] of [['stated heading', null], ['reversed', stated + Math.PI]]) {
      for (const arm of ARMS) {
        const run = await session.evaluate(MEASURE(arm, yaw, seconds * 1000));
        if (run.statsMax !== run.countedMax) {
          throw new Error(`${pose} ${arm}: the product's field says ${run.statsMax} and this count says `
            + `${run.countedMax}; they are the same frames and must agree`);
        }
        runs.push({ pose, ...run });
        process.stderr.write(`${pose} ${arm}: ${run.statsMax} draws, `
          + `${run.busiestFrame === null ? 'no' : Math.round(run.busiestFrame.triangles)} triangles, `
          + `over ${run.frames} frames\n`);
      }
    }
    socket.close();
    process.stdout.write(`${JSON.stringify({
      measuredAt: new Date().toISOString(), url, viewport: VIEWPORT, seconds, mountMs, settleMs,
      browser: version.Browser, renderer: attached.renderer, canvas: attached.canvas, title: attached.title,
      lights: attached.lights, roots: attached.roots, runs,
    }, null, 2)}\n`);
  } finally {
    chrome.kill('SIGKILL');
    await sleep(500);
    rmSync(profile, { recursive: true, force: true });
  }
}

await main();
// The DevTools socket and the child's pipes must not hold the process open once the record is out.
process.exit(0);
