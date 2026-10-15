import { pointerRay } from '../../../web/packages/atlas-react/src/playcanvas/index.ts';
import { buildInventoryRows, inventoryDetailPath, rowForSceneSelection } from './inventory-records.ts';
import { assertSelectedOffer } from './entity-inspection.mjs';
import { mountBuildMode } from './build-mode.ts';
import { mountFrameMeasurement } from './frame-measurement.mjs';
import { inspectionReach } from './discovery-policy.mjs';
import { createReadBackoff } from './read-backoff.mjs';
import { keepWorldInAddress, returnToFrontDoor } from './front-door.ts';
import { keepWorldPicture } from '/src/composition/world-pictures.ts';
import { SocietyClient } from '/src/society-api.ts';
import { SocietyModelsClient } from '/src/society-models-api.ts';
import { characterFacts, mountCharacterPresence } from './character-presence.ts';
import { PAGE_FRAMING, PERSON_RING_METRES, chosenCard, chosenDecision, didRows, doingLine, easePose, pageFraming, ringRadii, runQuestion, subjectWho, tagWords } from './character-view.mjs';
import { CHARACTER_WORDS, called, goneNote, lastRunLine, modelRefusalWords, orderedModels, outOfViewNote, pageSub, rowSub } from './character-words.mjs';
import { openCharacterPage } from './character-page.ts';
import { mountHistory } from './history.ts';
import { mountRunWatch } from './run-watch.ts';
import { runLength, runRefusalWords, runningLine, whoDecides } from './run-words.mjs';
import { recordEntityModel } from './entity-model-actions.mjs';
import { assignmentSubject } from './entity-properties.mjs';
import { worldTime } from './world-clock.mjs';
import { SocietyControlClient } from '/src/society-control-api.ts';
import { pop } from './world-ui-character.ts';
import { fetchThingCardRoute, writeThingCharacter } from '/src/thing-card-route-api.ts';
import { personalityBody, personalityRefusalWords, savedNote } from './personality-words.mjs';
import { placedLine } from './build-words.mjs';
import { areaBanner, keyWord, mountUiScale } from './world-ui.ts';
import { mountCorners } from './world-corners.ts';
import { endOpening } from './world-opening.ts';
import { populationLine } from './opening-steps.mjs';
import { OFFLINE_AFTER_FAILED_READS } from './world-ui-layout.mjs';
import { worldKey, wakesHints } from './world-keys.mjs';
import { CORNER_WORDS, NOTE_WORDS, availableHints } from './world-words.mjs';
import { openDecisionPage } from './decision-page.ts';
import { DECISION_WORDS, askedAt, choiceRows, choicesLabel, decisionTitle, overLabel, resultLines, toldLabel, toldSections } from './decision-words.mjs';
import { ASK_ASPECTS, askEntityCompanion, askWords } from './entity-companion.mjs';
import { choiceAccount, parseDecisionEvents } from '/src/decision-record.ts';
import { CompanionAskClient } from '/src/companion-ask-api.ts';
import { drawSimulated } from '/src/companion-simulated.ts';
import './blank-world.css';
import './contextual-world.css';

let disposePrior = () => {};

