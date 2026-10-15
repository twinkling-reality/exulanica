import { pointerRay } from '../../../web/packages/atlas-react/src/playcanvas/index.ts';
import { ACTION_LABELS, ACTIVITY_LABELS } from '/src/society-activity-words.ts';
import { buildInventoryRows, inventoryDetailPath, rowForSceneSelection } from './inventory-records.ts';
import { assertSelectedOffer, inspectionFacts } from './entity-inspection.mjs';
import { mountEntitySheet } from './entity-sheet.ts';
import { mountBuildMode } from './build-mode.ts';
import { mountFrameMeasurement } from './frame-measurement.mjs';
import { DECIDER_MARKS } from '/src/decider-marks.ts';
import { DISCOVERY, attentionCandidates, inspectionReach, promptPresentation, layoutDiscovery, markerAt } from './discovery-policy.mjs';
import { createReadBackoff } from './read-backoff.mjs';
import { keepWorldInAddress, returnToFrontDoor } from './front-door.ts';
import { keepWorldPicture } from '/src/composition/world-pictures.ts';
import { mountCorners } from './world-corners.ts';
import { keyWord, mountUiScale } from './world-ui.ts';
import { worldKey, wakesHints } from './world-keys.mjs';
import { CORNER_WORDS, NOTE_WORDS, availableHints } from './world-words.mjs';
import './entity-sheet.css';
import './blank-world.css';
import './contextual-world.css';

let disposePrior = () => {};

