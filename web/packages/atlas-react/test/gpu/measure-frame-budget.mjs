/**
 * Measure the data view's point budget against the frame, at 1440 by 900 in headless Chrome.
 *
 *   node web/packages/atlas-react/test/gpu/measure-frame-budget.mjs \
 *     --url http://127.0.0.1:5261/?preview=1 --budgets 65536,262144,1048576 --seconds 8
 *
 * The page is the app's own no-token preview (the owned district), served by a Vite server rooted
 * in the checkout being measured. For each budget the script rebuilds the page's representation
 * registry with that budget, moves the slider to the points end, prepares every subject's points,
 * and records two things over the same camera:
 *
 *   frame interval  the gap between consecutive requestAnimationFrame callbacks while every frame
 *                   is drawn: the Melbourne envelope's metric (p95 at or under 16.7 ms).
 *   frame cost      update plus render plus a one-pixel read, which blocks on the GPU: how much of
 *                   the interval the frame actually uses, and so how much room is left.
 *
 * Two views: the arrival at street level, and a frozen elevated view of the whole district. The
 * elevated view holds the camera by replacing the binding's per-frame update with a no-op for the
 * duration, which is recorded. Nothing is written to the product; the script prints one JSON
 * record. It needs no package beyond Node's own WebSocket.
 *
 * `--views overview` measures one view only. `--hide-district` hides, for the measurement only, every
 * draw under the owned district that is not a data view point draw (its surfaces and its extent and
 * datum lines), to tell the district's own drawing cost from the data view's. Each run records what
 * it hid and whether each draw was already visible, and puts every one back afterwards.
 * `--hide-points` hides the data view's own point draws instead, with every point still prepared.
 * `--style '<json>'` merges look values into the style the measured runtime is built with (for
 * example `{"points":{"minPixels":1,"maxPixels":1}}`), validated like any style; the product's
 * style is not touched.
 * `--half-res` draws the data view's points into an offscreen target at half the canvas size, from
 * a second camera that follows the first, and composites it additively over the frame: a prototype
 * of that lever for this measurement only, restored afterwards. The target has no scene depth, so
 * nothing hides a point in it; at the points end the dissolved surfaces hide nothing either, but the
 * district's lines no longer occlude points. Its look is approximate and is recorded as such.
 * `--picture <path>` saves the canvas after the run, with the camera and every switch still applied.
 */
import { spawn } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const VIEWPORT = { width: 1440, height: 900 };

function argument(name, fallback) {
  const index = process.argv.indexOf(`--${name}`);
  return index >= 0 && process.argv[index + 1] !== undefined ? process.argv[index + 1] : fallback;
}
const url = argument('url', 'http://127.0.0.1:5261/?preview=1');
const budgets = argument('budgets', '65536,262144,524288,1048576,2097152,4194304').split(',').map(Number);
const seconds = Number(argument('seconds', '8'));
const views = argument('views', 'street,overview').split(',');
const hideDistrict = process.argv.includes('--hide-district');
const hidePoints = process.argv.includes('--hide-points');
const styleOverride = JSON.parse(argument('style', '{}'));
const halfRes = process.argv.includes('--half-res');
const picture = argument('picture', null);
const port = Number(argument('port', String(9400 + Math.floor(Math.random() * 400))));

