/**
 * The visual gate harness: walk the product, measure what it drew, capture what a person saw.
 *
 *   cd web && npx tsx ../scripts/capture_visual_gate.mjs --out <scratch dir> --label run-1
 *
 * It opens the running application at 1440 by 900 in headless Chrome over the DevTools protocol,
 * with no package beyond Node's own WebSocket, and never substitutes a page or a handler:
 *
 *   1. waits for the product's own shell to mount a world, and halts on a credential gate, an
 *      empty world or an error surface rather than scoring something else;
 *   2. summons the Companion with a trusted X key, which is also the product's own way of keeping
 *      walking available while pointer lock is not held (automation never receives the lock);
 *   3. turns the player to the route heading by writing the controls' yaw, the one value mouse
 *      look would have written, and never writes a position;
 *   4. walks the route with trusted W key events through the product's own movement, collision
 *      and support resolution, recording every frame of the live player state, and captures the
 *      shell at the start, midpoint and endpoint;
 *   5. reads the drawn triangles, the listeners on the window, the document and the canvas, the
 *      product's own validation report and the network, and measures the eight mechanical keys
 *      with @exulanica/loom-gate. The judged key is left for the named human judge.
 *
 * It reads no credential and writes none. The API's refusal of an anonymous read is probed
 * without one, and request headers are never recorded.
 *
 * Environment it needs: the app dev server (default http://127.0.0.1:5188/) proxying /api to a
 * running API. Exit 0 with a run record, 3 with halt.json when a precondition of the gate fails.
 */

import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, isAbsolute, join, relative, resolve } from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';
import { fileURLToPath } from 'node:url';
import {
  CAPTURE_LABELS,
  GATE_KEY_SET_VERSION,
  MELBOURNE_ENVELOPE,
  THRESHOLDS,
  keySet,
  measureScene,
  mechanicalMeasurements,
  planRoute,
} from '../web/packages/loom-gate/src/index.ts';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const VIEWPORT = Object.freeze({ width: 1440, height: 900 });
const PRODUCT_TITLE = 'Exulanica';

class Halt extends Error {}

function argument(name, fallback) {
  const index = process.argv.indexOf(`--${name}`);
  if (index >= 0 && process.argv[index + 1] !== undefined) return process.argv[index + 1];
  if (fallback === undefined) throw new Halt(`--${name} is required`);
  return fallback;
}

const options = {
  app: argument('app', 'http://127.0.0.1:5188/'),
  artifact: argument('artifact', 'assets/owned-world/flatiron/flatiron-owned-district.json'),
  renderer: argument('renderer', 'web/packages/atlas-react/src/playcanvas/owned-district-runtime.ts'),
  out: argument('out'),
  label: argument('label', 'run'),
  port: Number(argument('cdp-port', '9351')),
  validationSeconds: Number(argument('validation-seconds', '40')),
};
const appUrl = new URL(options.app);
const appOrigin = appUrl.origin;

const sha256 = (bytes) => createHash('sha256').update(bytes).digest('hex');
const repoPath = (path) => (isAbsolute(path) ? path : join(ROOT, path));

/** A URL as a record may carry it: repository-relative, never an absolute local path. */
function normalizeUrl(raw) {
  if (raw === undefined || raw === null || raw === '') return '<no-url>';
  let url;
  try {
    url = new URL(raw);
  } catch {
    return '<unparsed-url>';
  }
  if (url.origin !== appOrigin) return `${url.protocol}//${url.host}${url.pathname}`;
  const path = decodeURIComponent(url.pathname);
  if (path.startsWith('/@fs/')) {
    const local = relative(ROOT, path.slice('/@fs'.length));
    return local.startsWith('..') ? '<outside-repository>' : local;
  }
  if (path.startsWith('/src/') || path.startsWith('/node_modules/') || path === '/') {
    return `web/packages/app${path}`;
  }
  return path;
}