/** Where the side card centres between the head and the feet, as frame 05 places it. */
const CARD_WAIST = 0.8;
/** A person's half width as a share of the ring's radius on screen (the ring is 0.44 m). */
const BODY_HALF_WIDTH = 0.4;
/** The most pages of the society's events a character's page reads back for its rows. */
const DID_PAGES = 4;
/** How often the reads behind a tag or card are refreshed while one shows, in milliseconds. */
const SUBJECT_READ_MS = Object.freeze({ society: 3000, models: 5000 });

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
    // A page or following moves the camera for a while; the view kept is the one before either.
    const kept = pageView?.before || following;
    const pose = kept?.pose || b.controls.state, hold = kept?.hold || b.controls.hold;
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
  const root = document.createElement('div'); root.id = 'contextual-world';
  root.dataset.revision = 'center-aim-proximity-v6';
  root.className = 'wu-root';
  document.body.append(root);
  mountUiScale(root, lifetime.signal);
  // Beside a character or thing (character-presence.ts): the name tag, ring and cards.
  const beside = document.createElement('div'); beside.className = 'cw-beside'; root.prepend(beside);
  root.dataset.navigation = JSON.stringify({ ground: b.worldKind.ground.form, centre: b.navigationWorld.centre,
    fieldRadius: b.navigationWorld.fieldRadius, blockers: b.navigationWorld.polygonObstacles });
  const disposeFrameMeasurement = mountFrameMeasurement(b, root);
  const $ = (selector) => root.querySelector(selector);
  // A character's page (character-page.ts) while one is open, with what it shows and the camera's pose before it.
  let pageView = null;
  // A page that is not a character's (History) while one is open: it takes the keys (`key(event)`)
  // until it closes (`close()`, or `dispose()` with the world). Either page hides the corners and
  // holds the world still.
  let otherPage = null;
  const pageShown = () => pageView !== null || otherPage !== null;
  // Your worlds: back to the front door with this world chosen, after keeping a picture of it for
  // its card, as the app does when a person leaves a world.
  let leaving = false;
  const leaveWorld = () => {
    if (leaving) return;
    leaving = true;
    void keepWorldPicture(b, entry.entryId).catch(() => false).finally(() => returnToFrontDoor(entry.entryId));
  };
  // The corners (world-corners.ts): the way out (or Back while something is chosen), the clock with
  // Play and Pause, the hints for what works here, the reticle and the note.
  // A read-only copy dims what needs the server (Play and Pause), as the offline state does.
  const corners = mountCorners({ host: root, people: selection.people ?? null, onLeave: () => { if (held) release(); else leaveWorld(); },
    readOnly: import.meta.env.VITE_EXULANICA_REVIEW_OBSERVER_ONLY === '1', flySpeed: () => b.controls.flyingSpeed });
  const guidance = corners.hintsRoot, worlds = corners.backRoot, worldNotes = corners.notes;
  let rows = [], inventory = null, target = null, held = null;
  let dragging = null, serial = 0, lastPick = 0, frameId = 0;
  const offers = new Map(), offerReads = new Map(), offerSerials = new Map();
  // Automatic reads of a subject whose read failed wait longer each time (read-backoff.mjs).
  const readBackoff = createReadBackoff();
  let targetReachable = false;
  let following = null;
  let lastMeasure = 0;
  const overlayCosts = [];
  const priorCallbacks = { pick: b.controls.onPointerPick, interact: b.controls.onInteract, summon: b.controls.onSummon, camera: b.controls.onCameraToggle, fly: b.controls.onFlyChange };
  b.controls.onPointerPick = null;
  b.controls.onInteract = null;
  b.controls.onSummon = null;
  b.controls.onCameraToggle = null;
  // Flying (F): the mode word at the top with its key, and the hints for flying while it lasts.
  // History opens in every world, a read-only copy's too: it only reads (history.ts). One flag for
  // its hint and its key, so the two never disagree.
  const historyHere = true;
  const worldHints = () => corners.worldHints(availableHints({ flying: Boolean(b.controls.flying), build: Boolean(build), history: historyHere }));
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
    ? mountBuildMode({ b, root, state, entry, read, send, binding, canvas, guidance, worlds, corners, inspecting: () => pageShown() || held !== null }) : null;
  worldHints();
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
  // What the tag and card say of a character: the society (what they are doing), the models read
  // (each character's model and newest decision) and, once chosen, how many choices that decision
  // offered. Each read is refreshed only while a tag or card shows, and never more often than
  // SUBJECT_READ_MS; a failed read keeps what was last read.
  const credentials = { ...state.credentials, worldId: entry.worldId };
  const societyClient = new SocietyClient(credentials), modelsClient = new SocietyModelsClient(credentials);
  const subjectReads = { society: null, models: null, societyAt: -Infinity, modelsAt: -Infinity, pending: new Set(), options: new Map() };
  function refreshSubjectReads(now) {
    const fetchOne = (name, at, run) => {
      if (subjectReads.pending.has(name) || now - subjectReads[at] < SUBJECT_READ_MS[name]) return;
      subjectReads.pending.add(name); subjectReads[at] = now;
      run().then(value => { if (!lifetime.signal.aborted && current()) subjectReads[name] = value; }, () => {})
        .finally(() => subjectReads.pending.delete(name));
    };
    fetchOne('society', 'societyAt', () => societyClient.read(entry.authoredVersionId, { places: true }));
    fetchOne('models', 'modelsAt', () => modelsClient.read(entry.authoredVersionId));
  }
  // A decision whose read failed is asked again after this long, not on every redraw.
  const OPTIONS_RETRY_MS = 30000;
  function decisionOptions(requestId) {
    if (!requestId) return null;
    if (subjectReads.options.has(requestId)) return subjectReads.options.get(requestId);
    subjectReads.options.set(requestId, null);
    modelsClient.readDecision(entry.authoredVersionId, requestId).then(data => {
      const options = data?.request?.context?.options;
      if (Array.isArray(options)) subjectReads.options.set(requestId, options.length);
      if (pageView) drawPage();
    }, () => { setTimeout(() => subjectReads.options.delete(requestId), OPTIONS_RETRY_MS); });
    return null;
  }
  /** Everything the tag and card say of a subject, from the reads held now. */
  function subjectView(row) {
    const offer = offers.get(row.key)?.offer ?? null;
    const being = row.scene.type === 'being';
    if (!being) return { being, who: subjectWho(row, offer), offer, reading: !offers.has(row.key), thingLine: placedLine() };
    const choice = subjectReads.models?.choices.find(item => item.subjectId === row.scene.id) ?? null;
    const facts = characterFacts(subjectReads.society, row.scene.id, choice?.played !== undefined);
    const who = subjectWho(row, offer, facts?.kind ?? null);
    const latest = subjectReads.models?.latest.find(item => item.subjectId === row.scene.id) ?? null;
    const decision = facts ? chosenDecision({ person: facts.person, latest, living: facts.living, startMinute: facts.startMinute,
      options: latest?.requestId && held?.key === row.key ? decisionOptions(latest.requestId) : null }) : null;
    return { being, who, offer, facts, decision, model: choice?.model?.name ?? null,
      doing: facts ? doingLine(facts.doing) : null, reading: !offers.has(row.key) || !facts || !subjectReads.models };
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
      // The head is the feet plus the height the figure stands (spec 5.3: the bounds' top); the body
      // point sits at half that height. The renderer's own mark anchor hangs a clearance above it.
      const height = b.authoredSociety?.heightOf?.(row.scene.id);
      if (!b.authoredSociety?.groundOf(row.scene.id, point) || !Number.isFinite(height)) return null;
      point.y += overhead ? height : height / 2;
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
    if (!ground) { stopFollowing(); worldNotes.show(outOfViewNote(subjectView(held).who)); return; }
    const delta = ground.clone().sub(following.ground);
    if (delta.lengthSq() > 0) {
      const pose = b.controls.state;
      b.controls.setView({ ...pose, x: pose.x + delta.x, y: pose.y + delta.y, z: pose.z + delta.z }, 'altitude');
      b.invalidate();
    }
    following.ground.copy(ground);
  }
  function screenFrame(row) {
    const body = targetPoint(row), head = targetPoint(row, true);
    if (!body || !head) return null;
    const centre = b.camera.camera.worldToScreen(body), overhead = b.camera.camera.worldToScreen(head);
    const points = [centre, overhead];
    let ground = null;
    if (row.scene.type === 'being') {
      ground = body.clone();
      if (!b.authoredSociety.groundOf(row.scene.id, ground)) return null;
      points.push(b.camera.camera.worldToScreen(ground));
    } else {
      const subject = b.representationReport.subjects.find(item => item.subject.subjectId === row.scene.id)?.subject;
      const bounds = subject && b.representationBounds(subject);
      if (!bounds?.length) return null;
      points.push(...bounds.map(value => b.camera.camera.worldToScreen(body.clone().set(...value))));
      ground = body.clone().set(body.x, Math.min(...bounds.map(value => value[1])), body.z);
    }
    const front = points.filter(value => value.z > 0 && Number.isFinite(value.x) && Number.isFinite(value.y));
    if (!front.length) return null;
    const left = Math.min(...front.map(point => point.x)), right = Math.max(...front.map(point => point.x));
    const top = Math.min(...front.map(point => point.y)), bottom = Math.max(...front.map(point => point.y));
    if (right < 0 || left > innerWidth || bottom < 0 || top > innerHeight) return null;
    const headInView = overhead.z > 0 && overhead.x >= 0 && overhead.x <= innerWidth && overhead.y >= 0 && overhead.y <= innerHeight;
    return { body, ground, centre, overhead, headInView, left, right, top, bottom, extent: Math.max(right - left, bottom - top) };
  }
  /** The ring under a subject: a person's footprint around its ground point, projected. */
  function ringAt(frame) {
    const ground = frame.ground, eye = b.camera.getPosition();
    const forward = ground.clone().sub(eye); forward.y = 0;
    if (forward.lengthSq() < 1e-6) return null;
    forward.normalize();
    const side = forward.clone().set(-forward.z, 0, forward.x);
    const at = b.camera.camera.worldToScreen(ground);
    const right = b.camera.camera.worldToScreen(ground.clone().add(side.clone().mulScalar(PERSON_RING_METRES)));
    const ahead = b.camera.camera.worldToScreen(ground.clone().add(forward.clone().mulScalar(PERSON_RING_METRES)));
    if (!(at.z > 0)) return null;
    return { x: at.x, y: at.y, ...ringRadii(at, right, ahead) };
  }
  function seen(row, frame) {
    if (!frame || (frame.extent < 2 && row.key !== held?.key)) return false;
    return !state.worldSight || state.worldSight.sees(b.camera.getPosition(), frame.body);
  }
  function setTarget(row) {
    const changed = target?.key !== row?.key;
    if (changed) targetReachable = false;
    target = row;
    root.dataset.target = row?.key || '';
    if (row && changed && readBackoff.ready(row.key, performance.now())) void entityOffer(row).catch(() => {});
  }
  const presence = mountCharacterPresence(beside, {
    onInspect: () => { void choose(); },
    onAction: (action) => questionAct(action),
  });
  /** Chooses the subject at the reticle (E): its ring and card; the world keeps moving. */
  async function choose(row = target) {
    if (!row || pageShown()) return;
    if (!inspectionReach(reachDistance(row), row.key === target?.key && targetReachable)) return;
    if (held?.key !== row.key) stopFollowing();
    held = row;
    root.dataset.held = row.key;
    worldNotes.clear();
    const request = ++serial;
    try {
      await refreshInventory();
      const refreshed = rows.find(item => item.key === row.key);
      if (request !== serial || lifetime.signal.aborted) return;
      if (!refreshed) { release(); worldNotes.show(goneNote(subjectView(row).who)); return; }
      held = refreshed;
      await entityOffer(refreshed, true);
    } catch { /* The card keeps what it last read; the next read tries again. */ }
  }
  function release() {
    stopFollowing();
    ++serial; held = null; root.dataset.held = '';
    presence.choose(null);
  }
  // A run (run-watch.ts): the strip, Stop, the ended note and the pops over characters whose model acted.
  const readOnly = import.meta.env.VITE_EXULANICA_REVIEW_OBSERVER_ONLY === '1';
  const pops = new Map();
  const modelName = (model) => subjectReads.models?.models.find(item => item.provider === model?.provider && item.modelId === (model?.model_id ?? model?.modelId))?.name ?? null;
  const eventsPath = (kinds, extra = '') => '/world/versions/' + encodeURIComponent(entry.authoredVersionId) + '/society/events?world_id=' + encodeURIComponent(entry.worldId)
    + kinds.map(kind => '&kinds=' + kind).join('') + extra;
  const runWatch = mountRunWatch({ host: root, notes: worldNotes, entry, credentials, isCurrent: current, readOnly,
    acts: async (fromTick) => {
      const page = await read(eventsPath(['said', 'decision_applied'], '&from_tick=' + fromTick + '&limit=256'));
      const said = new Set(page.events.filter(event => event.event_kind === 'said').map(event => event.document?.thing?.request_id));
      return page.events.flatMap(event => {
        const document = event.document || {};
        if (event.event_kind === 'said' && document.thing?.model && typeof document.thing.line === 'string') return [{ subjectId: event.subject_id, words: '“' + document.thing.line + '”', said: true }];
        if (event.event_kind === 'decision_applied' && document.model && !said.has(document.request_id) && typeof document.chose === 'string') return [{ subjectId: event.subject_id, words: document.chose.charAt(0).toUpperCase() + document.chose.slice(1), said: false }];
        return [];
      });
    },
    onAct: (act) => {
      let made = pops.get(act.subjectId);
      if (!made) { made = pop({ scale: () => Number.parseFloat(root.style.getPropertyValue('--ui-scale')) || 1 }); beside.append(made.root); pops.set(act.subjectId, made); }
      made.show(act.words, { said: act.said });
    },
    onChange: () => { if (pageView) drawPage(); },
  });
  void runWatch.refresh();
  /** The models read's choice for a character, and whether its model can be asked here. */
  function modelOf(row) {
    const choice = subjectReads.models?.choices.find(item => item.subjectId === row?.scene.id) ?? null;
    const connected = Boolean(subjectReads.models && !subjectReads.models.hostRefusal && !choice?.refusal);
    return { choice, model: choice?.model ?? null, connected };
  }
  // The question before a run (frame 08), while it is asked.
  let asking = null;
  function askRun() {
    const { model, connected } = modelOf(held);
    if (!held || held.scene.type !== 'being' || readOnly) return;
    if (runWatch.run) { void stopNow(); return; }
    if (!model || !connected) return;
    asking = { refusal: null, busy: false, shown: runWatch.limits(subjectReads.models) };
    drawQuestion();
  }
  function drawQuestion() {
    if (!asking || !held) { presence.ask(null); return; }
    const view = subjectView(held);
    presence.ask(runQuestion({ who: view.who, model: view.model, limits: asking.shown, refusal: asking.refusal, busy: asking.busy }));
  }
  async function startNow(showing) {
    const { model } = modelOf(held);
    if (!held || !model || showing.busy) return;
    showing.busy = true; showing.refusal = null; drawQuestion(); if (pageView) drawPage();
    const code = await runWatch.start({ subjectId: held.scene.id, expectedModel: model, shown: showing.shown, modelsClient, refresh: () => refreshSubject(held) });
    showing.busy = false; showing.refusal = code;
    // A refused start shows the limits a second press asks under, so "Press Run again" can work.
    if (code !== null) showing.shown = runWatch.limits(subjectReads.models);
    if (code === null && showing === asking) asking = null;
    drawQuestion(); if (pageView) drawPage();
  }
  async function stopNow() {
    const code = await runWatch.stop();
    if (code && pageView) { pageView.run.refusal = code; drawPage(); }
  }
  async function pauseNow() {
    const controlClient = new SocietyControlClient(credentials);
    try { const control = await controlClient.read(entry.authoredVersionId); await controlClient.configure(control, 'paused', control.speed); } catch { /* The card keeps its refusal. */ }
    if (asking) { asking.refusal = null; asking.shown = runWatch.limits(subjectReads.models); drawQuestion(); }
    await runWatch.refresh();
  }
  /** A fresh read of a character, its inventory row and offer, for a write that names it. */
  async function refreshSubject(row) {
    await refreshInventory();
    const fresh = rows.find(item => item.key === row.key);
    if (!fresh) throw Object.assign(Error('gone'), { code: 'person_not_in_this_world' });
    return { row: fresh, inventory, offer: await entityOffer(fresh, true) };
  }
  function act(action) {
    if (!held) return;
    if (action === 'details') void openPage(held);
    else if (action === 'follow' && held.scene.type === 'being') followView.toggle();
    else if (action === 'run') askRun();
    else if (action === 'stop') void stopNow();
    else if (action === 'pause') void pauseNow();
    else if (action === 'back') { asking = null; drawQuestion(); }
  }
  // The question card's answers come back through act as well.
  const questionAct = (action) => { if (action === 'run' && asking) void startNow(asking); else act(action); };
  /** What the character's page shows now. */
  function pageState() {
    const view = subjectView(pageView.row);
    const { choice, model, connected } = modelOf(pageView.row);
    const served = subjectReads.models?.models.find(item => item.provider === model?.provider && item.modelId === model?.modelId) ?? null;
    const run = runWatch.run, limits = runWatch.limits(subjectReads.models);
    const closed = runWatch.control?.livingSession;
    const start = view.facts?.startMinute;
    const from = closed?.state === 'closed' && closed.endTick !== null ? worldTime(closed.startTick, start ?? -1) : null;
    const to = from ? worldTime(closed.endTick, start) : null;
    const lastRun = from && to ? lastRunLine({ from: from.hhmm, to: to.hhmm, decisions: closed.used.decisions, spent: closed.used.usd }) : null;
    const choices = pageView.choosing && subjectReads.models
      ? [...orderedModels(subjectReads.models.models).map(item => ({ model: item, current: Boolean(model && item.provider === model.provider && item.modelId === model.modelId) })), { model: null, current: !model }]
      : null;
    const offer = offers.get(pageView.row.key)?.offer;
    const assignable = !readOnly && Boolean(inventory && offers.has(pageView.row.key) && subjectReads.models?.takesModelChoices && assignmentSubject(inventory, pageView.row, offer ?? null));
    return {
      who: view.who, sub: pageSub(view.who.named ? view.facts?.kind ?? null : null, entry.title), assignable,
      model: subjectReads.models ? (model ? { name: model.name, price: served?.price ?? null, local: served?.local === true } : null) : undefined,
      connected,
      run: { open: Boolean(run), big: run ? runningLine(run, Date.now()) : runLength(limits), small: whoDecides(view.who), busy: pageView.run.busy, refusal: pageView.run.refusal ? runRefusalWords(pageView.run.refusal) : null },
      // A row's choices are counted as each decision is read, so its sub-line is worded as the page draws.
      did: pageView.did ? pageView.did.map(row => ({ time: row.time, what: row.what, sub: row.model ? rowSub({ model: row.model, options: decisionOptions(row.requestId) }) : row.sub, decision: Boolean(row.requestId) })) : null,
      didFocus: pageView.didFocus, lastRun, canAsk: !readOnly,
      ask: pageView.ask ? { questions: ASK_ASPECTS.map(aspect => askWords(aspect, view.who)), focus: pageView.ask.focus, busy: pageView.ask.busy,
        asked: pageView.ask.asked, answer: pageView.ask.answer, failure: pageView.ask.failure } : null,
      personality: pageView.personality ? { character: pageView.personality.character, shown: pageView.personality.shown } : null,
      editing: pageView.editing ? { session: pageView.editing.session, refusal: pageView.editing.refusal, busy: pageView.editing.busy } : null,
      choosing: pageView.choosing ? { choices, focus: pageView.choosing.focus, refusal: pageView.choosing.refusal, busy: pageView.choosing.busy } : null,
    };
  }
  function drawPage() { if (pageView) { pageView.page.draw(pageState()); if (pageView.decision) pageView.decision.page.draw(decisionState()); } }
  /** The page's rows: the character's recorded events, read when the page opens and every few seconds. */
  async function readDid() {
    const showing = pageView;
    if (!showing) return;
    try {
      // The events read serves the whole society, newest first, a page at a time: read back until
      // the character's newest rows are found or DID_PAGES pages are read.
      const events = [];
      let before = '';
      for (let pageNumber = 0; pageNumber < DID_PAGES; pageNumber += 1) {
        const page = await read(eventsPath(['goal_selected', 'decision_applied', 'said'], '&limit=256' + (before ? '&before=' + encodeURIComponent(before) : '')));
        events.push(...page.events);
        if (!page.next || events.filter(event => event.subject_id === showing.row.scene.id).length >= 7 || showing !== pageView) break;
        before = page.next;
      }
      const facts = characterFacts(subjectReads.society, showing.row.scene.id);
      if (showing !== pageView) return;
      showing.events = events;
      showing.did = didRows({ events, subjectId: showing.row.scene.id, startMinute: facts?.startMinute ?? null, modelName,
        options: (requestId) => decisionOptions(requestId),
        wordGoal: (document) => {
          if (!facts) return null;
          const shown = { ...subjectReads.society, state: { ...subjectReads.society.state, inhabitants: subjectReads.society.state.inhabitants.map(person => person.id === showing.row.scene.id ? { ...person, goal: document.goal ?? null, action: document.action ?? person.action } : person) } };
          return doingLine(characterFacts(shown, showing.row.scene.id)?.doing ?? null);
        } });
      // The chosen row stays where it was; at first it is the newest row a decision stands behind.
      if (showing.didFocus === null || showing.didFocus >= showing.did.length) {
        const first = showing.did.findIndex(row => row.requestId);
        showing.didFocus = first >= 0 ? first : showing.did.length ? 0 : null;
      }
      drawPage();
    } catch { if (showing === pageView && showing.did === null) { showing.did = []; drawPage(); } }
  }
  function pageAct(action, index) {
    if (!pageView) return;
    const choosing = pageView.choosing, editing = pageView.editing;
    if (action === 'back') { if (editing) { pageView.editing = null; drawPage(); } else if (choosing) { pageView.choosing = null; drawPage(); } else if (pageView.ask) { pageView.ask = null; drawPage(); } else closePage(); }
    else if (action === 'row' && pageView.did?.[index]) { pageView.didFocus = index; drawPage(); }
    else if (action === 'inspect' && !choosing && !pageView.ask) void openDecision(index ?? pageView.didFocus);
    else if (action === 'ask' && !readOnly && !choosing) { pageView.ask = { focus: 0, busy: false, asked: null, answer: null, failure: null, serial: 0 }; drawPage(); }
    else if (action === 'question' && pageView.ask) void askQuestion(index ?? pageView.ask.focus);
    else if (action === 'personality' && pageView.personality && pageView.placedId && !readOnly && !choosing) {
      const written = pageView.personality.character;
      pageView.editing = { session: crypto.randomUUID(), name: written?.name ?? '', about: written?.about ?? '', refusal: null, busy: false };
      drawPage();
    }
    else if (action === 'draft' && editing) { editing.name = index?.name ?? ''; editing.about = index?.about ?? ''; }
    else if (action === 'save' && editing) void savePersonality();
    else if (action === 'model' && pageState().assignable) {
      const current = orderedModels(subjectReads.models?.models ?? []).findIndex(item => item.provider === modelOf(pageView.row).model?.provider && item.modelId === modelOf(pageView.row).model?.modelId);
      pageView.choosing = { focus: current < 0 ? (subjectReads.models?.models.length ?? 0) : current, refusal: null, busy: false, key: crypto.randomUUID() };
      drawPage();
    }
    else if (action === 'choose' && choosing) { choosing.focus = index; choosing.refusal = null; drawPage(); }
    else if (action === 'use' && choosing) void useModel(index ?? choosing.focus);
    else if (action === 'run' && !readOnly) void startNow(pageView.run);
    else if (action === 'stop') void stopNow();
  }
  /** The personality a person wrote for a being they placed, from its card: its words, revision and whether its model reads it. */
  async function readPersonality(showing) {
    try {
      const card = await fetchThingCardRoute(state.credentials, entry.worldId, entry.authoredVersionId, showing.row.scene.id);
      if (showing !== pageView) return;
      showing.personality = card?.character ?? null;
      drawPage();
    } catch { /* Without its card, the page shows no Personality section. */ }
  }
  /** Writes the personality against the revision its card was read at (an emptied pair clears it). */
  async function savePersonality() {
    const showing = pageView, editing = showing?.editing;
    if (!editing || editing.busy || !showing.personality || !showing.placedId) return;
    editing.busy = true; editing.refusal = null; drawPage();
    try {
      const outcome = await writeThingCharacter(state.credentials, entry.worldId, entry.authoredVersionId, showing.placedId, showing.personality.revision, personalityBody(editing.name, editing.about));
      if (showing !== pageView) return;
      if (outcome.written) {
        showing.personality = { ...showing.personality, revision: outcome.revision, character: outcome.character };
        showing.editing = null;
        if (showing.personality.shown) worldNotes.show(savedNote(subjectView(showing.row).who));
      } else {
        editing.refusal = personalityRefusalWords(outcome.code);
        if (outcome.code === 'character_changed') void readPersonality(showing);
      }
    } catch { editing.refusal = personalityRefusalWords(null); }
    finally { editing.busy = false; drawPage(); }
  }
  async function useModel(index) {
    const showing = pageView, choosing = showing?.choosing;
    if (!choosing || choosing.busy || !subjectReads.models) return;
    const list = orderedModels(subjectReads.models.models);
    const picked = index < list.length ? list[index] : null;
    choosing.busy = true; choosing.refusal = null; drawPage();
    try {
      const { verified } = await recordEntityModel({ entry, subjectId: showing.row.scene.id, selected: picked, key: choosing.key, refresh: () => refreshSubject(showing.row), client: modelsClient, current: () => showing === pageView && current() });
      subjectReads.models = verified;
      // A new model changes who decides in a run, so the run the page offers is read again.
      if (showing === pageView) { showing.choosing = null; showing.run.shown = runWatch.limits(verified); showing.run.refusal = null; }
    } catch (error) {
      choosing.refusal = modelRefusalWords(error.code ?? 'stale', subjectView(showing.row).who);
      choosing.key = crypto.randomUUID();
    } finally { choosing.busy = false; drawPage(); }
  }
  // Ask (8.6): the Companion's three questions, answered from this world's records alone.
  const companionClient = new CompanionAskClient(credentials);
  const personName = (id) => subjectReads.society?.state?.inhabitants?.find(person => person.id === id)?.display_name ?? selection.societyNames?.()?.people.get(id) ?? null;
  async function askQuestion(index) {
    const showing = pageView, ask = showing?.ask, aspect = ASK_ASPECTS[index];
    if (!ask || ask.busy || !aspect) return;
    const serial = ++ask.serial, who = subjectView(showing.row).who;
    Object.assign(ask, { focus: index, busy: true, asked: null, answer: null, failure: null });
    drawPage();
    const still = () => showing === pageView && showing.ask === ask && ask.serial === serial;
    try {
      const { answer } = await askEntityCompanion({ aspect, entry, row: showing.row, client: companionClient, current: () => still() && current(),
        refresh: async () => {
          await refreshInventory();
          const fresh = rows.find(item => item.key === showing.row.key);
          if (!fresh) throw Object.assign(Error(goneNote(who)), { plain: true });
          return { row: fresh, inventory, offer: await entityOffer(fresh, true) };
        } });
      if (!still()) return;
      // The answer names people and places by placeholder; they are drawn by this world's names.
      const known = selection.societyNames?.();
      const names = known?.versionId === entry.authoredVersionId ? { ...known, people: new Map(known.people) } : { versionId: entry.authoredVersionId, people: new Map(), spots: new Map() };
      names.people.set(showing.row.scene.id, who.title);
      const drawn = text => drawSimulated([{ kind: 'text', text }], answer, names).map(piece => piece.text).join('');
      ask.asked = askWords(aspect, who);
      ask.answer = answer.clauses.map(clause => ({ text: drawn(clause.text), note: clause.type === 'meta' }));
    } catch (error) {
      if (still()) ask.failure = error?.plain ? error.message : CHARACTER_WORDS.askFailed;
    } finally { if (still()) { ask.busy = false; drawPage(); } }
  }
  // A decision (frame 10): one recorded decision behind a row of What Teo did, over the page.
  async function openDecision(index) {
    const showing = pageView;
    if (!showing?.did || index === null || index === undefined || !showing.did[index]?.requestId) return;
    showing.didFocus = index;
    const page = showing.decision?.page ?? openDecisionPage(root, action => decisionAct(action));
    const decision = { page, rowIndex: index, requestId: showing.did[index].requestId, detail: null, failure: null, record: false };
    showing.decision = decision;
    showing.page.hide(true);
    drawPage();
    try {
      const detail = await modelsClient.readDecision(entry.authoredVersionId, decision.requestId);
      if (showing.decision === decision) decision.detail = detail;
    } catch { if (showing.decision === decision) decision.failure = DECISION_WORDS.unread; }
    if (showing === pageView) drawPage();
  }
  function closeDecision() {
    const showing = pageView;
    if (!showing?.decision) return;
    showing.decision.page.close(); showing.decision = null;
    showing.page.hide(false); drawPage();
  }
  /** The rows a decision stands behind, newest first, as indexes into What Teo did. */
  const decisionRows = (showing) => (showing.did ?? []).flatMap((row, at) => row.requestId ? [at] : []);
  function decisionAct(action) {
    const decision = pageView?.decision;
    if (!decision) return;
    if (action === 'back') { if (decision.record) { decision.record = false; drawPage(); } else closeDecision(); }
    else if (action === 'record' && decision.detail) { decision.record = !decision.record; drawPage(); }
    else if (action === 'earlier' || action === 'later') {
      const order = decisionRows(pageView), here = order.indexOf(decision.rowIndex);
      const next = here < 0 ? undefined : order[here + (action === 'earlier' ? 1 : -1)];
      if (next !== undefined) void openDecision(next);
    }
  }
  function decisionState() {
    const showing = pageView, decision = showing.decision, view = subjectView(showing.row), who = view.who;
    const order = decisionRows(showing), here = order.indexOf(decision.rowIndex);
    const blank = { over: '', title: '', model: null, done: null, verdict: null, toldLabel: toldLabel(who), told: decision.failure ? [] : null,
      choicesLabel: '', choices: [], earlier: here >= 0 && here < order.length - 1, later: here > 0, record: null, failure: decision.failure };
    const detail = decision.detail;
    if (!detail) return blank;
    const request = detail.request, receipt = detail.decision, context = request.context ?? null;
    const events = parseDecisionEvents({ events: showing.events ?? [] }).events;
    const latest = subjectReads.models?.latest.find(item => item.requestId === decision.requestId) ?? null;
    // The choice account's verdict; a record it cannot read says nothing of what came of it.
    let verdict = null;
    try { verdict = choiceAccount(detail, latest, events).verdict; } catch { verdict = null; }
    const consumed = events.find(event => event.kind === 'decision_applied' && event.requestId === decision.requestId)?.tick ?? latest?.consumedTick ?? null;
    const start = view.facts?.startMinute ?? null;
    const spoken = (showing.events ?? []).find(event => event.event_kind === 'said' && event.document?.thing?.request_id === decision.requestId);
    const proposal = receipt?.proposal ?? null, provider = receipt?.provider ?? null, config = request.provider_config ?? null;
    const choices = choiceRows(context, proposal?.label ?? null);
    const result = resultLines({ verdict, doneAt: consumed === null ? null : worldTime(consumed, start)?.hhmm ?? null,
      latencyMs: provider?.latency_ms ?? null, costUsd: provider?.cost_usd ?? null, costKnown: provider?.cost_known === true });
    return { ...blank,
      over: overLabel({ at: askedAt(request.base_tick, start), who, said: Boolean(spoken), to: spoken?.document?.thing?.to ? personName(spoken.document.thing.to) : null }),
      title: decisionTitle({ line: spoken ? spoken.document.thing.line : null, chose: proposal?.label ?? null }) || showing.did[decision.rowIndex]?.what || '',
      model: config ? modelName({ provider: config.provider, model_id: config.model_id }) ?? config.model_id ?? null : null,
      done: result.done, verdict: result.verdict, told: toldSections(context, who),
      choicesLabel: choicesLabel(who, choices.length), choices,
      record: decision.record ? JSON.stringify({ request, decision: receipt }, null, 2) : null };
  }
  /** The character's page (Enter): over the world, which keeps drawing, with the camera framing the character. */
  async function openPage(row) {
    if (!row || row.scene.type !== 'being' || pageShown()) return;
    asking = null; drawQuestion();
    stopFollowing();
    const page = openCharacterPage(root, (action, index) => pageAct(action, index));
    // Only a being its owner placed can have a personality: its inventory reference is the placed thing.
    const placedId = row.reference?.source === 'authored-thing' ? row.reference.id : null;
    pageView = { page, row, did: null, didFocus: null, events: [], ask: null, decision: null, choosing: null, personality: null, editing: null, placedId, run: { busy: false, refusal: null, shown: runWatch.limits(subjectReads.models) }, before: { pose: { ...b.controls.state }, hold: b.controls.hold }, ease: null };
    presence.setCovered(true); notice('');
    b.setControlsEnabled(false); b.setFreeCursorActive(true); canvas.inert = true;
    guidance.hidden = true; worlds.hidden = true;
    const ground = b.camera.getPosition().clone();
    if (b.authoredSociety?.groundOf(row.scene.id, ground)) {
      const eye = b.camera.getPosition();
      const to = pageFraming({ ground: { x: ground.x, y: ground.y, z: ground.z }, eye: { x: eye.x, z: eye.z }, fovDeg: b.camera.camera.fov, aspect: innerWidth / innerHeight });
      pageView.ease = { from: { ...b.controls.state }, to, at: performance.now(), ms: matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : PAGE_FRAMING.easeMs };
    }
    drawPage();
    void readDid();
    if (placedId) void readPersonality(pageView);
    void runWatch.refresh();
  }
  function closePage() {
    if (!pageView) return;
    const { page, before, decision } = pageView;
    pageView = null; page.close(); decision?.page.close();
    b.controls.setView(before.pose, before.hold); b.invalidate();
    canvas.inert = false; b.setFreeCursorActive(false); b.setControlsEnabled(current());
    guidance.hidden = false; worlds.hidden = false; presence.setCovered(false); canvas.focus({ preventScroll: true });
  }

  // History (H, from the world and from build mode): every change of this world version over the
  // dimmed world, read from the server alone. Undo and redo there are build mode's own.
  const history = mountHistory({
    root, worldId: entry.worldId, versionId: entry.authoredVersionId, title: entry.title, read,
    async names({ subjects, placed }) {
      if (!subjectReads.society) {
        subjectReads.society = await societyClient.read(entry.authoredVersionId, { places: true }).catch(() => null);
        subjectReads.societyAt = performance.now();
      }
      // One name per character (J20): as the tag and card call it, from its inventory offer: its name,
      // else "the" and its kind's label. Only the characters History's rows name are read; a
      // personality is kept by its placed being.
      const beings = new Map(rows.filter(row => row.scene?.type === 'being').map(row => [row.scene.id, row]));
      const placedBeings = new Map(rows.filter(row => row.scene?.type === 'being' && row.reference?.source === 'authored-thing').map(row => [row.reference.id, row]));
      const needed = new Set([...subjects.map(id => beings.get(id)), ...placed.map(id => placedBeings.get(id))].filter(Boolean));
      await Promise.all([...needed].map(row => entityOffer(row).catch(() => null)));
      const unlisted = (id) => called({ name: null, kind: characterFacts(subjectReads.society, id)?.kind ?? null }).within;
      return {
        subject: (id) => (beings.has(id) ? subjectView(beings.get(id)).who.within : unlisted(id)),
        placed: (placedId) => (placedBeings.has(placedId) ? subjectView(placedBeings.get(placedId)).who.within : called({ name: null, kind: null }).within),
      };
    },
    build: build ? { undo: () => build.undo(), redo: () => build.redo() } : null,
    worldTime(tick) {
      // The society's own first minute, as characterFacts reads it; with no society there is no clock (K5).
      const state = subjectReads.society?.state;
      return worldTime(tick, state?.start_minute_of_day ?? state?.clock?.start_minute_of_day ?? null)?.hhmm ?? null;
    },
    open: (url) => { window.open(url, '_blank', 'noopener'); },
    closed() {
      otherPage = null;
      canvas.inert = false; b.setFreeCursorActive(false); b.setControlsEnabled(current());
      guidance.hidden = false; worlds.hidden = false; presence.setCovered(false); canvas.focus({ preventScroll: true });
    },
  });
  function openHistory() {
    if (pageShown()) return;
    stopFollowing();
    otherPage = history;
    presence.setCovered(true); notice('');
    b.setControlsEnabled(false); b.setFreeCursorActive(true); canvas.inert = true;
    guidance.hidden = true; worlds.hidden = true;
    void history.open();
  }

  // Drag-to-look keeps the ordinary cursor and also works where pointer lock is unavailable.
  window.addEventListener('mousedown', event => {
    if (event.target !== canvas || pageShown() || ![0, 2].includes(event.button)) return;
    event.preventDefault(); event.stopImmediatePropagation(); canvas.focus({ preventScroll: true });
    if (build?.pointerDown(event)) return;
    dragging = { startX: event.clientX, startY: event.clientY, x: event.clientX, y: event.clientY, moved: false, button: event.button };
  }, { capture: true, signal: lifetime.signal });
  document.addEventListener('pointerlockchange', () => {
    if (document.pointerLockElement === canvas) document.exitPointerLock();
  }, { signal: lifetime.signal });
  if (document.pointerLockElement === canvas) document.exitPointerLock();
  document.addEventListener('mousemove', event => {
    if (!dragging || pageShown() || document.pointerLockElement) return;
    const dx = event.clientX - dragging.x, dy = event.clientY - dragging.y;
    dragging.x = event.clientX; dragging.y = event.clientY;
    dragging.moved ||= Math.hypot(event.clientX - dragging.startX, event.clientY - dragging.startY) > 4;
    if (!dragging.moved) return;
    b.controls.state.yaw -= dx * .0022;
    b.controls.state.pitch = Math.max(-Math.PI * .49, Math.min(Math.PI * .49, b.controls.state.pitch - dy * .0022));
    b.invalidate();
  }, { signal: lifetime.signal });
  document.addEventListener('mouseup', event => {
    if (!dragging) return;
    const press = dragging; dragging = null;
    root.dataset.gesture = JSON.stringify({ start: [press.startX, press.startY], end: [event.clientX, event.clientY], dragged: press.moved });
    rememberView();
    if (pageShown()) return;
    if (!press.moved && press.button === 0) build?.click(event.clientX, event.clientY);
    // The centre aim controls E. Canvas clicks do not select whatever lies under a spare cursor.
  }, { capture: true, signal: lifetime.signal });
  canvas.addEventListener('contextmenu', event => event.preventDefault(), { signal: lifetime.signal });
  window.addEventListener('blur', () => { dragging = null; corners.hold(false); }, { signal: lifetime.signal });
  window.addEventListener('keyup', event => { if (event.code === 'Tab') corners.hold(false); }, { signal: lifetime.signal });
  window.addEventListener('keydown', event => {
    if (!pageShown() && wakesHints(event)) corners.wake();
    if (!pageShown() && event.code === 'Tab') corners.hold(true);
    if (!pageShown() && !asking && build?.key(event)) { event.stopImmediatePropagation(); return; }
    // History takes its keys; what it leaves (Tab, Enter on a focused button) keeps the browser's own
    // default, and no key reaches the old shell's listeners while it is open (K8).
    if (otherPage) { otherPage.key(event); event.stopImmediatePropagation(); return; }
    if ((pageShown() || asking) && (event.metaKey || event.ctrlKey || event.altKey)) { event.stopImmediatePropagation(); return; }
    if (pageShown()) {
      // A page: Esc back, M model, N personality, R run or stop; while choosing a model, arrows and
      // Enter; while writing a personality, Enter saves, Esc cancels and every other key types.
      const choosing = pageView.choosing, ask = pageView.ask, decision = pageView.decision;
      if (decision) {
        // A decision: Esc back (from the record to the decision, then to the page), the arrows step
        // through the character's decisions, J shows the record, which the arrows then scroll.
        if (event.code === 'Escape') { event.preventDefault(); if (!event.repeat) decisionAct('back'); }
        else if (event.code === 'ArrowLeft' || event.code === 'ArrowRight') { event.preventDefault(); if (!event.repeat) decisionAct(event.code === 'ArrowLeft' ? 'earlier' : 'later'); }
        else if (event.code === 'KeyJ' && !event.repeat) { event.preventDefault(); decisionAct('record'); }
        else if (decision.record && ['ArrowUp', 'ArrowDown', 'PageUp', 'PageDown', 'Home', 'End', 'Space'].includes(event.code)) return;
        else if (event.code === 'Tab') return;
        else event.preventDefault();
        event.stopImmediatePropagation(); return;
      }
      if (ask && !pageView.editing) {
        // Ask: the arrows choose a question, Enter asks it, Esc goes back to the rows.
        if (event.code === 'Escape') { event.preventDefault(); if (!event.repeat) pageAct('back'); }
        else if (event.code === 'ArrowUp' || event.code === 'ArrowDown') { event.preventDefault(); if (!ask.busy) { ask.focus = Math.max(0, Math.min(ASK_ASPECTS.length - 1, ask.focus + (event.code === 'ArrowUp' ? -1 : 1))); drawPage(); } }
        else if (event.code === 'Enter' && event.target?.closest?.('.wu-page button')) return;
        else if (event.code === 'Enter' && !event.repeat) { event.preventDefault(); pageAct('question'); }
        else if (event.code === 'Tab') return;
        else event.preventDefault();
        event.stopImmediatePropagation(); return;
      }
      if (pageView.editing) {
        if (event.code === 'Enter' && !event.shiftKey) { event.preventDefault(); if (!event.repeat) pageAct('save'); event.stopImmediatePropagation(); }
        else if (event.code === 'Escape') { event.preventDefault(); if (!event.repeat) pageAct('back'); event.stopImmediatePropagation(); }
        return;
      }
      if (event.code === 'Escape') { event.preventDefault(); if (!event.repeat) pageAct('back'); }
      else if (event.code === 'KeyN' && !choosing && !event.repeat) { event.preventDefault(); pageAct('personality'); }
      else if (event.code === 'KeyM' && !choosing && !event.repeat) { event.preventDefault(); pageAct('model'); }
      else if (event.code === 'KeyR' && !choosing && !event.repeat) { event.preventDefault(); pageAct(runWatch.run ? 'stop' : 'run'); }
      else if (event.code === 'KeyQ' && !choosing && !event.repeat) { event.preventDefault(); pageAct('ask'); }
      else if (!choosing && (event.code === 'ArrowUp' || event.code === 'ArrowDown') && pageView.did?.length) {
        event.preventDefault();
        pageAct('row', Math.max(0, Math.min(pageView.did.length - 1, (pageView.didFocus ?? -1) + (event.code === 'ArrowUp' ? -1 : 1))));
      }
      else if (choosing && ['ArrowUp', 'ArrowDown'].includes(event.code)) {
        event.preventDefault();
        const last = subjectReads.models?.models.length ?? 0;
        pageAct('choose', Math.max(0, Math.min(last, choosing.focus + (event.code === 'ArrowUp' ? -1 : 1))));
      }
      else if (choosing && event.code === 'Enter' && !event.repeat) { event.preventDefault(); pageAct('use'); }
      else if (event.code === 'Enter' && event.target?.closest?.('.wu-page button')) return;
      else if (event.code === 'Enter' && !choosing && !event.repeat) { event.preventDefault(); pageAct('inspect'); }
      else if (event.code === 'Tab') return;
      else event.preventDefault();
      event.stopImmediatePropagation(); return;
    }
    if (asking) {
      // The question before a run keeps its answers together: Enter runs, Esc puts it away, P pauses first.
      if (event.code === 'Enter' && !event.repeat) { event.preventDefault(); if (!event.target?.closest?.('.cw-beside button')) questionAct('run'); else return; }
      else if (event.code === 'Escape' && !event.repeat) { event.preventDefault(); questionAct('back'); }
      else if (event.code === 'KeyP' && asking.refusal === 'society_not_paused' && !event.repeat) { event.preventDefault(); questionAct('pause'); }
      else if (['KeyW', 'KeyA', 'KeyS', 'KeyD', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'ShiftLeft', 'ShiftRight', 'Tab'].includes(event.code)) return;
      else event.preventDefault();
      event.stopImmediatePropagation(); return;
    }
    // A chosen subject: Esc lets go of it, Enter runs the focused prompt or else opens Details, R runs
    // or stops, V follows. Every other key's fate is world-keys.mjs's: movement goes on to the
    // renderer, the workspace's keys act, and any other key, the old shell's among them, goes no further.
    const being = held?.scene.type === 'being';
    if (held && !event.metaKey && !event.ctrlKey && !event.altKey) {
      if (event.code === 'Escape') { event.preventDefault(); if (!event.repeat) release(); event.stopImmediatePropagation(); return; }
      if (event.code === 'Enter' && event.target?.closest?.('.cw-beside button,.wu-prompt')) return;
      if (event.code === 'Enter' && being) { event.preventDefault(); if (!event.repeat) act('details'); event.stopImmediatePropagation(); return; }
      if (event.code === 'KeyR' && being) { event.preventDefault(); if (!event.repeat) act(runWatch.run ? 'stop' : 'run'); event.stopImmediatePropagation(); return; }
      if (event.code === 'KeyV' && being) { event.preventDefault(); if (!event.repeat) act('follow'); event.stopImmediatePropagation(); return; }
    }
    const fate = worldKey(event, { flying: Boolean(b.controls.flying), clock: corners.hasClock(), history: historyHere }, Boolean(event.target?.closest?.('.cw-beside button,.wu-prompt')));
    if (fate === 'move' || fate === 'pass') return;
    if (fate !== 'quiet') event.preventDefault();
    if (fate === 'inspect') void choose();
    else if (fate === 'leave') leaveWorld();
    else if (fate === 'play') corners.togglePlay();
    else if (fate === 'history') openHistory();
    event.stopImmediatePropagation();
  }, { capture: true, signal: lifetime.signal });
  function frame(now) {
    const workStart = performance.now();
    if (state.atlas?.binding !== b || !root.isConnected) { disposePrior(); return; }
    // The next frame is asked for first, so one failed read or word never stops the overlay.
    frameId = requestAnimationFrame(frame);
    trackHeld();
    root.dataset.camera = [b.controls.state.yaw, b.controls.state.pitch].map(value => value.toFixed(6)).join(',');
    root.dataset.viewerPosition = JSON.stringify([b.controls.state.x, b.controls.state.y, b.controls.state.z]);
    build?.frame(now);
    // The page's camera eases to frame its character (600 ms), then holds.
    if (pageView?.ease) {
      const { from, to, at, ms } = pageView.ease, t = ms ? (now - at) / ms : 1;
      b.controls.setView(easePose(from, to, Math.min(1, t)), 'altitude'); b.invalidate();
      if (t >= 1) pageView.ease = null;
    }
    if (!pageShown() && now - lastPick >= 33) {
      lastPick = now;
      setTarget(picked(innerWidth / 2, innerHeight / 2));
    }
    // Looking: the name tag and [E] Inspect over the subject at the reticle, within reach.
    const targetFrame = target && screenFrame(target);
    const distance = targetFrame ? reachDistance(target) : Infinity;
    targetReachable = Boolean(target && inspectionReach(distance, targetReachable));
    corners.frame(now);
    // The Back corner says Back while something is chosen, and hides its Esc while a question shows its own.
    corners.back(asking ? null : held ? CORNER_WORDS.back : CORNER_WORDS.yourWorlds);
    corners.reticle.hidden = pageShown();
    corners.reticle.dataset.state = target ? targetReachable ? 'ready' : 'far' : 'empty';
    root.dataset.reachable = String(targetReachable);
    root.dataset.focusDistance = Number.isFinite(distance) ? distance.toFixed(2) : '';
    if (target || held) refreshSubjectReads(now);
    const looking = !pageShown() && !asking && !dragging && targetReachable && target.key !== held?.key && targetFrame?.headInView && seen(target, targetFrame);
    if (looking) {
      const view = subjectView(target);
      if (!view.offer && !offers.has(target.key) && readBackoff.ready(target.key, performance.now())) void entityOffer(target).catch(() => {});
      presence.look(tagWords({ who: view.who, being: view.being, doing: view.doing, model: view.model, live: Boolean(runWatch.run), popping: Boolean(pops.get(target.scene.id)?.showing) }), { x: targetFrame.overhead.x, y: targetFrame.overhead.y }, true);
    } else presence.look(null);
    // Chosen: the ring at its feet and the card beside it; both follow it as the world moves.
    if (held) {
      const view = subjectView(held), { connected } = modelOf(held);
      presence.choose(chosenCard({ who: view.who, being: view.being, doing: view.doing, decision: view.decision, model: view.model ?? null,
        running: Boolean(runWatch.run), connected, following: followView.active(), reading: view.reading && view.being, thingLine: view.thingLine ?? null }));
      const heldFrame = screenFrame(held);
      const ring = heldFrame && seen(held, heldFrame) ? ringAt(heldFrame) : null;
      if (ring) {
        const headY = heldFrame.headInView ? heldFrame.overhead.y : heldFrame.top;
        // The projected points run down the character's middle; its body reaches about 0.4 of the
        // ring's radius either side, so the card keeps clear of the shoulder as frame 05 does.
        const half = ring.rx * BODY_HALF_WIDTH;
        presence.place({ ring, bounds: { left: Math.min(heldFrame.left, ring.x - half), right: Math.max(heldFrame.right, ring.x + half), top: heldFrame.top, bottom: heldFrame.bottom,
          headY, waistY: headY + (ring.y - headY) * CARD_WAIST } });
      } else presence.place(null);
    }
    // Pops over the characters whose model acted, 12 px over the head, while they show.
    for (const [subjectId, made] of pops) {
      if (!made.showing) continue;
      const row = rows.find(item => item.scene?.type === 'being' && item.scene.id === subjectId);
      const frameOf = row && screenFrame(row);
      const tagShown = row?.key === target?.key && looking ? presence.tagTop() : null;
      if (frameOf?.headInView && seen(row, frameOf)) made.place(frameOf.overhead.x, tagShown ?? frameOf.overhead.y);
      else made.root.style.transform = 'translate3d(-9999px,0,0)';
    }
    if (pageView && now - (pageView.drawnAt ?? 0) >= 1000) { pageView.drawnAt = now; drawPage(); }
    overlayCosts.push(performance.now() - workStart); if (overlayCosts.length > 120) overlayCosts.shift();
    if (now - lastMeasure >= 1000) {
      lastMeasure = now;
      const stats = values => { const sorted = [...values].sort((a,b) => a-b); return { samples: values.length, meanMs: +(values.reduce((sum, value) => sum + value, 0) / Math.max(1, values.length)).toFixed(3), p95Ms: +(sorted[Math.floor((sorted.length - 1) * .95)] || 0).toFixed(3) }; };
      root.dataset.overlayCost = JSON.stringify({ frame: stats(overlayCosts) });
    }
  }
  disposePrior = () => {
    stopFollowing();
    disposeFrameMeasurement();
    build?.dispose();
    presence.dispose();
    runWatch.dispose();
    corners.dispose();
    if (pageView) { pageView.page.close(); pageView.decision?.page.close(); pageView = null; }
    otherPage?.dispose(); otherPage = null;
    lifetime.abort(); cancelAnimationFrame(frameId); ++serial; root.remove(); canvas.inert = false;
    b.controls.onPointerPick = priorCallbacks.pick; b.controls.onInteract = priorCallbacks.interact;
    b.controls.onSummon = priorCallbacks.summon; b.controls.onCameraToggle = priorCallbacks.camera; b.controls.onFlyChange = priorCallbacks.fly;
    b.setFreeCursorActive(false); b.setControlsEnabled(true);
  };
  // The world's own read of what is in it: a failure retries quietly with the backoff, and only
  // failures in a row say the world is not connected, until a read succeeds (DESIGN's ruling L14).
  let inventoryFailures = 0, inventoryReading = false;
  const readInventory = async () => {
    if (inventoryReading || lifetime.signal.aborted) return;
    inventoryReading = true;
    try {
      await refreshInventory();
      if (inventoryFailures >= OFFLINE_AFTER_FAILED_READS) notice('');
      inventoryFailures = 0; readBackoff.succeeded('world-inventory');
    } catch {
      inventoryFailures++; readBackoff.failed('world-inventory', performance.now());
      if (inventoryFailures >= OFFLINE_AFTER_FAILED_READS && !lifetime.signal.aborted) corners.notes.show(NOTE_WORDS.offline, { ms: 0 });
    } finally { inventoryReading = false; }
  };
  const retrying = window.setInterval(() => { if (inventoryFailures > 0 && readBackoff.ready('world-inventory', performance.now())) void readInventory(); }, 500);
  lifetime.signal.addEventListener('abort', () => clearInterval(retrying), { once: true });
  await readInventory();
  canvas.focus({ preventScroll: true }); frameId = requestAnimationFrame(frame);
  // Arriving (frame 02): the opening gives way, and the world's name shows once with who lives here.
  if (endOpening()) {
    const banner = areaBanner({ name: entry.title, sub: populationLine(selection.people?.clock().population ?? null) ?? undefined });
    root.append(banner.root);
    void banner.play().then(() => banner.remove());
  }
}