/** Targeting and inspection use real native hits and authorized inventory identities. */
export async function mountContextualWorld({ state, renderer, selection, objects, send, binding }) {
  disposePrior();
  const b = renderer.atlas.binding, canvas = document.getElementById('atlas');
  const entry = state.activeWorldEntry;
  if (!b || !canvas || !entry) return;
  const lifetime = new AbortController();
  const viewKey = 'exulanica.workspace-review.camera:' + entry.entryId + ':' + entry.authoredVersionId;
  try {
    const view = JSON.parse(sessionStorage.getItem(viewKey) || 'null');
    if (view && Number.isFinite(view.yaw) && Number.isFinite(view.pitch) && Math.abs(view.pitch) <= Math.PI * .49) {
      if (view.pose && ['x','y','z','yaw','pitch'].every(key => Number.isFinite(view.pose[key])) && ['ground','altitude'].includes(view.hold)) b.controls.setView(view.pose, view.hold);
      else { b.controls.state.yaw = view.yaw; b.controls.state.pitch = view.pitch; }
      b.invalidate();
    }
  } catch { /* Camera memory is optional and never world state. */ }
  const rememberView = () => {
    const pose = following?.pose || b.controls.state, hold = following?.hold || b.controls.hold;
    try { sessionStorage.setItem(viewKey, JSON.stringify({ yaw: pose.yaw, pitch: pose.pitch, pose: { ...pose }, hold })); } catch {}
  };
  keepWorldInAddress(entry.entryId, lifetime.signal);
  window.addEventListener('beforeunload', rememberView, { signal: lifetime.signal });
  window.addEventListener('keyup', event => { if (event.code.startsWith('Arrow') || ['KeyW','KeyA','KeyS','KeyD'].includes(event.code)) rememberView(); }, { signal: lifetime.signal });
  selection.closePanels(); objects.close();
  document.body.classList.remove('ux-world-active', 'ux-review');
  document.body.classList.add('ux-world-cleared');
  const shell = document.getElementById('shell');
  if (shell) { shell.inert = true; shell.setAttribute('aria-hidden', 'true'); }
  const root = document.createElement('div'); root.id = 'contextual-world'; root.className = 'wu-root';
  root.dataset.revision = 'center-aim-proximity-v6';
  root.innerHTML = `<div class="cw-discovery" aria-label="People and things in view"></div>
    <aside class="cw-prompt" hidden aria-label="Available action"><button class="cw-inspect" type="button"><kbd>E</kbd><span>Inspect</span></button></aside>
    <section class="cw-panel" hidden role="dialog" aria-modal="true" aria-labelledby="cw-panel-title"></section>`;
  document.body.append(root);
  mountUiScale(root, lifetime.signal);
  root.dataset.navigation = JSON.stringify({ ground: b.worldKind.ground.form, centre: b.navigationWorld.centre,
    fieldRadius: b.navigationWorld.fieldRadius, blockers: b.navigationWorld.polygonObstacles });
  const disposeFrameMeasurement = mountFrameMeasurement(b, root);
  const $ = (selector) => root.querySelector(selector);
  const prompt = $('.cw-prompt'), discovery = $('.cw-discovery'), panel = $('.cw-panel');
  // Your worlds: back to the front door with this world chosen, after keeping a picture of it for
  // its card, as the app does when a person leaves a world.
  let leaving = false;
  const leaveWorld = () => {
    if (leaving) return;
    leaving = true;
    void keepWorldPicture(b, entry.entryId).catch(() => false).finally(() => returnToFrontDoor(entry.entryId));
  };
  // The corners (world-corners.ts): the way out, the clock with Play and Pause, the hints for what
  // works here, the reticle and the note.
  // A read-only copy dims what needs the server (Play and Pause), as the offline state does.
  const corners = mountCorners({ host: root, people: selection.people ?? null, onLeave: leaveWorld,
    readOnly: import.meta.env.VITE_EXULANICA_REVIEW_OBSERVER_ONLY === '1' });
  const guidance = corners.hintsRoot, worlds = corners.backRoot;
  let rows = [], inventory = null, target = null, held = null, pointer = null;
  let dragging = null, overPrompt = false, serial = 0, lastPick = 0, frameId = 0;
  const activityLabels = new Map([...Object.entries(ACTION_LABELS), ...ACTIVITY_LABELS]);
  const offers = new Map(), offerReads = new Map(), offerSerials = new Map();
  // Automatic reads of a subject whose read failed wait longer each time (read-backoff.mjs).
  const readBackoff = createReadBackoff();
  let entitySheet = null, targetReachable = false;
  let following = null;
  let visibleMarkers = [], lastDiscovery = -Infinity, pointerIntent = false;
  const surfaceSizes = new Map();
  const sizeObserver = new ResizeObserver(entries => { for (const { target, borderBoxSize } of entries) { const size = borderBoxSize[0]; if (size) surfaceSizes.set(target, { width: size.inlineSize, height: size.blockSize }); } });
  sizeObserver.observe(prompt); sizeObserver.observe(panel);
  let lastMeasure = 0;
  const overlayCosts = [], discoveryCosts = [];
  const markerNodes = new Map();
  const measure = document.createElement('canvas').getContext('2d');
  if (measure) measure.font = `500 ${DECIDER_MARKS.nameLeastPx}px "IBM Plex Sans"`;
  const priorCallbacks = { pick: b.controls.onPointerPick, interact: b.controls.onInteract, summon: b.controls.onSummon, camera: b.controls.onCameraToggle, fly: b.controls.onFlyChange };
  b.controls.onPointerPick = null;
  b.controls.onInteract = null;
  b.controls.onSummon = null;
  b.controls.onCameraToggle = null;
  // Flying (F): the mode word at the top with its key, and the hints for flying while it lasts.
  const worldHints = () => corners.worldHints(availableHints({ flying: Boolean(b.controls.flying), build: Boolean(build), history: false }));
  b.controls.onFlyChange = (flying) => {
    corners.mode(flying ? CORNER_WORDS.flying : null, flying ? keyWord({ keys: ['F'], word: CORNER_WORDS.land }) : null);
    worldHints();
  };
  b.setControlsEnabled(true); b.setFreeCursorActive(false);

  const current = () => state.activeWorldEntry?.worldId === entry.worldId && state.activeWorldEntry?.authoredVersionId === entry.authoredVersionId;
  const read = async (path) => {
    const response = await fetch('/review-api' + path, { cache: 'no-store', signal: lifetime.signal });
    if (!response.ok) throw Error(response.status === 424 ? 'This source is no longer available.' : 'This world could not be read. Try again.');
    return response.json();
  };
  // Build mode (build-mode.ts), where this page may change the world: B, then point and click.
  const build = send && binding && import.meta.env.VITE_EXULANICA_REVIEW_OBSERVER_ONLY !== '1'
    ? mountBuildMode({ b, root, state, entry, read, send, binding, canvas, guidance, worlds, corners, inspecting: () => !panel.hidden }) : null;
  worldHints();
  function node(tag, words = '', cls = '') {
    const item = document.createElement(tag); item.textContent = String(words); item.className = cls; return item;
  }
  function control(words, run, cls = '') {
    const item = node('button', words, cls); item.type = 'button'; item.onclick = run; return item;
  }
  function notice(words) {
    if (words) corners.notes.show(words); else corners.notes.clear();
  }
  async function refreshInventory() {
    if (!current()) throw Error('The world changed. Reload it before inspecting.');
    const data = await read('/world/versions/' + encodeURIComponent(entry.authoredVersionId) + '/inventory?world_id=' + encodeURIComponent(entry.worldId));
    if (!current() || data.world_id !== entry.worldId || data.version_id !== entry.authoredVersionId) throw Error('The world changed. Reload it before inspecting.');
    rows = buildInventoryRows(data).filter(row => row.scene && row.availability === 'available');
    inventory = data;
    root.dataset.listed = String(rows.length);
  }
  async function entityOffer(row, force = false) {
    const known = offers.get(row.key);
    if (!force && known && performance.now() - known.at < 5000) return known.offer;
    if (!force && offerReads.has(row.key)) return offerReads.get(row.key);
    const sequence = (offerSerials.get(row.key) || 0) + 1; offerSerials.set(row.key, sequence);
    const request = (async () => {
      const path = inventoryDetailPath(inventory, row);
      const offer = path ? await read(path) : null;
      if (offer) assertSelectedOffer(offer, entry, row);
      if (!current()) throw Error('This world changed. Reload it before inspecting.');
      if (offerSerials.get(row.key) === sequence && !lifetime.signal.aborted) offers.set(row.key, { offer, at: performance.now() });
      return offer;
    })();
    request.then(() => readBackoff.succeeded(row.key), () => readBackoff.failed(row.key, performance.now()));
    offerReads.set(row.key, request);
    try { return await request; } finally { if (offerReads.get(row.key) === request) offerReads.delete(row.key); }
  }
  function picked(x, y) {
    if (!current() || !inventory || !b.__workspacePick) return null;
    const ray = pointerRay(b, x, y); if (!ray) return null;
    const hit = b.__workspacePick(ray.origin, ray.direction);
    const being = hit?.inhabitantId || hit?.thing?.pick?.subjectId;
    return being ? rowForSceneSelection(rows, { type: 'being', id: being })
      : hit?.authored?.objectId ? rowForSceneSelection(rows, { type: 'object', id: hit.authored.objectId }) : null;
  }
  function targetPoint(row, overhead = false) {
    const point = b.camera.getPosition().clone();
    if (row.scene.type === 'being') {
      if (!b.authoredSociety?.anchorOf(row.scene.id, point)) return null;
      const ground = point.clone();
      if (!overhead && b.authoredSociety.groundOf(row.scene.id, ground)) point.lerp(ground, point, .6);
      return point;
    }
    const subject = b.representationReport.subjects.find(item => item.subject.subjectId === row.scene.id)?.subject;
    const bounds = subject && b.representationBounds(subject);
    if (!bounds?.length) return null;
    point.set(...[0, 1, 2].map(axis => overhead && axis === 1 ? Math.max(...bounds.map(value => value[axis])) : bounds.reduce((sum, value) => sum + value[axis], 0) / bounds.length));
    return point;
  }
  /** How far the camera is from a subject for inspect reach: to the nearest point of a being's box, so a being of any size can be inspected from beside it; to an object's middle. */
  function reachDistance(row) {
    const eye = b.camera.getPosition();
    if (row.scene.type === 'being') {
      const nearest = eye.clone();
      return b.authoredSociety?.nearestPointOf(row.scene.id, eye, nearest) ? eye.distance(nearest) : Infinity;
    }
    const point = targetPoint(row);
    return point ? eye.distance(point) : Infinity;
  }
  function visitorGround(row) {
    if (row?.scene.type !== 'being') return null;
    const point = b.camera.getPosition().clone();
    if (!b.authoredSociety?.groundOf(row.scene.id, point)) return null;
    const camera = b.camera.getPosition(), origin = b.interactionRay().origin;
    return point.add(point.clone().set(origin[0] - camera.x, origin[1] - camera.y, origin[2] - camera.z));
  }
  function stopFollowing() {
    if (!following) return;
    b.controls.setView(following.pose, following.hold); following = null; b.invalidate();
    root.dataset.following = 'false';
  }
  const followView = {
    active: () => following !== null,
    toggle: () => {
      if (following) { stopFollowing(); return; }
      const ground = visitorGround(held); if (!ground) return;
      following = { pose: { ...b.controls.state }, hold: b.controls.hold, ground };
      b.controls.setView({ ...b.controls.state }, 'altitude');
      root.dataset.following = 'true'; b.invalidate();
    },
  };
  function trackHeld() {
    if (!following) return;
    const ground = visitorGround(held);
    if (!ground) { stopFollowing(); notice('This character is no longer visible here. Your viewpoint was restored.'); return; }
    const delta = ground.clone().sub(following.ground);
    if (delta.lengthSq() > 0) {
      const pose = b.controls.state;
      b.controls.setView({ ...pose, x: pose.x + delta.x, y: pose.y + delta.y, z: pose.z + delta.z }, 'altitude');
      b.invalidate();
    }
    following.ground.copy(ground);
  }
  function targetLabel(row) {
    const known = offers.get(row.key)?.offer;
    return known ? inspectionFacts(row, known, null, activityLabels).title : row.scene.type === 'being' ? 'Character' : 'Object';
  }
  function screenFrame(row) {
    const body = targetPoint(row), head = targetPoint(row, true);
    if (!body || !head) return null;
    const centre = b.camera.camera.worldToScreen(body), overhead = b.camera.camera.worldToScreen(head);
    const points = [centre, overhead];
    if (row.scene.type === 'being') {
      const ground = body.clone();
      if (!b.authoredSociety.groundOf(row.scene.id, ground)) return null;
      points.push(b.camera.camera.worldToScreen(ground));
    } else {
      const subject = b.representationReport.subjects.find(item => item.subject.subjectId === row.scene.id)?.subject;
      const bounds = subject && b.representationBounds(subject);
      if (!bounds?.length) return null;
      points.push(...bounds.map(value => b.camera.camera.worldToScreen(body.clone().set(...value))));
    }
    const front = points.filter(value => value.z > 0 && Number.isFinite(value.x) && Number.isFinite(value.y));
    if (!front.length) return null;
    const left = Math.min(...front.map(point => point.x)), right = Math.max(...front.map(point => point.x));
    const top = Math.min(...front.map(point => point.y)), bottom = Math.max(...front.map(point => point.y));
    if (right < 0 || left > innerWidth || bottom < 0 || top > innerHeight) return null;
    const focus = centre.z > 0 ? centre : front[0];
    const projected = { x: Math.max(16, Math.min(innerWidth - 16, focus.x)), y: Math.max(16, Math.min(innerHeight - 16, focus.y)), z: focus.z };
    const headInView = overhead.z > 0 && overhead.x >= 0 && overhead.x <= innerWidth && overhead.y >= 0 && overhead.y <= innerHeight;
    return { body, projected, overhead, headInView, extent: Math.max(right - left, bottom - top),
      x: Math.max(28, Math.min(innerWidth - 28, headInView ? overhead.x : projected.x)),
      y: Math.max(72, Math.min(innerHeight - 12, headInView ? overhead.y - 8 : projected.y - 24)) };
  }
  function projectDiscovery(row) {
    const frame = screenFrame(row);
    if (!frame || frame.extent < DISCOVERY.leastExtentPx && row.key !== target?.key && row.key !== held?.key) return null;
    const eye = b.camera.getPosition();
    if (state.worldSight && !state.worldSight.sees(eye, frame.body)) return null;
    const label = targetLabel(row);
    return { key: row.key, row, x: frame.x, y: frame.y, z: frame.projected.z, extent: frame.extent,
      distance: eye.distance(frame.body), visible: true, label,
      nameWidth: Math.min(230, (measure?.measureText(label).width || label.length * 7) + 8), nameHeight: DECIDER_MARKS.nameLeastPx * 2.6 };
  }
  function refreshDiscovery() {
    const focused = held || target;
    const candidates = rows.filter(row => row.detail && (panel.hidden || row.key === held?.key)).map(projectDiscovery).filter(Boolean);
    visibleMarkers = layoutDiscovery(attentionCandidates(candidates, { width: innerWidth, height: innerHeight }, focused?.key), { width: innerWidth, height: innerHeight }, DECIDER_MARKS, focused?.key);
    root.dataset.markers = String(visibleMarkers.length);
    const shown = new Set(visibleMarkers.map(item => item.key));
    for (const [key, marker] of markerNodes) if (!shown.has(key) && !marker.root.hidden) marker.root.hidden = true;
    for (const item of visibleMarkers) {
      let marker = markerNodes.get(item.key);
      if (!marker) {
        const root = node('button', '', 'cw-marker'); root.type = 'button'; root.dataset.subject = item.key;
        const name = node('span', '', 'cw-marker-name'), glyph = node('span', '', 'cw-marker-glyph');
        glyph.innerHTML = '<svg viewBox="0 0 28 30" fill="none" aria-hidden="true"><path d="M14 3 23 12 14 21 5 12Z"/><path d="m10 24 4 4 4-4"/></svg>';
        root.append(name, glyph); discovery.append(root); marker = { root, name, glyph }; markerNodes.set(item.key, marker);
        root.addEventListener('pointerenter', event => { pointer = { x: event.clientX, y: event.clientY }; }, { signal: lifetime.signal });
        root.addEventListener('pointermove', event => { pointer = { x: event.clientX, y: event.clientY }; }, { signal: lifetime.signal });
        root.addEventListener('pointerleave', event => { pointer = { x: event.clientX, y: event.clientY }; pointerIntent = true; }, { signal: lifetime.signal });
        root.addEventListener('focus', () => { overPrompt = true; }, { signal: lifetime.signal });
        root.addEventListener('blur', () => { overPrompt = false; }, { signal: lifetime.signal });
        root.onclick = () => { const row = rows.find(row => row.key === item.key); if (row) void inspect(row); };
      }
      if (marker.root.hidden) marker.root.hidden = false;
      if (marker.root.disabled !== !panel.hidden) marker.root.disabled = !panel.hidden;
      marker.root.style.setProperty('--cw-marker-opacity', String(item.opacity));
      marker.root.style.setProperty('--cw-glyph-size', item.glyph + 'px');
      marker.root.dataset.focused = String(item.key === focused?.key);
      marker.root.dataset.extent = item.extent.toFixed(1);
      marker.root.dataset.distance = item.distance.toFixed(1);
      marker.root.setAttribute('aria-label', 'Focus ' + item.label);
      if (marker.name.textContent !== item.label) marker.name.textContent = item.label; marker.name.hidden = item.key !== focused?.key || !item.named || !panel.hidden;
      if (!offers.has(item.key) && !offerReads.has(item.key) && readBackoff.ready(item.key, performance.now())) void entityOffer(item.row).catch(() => {});
    }
  }
  function targetAt(at) {
    return at ? picked(at.x, at.y) || markerAt(visibleMarkers.filter(item => !markerNodes.get(item.key)?.root.hidden), at)?.row || null : null;
  }
  function positionMarkers() {
    for (const item of visibleMarkers) {
      const frame = screenFrame(item.row), marker = markerNodes.get(item.key);
      if (!frame) { marker.root.hidden = true; continue; }
      item.x = frame.x; item.y = frame.y;
      const transform = `translate3d(${item.x.toFixed(1)}px,${item.y.toFixed(1)}px,0) translate(-50%,-100%)`;
      if (marker.root.style.transform !== transform) marker.root.style.transform = transform;
    }
  }
  function setTarget(row) {
    const changed = target?.key !== row?.key;
    if (changed) targetReachable = false;
    target = row;
    prompt.hidden = !row || !panel.hidden;
    root.dataset.target = row?.key || '';
    if (row) {
      $('.cw-inspect').setAttribute('aria-label', 'Inspect ' + row.label);
      if (changed) {
        lastDiscovery = -Infinity;
        if (readBackoff.ready(row.key, performance.now())) void entityOffer(row).catch(() => {});
      }
    }
  }
  function renderHeader(row, titleWords = 'Inspecting entity') {
    panel.replaceChildren();
    const header = node('header', '', 'cw-panel-header');
    const title = node('div');
    const heading = node('h2', titleWords.charAt(0).toUpperCase() + titleWords.slice(1)); heading.id = 'cw-panel-title'; heading.tabIndex = -1; title.append(heading);
    header.append(title); panel.append(header);
    const content = node('div', '', 'cw-panel-content'); panel.append(content); heading.focus({ preventScroll: true }); return content;
  }
  function renderBack() {
    const footer = node('footer', '', 'cw-panel-footer');
    const back = control('', closeInspect, 'cw-back'); back.setAttribute('aria-label', 'Close inspection');
    back.append(node('kbd', 'Esc'), node('span', 'Back')); footer.append(back); panel.append(footer);
  }
  function renderOffer(row, offer, playback) {
    entitySheet?.dispose();
    const view = inspectionFacts(row, offer, null, activityLabels);
    entitySheet = mountEntitySheet({ panel, row, offer, title: view.title, entry, inventory, credentials: state.credentials, read, isCurrent: current,
      close: closeInspect, societyNames: () => selection.societyNames(), followView: row.scene.type === 'being' ? followView : null,
      refresh: async () => {
        await refreshInventory();
        const fresh = rows.find(item => item.key === row.key);
        if (!fresh) throw Error('This entity is no longer in this world.');
        return { row: fresh, inventory, offer: await entityOffer(fresh, true) };
      },
    });
  }
  async function inspect(row = target) {
    if (!row || !panel.hidden) return;
    if (!inspectionReach(reachDistance(row), row.key === target?.key && targetReachable)) { notice(NOTE_WORDS.closer); return; }
    held = row; panel.hidden = false; prompt.hidden = true; notice('');
    b.setControlsEnabled(false); b.setFreeCursorActive(true); canvas.inert = true;
    if (document.pointerLockElement) document.exitPointerLock();
    guidance.hidden = true; worlds.hidden = true;
    const request = ++serial;
    const previousOffer = offers.get(row.key)?.offer;
    const heading = previousOffer ? inspectionFacts(row, previousOffer, null, activityLabels).title : 'Loading details';
    renderHeader(row, heading).append(node('p', 'Loading details…', 'cw-reading'));
    renderBack();
    try {
      await refreshInventory();
      const refreshed = rows.find(item => item.key === row.key);
      if (!refreshed) throw Error('This entity is no longer in the world.');
      const offer = await entityOffer(refreshed, true);
      if (request !== serial || lifetime.signal.aborted) return;
      if (!current()) throw Error('This world changed. Reload it before inspecting.');
      held = refreshed; renderOffer(refreshed, offer, null);
    } catch (error) {
      if (request !== serial || lifetime.signal.aborted) return;
      const content = renderHeader(row); content.append(node('p', error.message));
      content.append(control('Try again', () => { closeInspect(); void inspect(row); }, 'cw-retry'));
      renderBack();
    }
  }
  function closeInspect() {
    stopFollowing();
    entitySheet?.dispose(); entitySheet = null; panel.classList.remove('cw-entity-sheet');
    ++serial; panel.hidden = true; panel.replaceChildren(); held = null; dragging = null; overPrompt = false;
    canvas.inert = false; b.setFreeCursorActive(false); b.setControlsEnabled(current());
    guidance.hidden = false; worlds.hidden = false; setTarget(null); canvas.focus({ preventScroll: true });
  }
  $('.cw-inspect').onclick = () => { void inspect(); };
  prompt.addEventListener('pointerenter', () => { overPrompt = true; }, { signal: lifetime.signal });
  prompt.addEventListener('pointerleave', event => { overPrompt = false; pointer = { x: event.clientX, y: event.clientY }; }, { signal: lifetime.signal });
  prompt.addEventListener('focusin', () => { overPrompt = true; }, { signal: lifetime.signal });
  prompt.addEventListener('focusout', () => { overPrompt = false; }, { signal: lifetime.signal });
  canvas.addEventListener('pointermove', event => {
    if (!dragging && panel.hidden && !document.pointerLockElement) { pointer = { x: event.clientX, y: event.clientY }; pointerIntent = true; }
  }, { signal: lifetime.signal });
  canvas.addEventListener('pointerleave', event => {
    if (!dragging && !event.relatedTarget?.closest?.('.cw-prompt,.cw-marker')) { pointer = null; pointerIntent = false; }
  }, { signal: lifetime.signal });

  // Drag-to-look keeps the ordinary cursor and also works where pointer lock is unavailable.
  window.addEventListener('mousedown', event => {
    if (event.target !== canvas || !panel.hidden || ![0, 2].includes(event.button)) return;
    event.preventDefault(); event.stopImmediatePropagation(); canvas.focus({ preventScroll: true });
    if (build?.pointerDown(event)) return;
    dragging = { startX: event.clientX, startY: event.clientY, x: event.clientX, y: event.clientY, moved: false, button: event.button };
  }, { capture: true, signal: lifetime.signal });
  document.addEventListener('pointerlockchange', () => {
    if (document.pointerLockElement === canvas) document.exitPointerLock();
  }, { signal: lifetime.signal });
  if (document.pointerLockElement === canvas) document.exitPointerLock();
  document.addEventListener('mousemove', event => {
    if (!dragging || !panel.hidden || document.pointerLockElement) return;
    const dx = event.clientX - dragging.x, dy = event.clientY - dragging.y;
    dragging.x = event.clientX; dragging.y = event.clientY;
    dragging.moved ||= Math.hypot(event.clientX - dragging.startX, event.clientY - dragging.startY) > 4;
    if (!dragging.moved) return;
    b.controls.state.yaw -= dx * .0022;
    b.controls.state.pitch = Math.max(-Math.PI * .49, Math.min(Math.PI * .49, b.controls.state.pitch - dy * .0022));
    pointerIntent = false; prompt.hidden = true; b.invalidate();
  }, { signal: lifetime.signal });
  document.addEventListener('mouseup', event => {
    if (!dragging) return;
    const press = dragging; dragging = null;
    root.dataset.gesture = JSON.stringify({ start: [press.startX, press.startY], end: [event.clientX, event.clientY], dragged: press.moved });
    rememberView();
    if (!panel.hidden) return;
    pointer = { x: event.clientX, y: event.clientY };
    pointerIntent = !press.moved || !target;
    if (!press.moved && press.button === 0) build?.click(event.clientX, event.clientY);
    // The centre aim controls E. Canvas clicks do not select whatever lies under a spare cursor.
  }, { capture: true, signal: lifetime.signal });
  canvas.addEventListener('contextmenu', event => event.preventDefault(), { signal: lifetime.signal });
  window.addEventListener('blur', () => { dragging = null; pointer = null; pointerIntent = false; corners.hold(false); }, { signal: lifetime.signal });
  // Tab held shows the hints; a key that has a hint brings them back for a while.
  window.addEventListener('keyup', event => { if (event.code === 'Tab') corners.hold(false); }, { signal: lifetime.signal });
  window.addEventListener('keydown', event => {
    if (panel.hidden && wakesHints(event)) corners.wake();
    if (panel.hidden && event.code === 'Tab') corners.hold(true);
    if (panel.hidden && build?.key(event)) { event.stopImmediatePropagation(); return; }
    if (!panel.hidden && (event.metaKey || event.ctrlKey || event.altKey)) { event.stopImmediatePropagation(); return; }
    if (!panel.hidden) {
      if (entitySheet?.key(event)) { event.stopImmediatePropagation(); return; }
      if (event.code === 'Escape') { event.preventDefault(); closeInspect(); }
      else if (event.code === 'Tab') {
        const controls = [...panel.querySelectorAll('button,summary,input,select')].filter(item => item.getClientRects().length && !item.disabled);
        const active = controls.indexOf(document.activeElement);
        if (controls.length && (event.shiftKey && active <= 0 || !event.shiftKey && (active === controls.length - 1 || active < 0))) {
          event.preventDefault(); controls[event.shiftKey ? controls.length - 1 : 0].focus();
        }
      }
      event.stopImmediatePropagation(); return;
    }
    // Each key's fate is world-keys.mjs's: movement goes on to the renderer, the workspace's keys
    // act, and every other key, the old shell's among them, goes no further.
    const fate = worldKey(event, { flying: Boolean(b.controls.flying), clock: corners.hasClock() }, Boolean(event.target?.closest?.('.cw-prompt,.wu-prompt')));
    if (fate === 'move' || fate === 'pass') return;
    if (fate !== 'quiet') event.preventDefault();
    if (fate === 'inspect') void inspect();
    else if (fate === 'leave') leaveWorld();
    else if (fate === 'play') corners.togglePlay();
    event.stopImmediatePropagation();
  }, { capture: true, signal: lifetime.signal });
  function frame(now) {
    const workStart = performance.now();
    if (state.atlas?.binding !== b || !root.isConnected) { disposePrior(); return; }
    trackHeld();
    root.dataset.camera = [b.controls.state.yaw, b.controls.state.pitch].map(value => value.toFixed(6)).join(',');
    root.dataset.viewerPosition = JSON.stringify([b.controls.state.x, b.controls.state.y, b.controls.state.z]);
    if (now - lastDiscovery >= 160) {
      lastDiscovery = now;
      const discoveryStart = performance.now(); refreshDiscovery();
      discoveryCosts.push(performance.now() - discoveryStart); if (discoveryCosts.length > 120) discoveryCosts.shift();
    }
    positionMarkers();
    build?.frame(now);
    if (panel.hidden && now - lastPick >= 33) {
      lastPick = now;
      const row = picked(innerWidth / 2, innerHeight / 2);
      setTarget(row);
    }
    const row = held || target;
    const subjectFrame = row && screenFrame(row);
    const point = subjectFrame?.body, projected = subjectFrame?.projected;
    const visible = projected && projected.z > 0 && projected.x >= 0 && projected.x <= innerWidth && projected.y >= 0 && projected.y <= innerHeight && (held || visibleMarkers.some(item => item.key === row?.key));
    const distance = point ? reachDistance(row) : Infinity;
    targetReachable = Boolean(target && inspectionReach(distance, targetReachable));
    corners.frame(now);
    corners.reticle.hidden = !panel.hidden;
    corners.reticle.dataset.state = target ? targetReachable ? 'ready' : 'far' : 'empty';
    root.dataset.reachable = String(targetReachable);
    root.dataset.focusDistance = Number.isFinite(distance) ? distance.toFixed(2) : '';
    if (visible) {
      const label = targetLabel(row);
      $('.cw-inspect').setAttribute('aria-label', 'Inspect ' + label);
      {
        if (panel.hidden) prompt.hidden = !targetReachable || Boolean(dragging);
        if (panel.hidden && targetReachable) {
          const presentation = promptPresentation(distance);
          prompt.style.setProperty('--cw-inspect-height', presentation.height + 'px');
          prompt.style.setProperty('--cw-inspect-key', presentation.key + 'px');
          prompt.style.setProperty('--cw-inspect-font', presentation.font + 'px');
          prompt.style.opacity = String(presentation.opacity);
        }
        const surface = panel.hidden ? prompt : panel;
        const { width, height } = surfaceSizes.get(surface) || { width: panel.hidden ? 132 : 330, height: panel.hidden ? 52 : 420 };
        let offset = 38;
        if (row.scene.type === 'being') {
          const top = point.clone(), ground = point.clone();
          if (b.authoredSociety.anchorOf(row.scene.id, top) && b.authoredSociety.groundOf(row.scene.id, ground)) {
            const topScreen = b.camera.camera.worldToScreen(top), groundScreen = b.camera.camera.worldToScreen(ground);
            offset = Math.max(38, Math.min(180, Math.abs(topScreen.y - groundScreen.y) * .5 + 16));
          }
        }
        const right = projected.x + offset;
        const left = right + width <= innerWidth - 16 ? right : projected.x - offset - width;
        const x = Math.max(16, Math.min(innerWidth - width - 16, left)), y = Math.max(16, Math.min(innerHeight - height - 16, projected.y - (panel.hidden ? height / 2 : 32)));
        const transform = `translate3d(${x.toFixed(1)}px,${y.toFixed(1)}px,0)`;
        if (surface.style.transform !== transform) surface.style.transform = transform;
        surface.dataset.side = left === right ? 'right' : 'left';
      }
    } else prompt.hidden = true;
    overlayCosts.push(performance.now() - workStart); if (overlayCosts.length > 120) overlayCosts.shift();
    if (now - lastMeasure >= 1000) {
      lastMeasure = now;
      const stats = values => { const sorted = [...values].sort((a,b) => a-b); return { samples: values.length, meanMs: +(values.reduce((sum, value) => sum + value, 0) / Math.max(1, values.length)).toFixed(3), p95Ms: +(sorted[Math.floor((sorted.length - 1) * .95)] || 0).toFixed(3) }; };
      root.dataset.overlayCost = JSON.stringify({ frame: stats(overlayCosts), discovery: stats(discoveryCosts) });
    }
    frameId = requestAnimationFrame(frame);
  }
  disposePrior = () => {
    stopFollowing();
    disposeFrameMeasurement();
    build?.dispose();
    corners.dispose();
    entitySheet?.dispose(); entitySheet = null;
    lifetime.abort(); sizeObserver.disconnect(); cancelAnimationFrame(frameId); ++serial; root.remove(); canvas.inert = false;
    b.controls.onPointerPick = priorCallbacks.pick; b.controls.onInteract = priorCallbacks.interact;
    b.controls.onSummon = priorCallbacks.summon; b.controls.onCameraToggle = priorCallbacks.camera; b.controls.onFlyChange = priorCallbacks.fly;
    b.setFreeCursorActive(false); b.setControlsEnabled(true);
  };
  try { await refreshInventory(); } catch (error) { notice(error.message); }
  canvas.focus({ preventScroll: true }); frameId = requestAnimationFrame(frame);
}