class Session {
  #socket; #id = 0; #pending = new Map();
  constructor(socket) {
    this.#socket = socket;
    socket.addEventListener('message', (event) => {
      const message = JSON.parse(event.data);
      const waiter = this.#pending.get(message.id);
      if (waiter === undefined) return;
      this.#pending.delete(message.id);
      if (message.error) waiter.reject(new Error(`${message.error.message}`));
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

const ATTACH = `(async () => {
  for (let i = 0; i < 120; i += 1) {
    const names = performance.getEntriesByType('resource').map(e => e.name);
    const bindingUrl = names.filter(n => n.includes('/playcanvas/atlas-binding.ts')).pop();
    const pcUrl = names.find(n => n.includes('/node_modules/.vite/deps/playcanvas.js'));
    if (bindingUrl && pcUrl) {
      const m = await import(bindingUrl);
      const pc = await import(pcUrl);
      const app = pc.AppBase.getApplication();
      if (app) {
        const orig = m.AtlasBinding.prototype.update;
        if (!orig.__measure) {
          const f = function (...a) { window.__measureBinding = this; return orig.apply(this, a); };
          f.__measure = true;
          m.AtlasBinding.prototype.update = f;
        }
        window.__measurePc = pc;
        // One update from here as well: a page whose frame loop has not ticked yet still exposes it.
        try { app.update(1 / 60); } catch { /* the app may still be starting */ }
        await new Promise(r => setTimeout(r, 500));
        if (window.__measureBinding) {
          const b = window.__measureBinding;
          const gl = b.device.gl;
          const info = gl.getExtension('WEBGL_debug_renderer_info');
          return { renderer: gl.getParameter(info.UNMASKED_RENDERER_WEBGL), canvas: [b.device.width, b.device.height],
            subjects: b.representationReport.subjects.length };
        }
      }
    }
    await new Promise(r => setTimeout(r, 500));
  }
  const app = window.__measurePc?.AppBase.getApplication();
  throw new Error('the page never exposed a binding: ' + JSON.stringify({ visibility: document.visibilityState,
    frame: app?.frame ?? null, title: document.title, resources: performance.getEntriesByType('resource').length }));
})()`;

const MEASURE = (budget, view) => `(async () => {
  const b = window.__measureBinding;
  const pc = window.__measurePc;
  const names = performance.getEntriesByType('resource').map(e => e.name);
  const { RepresentationRuntime } = await import(names.filter(n => n.includes('/playcanvas/representation-runtime.ts')).pop());
  const core = await import(names.filter(n => n.includes('/atlas-core/src/index.ts')).pop());
  const perSubject = Math.min(${budget}, core.REPRESENTATION_POINTS_PER_SUBJECT);
  b.representationController?.destroy();
  b.representationOverlay?.destroy();
  b.representationDefaults.clear(); b.representationOverrides.clear(); b.representationFrames.clear();
  const merge = (base, over) => Object.fromEntries(Object.entries(base).map(([k, v]) =>
    [k, over && Object.hasOwn(over, k) ? (typeof v === 'object' && v !== null && !Array.isArray(v) ? merge(v, over[k]) : over[k]) : v]));
  const style = core.dataViewStyle(merge(JSON.parse(JSON.stringify(core.DATA_VIEW_STYLE)), ${JSON.stringify(styleOverride)}));
  b.representationController = new RepresentationRuntime(${budget}, perSubject, { style });
  b.initializeRepresentation([]);
  const prepareStart = performance.now();
  let report = b.setRepresentationIntent({ ...b.representationReport.intent, pointMix: 1 });
  while (report.pendingSubjects > 0) report = b.representation.update();
  const prepareMs = performance.now() - prepareStart;
  const frozen = ${JSON.stringify(view)} === 'overview';
  const hidden = [];
  if (${hideDistrict}) {
    const district = b.app.root.findByName('owned-district');
    if (!district) throw new Error('No owned-district node to hide');
    district.forEach(e => {
      for (const mi of e.render?.meshInstances ?? []) {
        if (e.name.startsWith('data-view-points:')) continue;
        hidden.push({ name: e.name, primitive: mi.mesh.primitive[0].type, wasVisible: mi.visible, mi });
        mi.visible = false;
      }
    });
  }
  if (${hidePoints}) {
    const district = b.app.root;
    district.forEach(e => {
      if (!e.name.startsWith('data-view-points:')) return;
      for (const mi of e.render?.meshInstances ?? []) {
        hidden.push({ name: e.name, primitive: mi.mesh.primitive[0].type, wasVisible: mi.visible, mi });
        mi.visible = false;
      }
    });
  }
  if (frozen) {
    // The whole district: every aggregate batch's own box, projected into display space.
    const corners = report.subjects.filter(e => e.subject.subjectKind === 'geometry-group')
      .flatMap(e => b.representationBounds(e.subject) ?? []);
    if (corners.length === 0) throw new Error('No district batch states bounds to frame the overview');
    const xs = corners.map(c => c[0]), zs = corners.map(c => c[2]);
    const cx = (Math.min(...xs) + Math.max(...xs)) / 2, cz = (Math.min(...zs) + Math.max(...zs)) / 2;
    b.update = function () {};
    b.camera.setPosition(cx - 520, 330, cz + 520);
    b.camera.lookAt(new pc.Vec3(cx, 20, cz));
  }
  const summary = (values) => {
    const sorted = [...values].sort((x, y) => x - y);
    const at = (f) => sorted.length === 0 ? 0 : sorted[Math.min(sorted.length - 1, Math.round((sorted.length - 1) * f))];
    const r = (v) => Math.round(v * 100) / 100;
    return { frames: sorted.length, p50: r(at(0.5)), p95: r(at(0.95)), p99: r(at(0.99)), max: r(at(1)),
      over16_7: sorted.filter(v => v > 16.7).length,
      // A 60 Hz display presents every 16.67 ms, which the page clock reads as 16.7 or 16.8; a
      // missed presentation reads as 33 ms or more.
      missed: sorted.filter(v => v > 20).length };
  };
  let composite = null;
  if (${halfRes}) {
    const device = b.device;
    const width = Math.max(1, Math.floor(device.width / 2)), height = Math.max(1, Math.floor(device.height / 2));
    const colour = new pc.Texture(device, { name: 'measure-half-points', width, height, format: pc.PIXELFORMAT_RGBA8,
      mipmaps: false, minFilter: pc.FILTER_LINEAR, magFilter: pc.FILTER_LINEAR,
      addressU: pc.ADDRESS_CLAMP_TO_EDGE, addressV: pc.ADDRESS_CLAMP_TO_EDGE });
    const target = new pc.RenderTarget({ colorBuffer: colour, depth: true });
    const pointsLayer = new pc.Layer({ name: 'measure-half-points' });
    const overlayLayer = new pc.Layer({ name: 'measure-half-composite' });
    b.app.scene.layers.pushTransparent(pointsLayer);
    b.app.scene.layers.pushTransparent(overlayLayer);
    const moved = [];
    b.app.root.forEach(e => {
      if (!e.name.startsWith('data-view-points:') || !e.render) return;
      moved.push({ e, layers: [...e.render.layers] });
      e.render.layers = [pointsLayer.id];
    });
    const main = b.camera.camera;
    const half = new pc.Entity('measure-half-camera');
    half.addComponent('camera', { fov: main.fov, nearClip: main.nearClip, farClip: main.farClip,
      clearColor: new pc.Color(0, 0, 0, 0), clearColorBuffer: true, clearDepthBuffer: true,
      layers: [pointsLayer.id], renderTarget: target, priority: main.priority - 1 });
    b.camera.addChild(half);
    const mainLayers = [...main.layers];
    main.layers = [...mainLayers, overlayLayer.id];
    const material = new pc.StandardMaterial();
    material.useLighting = false; material.useFog = false; material.useSkybox = false;
    material.diffuse = new pc.Color(0, 0, 0); material.emissive = new pc.Color(1, 1, 1);
    material.emissiveMap = colour; material.blendType = pc.BLEND_ADDITIVE;
    material.depthTest = false; material.depthWrite = false; material.update();
    const quad = new pc.Entity('measure-half-composite');
    quad.addComponent('render', { type: 'plane', material, layers: [overlayLayer.id], castShadows: false, receiveShadows: false });
    const distance = main.nearClip * 2;
    const tall = 2 * distance * Math.tan(main.fov * Math.PI / 360);
    quad.setLocalPosition(0, 0, -distance);
    quad.setLocalEulerAngles(90, 0, 0);
    quad.setLocalScale(tall * device.width / device.height, 1, tall);
    b.camera.addChild(quad);
    composite = { width, height, moved: moved.length, restore: () => {
      for (const { e, layers } of moved) e.render.layers = layers;
      main.layers = mainLayers;
      quad.destroy(); half.destroy();
      b.app.scene.layers.remove(pointsLayer); b.app.scene.layers.remove(overlayLayer);
      target.destroy(); colour.destroy(); material.destroy();
    } };
  }
  const intervals = [];
  await new Promise(resolve => {
    let last = null; const start = performance.now();
    const tick = (t) => {
      b.invalidate();
      if (last !== null && t - start > 2000) intervals.push(t - last);
      last = t;
      if (t - start < 2000 + ${seconds} * 1000) requestAnimationFrame(tick); else resolve();
    };
    requestAnimationFrame(tick);
  });
  const app = b.app;
  const gl = b.device.gl;
  const pixel = new Uint8Array(4);
  const costs = [];
  for (let i = 0; i < 150; i += 1) {
    const t = performance.now();
    app.update(1 / 60);
    app.renderNextFrame = true;
    app.render();
    gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, pixel);
    if (i >= 30) costs.push(performance.now() - t);
  }
  let pictureUrl = null;
  if (${picture !== null}) {
    app.renderNextFrame = true; app.update(1 / 60); app.render();
    pictureUrl = b.device.canvas.toDataURL('image/png');
  }
  const compositeReport = composite && { width: composite.width, height: composite.height, movedDraws: composite.moved };
  composite?.restore();
  if (frozen) delete b.update;
  // Anything that turned itself back on during the run would make the hiding a false result.
  const reshown = hidden.filter(h => h.mi.visible).map(h => h.name);
  for (const h of hidden) h.mi.visible = h.wasVisible;
  const inView = report.subjects.filter(e => e.resolved.pointWeight > 0).length;
  return {
    budget: ${budget}, perSubject, view: ${JSON.stringify(view)}, heldCamera: frozen,
    allocatedPoints: report.allocatedPoints, allocatedBytes: report.allocatedBytes, prepareMs: Math.round(prepareMs),
    subjectsWithPoints: inView, drawCalls: app.stats.drawCalls.total,
    halfResolution: compositeReport, picture: pictureUrl,
    hiddenDistrictDraws: hidden.map(h => ({ name: h.name, primitive: h.primitive, wasVisible: h.wasVisible })),
    reshownDuringRun: reshown,
    interval: summary(intervals), cost: summary(costs),
    heapMB: performance.memory ? Math.round(performance.memory.usedJSHeapSize / 1048576) : null,
  };
})()`;

async function main() {
  const profile = mkdtempSync(join(tmpdir(), 'data-view-budget-'));
  const chrome = spawn(CHROME, [
    '--headless=new', `--remote-debugging-port=${port}`,
    `--window-size=${VIEWPORT.width},${VIEWPORT.height}`, '--force-device-scale-factor=1',
    '--hide-scrollbars', '--no-first-run', '--no-default-browser-check', '--enable-precise-memory-info',
    '--disable-background-timer-throttling', '--disable-renderer-backgrounding',
    '--disable-backgrounding-occluded-windows', '--disable-features=Translate,MediaRouter',
    `--user-data-dir=${profile}`, 'about:blank',
  ], { stdio: ['ignore', 'ignore', 'ignore'] });
  try {
    let page;
    for (let attempt = 0; attempt < 80 && page === undefined; attempt += 1) {
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
    // The page finds its own module URLs in resource timing, whose default buffer holds 250 entries.
    await session.send('Page.enable');
    await session.send('Page.addScriptToEvaluateOnNewDocument', {
      source: 'performance.setResourceTimingBufferSize(100000);',
    });
    await session.send('Page.navigate', { url });
    await sleep(3000);
    const attached = await session.evaluate(ATTACH);
    const runs = [];
    for (const view of views) {
      for (const budget of budgets) {
        const run = await session.evaluate(MEASURE(budget, view));
        if (run.picture) {
          const { writeFileSync } = await import('node:fs');
          writeFileSync(budgets.length > 1 ? picture.replace(/\.png$/, `-${view}-${budget}.png`) : picture,
            Buffer.from(run.picture.slice(run.picture.indexOf(',') + 1), 'base64'));
          run.picture = 'written';
        }
        runs.push(run);
        process.stderr.write(`${new Date().toISOString()} ${view} ${budget}: interval p95 ${run.interval.p95} ms, `
          + `max ${run.interval.max} ms, ${run.interval.missed} missed of ${run.interval.frames}, `
          + `${run.allocatedPoints} points, prepared in ${run.prepareMs} ms\n`);
      }
    }
    socket.close();
    process.stdout.write(`${JSON.stringify({
      measuredAt: new Date().toISOString(), url, viewport: VIEWPORT, seconds, browser: version.Browser,
      renderer: attached.renderer, canvas: attached.canvas, subjects: attached.subjects, hideDistrict, hidePoints,
      styleOverride, halfRes, runs,
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