/** Free text as a record may carry it: local paths made relative or withheld. */
function sanitize(text) {
  return String(text)
    .replaceAll(`${appOrigin}/@fs${ROOT}/`, '')
    .replaceAll(`${ROOT}/`, '')
    .replace(/\/Users\/[^\s'")]*/g, '<local-path>');
}

function listenerSource(normalized) {
  if (normalized.startsWith('web/packages/') || normalized.startsWith('web/node_modules/')) {
    return 'product';
  }
  if (normalized.startsWith('/@vite/') || normalized.startsWith('/@id/') || normalized === '/@react-refresh') {
    return 'dev-server';
  }
  return 'foreign';
}

// ---- Chrome and the protocol -------------------------------------------------------------

class Session {
  constructor(socket) {
    this.socket = socket;
    this.nextId = 0;
    this.pending = new Map();
    this.events = [];
    this.listeners = new Map();
    socket.addEventListener('message', (event) => {
      const message = JSON.parse(event.data);
      if (message.id !== undefined) {
        const slot = this.pending.get(message.id);
        this.pending.delete(message.id);
        if (message.error) slot.reject(new Error(`${slot.method}: ${JSON.stringify(message.error)}`));
        else slot.resolve(message.result);
        return;
      }
      this.events.push(message);
      for (const handler of this.listeners.get(message.method) ?? []) handler(message.params);
    });
  }

  on(method, handler) {
    const held = this.listeners.get(method) ?? [];
    held.push(handler);
    this.listeners.set(method, held);
  }

  send(method, params = {}) {
    const id = (this.nextId += 1);
    return new Promise((resolvePromise, reject) => {
      this.pending.set(id, { resolve: resolvePromise, reject, method });
      this.socket.send(JSON.stringify({ id, method, params }));
    });
  }

  async evaluate(expression) {
    const result = await this.send('Runtime.evaluate', {
      expression,
      returnByValue: true,
      awaitPromise: true,
    });
    if (result.exceptionDetails) {
      throw new Error(`page threw: ${result.exceptionDetails.exception?.description ?? result.exceptionDetails.text}`);
    }
    return result.result.value;
  }

  async reference(expression) {
    const result = await this.send('Runtime.evaluate', { expression, returnByValue: false, awaitPromise: true });
    if (result.exceptionDetails) {
      throw new Error(`page threw: ${result.exceptionDetails.exception?.description ?? result.exceptionDetails.text}`);
    }
    return result.result.objectId;
  }

  async call(objectId, declaration, args = [], byValue = true) {
    const result = await this.send('Runtime.callFunctionOn', {
      objectId,
      functionDeclaration: declaration,
      arguments: args.map((value) => ({ value })),
      returnByValue: byValue,
      awaitPromise: true,
    });
    if (result.exceptionDetails) {
      throw new Error(`page threw: ${result.exceptionDetails.exception?.description ?? result.exceptionDetails.text}`);
    }
    return byValue ? result.result.value : result.result.objectId;
  }
}

async function launchChrome(profile) {
  const chrome = spawn(CHROME, [
    '--headless=new',
    `--remote-debugging-port=${options.port}`,
    `--window-size=${VIEWPORT.width},${VIEWPORT.height}`,
    '--force-device-scale-factor=1',
    '--hide-scrollbars',
    '--no-first-run',
    '--no-default-browser-check',
    '--enable-precise-memory-info',
    '--disable-background-timer-throttling',
    '--disable-renderer-backgrounding',
    '--disable-backgrounding-occluded-windows',
    '--disable-features=Translate,MediaRouter',
    `--user-data-dir=${profile}`,
    'about:blank',
  ], { stdio: ['ignore', 'pipe', 'pipe'] });
  let log = '';
  chrome.stdout.on('data', (chunk) => { log += chunk.toString(); });
  chrome.stderr.on('data', (chunk) => { log += chunk.toString(); });
  for (let attempt = 0; attempt < 80; attempt += 1) {
    try {
      const version = await (await fetch(`http://127.0.0.1:${options.port}/json/version`)).json();
      const targets = await (await fetch(`http://127.0.0.1:${options.port}/json/list`)).json();
      const page = targets.find((target) => target.type === 'page');
      if (page !== undefined) return { chrome, version, page, log: () => log };
    } catch {
      // not listening yet
    }
    await sleep(250);
  }
  chrome.kill();
  throw new Halt(`Chrome exposed no page target on ${options.port}`);
}

async function connect(url) {
  const socket = new WebSocket(url);
  await new Promise((resolvePromise, reject) => {
    socket.addEventListener('open', resolvePromise, { once: true });
    socket.addEventListener('error', reject, { once: true });
  });
  return new Session(socket);
}

async function waitFor(session, expression, label, timeoutMs) {
  const started = Date.now();
  for (;;) {
    const value = await session.evaluate(expression);
    if (value === true) return Date.now() - started;
    if (typeof value === 'string') throw new Halt(`${label}: ${value}`);
    if (Date.now() - started > timeoutMs) throw new Halt(`timed out after ${timeoutMs} ms waiting for ${label}`);
    await sleep(250);
  }
}

function toBase64(array) {
  return Buffer.from(array.buffer, array.byteOffset, array.byteLength).toString('base64');
}

function float64FromBase64(text) {
  const bytes = Buffer.from(text, 'base64');
  const copy = new Uint8Array(bytes.byteLength);
  copy.set(bytes);
  return new Float64Array(copy.buffer);
}

// ---- page-side functions, called on product objects the protocol hands back -------------------

const PAGE_BASE64 = `
  const encode = (typed) => {
    const bytes = new Uint8Array(typed.buffer, typed.byteOffset, typed.byteLength);
    let text = '';
    for (let i = 0; i < bytes.length; i += 0x8000) text += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
    return btoa(text);
  };
  const decode = (text) => {
    const binary = atob(text);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
    return new Float64Array(bytes.buffer);
  };
`;

const READ_POSE = `function () {
  const s = this.controls.state;
  return { x: s.x, y: s.y, z: s.z, yaw: s.yaw, pitch: s.pitch,
    speed: this.controls.movementSpeed, mode: this.controls.mode,
    conversationActive: this.controls.conversationActive === true,
    enabled: this.controls.enabled === true };
}`;

const CAPTURE_STATE = `function (origin, title) {
  const shell = document.getElementById('shell');
  const canvas = document.getElementById('atlas');
  const box = (node) => {
    if (!node) return null;
    const r = node.getBoundingClientRect();
    const s = getComputedStyle(node);
    return { x: r.x, y: r.y, width: r.width, height: r.height, display: s.display,
      visibility: s.visibility, opacity: Number(s.opacity) };
  };
  const drawn = (b) => b !== null && b.display !== 'none' && b.visibility !== 'hidden' &&
    b.opacity > 0 && b.width > 0 && b.height > 0;
  const inViewport = (b) => b !== null && b.x < innerWidth && b.y < innerHeight &&
    b.x + b.width > 0 && b.y + b.height > 0;
  const reticle = document.querySelector('#shell .reticle');
  const reticleBox = box(reticle);
  const reticleCentred = reticle !== null && reticle.isConnected && drawn(reticleBox) &&
    Math.abs(reticleBox.x + reticleBox.width / 2 - innerWidth / 2) <= 1 &&
    Math.abs(reticleBox.y + reticleBox.height / 2 - innerHeight / 2) <= 1;
  const stage = document.querySelector('.companion-stage');
  const stageBox = box(stage);
  const encounter = document.querySelector('.companion-encounter');
  const encounterBox = box(encounter);
  const companionShown = stage !== null && stage.isConnected && stage.dataset.ready === 'true' &&
    stage.dataset.shown === 'true' && drawn(stageBox) && inViewport(stageBox) &&
    stage.querySelector('svg') !== null &&
    encounter !== null && encounter.isConnected && encounter.dataset.state === 'open' &&
    encounterBox !== null && encounterBox.width > 0 && encounterBox.height > 0;
  const worldMounted = shell !== null && !shell.hasAttribute('data-world-state') &&
    canvas instanceof HTMLCanvasElement && !canvas.hidden &&
    canvas.dataset.worldTopology !== undefined;
  const inProductShell = location.origin === origin && location.pathname === '/' &&
    document.title === title && worldMounted &&
    document.querySelector('.credential-gate') === null &&
    document.querySelector('[data-empty-world]') === null;
  const active = document.activeElement;
  return {
    locationPath: location.pathname,
    title: document.title,
    shellAttributes: shell === null ? null :
      Object.fromEntries([...shell.attributes].map((a) => [a.name, a.value])),
    atlasDataset: canvas === null ? null : { ...canvas.dataset },
    reticle: { present: reticle !== null, box: reticleBox, centred: reticleCentred },
    companion: {
      stage: stage === null ? null : { ...stage.dataset, box: stageBox },
      encounter: encounter === null ? null : { state: encounter.dataset.state, box: encounterBox },
      shown: companionShown,
    },
    inProductShell,
    worldMounted,
    credentialGate: document.querySelector('.credential-gate') !== null,
    emptyWorld: document.querySelector('[data-empty-world]') !== null,
    activeElement: active === null ? null : active.tagName.toLowerCase(),
    typingTarget: active instanceof HTMLInputElement || active instanceof HTMLTextAreaElement ||
      active instanceof HTMLSelectElement || (active instanceof HTMLElement && active.isContentEditable),
    heapBytes: performance.memory?.usedJSHeapSize ?? null,
    pointerLocked: document.pointerLockElement !== null,
  };
}`;

const INSTALL_RECORDER = `function () {
  const binding = this;
  const recorder = { poses: [], recording: false, failures: [], handle: null, observer: null };
  recorder.handle = binding.app.on('update', () => {
    if (!recorder.recording) return;
    const s = binding.controls.state;
    recorder.poses.push([s.x, s.y, s.z, s.yaw, s.pitch, binding.controls.movementSpeed]);
  });
  const status = document.querySelector('.travel-status');
  if (status !== null) {
    recorder.observer = new MutationObserver(() => {
      if (recorder.recording && !status.hidden && status.dataset.kind === 'failure') {
        recorder.failures.push(status.textContent ?? '');
      }
    });
    recorder.observer.observe(status, { attributes: true, childList: true, characterData: true, subtree: true });
  }
  return recorder;
}`;

const EXTRACT_SCENE = `async function (pcUrl) {
  ${PAGE_BASE64}
  const pc = await import(pcUrl);
  const app = this.app;
  const origin = this.renderOriginState.origin;
  const cameras = app.root.findComponents('camera').filter((c) => c.enabled && c.entity.enabled);
  const layers = new Set(cameras.flatMap((c) => c.layers));
  const culls = { [pc.CULLFACE_NONE]: 'none', [pc.CULLFACE_BACK]: 'back', [pc.CULLFACE_FRONT]: 'front', [pc.CULLFACE_FRONTANDBACK]: 'both' };
  const pathOf = (entity) => {
    const names = [];
    for (let node = entity; node !== null && node !== app.root; node = node.parent) names.unshift(node.name);
    return names.join('/');
  };
  const meshes = [];
  const environmentTextures = new Map();
  const skipped = { disabledOrHidden: 0, notInCameraLayers: 0, notTriangles: 0 };
  for (const render of app.root.findComponents('render')) {
    if (!render.enabled || !render.entity.enabled) { skipped.disabledOrHidden += render.meshInstances.length; continue; }
    if (!render.layers.some((id) => layers.has(id))) { skipped.notInCameraLayers += render.meshInstances.length; continue; }
    render.meshInstances.forEach((instance, ordinal) => {
      if (!instance.visible) { skipped.disabledOrHidden += 1; return; }
      const mesh = instance.mesh;
      const primitive = mesh.primitive[0];
      if (primitive.type !== pc.PRIMITIVE_TRIANGLES) { skipped.notTriangles += 1; return; }
      const local = new Float32Array(mesh.vertexBuffer.numVertices * 3);
      mesh.getPositions(local);
      let order;
      if (mesh.indexBuffer && mesh.indexBuffer[0]) {
        const all = new Uint32Array(mesh.indexBuffer[0].numIndices);
        mesh.getIndices(all);
        order = all.subarray(primitive.base, primitive.base + primitive.count);
      } else {
        order = new Uint32Array(primitive.count);
        for (let k = 0; k < primitive.count; k += 1) order[k] = primitive.base + k;
      }
      const m = instance.node.getWorldTransform().data;
      const world = new Float64Array(order.length * 3);
      for (let k = 0; k < order.length; k += 1) {
        const v = order[k] * 3;
        const x = local[v];
        const y = local[v + 1];
        const z = local[v + 2];
        world[k * 3] = m[0] * x + m[4] * y + m[8] * z + m[12] + origin.x;
        world[k * 3 + 1] = m[1] * x + m[5] * y + m[9] * z + m[13] + origin.y;
        world[k * 3 + 2] = m[2] * x + m[6] * y + m[10] * z + m[14] + origin.z;
      }
      const material = instance.material;
      const textures = new Set();
      for (const name of Object.getOwnPropertyNames(material)) {
        const value = material[name];
        if (value instanceof pc.Texture) textures.add(value);
      }
      for (const parameter of Object.values(material.parameters ?? {})) {
        if (parameter && parameter.data instanceof pc.Texture) textures.add(parameter.data);
      }
      let decoded = 0;
      for (const texture of textures) {
        decoded += texture.gpuSize;
        environmentTextures.set(texture, texture.gpuSize);
      }
      meshes.push({
        id: pathOf(render.entity) + '#' + ordinal,
        cull: culls[material.cull] ?? 'back',
        hasUv: mesh.vertexBuffer.format.elements.some((element) => element.name.startsWith('TEXCOORD')),
        decodedTextureBytes: decoded,
        textureCount: textures.size,
        triangles: encode(world),
      });
    });
  }
  let environmentTextureBytes = 0;
  for (const bytes of environmentTextures.values()) environmentTextureBytes += bytes;
  return {
    meshes,
    skipped,
    origin: { x: origin.x, y: origin.y, z: origin.z },
    environmentTextureBytes,
    environmentTextures: environmentTextures.size,
    deviceTextureBytes: app.graphicsDevice._vram.tex,
    deviceVram: { ...app.graphicsDevice._vram },
  };
}`;

const SAMPLE_SUPPORT = `function (pointsText) {
  ${PAGE_BASE64}
  const points = decode(pointsText);
  const heights = new Float64Array(points.length / 2);
  for (let i = 0; i < heights.length; i += 1) {
    const sample = this.navigationWorld.surface.sample(points[i * 2], points[i * 2 + 1]);
    heights[i] = sample === null ? Number.NaN : sample.height;
  }
  return encode(heights);
}`;

const READ_OBSTACLES = `function () {
  return (this.navigationWorld.polygonObstacles ?? []).map((obstacle) => ({
    id: obstacle.id,
    rings: obstacle.rings.map((ring) => ring.map((point) => [point.x, point.z])),
  }));
}`;

// ---- the run ---------------------------------------------------------------------------------

async function main() {
  const out = resolve(options.out);
  mkdirSync(out, { recursive: true });
  const profile = join(out, `.chrome-profile-${options.label}`);
  rmSync(profile, { recursive: true, force: true });

  const artifactBytes = readFileSync(repoPath(options.artifact));
  const rendererBytes = readFileSync(repoPath(options.renderer));
  const artifact = JSON.parse(artifactBytes.toString('utf8'));
  if (artifact.profile !== 'exulanica.owned-district/v1') {
    throw new Halt(`no adapter reads ${artifact.profile}; the corridor needs its own prism reader`);
  }
  const heights = new Map(artifact.buildings.map((building) => [building.id, building.height_cm / 100]));
  const [west, north, east, south] = artifact.bounds_cm.map((value) => value / 100);

  // The API behind the product's own proxy must refuse a read that carries no credential.
  const anonymous = await fetch(new URL('/api/graph', appUrl));
  const anonymousStatus = anonymous.status;
  await anonymous.arrayBuffer();

  const { chrome, version, page, log } = await launchChrome(profile);
  const session = await connect(page.webSocketDebuggerUrl);
  const network = new Map();
  const exceptions = [];
  const consoleErrors = [];
  const networkLogErrors = [];
  const navigations = [];
  session.on('Network.requestWillBeSent', (event) => {
    network.set(event.requestId, {
      url: event.request.url,
      method: event.request.method,
      type: event.type,
      status: null,
      encodedBytes: 0,
      decodedBytes: 0,
      finished: false,
      failed: null,
    });
  });
  session.on('Network.responseReceived', (event) => {
    const entry = network.get(event.requestId);
    if (entry !== undefined) {
      entry.status = event.response.status;
      entry.mimeType = event.response.mimeType;
    }
  });
  session.on('Network.dataReceived', (event) => {
    const entry = network.get(event.requestId);
    if (entry !== undefined) entry.decodedBytes += event.dataLength;
  });
  session.on('Network.loadingFinished', (event) => {
    const entry = network.get(event.requestId);
    if (entry !== undefined) {
      entry.finished = true;
      entry.encodedBytes = event.encodedDataLength;
    }
  });
  session.on('Network.loadingFailed', (event) => {
    const entry = network.get(event.requestId);
    if (entry !== undefined) entry.failed = event.errorText;
  });
  session.on('Runtime.exceptionThrown', (event) => {
    const detail = event.exceptionDetails;
    exceptions.push(sanitize(String(detail.exception?.description ?? detail.text).split('\n')[0]).slice(0, 300));
  });
  session.on('Runtime.consoleAPICalled', (event) => {
    if (event.type !== 'error') return;
    consoleErrors.push(sanitize(event.args.map((arg) => String(arg.value ?? arg.description ?? '')).join(' ')).slice(0, 300));
  });
  session.on('Log.entryAdded', (event) => {
    if (event.entry.level !== 'error') return;
    const text = sanitize(`${event.entry.source}: ${event.entry.text}`).slice(0, 300);
    if (event.entry.source === 'network') networkLogErrors.push(text);
    else consoleErrors.push(text);
  });
  session.on('Page.frameNavigated', (event) => {
    if (event.frame.parentId === undefined) navigations.push(event.frame.url);
  });

  const halt = async (reason) => {
    const state = await session.call(await session.reference('document'), CAPTURE_STATE, [appOrigin, PRODUCT_TITLE]).catch(() => null);
    const { data } = await session.send('Page.captureScreenshot', { format: 'png' }).catch(() => ({ data: null }));
    if (data !== null) writeFileSync(join(out, `${options.label}-halt.png`), Buffer.from(data, 'base64'));
    throw new Halt(`${reason}\nstate: ${JSON.stringify(state)}`);
  };

  try {
    await session.send('Page.enable');
    await session.send('Runtime.enable');
    await session.send('Log.enable');
    await session.send('Network.enable', { maxTotalBufferSize: 256_000_000, maxResourceBufferSize: 64_000_000 });
    await session.send('Emulation.setDeviceMetricsOverride', {
      width: VIEWPORT.width, height: VIEWPORT.height, deviceScaleFactor: 1, mobile: false,
    });
    await session.send('Emulation.setFocusEmulationEnabled', { enabled: true });

    const target = new URL(appUrl);
    target.searchParams.set('validation', '1');
    target.searchParams.set('validation-seconds', String(options.validationSeconds));
    target.searchParams.set('validation-warmup', '2');
    const navigatedAt = Date.now();
    await session.send('Page.navigate', { url: target.href });
    const mountMs = await waitFor(session, `(() => {
      if (document.querySelector('.credential-gate')) return 'the product showed its credential gate';
      if (document.querySelector('[data-empty-world]')) return 'the product showed its empty world';
      if (document.getElementById('shell')?.getAttribute('data-world-state') === 'error') return 'the product failed to start';
      const canvas = document.getElementById('atlas');
      return canvas instanceof HTMLCanvasElement && canvas.dataset.worldTopology !== undefined &&
        document.querySelector('#shell .reticle') !== null &&
        document.querySelector('.reconstruction-loading') === null;
    })()`, 'the product shell to mount a world', 240_000);
    // The direct-navigation transition and the first frames settle before anything is read.
    await sleep(3000);

    const pcUrl = await session.evaluate(
      `performance.getEntriesByType('resource').map((e) => e.name).find((n) => n.includes('/.vite/deps/playcanvas.js')) ?? null`,
    );
    if (pcUrl === null) await halt('the page never loaded the rendering engine module');

    // The binding is reached through the engine's own update listener, read by the debugger.
    const appId = await session.reference(`(async () => (await import(${JSON.stringify(pcUrl)})).AppBase.getApplication())()`);
    const handlersId = await session.call(appId, `function () { return (this._callbacks.get('update') ?? []).map((h) => h.callback); }`, [], false);
    const handlers = await session.send('Runtime.getProperties', { objectId: handlersId, ownProperties: true });
    let bindingId = null;
    for (const property of handlers.result) {
      if (bindingId !== null || property.value?.type !== 'function') continue;
      const internal = await session.send('Runtime.getProperties', { objectId: property.value.objectId, ownProperties: false });
      const scopes = internal.internalProperties?.find((entry) => entry.name === '[[Scopes]]');
      if (scopes === undefined) continue;
      const list = await session.send('Runtime.getProperties', { objectId: scopes.value.objectId, ownProperties: true });
      for (const scope of list.result) {
        if (scope.value?.objectId === undefined) continue;
        const variables = await session.send('Runtime.getProperties', { objectId: scope.value.objectId, ownProperties: true });
        const found = variables.result.find((variable) => variable.name === 'binding');
        if (found?.value?.objectId !== undefined) {
          bindingId = found.value.objectId;
          break;
        }
      }
    }
    if (bindingId === null) await halt('the Atlas binding was not reachable from the engine update listener');
    const documentId = await session.reference('document');
    const captureState = () => session.call(documentId, CAPTURE_STATE, [appOrigin, PRODUCT_TITLE]);
    const pose = () => session.call(bindingId, READ_POSE);

    const arrival = await pose();
    const before = await captureState();
    if (!before.inProductShell) await halt('the page is not the product shell with a mounted world');

    // The route, chosen by rule from the product's own arrival pose and collision proxy.
    const obstacles = await session.call(bindingId, READ_OBSTACLES);
    const prisms = [];
    for (const obstacle of obstacles) {
      const top = heights.get(obstacle.id);
      if (top === undefined) await halt(`collision obstacle ${obstacle.id} has no record in the scored artifact`);
      for (const ring of obstacle.rings) prisms.push({ id: obstacle.id, ring, baseY: 0, topY: top });
    }
    const plan = planRoute([arrival.x, arrival.z], prisms, [west, north, east, south]);

    const interactions = [];
    const harnessWrites = [];
    const key = async (type, code, keyName, virtual) => {
      await session.send('Input.dispatchKeyEvent', {
        type, code, key: keyName, windowsVirtualKeyCode: virtual, nativeVirtualKeyCode: virtual,
        text: type === 'keyDown' ? keyName : undefined, autoRepeat: false,
      });
    };
    const refuseTyping = async (what) => {
      const state = await captureState();
      if (state.typingTarget) await halt(`${what}: focus is in a text field, so keys would type instead of act`);
    };

    // Summon the Companion through the product's own X handler.
    await refuseTyping('summon');
    await key('keyDown', 'KeyX', 'x', 88);
    await key('keyUp', 'KeyX', 'x', 88);
    let summoned = false;
    for (let attempt = 0; attempt < 30 && !summoned; attempt += 1) {
      await sleep(100);
      const state = await captureState();
      const controls = await pose();
      summoned = state.companion.shown && controls.conversationActive;
    }
    interactions.push({ kind: 'summon-companion', key: 'KeyX', carriedByProduct: summoned });
    if (!summoned) await halt('the product did not summon the Companion on X');

    // Face along the route. Mouse look would write this same value; nothing writes a position.
    await session.call(bindingId, `function (yaw) { this.controls.state.yaw = yaw; return true; }`, [plan.yaw]);
    harnessWrites.push({ field: 'controls.state.yaw', valueMicroradians: Math.round(plan.yaw * 1e6), why: 'pointer lock, and so mouse look, is not granted to automation' });

    const recorderId = await session.call(bindingId, INSTALL_RECORDER, [], false);
    const accelTime = await session.call(bindingId, `function () { return this.controls.config.accelTime; }`);
    const [fx, fz] = plan.forward;
    const along = (p) => (p.x - arrival.x) * fx + (p.z - arrival.z) * fz;

    const settle = async () => {
      const started = Date.now();
      for (;;) {
        const p = await pose();
        if (p.speed < 0.002) return p;
        if (Date.now() - started > 5000) await halt('the player did not come to rest');
        await sleep(20);
      }
    };

    const captures = [];
    const capture = async (label) => {
      await settle();
      await session.call(bindingId, `function () { this.invalidate(); return true; }`);
      await sleep(500);
      for (let attempt = 0; attempt < 3; attempt += 1) {
        const p0 = await pose();
        const state = await captureState();
        const stats = await session.call(appId, `function () { return { drawCalls: this.stats.drawCalls.total, frame: this.frame }; }`);
        const { data } = await session.send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
        const p1 = await pose();
        const moved = Math.hypot(p1.x - p0.x, p1.y - p0.y, p1.z - p0.z);
        if (moved > 0.001 || Math.abs(p1.yaw - p0.yaw) > 1e-6) continue;
        const bytes = Buffer.from(data, 'base64');
        const file = `${options.label}-capture-${String(captures.length + 1).padStart(2, '0')}-route-${label}.png`;
        writeFileSync(join(out, file), bytes);
        captures.push({
          label,
          file,
          byteSize: bytes.byteLength,
          sha256: sha256(bytes),
          pose: p1,
          alongMetres: along(p1),
          stats,
          state,
        });
        return;
      }
      await halt(`the pose would not hold still for the ${label} capture`);
    };

    const routeLength = THRESHOLDS.routeLengthMm / 1000;
    const walkTo = async (targetAlong) => {
      await refuseTyping('walk');
      const start = await pose();
      // The rest pose opens the trace, so the walk is measured from where the player stood.
      const opened = await session.send('Runtime.callFunctionOn', {
        objectId: recorderId,
        functionDeclaration: `function (binding) {
          const s = binding.controls.state;
          this.poses.push([s.x, s.y, s.z, s.yaw, s.pitch, binding.controls.movementSpeed]);
          this.recording = true;
          return true;
        }`,
        arguments: [{ objectId: bindingId }],
        returnByValue: true,
      });
      if (opened.exceptionDetails) await halt('the trace recorder could not be started');
      await key('keyDown', 'KeyW', 'w', 87);
      const started = Date.now();
      try {
        for (;;) {
          const p = await pose();
          if (along(p) + p.speed * accelTime >= targetAlong) break;
          if (Date.now() - started > 30_000) await halt(`the walk stalled at ${along(p).toFixed(2)} m of ${targetAlong} m`);
          await sleep(4);
        }
      } finally {
        await key('keyUp', 'KeyW', 'w', 87);
      }
      const end = await settle();
      const displacement = along(end) - along(start);
      interactions.push({
        kind: 'walk',
        key: 'KeyW',
        targetAlongMm: Math.round(targetAlong * 1000),
        displacementMillimetres: Math.round(displacement * 1000),
        carriedByProduct: displacement > 1,
      });
      if (displacement <= 1) await halt('the product did not move the player on W');
    };

    await capture(CAPTURE_LABELS[0]);
    await walkTo(routeLength / 2);
    await capture(CAPTURE_LABELS[1]);
    await walkTo(routeLength);
    await capture(CAPTURE_LABELS[2]);
    await session.call(recorderId, `function () { this.recording = false; return true; }`);
    const recorded = await session.call(recorderId, `function () {
      const out = { poses: this.poses, failures: this.failures };
      this.handle.off();
      this.observer?.disconnect();
      return out;
    }`);
    const poses = recorded.poses.map(([x, y, z, yaw, pitch, speed]) => ({ x, y, z, yaw, pitch, speed }));
    if (poses.length === 0) await halt('the live trace recorded no frame of the walk');

    // Listeners on the window, the document and the world canvas, by the script that added them.
    await session.send('Debugger.enable');
    await sleep(300);
    const scripts = new Map();
    for (const event of session.events) {
      if (event.method === 'Debugger.scriptParsed') scripts.set(event.params.scriptId, event.params.url);
    }
    const listenerInventory = [];
    const counts = { product: 0, 'dev-server': 0, foreign: 0 };
    let productWindowKeydownListeners = 0;
    for (const [targetName, expression] of [
      ['window', 'window'],
      ['document', 'document'],
      ['canvas', `document.getElementById('atlas')`],
    ]) {
      const objectId = await session.reference(expression);
      const { listeners } = await session.send('DOMDebugger.getEventListeners', { objectId });
      for (const listener of listeners) {
        const source = normalizeUrl(scripts.get(listener.scriptId));
        const kind = listenerSource(source);
        counts[kind] += 1;
        if (targetName === 'window' && listener.type === 'keydown' && kind === 'product') {
          productWindowKeydownListeners += 1;
        }
        listenerInventory.push({ target: targetName, type: listener.type, source, kind, line: listener.lineNumber });
      }
    }
    await session.send('Debugger.disable');
    listenerInventory.sort((a, b) =>
      `${a.target}|${a.type}|${a.source}|${a.line}`.localeCompare(`${b.target}|${b.type}|${b.source}|${b.line}`));

    const authored = await session.call(bindingId, `function () {
      return { objectIds: [...this.objects.objectIds], district: this.ownedDistrict?.metrics ?? null };
    }`);

    // What was drawn, and the product's own support under it.
    const scene = await session.call(bindingId, EXTRACT_SCENE, [pcUrl]);
    const meshes = scene.meshes.map((mesh) => ({
      id: mesh.id,
      cull: mesh.cull,
      hasUv: mesh.hasUv,
      decodedTextureBytes: mesh.decodedTextureBytes,
      triangles: float64FromBase64(mesh.triangles),
    }));
    let supportQueries = 0;
    const measured = await measureScene({
      meshes,
      prisms,
      plan,
      poses,
      sampleSupport: async (points) => {
        supportQueries += points.length / 2;
        const text = await session.call(bindingId, SAMPLE_SUPPORT, [toBase64(points)]);
        return [...float64FromBase64(text)].map((value) => (Number.isNaN(value) ? null : value));
      },
    });

    // The product's own validation report, emitted once its measuring window closes.
    const report = await (async () => {
      const deadline = navigatedAt + (options.validationSeconds + 90) * 1000;
      for (;;) {
        const text = await session.evaluate(`document.getElementById('exulanica-browser-validation-report')?.textContent ?? null`);
        if (text !== null) return JSON.parse(text);
        if (Date.now() > deadline) await halt('the product never emitted its validation report');
        await sleep(1000);
      }
    })();

    // The scored artifact, found on the wire by its bytes rather than by its name.
    let environment = null;
    for (const [requestId, entry] of network) {
      if (!entry.finished || entry.decodedBytes !== artifactBytes.byteLength) continue;
      const body = await session.send('Network.getResponseBody', { requestId }).catch(() => null);
      if (body === null) continue;
      const bytes = Buffer.from(body.body, body.base64Encoded ? 'base64' : 'utf8');
      if (sha256(bytes) !== sha256(artifactBytes)) continue;
      environment = { requestPath: normalizeUrl(entry.url), transferredBytes: entry.encodedBytes, decodedBytes: bytes.byteLength, status: entry.status };
      break;
    }
    if (environment === null) await halt('the page never fetched the scored artifact byte for byte');

    const requests = [...network.values()];
    const pathOf = (entry) => {
      try {
        return new URL(entry.url).pathname;
      } catch {
        return '';
      }
    };
    const apiResponses = {};
    for (const entry of requests) {
      const path = pathOf(entry);
      if (!path.startsWith('/api/')) continue;
      const route = path.replace(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi, '{id}');
      const name = `${entry.method} ${route} ${entry.status ?? 'none'}`;
      apiResponses[name] = (apiResponses[name] ?? 0) + 1;
    }
    const previewApi = requests
      .filter((entry) => pathOf(entry).startsWith('/preview-api/'))
      .map((entry) => ({ url: normalizeUrl(entry.url), status: entry.status }));
    const graphRead = requests.some((entry) => pathOf(entry) === '/api/graph' && entry.status === 200);
    let authenticationCondition = null;
    if (previewApi.length === 0 && graphRead && anonymousStatus === 401) authenticationCondition = 'credentialed-api';
    else if (previewApi.length > 0 && !requests.some((entry) => pathOf(entry).startsWith('/api/'))) authenticationCondition = 'vite-preview-api';
    if (authenticationCondition === null) {
      await halt(`the authentication condition cannot be named: preview requests ${previewApi.length}, graph read ${graphRead}, anonymous status ${anonymousStatus}`);
    }

    const gpuError = report.renderer?.gpu_error;
    if (typeof gpuError !== 'number') await halt('the product report did not measure the GPU error state');
    const substitutedPages = navigations.filter((url) => {
      if (url === 'about:blank') return false;
      try {
        const parsed = new URL(url);
        return parsed.origin !== appOrigin || parsed.pathname !== '/';
      } catch {
        return true;
      }
    }).length;
    const observation = {
      captures: captures.map((item) => ({
        label: item.label,
        companionShown: item.state.companion.shown,
        reticleCentred: item.state.reticle.centred,
        inProductShell: item.state.inProductShell,
      })),
      foreignListeners: counts.foreign,
      productWindowKeydownListeners,
      interactionsNotCarriedByProduct: interactions.filter((item) => !item.carriedByProduct).length,
      substitutedPages,
      recoveryEvents: recorded.failures.length,
      harnessPositionWrites: harnessWrites.filter((write) => /\.(x|y|z)$/.test(write.field)).length,
      environmentTransferredBytes: environment.transferredBytes,
      environmentDecodedTextureBytes: scene.environmentTextureBytes,
      maxDrawCalls: report.renderer.max_draw_calls,
      gpuErrors: gpuError === 0 ? 0 : 1,
      pageErrors: exceptions.length,
    };
    const mechanical = mechanicalMeasurements(measured, observation);
    const keys = keySet(mechanical);

    const run = {
      profile: 'exulanica.visual-gate-run/v1',
      keySet: GATE_KEY_SET_VERSION,
      label: options.label,
      app: { origin: appOrigin, path: appUrl.pathname, validationSeconds: options.validationSeconds },
      scored: {
        artifact: { path: options.artifact, byteSize: artifactBytes.byteLength, sha256: sha256(artifactBytes), profile: artifact.profile, districtId: artifact.district_id },
        renderer: { path: options.renderer, byteSize: rendererBytes.byteLength, sha256: sha256(rendererBytes) },
      },
      browser: {
        engine: `${version.Browser} over the Chrome DevTools Protocol, driven by scripts/capture_visual_gate.mjs (no Playwright)`,
        protocolVersion: version['Protocol-Version'],
        viewport: [VIEWPORT.width, VIEWPORT.height],
        deviceScaleFactor: 1,
        mountMs,
      },
      authentication: {
        condition: authenticationCondition,
        anonymousGraphReadStatus: anonymousStatus,
        apiResponses,
        previewApiRequests: previewApi,
      },
      arrival,
      route: {
        rule: plan.rule,
        startMm: [Math.round(plan.start[0] * 1000), Math.round(plan.start[1] * 1000)],
        headingMillidegrees: plan.headingMillidegrees,
        clearRunMm: plan.clearRunMm,
        frontageSamples: plan.frontageSamples,
        frontageBothSidesSamples: plan.frontageBothSidesSamples,
        meanFrontageSkewMillionths: plan.meanFrontageSkewMillionths,
        candidatesTried: plan.candidatesTried,
        candidatesQualified: plan.candidatesQualified,
        obstacles: prisms.length,
        fieldBoundsCm: artifact.bounds_cm,
      },
      interactions,
      harnessWrites,
      harnessObservers: [
        'one engine update listener that copies the controls state each frame while the walk runs',
        'one MutationObserver on the travel status that records failure messages while the walk runs',
      ],
      captures,
      trace: {
        frames: poses.length,
        first: poses[0],
        last: poses[poses.length - 1],
        recoveryMessages: recorded.failures,
      },
      listeners: { counts, productWindowKeydownListeners, inventory: listenerInventory },
      authoredObjects: authored,
      scene: {
        meshes: scene.meshes.map((mesh) => ({
          id: mesh.id, cull: mesh.cull, hasUv: mesh.hasUv, textureCount: mesh.textureCount,
          decodedTextureBytes: mesh.decodedTextureBytes,
          triangles: Buffer.from(mesh.triangles, 'base64').byteLength / 72,
        })),
        skipped: scene.skipped,
        renderOrigin: scene.origin,
        environmentTextures: scene.environmentTextures,
        environmentTextureBytes: scene.environmentTextureBytes,
        deviceTextureBytes: scene.deviceTextureBytes,
        deviceVram: scene.deviceVram,
        supportQueries,
      },
      measured,
      network: {
        environment,
        requests: requests.length,
        finishedRequests: requests.filter((entry) => entry.finished).length,
        failedRequests: requests.filter((entry) => entry.failed !== null).map((entry) => ({ url: normalizeUrl(entry.url), error: entry.failed })),
        httpErrors: requests.filter((entry) => (entry.status ?? 0) >= 400).map((entry) => ({ url: normalizeUrl(entry.url), status: entry.status })),
        transferredBytes: requests.reduce((sum, entry) => sum + entry.encodedBytes, 0),
      },
      errors: { exceptions, consoleErrors, networkLogErrors },
      validationReport: report,
      budgetEnvelope: MELBOURNE_ENVELOPE,
      observation,
      mechanical,
      keys,
    };
    writeFileSync(join(out, `${options.label}-run.json`), `${JSON.stringify(run, null, 2)}\n`);
    writeFileSync(join(out, `${options.label}-trace.json`), `${JSON.stringify({
      profile: 'exulanica.visual-gate-trace/v1',
      frames: poses.map((p) => [
        Math.round(p.x * 1000), Math.round(p.y * 1000), Math.round(p.z * 1000),
        Math.round(p.yaw * 1e6), Math.round(p.pitch * 1e6), Math.round(p.speed * 1000),
      ]),
      columns: ['xMm', 'yMm', 'zMm', 'yawMicroradians', 'pitchMicroradians', 'speedMmPerSecond'],
    })}\n`);
    for (const text of JSON.stringify(run).match(/\/Users\/|Bearer |api-token/g) ?? []) {
      throw new Halt(`the run record would carry ${text}`);
    }
    console.log(JSON.stringify({ label: options.label, keys, route: run.route.headingMillidegrees, captures: captures.map((c) => c.file) }, null, 2));
  } finally {
    session.socket.close();
    chrome.kill();
    await sleep(500);
    rmSync(profile, { recursive: true, force: true });
    if (process.env.VISUAL_GATE_CHROME_LOG === '1') process.stderr.write(log());
  }
}

main().catch((error) => {
  const out = process.argv.includes('--out') ? resolve(argument('out')) : null;
  if (error instanceof Halt) {
    if (out !== null) {
      mkdirSync(out, { recursive: true });
      writeFileSync(join(out, `${options.label}-halt.json`), `${JSON.stringify({ halted: true, reason: error.message }, null, 2)}\n`);
    }
    console.error(`HALT: ${error.message}`);
    process.exit(3);
  }
  console.error(error);
  process.exit(1);
});
