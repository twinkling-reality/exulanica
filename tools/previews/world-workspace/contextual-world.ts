import { GROUND_RING, createGroundRing, pointerRay } from '../../../web/packages/atlas-react/src/playcanvas/index.ts';
import { buildInventoryRows, inventoryDetailPath, rowForSceneSelection } from './inventory-records.ts';
import { assertSelectedOffer } from './entity-inspection.mjs';
import { THING_RING, mountBuildMode } from './build-mode.ts';
import { mountFrameMeasurement } from './frame-measurement.mjs';
import { inspectionReach } from './discovery-policy.mjs';
import { createReadBackoff } from './read-backoff.mjs';
import { keepWorldInAddress, returnToFrontDoor } from './front-door.ts';
import { keepWorldPicture } from '/src/composition/world-pictures.ts';
import { SocietyClient } from '/src/society-api.ts';
import { SocietyModelsClient } from '/src/society-models-api.ts';
import { characterFacts, mountCharacterPresence } from './character-presence.ts';
import { SAID_READ, deciderOf, groupContent, keepLastSaid, modelGroup, modelPicker, questionGroup } from './character-group.mjs';
import { PAGE_FRAMING, PERSON_RING_METRES, chosenCard, chosenDecision, didRows, doingLine, easePose, pageFraming, pairFraming, ringRadii, subjectWho, tagWords } from './character-view.mjs';
import { CHARACTER_WORDS, called, deciderWords, goneNote, lastRunLine, modelRefusalWords, orderedModels, outOfViewNote, pageSub, runSectionLine } from './character-words.mjs';
import { openCharacterPage } from './character-page.ts';
import { mountHistory } from './history.ts';
import { WATCH_MS, mountRunWatch } from './run-watch.ts';
import { runLength, runRefusalWords, runningLine, timeLeft, whoDecides } from './run-words.mjs';
import { recordEntityModel } from './entity-model-actions.mjs';
import { assignmentSubject } from './entity-properties.mjs';
import { worldTime } from './world-clock.mjs';
import { SocietyControlClient } from '/src/society-control-api.ts';
import { edgeInset, nameOver, speech, talkScene } from './world-ui-talk.ts';
import { SPEAKING_ABOVE, createScene } from './talk-scene.mjs';
import { NAMED_LEAST_PX, OVER_HEAD, STACK_GAP, TALK_FRAMING, createTalk, edgePlace, quietWords, endedBy, exchangeOf, framingStep, nameGroups, namedPeople, popLeft, popPlacement, shownWhile, stackPops, talkActs } from './talk-pops.mjs';
import { SCENE_WORDS, dayWord, knownWho, orbLetter, plateTo, speechLabel, togetherNames } from './talk-words.mjs';
import { fetchThingCardRoute, writeThingCharacter } from '/src/thing-card-route-api.ts';
import { historyHooks, historyWrite, recordPictures } from './history-host.ts';
import { recordStates } from './record-host.ts';
import { personalityBody, personalityRefusalWords } from './personality-words.mjs';
import { createKindLabels, placedLine } from './build-words.mjs';
import { kindDocumentLabel } from '/src/composition/visitor-notices.ts';
import { areaBanner, mountUiScale } from './world-ui.ts';
import { mountCorners } from './world-corners.ts';
import { endOpening } from './world-opening.ts';
import { MADE_HANDOFF_KEY, readMade } from './create-steps.mjs';
import { CREATE_WORDS } from './create-words.mjs';
import { madeNote } from './world-ui-create.ts';
import { populationLine } from './opening-steps.mjs';
import { BESIDE, OFFLINE_AFTER_FAILED_READS } from './world-ui-layout.mjs';
import { worldKey, wakesHints } from './world-keys.mjs';
import { CORNER_WORDS, NOTE_WORDS, availableHints } from './world-words.mjs';
import { openDecisionPage } from './decision-page.ts';
import { DECISION_WORDS } from './decision-words.mjs';
import { ASK_ASPECTS, askEntityCompanion, askWords } from './entity-companion.mjs';
import { CompanionAskClient } from '/src/companion-ask-api.ts';
import { drawSimulated } from '/src/companion-simulated.ts';
import { DecisionAsksClient } from '/src/society-decision-asks-api.ts';
import { openComparePage } from './compare-page.ts';
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

/** A design token's colour (`#rgb`, `#rrggbb` or `rgb()`) as sRGB 0 to 1, or null where it is not one. */
function tokenRgb(element: Element, name: string): readonly [number, number, number] | null {
  const text = getComputedStyle(element).getPropertyValue(name).trim();
  const hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(text)?.[1];
  if (hex) {
    const full = hex.length === 3 ? [...hex].map((digit) => digit + digit).join('') : hex;
    return [0, 2, 4].map((at) => Number.parseInt(full.slice(at, at + 2), 16) / 255) as unknown as readonly [number, number, number];
  }
  const parts = /^rgba?\(([^)]*)\)$/i.exec(text)?.[1]?.split(/[\s,/]+/).filter(Boolean).slice(0, 3).map(Number);
  return parts?.length === 3 && parts.every((part) => part >= 0 && part <= 255) ? parts.map((part) => part / 255) as unknown as readonly [number, number, number] : null;
}

/** Targeting and inspection use real native hits and authorized inventory identities. */
export async function mountContextualWorld({ state, renderer, selection, objects, send, binding, makeCreature = null }) {
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
  // Beside a character or thing (character-presence.ts): the name tag and cards.
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
  // A read-only copy dims what needs the server (Play and Pause), as the offline state does. Where
  // nobody lives yet, a page that may change the world offers to bring people in from the clock's
  // corner, and with nowhere for them to go, build mode (K13), as B opens it.
  const writable = Boolean(send && binding) && import.meta.env.VITE_EXULANICA_REVIEW_OBSERVER_ONLY !== '1';
  const corners = mountCorners({ host: root, people: selection.people ?? null, onLeave: () => { if (held) release(); else leaveWorld(); },
    readOnly: import.meta.env.VITE_EXULANICA_REVIEW_OBSERVER_ONLY === '1', flySpeed: () => b.controls.flyingSpeed,
    canBringIn: writable, onBuild: writable ? () => { build?.key(new KeyboardEvent('keydown', { code: 'KeyB', key: 'b' })); } : null,
    // The world screen (r02): the pill's name, the rail's History and Fly as H and F do, and where the
    // person stands for when the first-minute hint leaves (once per world on this computer).
    title: entry.title, worldId: entry.worldId, onHistory: () => openHistory(), onFly: () => b.controls.toggleFly(),
    pose: () => { const at = b.controls.state; return at ? { x: at.x, z: at.z, yaw: at.yaw, pitch: at.pitch } : null; } });
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
  // Flying (F): Fly lit in the rail, its word Land, and the hints for flying while it lasts.
  // History opens in every world, a read-only copy's too: it only reads (history.ts). One flag for
  // its hint and its key, so the two never disagree.
  const historyHere = true;
  const worldHints = () => corners.worldHints(availableHints({ flying: Boolean(b.controls.flying), build: Boolean(build), history: historyHere }));
  b.controls.onFlyChange = (flying) => {
    corners.flying(Boolean(flying));
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
  const build = writable
    ? mountBuildMode({
      b, root, state, entry, read, send, binding, canvas, corners, inspecting: () => pageShown() || held !== null,
      groundRing: createGroundRing(b.app, { camera: b.camera.camera, invalidate: () => b.invalidate(), look: { ...GROUND_RING, ...THING_RING, live: tokenRgb(root, '--live') ?? GROUND_RING.live } }),
      // Who is drawn and where, for the names over people near what is held; read as the people arrive.
      people: {
        ids: () => b.authoredSociety?.visibleInhabitantIds ?? [],
        groundOf: (id, out) => b.authoredSociety?.groundOf(id, out) ?? false,
        heightOf: (id) => b.authoredSociety?.heightOf(id) ?? null,
        // A person's own name only: someone the world has not named is not labelled over their head.
        name: (id) => subjectReads.society?.state?.inhabitants?.find(person => person.id === id)?.display_name ?? null,
        // The society read the names come from, refreshed no more often than any subject read.
        refresh: () => refreshSubjectReads(performance.now()),
      },
      // The tray's first tile opens the page's own creature maker.
      makeCreature,
    }) : null;
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
      const options = (data?.request?.context as { readonly options?: unknown } | undefined)?.options;
      if (Array.isArray(options)) subjectReads.options.set(requestId, options.length);
      if (pageView) drawPage();
    }, () => { setTimeout(() => subjectReads.options.delete(requestId), OPTIONS_RETRY_MS); });
    return null;
  }
  /** A character's row by its society id. */
  const beingRow = (id) => rows.find(item => item.scene?.type === 'being' && item.scene.id === id) ?? null;
  const personName = (id) => subjectReads.society?.state?.inhabitants?.find(person => person.id === id)?.display_name ?? selection.societyNames?.()?.people.get(id) ?? null;
  /** A person inside History's sentences (J20): as their tag and card call them, else "the" and their kind. */
  const calledAs = (id) => { const row = beingRow(id); return row ? subjectView(row).who : called({ name: null, kind: characterFacts(subjectReads.society, id)?.kind ?? null }); };
  const calledWithin = (id) => calledAs(id).within;
  /** A person as the tag and card call them (J20), by society id: from their offer, else their society name, else "the" and their kind. */
  function whoOf(id) {
    const row = beingRow(id), kind = characterFacts(subjectReads.society, id)?.kind ?? null;
    return knownWho(row ? subjectWho(row, offers.get(row.key)?.offer ?? null, kind) : called({ name: null, kind }), personName(id));
  }
  const popScale = () => Number.parseFloat(root.style.getPropertyValue('--ui-scale')) || 1;
  /**
   * Just over a character's drawn head on screen, seated or standing: the point the renderer hangs
   * its own marks at (authored-society anchorOf), so a pop and its connector meet a seated person's
   * head rather than the air over where it stands; else the standing head. Null behind the camera.
   */
  function headOnScreen(row) {
    const point = b.camera.getPosition().clone();
    const head = row && b.authoredSociety?.anchorOf?.(row.scene.id, point) ? point : row ? targetPoint(row, true) : null;
    const at = head ? b.camera.camera.worldToScreen(head) : null;
    return at && at.z > 0 ? { x: at.x, y: at.y } : null;
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
    // Who decides where a model does not (T7): a person playing them, or an outside program at the door.
    const decider = choice?.played ? 'person' : subjectReads.models?.outside?.some(item => item.subjectId === row.scene.id) ? 'external' : null;
    return { being, who, offer, facts, decision, model: choice?.model?.name ?? null, decider,
      deciderChose: facts?.person?.goal?.reason === 'chosen_by_their_model', chip: deciderWords(decider) ?? choice?.model?.name ?? null,
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
  /**
   * Following an exchange (T5): when the followed character talks with someone within 15 m who is
   * seen, the camera eases over 600 ms to frame both and their pops, never nearer the two than
   * following stood, and eases back 2 s after the exchange's last pop has gone. The person's own
   * movement, a page or reduced motion ends it where the camera stands.
   */
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
  let shownNow = [];
  function framePair(now, shownPops) {
    if (!following) return;
    if (!held || pageShown() || reducedMotion.matches) { following.pair = null; return; }
    const exchange = exchangeOf(shownPops, held.scene.id), other = exchange ? beingRow(exchange.other) : null;
    const mine = targetPoint(held, true), theirs = other && targetPoint(other, true);
    const near = Boolean(mine && theirs && Math.hypot(mine.x - theirs.x, mine.z - theirs.z) <= TALK_FRAMING.nearMetres);
    const framed = Boolean(following.pair && !following.pair.back);
    const otherFrame = near && !framed ? screenFrame(other) : null;
    // An exchange the person's own movement ended stays ended (talk-pops.mjs framingStep, AUDIT B1).
    const step = framingStep({ exchange, ended: following.ended ?? null, framed, near, seen: Boolean(otherFrame && seen(other, otherFrame)) });
    following.ended = step.ended;
    const base = following.pair?.base ?? { ...b.controls.state };
    const to = step.frame ? pairFraming({ from: base, a: mine, b: theirs, fovDeg: b.camera.camera.fov, aspect: innerWidth / innerHeight,
      safe: TALK_FRAMING.safe, least: Math.hypot(mine.x - base.x, mine.z - base.z) }) : null;
    if (to && ['x', 'y', 'z', 'yaw', 'pitch'].every(key => Number.isFinite(to[key]))) {
      if (!following.pair || following.pair.back) following.pair = { base, from: { ...b.controls.state }, at: now, to, quiet: null, back: null };
      else Object.assign(following.pair, { to, quiet: null });
    } else if (following.pair && !following.pair.back) {
      following.pair.quiet ??= now;
      if (now - following.pair.quiet >= TALK_FRAMING.backAfterMs) following.pair.back = { from: { ...b.controls.state }, at: now };
    }
    const pair = following.pair;
    if (!pair) return;
    const t = (now - (pair.back ?? pair).at) / TALK_FRAMING.easeMs;
    b.controls.setView(pair.back ? easePose(pair.back.from, pair.base, t) : easePose(pair.from, pair.to, t), 'altitude');
    b.invalidate();
    if (pair.back && t >= 1) following.pair = null;
  }
  /**
   * While following an exchange, the card's side away from the other person (T5), from their
   * projected head; none where they stand behind the camera.
   */
  function awaySide(shownPops, x) {
    if (!following || !held) return null;
    const exchange = exchangeOf(shownPops, held.scene.id), other = exchange ? beingRow(exchange.other) : null;
    const head = other ? targetPoint(other, true) : null;
    const at = head ? b.camera.camera.worldToScreen(head) : null;
    return at && at.z > 0 ? (at.x > x ? 'left' : 'right') : null;
  }
  /**
   * The person moves the camera themselves: an exchange's framing ends where the camera stands, and
   * that exchange stays ended (T5, AUDIT B1).
   */
  const endPair = () => {
    if (!following || !held) return;
    following.ended = endedBy(exchangeOf(shownNow, held.scene.id)) ?? following.ended ?? null;
    following.pair = null;
  };
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
      // While an exchange is framed, the pose following would hold moves; the framing places the camera.
      const pose = following.pair ? following.pair.base : b.controls.state;
      const moved = { ...pose, x: pose.x + delta.x, y: pose.y + delta.y, z: pose.z + delta.z };
      if (following.pair) following.pair.base = moved; else { b.controls.setView(moved, 'altitude'); b.invalidate(); }
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
  // The ring at a chosen subject's feet, on the ground in the world (atlas-react ground-ring.ts), in
  // the design's --live.
  const groundRing = createGroundRing(b.app, { camera: b.camera.camera, invalidate: () => b.invalidate(), look: { ...GROUND_RING, live: tokenRgb(root, '--live') ?? GROUND_RING.live } });
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
    ++serial; held = null; picker.drop(); root.dataset.held = '';
    presence.choose(null); presence.group(null);
  }
  // A run (run-watch.ts): the pill's run line and Stop, and why it ended (r09).
  const readOnly = import.meta.env.VITE_EXULANICA_REVIEW_OBSERVER_ONLY === '1';
  const modelName = (model) => subjectReads.models?.models.find(item => item.provider === model?.provider && item.modelId === (model?.model_id ?? model?.modelId))?.name ?? null;
  const eventsPath = (kinds, extra = '') => '/world/versions/' + encodeURIComponent(entry.authoredVersionId) + '/society/events?world_id=' + encodeURIComponent(entry.worldId)
    + kinds.map(kind => '&kinds=' + kind).join('') + extra;
  // The chosen character's last line said (J30), read from the said events once chosen and every few seconds.
  const saidLines = keepLastSaid({ readPage: (before) => read(eventsPath(['said'], '&limit=' + SAID_READ.limit + (before ? '&before=' + encodeURIComponent(before) : ''))) });
  /** What a chosen character's group says (J30, character-group.mjs) from what the page holds now; the Run question (r08) while asking. */
  function chosenGroup(row, now) {
    const view = subjectView(row), { connected } = modelOf(row);
    const offer = offers.get(row.key)?.offer ?? null;
    const assignable = !readOnly && Boolean(inventory && offer && subjectReads.models?.takesModelChoices && assignmentSubject(inventory, row, offer));
    // Someone else the group names (the run's other askers, a line's listener), as their own tag calls them (J20): their
    // offer is read once, so a person with a name is named here as everywhere else.
    const named = (id) => { const other = beingRow(id); if (other && !offers.has(other.key) && readBackoff.ready(other.key, performance.now())) void entityOffer(other).catch(() => {}); return whoOf(id); };
    const picking = picker.of(row);
    if (picking) return modelGroup({ who: view.who, models: subjectReads.models?.models ?? [], current: modelOf(row).model, focus: picking.focus, refusal: picking.refusal, busy: picking.busy });
    if (asking) {
      // J28: the run asks everyone with a model, the chosen character first, each as the tag calls them (J20).
      const askerIds = [row.scene.id, ...(subjectReads.models?.choices ?? []).filter(item => item.model && item.subjectId !== row.scene.id).map(item => item.subjectId)];
      return questionGroup({ who: view.who, askers: askerIds.map(id => id === row.scene.id ? view.who : named(id)), others: (subjectReads.society?.state?.inhabitants?.length ?? 0) > askerIds.length,
        model: view.model, limits: asking.shown, refusal: asking.refusal, busy: asking.busy, anotherModel: assignable && (subjectReads.models?.models.length ?? 0) > 1 });
    }
    const said = saidLines.of(row.scene.id, now);
    return groupContent({ who: view.who, doing: view.doing, said, toWho: said?.to ? named(said.to) : null, startMinute: view.facts?.startMinute ?? null,
      decider: deciderOf({ decider: view.decider ?? null, model: view.model ?? null }), model: view.model ?? null, connected, assignable,
      running: Boolean(runWatch.run), left: runWatch.run ? timeLeft(runWatch.run.endsBy, Date.now()) : null, following: followView.active(), reading: view.reading });
  }
  let groupActions = new Set(), groupFirst = 0;
  // Choose a model in the group (r07, character-group.mjs): the page's own write; the Run question then asks again.
  const picker = modelPicker({ models: () => subjectReads.models?.models ?? [], currentOf: (row) => modelOf(row).model,
    write: async (row, selected, key) => (await recordEntityModel({ entry, subjectId: row.scene.id, selected, key, refresh: () => refreshSubject(row),
      client: modelsClient, current: () => picker.of(row) !== null && held === row && current() })).verified,
    refusal: (error, row) => modelRefusalWords(error.code ?? 'stale', subjectView(row).who),
    onUsed: (verified) => { subjectReads.models = verified; if (asking) { asking.shown = runWatch.limits(verified); asking.refusal = null; } } });
  const runWatch = mountRunWatch({ pill: corners, entry, credentials, isCurrent: current, readOnly,
    askers: () => (subjectReads.models?.choices ?? []).filter(choice => choice.model && !choice.refusal).map(choice => whoOf(choice.subjectId)),
    onChange: () => { if (pageView) drawPage(); },
  });
  void runWatch.refresh();
  // Talking (talk-pops.mjs, rulings T1 to T8 and N28): while the world plays, a line said and a choice a
  // mind made show over whoever did it, read on the run's cadence from the minute after the last one
  // read, retrying quietly (L14). Nothing shows while the world is paused. A name marks someone farther
  // off: in a conversation out of hearing, or the person chosen last.
  const talk = createTalk();
  // The choices that change nothing to see (T11), by the decision-action catalog's own words, every version.
  const quietChoices = quietWords(Object.values(import.meta.glob('../../../assets/catalogs/society/society-decision-action.v*.json', { eager: true, import: 'default' })));
  const speechParts = new Map(), nameParts = new Map(), togetherParts = new Map();
  const insetNow = edgeInset(beside);
  let lastChosen = null;
  // Talking while following a conversation (talk-scene.mjs, ruling T9): the scene's lines, and who speaks.
  const scene = createScene();
  let sceneSpeaker = null;
  const sceneView = talkScene({ onStop: () => stopFollowing(), onDay: () => openSpeakerPage() });
  root.append(sceneView.root);
  /** The scene's Enter (T9): the page of whoever is speaking now, chosen if it is not the one followed. */
  function openSpeakerPage() {
    const row = (sceneSpeaker && beingRow(sceneSpeaker)) || held;
    if (!row) return;
    if (row.key !== held?.key) { stopFollowing(); held = row; root.dataset.held = row.key; }
    void openPage(row);
  }
  /** Draws the scene (T9): open while it shows, the world view's chrome hidden under its bars. */
  function drawScene(scened) {
    sceneView.open(scened.showing);
    root.dataset.scene = scened.showing ? 'talking' : '';
    sceneSpeaker = scened.showing ? scened.now.speaker : null;
    if (!scened.showing) return;
    const speaker = whoOf(scened.now.speaker);
    const listener = scened.now.to && scened.now.to !== scened.now.speaker ? whoOf(scened.now.to) : null;
    const row = beingRow(scened.now.speaker), frameOf = row && screenFrame(row);
    const head = frameOf?.headInView && seen(row, frameOf) ? headOnScreen(row) ?? frameOf.overhead : null;
    sceneView.draw({
      before: scened.before ? { speaker: whoOf(scened.before.speaker).start, words: scened.before.words } : null,
      now: scened.now.words,
      plate: { name: speaker.start, to: plateTo(listener), letter: orbLetter(speaker), portrait: null },
      day: dayWord(speaker),
      stopFollowing: SCENE_WORDS.stopFollowing,
      dot: head ? { x: head.x, y: head.y - SPEAKING_ABOVE * popScale() } : null,
    });
  }
  let talkSeen = null, talkReading = false;
  async function readTalk() {
    const clock = selection.people?.clock() ?? null;
    // Paused, or the page hidden: nothing is read, and what was said meanwhile never pops late (AUDIT S2).
    if (clock?.mode !== 'playing' || !Number.isFinite(clock.minute) || document.hidden) { talkSeen = null; talk.clear(); return; }
    if (talkSeen === null) { talkSeen = clock.minute; return; }
    if (talkReading || clock.minute <= talkSeen || !readBackoff.ready('talk', performance.now())) return;
    talkReading = true;
    const upTo = clock.minute;
    try {
      const page = await read(eventsPath(['said', 'decision_applied'], '&from_tick=' + (talkSeen + 1) + '&limit=256'));
      readBackoff.succeeded('talk');
      talkSeen = Math.max(upTo, ...page.events.map(event => event.tick).filter(Number.isFinite));
      // A page with more after it is a backlog, not what was just said: none of it pops.
      if (page.next || lifetime.signal.aborted || selection.people?.clock().mode !== 'playing') return;
      const now = performance.now();
      for (const act of talkActs(page.events, quietChoices)) { talk.add(act, now); scene.add(act); }
    } catch { readBackoff.failed('talk', performance.now()); } finally { talkReading = false; }
  }
  const talkTimer = window.setInterval(() => { void readTalk(); }, WATCH_MS);
  lifetime.signal.addEventListener('abort', () => clearInterval(talkTimer), { once: true });
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
  // The Run question is the chosen character's group in its question state (r08): chosenGroup draws it each frame.
  function drawQuestion() { presence.ask(null); }
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
    else if (action === 'model' && held.scene.type === 'being' && !readOnly && subjectReads.models) picker.open(held);
    else if (action.startsWith('use:')) void picker.use(Number(action.slice(4)));
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
      runLine: subjectReads.models ? runSectionLine(view.who, { hostRefusal: subjectReads.models.hostRefusal, offered: subjectReads.models.models,
        chosen: Boolean(model), chosenRefusal: choice?.refusal ?? null, assignable }) : null,
      run: { open: Boolean(run), big: run ? runningLine(run, Date.now()) : runLength(limits), small: whoDecides(view.who), busy: pageView.run.busy, refusal: pageView.run.refusal ? runRefusalWords(pageView.run.refusal) : null },
      // A row's choices are counted as each decision is read, so its sub-line is worded as the page draws.
      did: pageView.did ? pageView.did.map(row => ({ time: row.time, what: row.what, sub: row.sub, decision: Boolean(row.requestId), heard: row.heard === true, ...(row.heard ? {} : { model: row.model ?? null, choices: row.model ? decisionOptions(row.requestId) ?? null : null, decisions: row.decisions ?? null, decider: row.decider === 'person' || row.decider === 'external' ? row.decider : null }), ...records.dayRow(pageView, row) })) : null,
      didFocus: pageView.didFocus, lastRun, canAsk: !readOnly,
      ask: pageView.ask ? { questions: ASK_ASPECTS.map(aspect => askWords(aspect, view.who)), focus: pageView.ask.focus, busy: pageView.ask.busy,
        asked: pageView.ask.asked, answer: pageView.ask.answer, failure: pageView.ask.failure } : null,
      personality: pageView.personality ? { character: pageView.personality.character, shown: pageView.personality.shown } : null,
      editing: pageView.editing ? { session: pageView.editing.session, refusal: pageView.editing.refusal, busy: pageView.editing.busy } : null,
      choosing: pageView.choosing ? { choices, focus: pageView.choosing.focus, refusal: pageView.choosing.refusal, busy: pageView.choosing.busy } : null,
      canCompare: comparable(pageView) && (pageView.did ?? []).some(modelAnswered),
      compare: pageView.compare ? records.compare(pageView, view.who) : null, ...records.day(pageView, view, Boolean(subjectReads.models)),
    };
  }
  function drawPage() {
    if (!pageView) return;
    pageView.page.draw(pageState());
    if (pageView.decision) pageView.decision.page.draw(decisionState());
    if (pageView.comparison) pageView.comparison.page.draw(comparisonState());
  }
  /** The page's rows: the character's recorded events, read when the page opens and every few seconds. */
  async function readDid() {
    const showing = pageView;
    if (!showing) return;
    try {
      // The events read serves the whole society, newest first, a page at a time: read back until
      // the character's newest rows are found (counted as they fold, R5e) or DID_PAGES pages are read.
      const events = [];
      let before = '';
      for (let pageNumber = 0; pageNumber < DID_PAGES; pageNumber += 1) {
        const page = await read(eventsPath(['goal_selected', 'decision_applied', 'said'], '&limit=256' + (before ? '&before=' + encodeURIComponent(before) : '')));
        events.push(...page.events);
        if (!page.next || didRows({ events, subjectId: showing.row.scene.id, wordGoal: () => true, modelName: () => null, foldable: () => true }).length >= 7 || showing !== pageView) break;
        before = page.next;
      }
      const facts = characterFacts(subjectReads.society, showing.row.scene.id);
      showing.events = events;
      await records.readMoments(showing);
      if (showing !== pageView) return;
      showing.did = didRows({ events, subjectId: showing.row.scene.id, startMinute: facts?.startMinute ?? null, modelName,
        options: (requestId) => decisionOptions(requestId), who: whoOf, foldable: (row) => records.foldable(showing, row),
        wordGoal: (document) => {
          if (!facts) return null;
          const shown = { ...subjectReads.society, state: { ...subjectReads.society.state, inhabitants: subjectReads.society.state.inhabitants.map(person => person.id === showing.row.scene.id ? { ...person, goal: document.goal ?? null, action: document.action ?? person.action } : person) } };
          return doingLine(characterFacts(shown, showing.row.scene.id)?.doing ?? null);
        } });
      // The chosen row stays where it was; at first it is the newest row a decision stands behind. A
      // line heard is never chosen (T6).
      if (showing.didFocus === null || showing.didFocus >= showing.did.length || showing.did[showing.didFocus]?.heard) {
        const first = showing.did.findIndex(row => row.requestId);
        const own = showing.did.findIndex(row => !row.heard);
        showing.didFocus = first >= 0 ? first : own >= 0 ? own : null;
      }
      drawPage();
    } catch { if (showing === pageView && showing.did === null) { showing.did = []; drawPage(); } }
  }
  function pageAct(action, index?) {
    if (!pageView) return;
    const choosing = pageView.choosing, editing = pageView.editing;
    const compare = pageView.compare;
    if (action === 'back') {
      if (compare) { pageView.compare = null; drawPage(); }
      else if (editing) { pageView.editing = null; drawPage(); } else if (choosing) { pageView.choosing = null; drawPage(); } else if (pageView.ask) { pageView.ask = null; drawPage(); } else closePage();
    }
    else if (action === 'compare' && !readOnly && !choosing && !editing && !compare) { pageView.compare = { focus: 0, offers: new Map(), asking: null, answers: new Map(), single: index ?? null }; readOffer(pageView); drawPage(); }
    else if (action === 'compareChoose' && compare && !compare.asking) { compare.focus = index; readOffer(pageView); drawPage(); }
    else if (action === 'compareStart' && compare && !compare.asking) void compareAsk(pageView);
    else if (action === 'row' && pageView.did?.[index] && !pageView.did[index].heard) { pageView.didFocus = index; drawPage(); }
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
      if (outcome.written === true) {
        showing.personality = { ...showing.personality, revision: outcome.revision, character: outcome.character };
        showing.editing = null;
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
    if (!pictures.still()) void pictures.takeStill().then(drawPage);
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
  const pictures = recordPictures({ entry, credentials: state.credentials, source: b, changed: () => drawPage() });
  lifetime.signal.addEventListener('abort', () => pictures.dispose(), { once: true });
  const records = recordStates({ versionPath: '/world/versions/' + encodeURIComponent(entry.authoredVersionId), scope: '?world_id=' + encodeURIComponent(entry.worldId), read, pictures,
    subjectView, modelOf, nameOf: calledWithin, personName: (id) => personName(id), modelName: (model) => modelName(model), latest: (requestId) => subjectReads.models?.latest.find(item => item.requestId === requestId) ?? null,
    compareModels, modelKey: (model) => modelKey(model), comparedDecisions: (compare, offer) => comparedDecisions(compare, offer), boundOf: (decisions) => boundOf(decisions),
    label: (kind) => kindLabels.label(kind), run: () => runWatch.run ?? null, assignable: () => pageState().assignable });
  /** The rows a decision stands behind, newest first, as indexes into What Teo did. */
  const decisionRows = (showing) => (showing.did ?? []).flatMap((row, at) => row.requestId ? [at] : []);
  function decisionAct(action) {
    const decision = pageView?.decision;
    if (!decision) return;
    if (action === 'back') { if (decision.record) { decision.record = false; drawPage(); } else closeDecision(); }
    else if (action === 'record' && decision.detail) { decision.record = !decision.record; drawPage(); }
    else if (action === 'compare' && comparable(pageView) && modelAnswered(pageView.did?.[decision.rowIndex])) {
      // The same flow for this one moment, on the character's page (C1).
      const requestId = decision.requestId;
      closeDecision();
      pageAct('compare', requestId);
    }
    else if (action === 'earlier' || action === 'later') {
      const order = decisionRows(pageView), here = order.indexOf(decision.rowIndex);
      const next = here < 0 ? undefined : order[here + (action === 'earlier' ? 1 : -1)];
      if (next !== undefined) void openDecision(next);
    }
  }
  function decisionState() {
    const showing = pageView, decision = showing.decision, order = decisionRows(showing), here = order.indexOf(decision.rowIndex);
    return records.decision(showing, decision, { earlier: here >= 0 && here < order.length - 1, later: here > 0, canCompare: comparable(showing) && modelAnswered(showing.did?.[decision.rowIndex]) });
  }
  // Compare (frames 12a and 12b, rulings C1 and C2): a character's recorded decisions asked again,
  // exactly as asked, of a chosen model and once more of the model that answered each. The count and
  // the bounds are the server's offer; each ask is one D1 ask; nothing is applied.
  const decisionAsks = new DecisionAsksClient(credentials);
  const modelKey = (model) => model ? `${model.provider}/${model.modelId}` : '';
  /** The models to ask beside the recorded one: every model offered here but the character's own. */
  function compareModels(row) {
    if (!subjectReads.models) return null;
    const own = modelOf(row).model;
    return orderedModels(subjectReads.models.models).filter(item => !item.refusal && !(own && item.provider === own.provider && item.modelId === own.modelId));
  }
  /** [C] is drawn only where it works (C4, K6): a model to ask beside the character's own, and a decision a model answered. */
  const comparable = (showing) => !readOnly && Boolean(showing && compareModels(showing.row)?.length);
  const modelAnswered = (row) => Boolean(row?.requestId && row?.model);
  function readOffer(showing) {
    const compare = showing?.compare, model = compareModels(showing.row)?.[compare.focus];
    if (!model || compare.offers.has(modelKey(model))) return;
    const held = { offer: null, failed: false };
    compare.offers.set(modelKey(model), held);
    // One moment's offer names it, so a decision of any age is asked like any other (C4).
    decisionAsks.offer(entry.authoredVersionId, showing.row.scene.id, { provider: model.provider, modelId: model.modelId }, compare.single)
      .then(offer => { held.offer = offer; }, () => { held.failed = true; compare.offers.delete(modelKey(model)); })
      .finally(() => { if (showing === pageView) drawPage(); });
  }
  /** The offer's decisions this comparison asks: every one offered, or the one moment a decision named. */
  const comparedDecisions = (compare, offer) => (offer?.decisions ?? []).filter(decision => decision.askUsd !== null && (compare.single === null || decision.requestId === compare.single));
  const boundOf = (decisions) => decisions.reduce((sum, decision) => sum + Number(decision.askUsd.chosen) + Number(decision.askUsd.again ?? 0), 0);
  /** Ask each offered decision of the chosen model and once more of its own, one at a time, on Compare's page. */
  async function compareAsk(showing) {
    const compare = showing.compare, model = compareModels(showing.row)?.[compare.focus];
    const offer = model ? compare.offers.get(modelKey(model))?.offer : null;
    const decisions = comparedDecisions(compare, offer);
    if (!model || !decisions.length || offer.refusal) return;
    const chosen = { provider: model.provider, modelId: model.modelId };
    const steps = decisions.flatMap(decision => [
      { decision, which: 'other', model: chosen, bound: decision.askUsd.chosen, key: crypto.randomUUID() },
      ...(decision.askUsd.again !== null && decision.model ? [{ decision, which: 'again', model: decision.model, bound: decision.askUsd.again, key: crypto.randomUUID() }] : []),
    ]);
    const asking = { done: 0, total: steps.length, spent: 0, stop: false };
    const comparison = openComparison(showing, { decisions, other: model, single: compare.single !== null, asking });
    for (const step of steps) {
      // Stop sends nothing more; an ask already sent is answered and counted (C2).
      if (asking.stop || showing !== pageView || showing.comparison !== comparison) break;
      try {
        const answer = await decisionAsks.ask(entry.authoredVersionId, step.decision.requestId, step.model, step.bound, step.key);
        const pair = comparison.answers.get(step.decision.requestId) ?? {};
        pair[step.which] = answer;
        comparison.answers.set(step.decision.requestId, pair);
        asking.spent += Number(answer.costUsd) || 0;
      } catch { break; /* A refused ask ends the asking; what came back is shown (C2). */ }
      asking.done += 1;
      if (showing === pageView) drawPage();
    }
    comparison.asking = null;
    if (showing === pageView) drawPage();
  }
  function openComparison(showing, { decisions, other, single, asking }) {
    showing.compare = null;
    const page = openComparePage(root, action => comparisonAct(action));
    // The recorded model by the name the models read gives it: the newest moment's.
    const recorded = decisions.at(-1)?.model ?? null;
    const recordedName = recorded ? modelName({ provider: recorded.provider, model_id: recorded.modelId }) ?? recorded.modelId : modelOf(showing.row).model?.name ?? '';
    // The recorded model's own asks were all refused (each decision's again refusal): it could not be asked again (C3).
    const againRefused = decisions.every(decision => decision.askUsd?.again === null);
    showing.comparison = { page, decisions, answers: new Map(), other, single: single || decisions.length === 1, againRefused, recordedName, focus: Math.max(0, decisions.length - 1), details: new Map(), busy: false, asking, most: boundOf(decisions) };
    showing.page.hide(true);
    if (!pictures.still()) void pictures.takeStill().then(drawPage);
    // Who a line was said to is in the decision's own options: read once a moment.
    for (const decision of decisions) {
      modelsClient.readDecision(entry.authoredVersionId, decision.requestId).then(detail => {
        if (showing.comparison) { showing.comparison.details.set(decision.requestId, detail); if (showing === pageView) drawPage(); }
      }, () => {});
    }
    drawPage();
    return showing.comparison;
  }
  function closeComparison() {
    const showing = pageView;
    if (!showing?.comparison) return;
    showing.comparison.page.close(); showing.comparison = null;
    showing.page.hide(false); drawPage();
  }
  const comparisonState = () => records.comparison(pageView);
  function comparisonAct(action) {
    const comparison = pageView?.comparison;
    if (!comparison) return;
    // While the asks run, [Esc] Stop alone: nothing more is sent, and the page then shows what came back.
    if (comparison.asking) { if (action === 'back' || action === 'stop') { comparison.asking.stop = true; drawPage(); } }
    else if (action === 'back') closeComparison();
    else if ((action === 'earlier' || action === 'later') && !comparison.single) {
      comparison.focus = Math.max(0, Math.min(comparison.decisions.length - 1, comparison.focus + (action === 'earlier' ? -1 : 1)));
      drawPage();
    }
    else if (action === 'use' && !comparison.busy && pageState().assignable) void useCompared(pageView);
  }
  /** Use the asked model for the character (frame 12b's Enter), as Choose a model does. */
  async function useCompared(showing) {
    const comparison = showing.comparison;
    comparison.busy = true; drawPage();
    try {
      const { verified } = await recordEntityModel({ entry, subjectId: showing.row.scene.id, selected: comparison.other, key: crypto.randomUUID(), refresh: () => refreshSubject(showing.row), client: modelsClient, current: () => showing === pageView && current() });
      subjectReads.models = verified;
      if (showing === pageView) { showing.run.shown = runWatch.limits(verified); closeComparison(); }
    } catch (error) {
      if (showing === pageView) worldNotes.show(modelRefusalWords(error.code ?? 'stale', subjectView(showing.row).who));
    } finally { if (showing.comparison) { showing.comparison.busy = false; drawPage(); } }
  }
  /** The character's page (Enter): over the world, which keeps drawing, with the camera framing the character. */
  async function openPage(row) {
    if (!row || row.scene.type !== 'being' || pageShown()) return;
    asking = null; drawQuestion();
    stopFollowing();
    const page = openCharacterPage(root, (action, index) => pageAct(action, index));
    // Only a being its owner placed can have a personality: its inventory reference is the placed thing.
    const placedId = row.reference?.source === 'authored-thing' ? row.reference.id : null;
    pageView = { page, row, did: null, didFocus: null, events: [], ask: null, decision: null, compare: null, comparison: null, choosing: null, personality: null, editing: null, placedId, run: { busy: false, refusal: null, shown: runWatch.limits(subjectReads.models) }, before: { pose: { ...b.controls.state }, hold: b.controls.hold }, ease: null };
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
    const { page, before, decision, comparison } = pageView;
    pageView = null; page.close(); decision?.page.close(); comparison?.page.close(); pictures.release();
    b.controls.setView(before.pose, before.hold); b.invalidate();
    canvas.inert = false; b.setFreeCursorActive(false); b.setControlsEnabled(current());
    guidance.hidden = false; worlds.hidden = false; presence.setCovered(false); canvas.focus({ preventScroll: true });
  }

  const kindLabels = build?.kindLabels ?? createKindLabels(read, kindDocumentLabel);
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
      const placedBeings = new Map(rows.filter(row => row.scene?.type === 'being' && row.reference?.source === 'authored-thing').map(row => [row.reference.id, row]));
      const needed = new Set([...subjects.map(beingRow), ...placed.map(id => placedBeings.get(id))].filter(Boolean));
      await Promise.all([...needed].map(row => entityOffer(row).catch(() => null)));
      return {
        subject: calledWithin, speaker: (id) => calledAs(id).title,
        placed: (placedId) => (placedBeings.has(placedId) ? subjectView(placedBeings.get(placedId)).who.within : called({ name: null, kind: null }).within),
      };
    },
    build: build ? { undo: () => build.undo(), redo: () => build.redo() } : null,
    // Made creatures by their labels (J20): build mode's reader where it is mounted, else History's own.
    kindLabels,
    worldClock(tick) {
      // The society's own first minute, as characterFacts reads it; with no society there is no clock (K5).
      const state = subjectReads.society?.state;
      return worldTime(tick, state?.start_minute_of_day ?? state?.clock?.start_minute_of_day ?? null);
    },
    // The world's minute now, as the clock corner reads it, for Now where the moments read did not answer.
    worldNow: () => selection.people?.clock().minute ?? null,
    write: readOnly ? null : historyWrite(state.credentials, lifetime.signal), ...historyHooks(pictures),
    openDecision: (asked) => void openHistoryDecision(asked),
    open: (url) => { window.open(url, '_blank', 'noopener'); },
    closed() {
      otherPage = null; historyDecision?.page.close(); historyDecision = null; pictures.release();
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
    // The still behind History is taken before the page covers the world.
    void pictures.takeStill().finally(() => history.open());
  }
  // A decision from History ([Enter] See the decision): the r10 page over History, by its request.
  let historyDecision = null;
  async function openHistoryDecision({ requestId, subject }) {
    const row = subject ? beingRow(subject) : null;
    if (!requestId || !row) return;
    const showing = { row, events: [], moments: null, things: null, did: null };
    historyDecision?.page.close();
    historyDecision = { page: openDecisionPage(root, historyDecisionAct), showing, decision: { requestId, detail: null, failure: null, record: false } };
    drawHistoryDecision();
    const [detail] = await Promise.all([modelsClient.readDecision(entry.authoredVersionId, requestId).catch(() => null), records.readMoments(showing)]);
    // Its people named as History names them: their offers read first.
    const people = (showing.moments ?? []).filter(moment => moment.request_id === requestId || moment.said?.some(line => line.request_id === requestId)).flatMap(moment => moment.subjects ?? []);
    await Promise.all([...new Set(people.map(beingRow).filter(Boolean))].map(one => entityOffer(one).catch(() => null)));
    if (historyDecision?.showing !== showing) return;
    if (detail) historyDecision.decision.detail = detail; else historyDecision.decision.failure = DECISION_WORDS.unread;
    drawHistoryDecision();
  }
  const drawHistoryDecision = () => historyDecision?.page.draw(records.decision(historyDecision.showing, historyDecision.decision));
  function historyDecisionAct(action) {
    const decision = historyDecision?.decision;
    if (!decision) return;
    if (action === 'record' && decision.detail) { decision.record = !decision.record; drawHistoryDecision(); }
    else if (action === 'back' && decision.record) { decision.record = false; drawHistoryDecision(); }
    else if (action === 'back') { historyDecision.page.close(); historyDecision = null; }
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
    endPair(); // turning the camera oneself ends an exchange's framing (T5)
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
    if (!pageShown() && ['KeyW', 'KeyA', 'KeyS', 'KeyD', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Space'].includes(event.code)) endPair();
    if (!pageShown() && wakesHints(event)) corners.wake();
    if (!pageShown() && !event.repeat) corners.pressed(event.code);
    if (!pageShown() && event.code === 'Tab') corners.hold(true);
    if (!pageShown() && !asking && build?.key(event)) { event.stopImmediatePropagation(); return; }
    // History takes its keys; what it leaves (Tab, Enter on a focused button) keeps the browser's own
    // default, and no key reaches the old shell's listeners while it is open (K8).
    if (otherPage && historyDecision) {
      // A decision over History: Esc back (from the record to the decision, then to History), J the record.
      if (event.code === 'Escape' && !event.repeat) historyDecisionAct('back');
      else if (event.code === 'KeyJ' && !event.repeat) historyDecisionAct('record');
      if (event.code !== 'Tab' && !(historyDecision?.decision.record && ['ArrowUp', 'ArrowDown', 'PageUp', 'PageDown', 'Home', 'End', 'Space'].includes(event.code))) event.preventDefault();
      event.stopImmediatePropagation(); return;
    }
    if (otherPage) { otherPage.key(event); event.stopImmediatePropagation(); return; }
    if ((pageShown() || asking) && (event.metaKey || event.ctrlKey || event.altKey)) { event.stopImmediatePropagation(); return; }
    if (pageShown()) {
      // A page: Esc back, M model, N personality, R run or stop; while choosing a model, arrows and
      // Enter; while writing a personality, Enter saves, Esc cancels and every other key types.
      const choosing = pageView.choosing, ask = pageView.ask, decision = pageView.decision;
      const comparison = pageView.comparison, compare = pageView.compare;
      if (comparison) {
        // Compare's result (12b): the arrows step the moments, Enter uses the asked model, Esc goes back.
        if (event.code === 'Escape') { event.preventDefault(); if (!event.repeat) comparisonAct('back'); }
        else if (event.code === 'ArrowLeft' || event.code === 'ArrowRight') { event.preventDefault(); comparisonAct(event.code === 'ArrowLeft' ? 'earlier' : 'later'); }
        else if (event.code === 'Enter' && (event.target as Element | null)?.closest?.('.wu-page button')) return;
        else if (event.code === 'Enter' && !event.repeat) { event.preventDefault(); comparisonAct('use'); }
        else if (event.code === 'Tab') return;
        else event.preventDefault();
        event.stopImmediatePropagation(); return;
      }
      if (compare) {
        // Compare's question (12a): the arrows choose the model, Enter asks, Esc goes back, or stops while asking.
        // With nothing to ask, only Esc (C4).
        const nothing = Boolean(pageState().compare?.nothing);
        if (event.code === 'Escape') { event.preventDefault(); if (!event.repeat) pageAct('back'); }
        else if (nothing && event.code !== 'Tab') event.preventDefault();
        else if ((event.code === 'ArrowUp' || event.code === 'ArrowDown') && !compare.asking) {
          event.preventDefault();
          const last = (compareModels(pageView.row)?.length ?? 1) - 1;
          pageAct('compareChoose', Math.max(0, Math.min(last, compare.focus + (event.code === 'ArrowUp' ? -1 : 1))));
        }
        else if (event.code === 'Enter' && (event.target as Element | null)?.closest?.('.wu-page button')) return;
        else if (event.code === 'Enter' && !event.repeat) { event.preventDefault(); pageAct('compareStart'); }
        else if (event.code === 'Tab') return;
        else event.preventDefault();
        event.stopImmediatePropagation(); return;
      }
      if (decision) {
        // A decision: Esc back (from the record to the decision, then to the page), the arrows step
        // through the character's decisions, J shows the record, which the arrows then scroll.
        if (event.code === 'Escape') { event.preventDefault(); if (!event.repeat) decisionAct('back'); }
        else if (event.code === 'ArrowLeft' || event.code === 'ArrowRight') { event.preventDefault(); if (!event.repeat) decisionAct(event.code === 'ArrowLeft' ? 'earlier' : 'later'); }
        else if (event.code === 'KeyJ' && !event.repeat) { event.preventDefault(); decisionAct('record'); }
        else if (event.code === 'KeyC' && !event.repeat) { event.preventDefault(); decisionAct('compare'); }
        else if (decision.record && ['ArrowUp', 'ArrowDown', 'PageUp', 'PageDown', 'Home', 'End', 'Space'].includes(event.code)) return;
        else if (event.code === 'Tab') return;
        else event.preventDefault();
        event.stopImmediatePropagation(); return;
      }
      if (ask && !pageView.editing) {
        // Ask: the arrows choose a question, Enter asks it, Esc goes back to the rows.
        if (event.code === 'Escape') { event.preventDefault(); if (!event.repeat) pageAct('back'); }
        else if (event.code === 'ArrowUp' || event.code === 'ArrowDown') { event.preventDefault(); if (!ask.busy) { ask.focus = Math.max(0, Math.min(ASK_ASPECTS.length - 1, ask.focus + (event.code === 'ArrowUp' ? -1 : 1))); drawPage(); } }
        else if (event.code === 'Enter' && (event.target as Element | null)?.closest?.('.wu-page button')) return;
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
      else if (event.code === 'KeyC' && !choosing && !event.repeat && pageState().canCompare) { event.preventDefault(); pageAct('compare'); }
      else if (event.code === 'KeyQ' && !choosing && !event.repeat) { event.preventDefault(); pageAct('ask'); }
      else if (!choosing && (event.code === 'ArrowUp' || event.code === 'ArrowDown') && pageView.did?.length) {
        event.preventDefault();
        // The arrows step over the lines heard (T6).
        const step = event.code === 'ArrowUp' ? -1 : 1;
        let next = (pageView.didFocus ?? -1) + step;
        while (pageView.did[next]?.heard) next += step;
        if (pageView.did[next]) pageAct('row', next);
      }
      else if (choosing && ['ArrowUp', 'ArrowDown'].includes(event.code)) {
        event.preventDefault();
        const last = subjectReads.models?.models.length ?? 0;
        pageAct('choose', Math.max(0, Math.min(last, choosing.focus + (event.code === 'ArrowUp' ? -1 : 1))));
      }
      else if (choosing && event.code === 'Enter' && !event.repeat) { event.preventDefault(); pageAct('use'); }
      else if (event.code === 'Enter' && (event.target as Element | null)?.closest?.('.wu-page button')) return;
      else if (event.code === 'Enter' && !choosing && !event.repeat) { event.preventDefault(); pageAct('inspect'); }
      else if (event.code === 'Tab') return;
      else event.preventDefault();
      event.stopImmediatePropagation(); return;
    }
    // The model list (r07) keeps its keys; movement still moves.
    const listed = held ? picker.key(event, groupFirst, Boolean((event.target as Element | null)?.closest?.('.cw-beside button'))) : false;
    if (listed === 'pass') return;
    if (listed) { event.stopImmediatePropagation(); return; }
    if (asking) {
      // The question before a run keeps its answers together: Enter runs, Esc puts it away, P pauses first.
      if (event.code === 'Enter' && !event.repeat) { event.preventDefault(); if (!(event.target as Element | null)?.closest?.('.cw-beside button')) questionAct('run'); else return; }
      else if (event.code === 'Escape' && !event.repeat) { event.preventDefault(); questionAct('back'); }
      else if (event.code === 'KeyP' && asking.refusal === 'society_not_paused' && !event.repeat) { event.preventDefault(); questionAct('pause'); }
      else if (event.code === 'KeyM' && groupActions.has('model') && !event.repeat) { event.preventDefault(); act('model'); }
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
      if (event.code === 'Enter' && (event.target as Element | null)?.closest?.('.cw-beside button,.wu-prompt,.wu-scene button')) return;
      if (event.code === 'Enter' && root.dataset.scene === 'talking') { event.preventDefault(); if (!event.repeat) openSpeakerPage(); event.stopImmediatePropagation(); return; }
      if (event.code === 'Enter' && being) { event.preventDefault(); if (!event.repeat) act('details'); event.stopImmediatePropagation(); return; }
      if (event.code === 'KeyR' && being) { event.preventDefault(); if (!event.repeat) act(runWatch.run ? 'stop' : 'run'); event.stopImmediatePropagation(); return; }
      if (event.code === 'KeyV' && being) { event.preventDefault(); if (!event.repeat) act('follow'); event.stopImmediatePropagation(); return; }
      if (event.code === 'KeyM' && being && groupActions.has('model')) { event.preventDefault(); if (!event.repeat) act('model'); event.stopImmediatePropagation(); return; }
    }
    const fate = worldKey(event, { flying: Boolean(b.controls.flying), clock: corners.hasClock(), history: historyHere, bringIn: corners.offersBringIn() }, Boolean((event.target as Element | null)?.closest?.('.cw-beside button,.wu-prompt')));
    if (fate === 'move' || fate === 'pass') return;
    if (fate !== 'quiet') event.preventDefault();
    if (fate === 'inspect') void choose();
    else if (fate === 'leave') { if (!corners.closeKeys()) leaveWorld(); }
    else if (fate === 'play') corners.togglePlay();
    else if (fate === 'bring-in') corners.bringIn();
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
    // The Back corner says Back while something is chosen, the Run question and the model list included (r07, r08):
    // they are the group's own states, and Esc goes back from them.
    if (!build?.active()) corners.back(held ? CORNER_WORDS.back : CORNER_WORDS.yourWorlds); // build mode keeps its own
    corners.reticle.hidden = pageShown();
    corners.reticle.dataset.state = target ? targetReachable ? 'ready' : 'far' : 'empty';
    root.dataset.reachable = String(targetReachable);
    root.dataset.focusDistance = Number.isFinite(distance) ? distance.toFixed(2) : '';
    if (target || held) refreshSubjectReads(now);
    // What pops now (T2: nothing while the world is paused), and the exchange a followed character is in (T5).
    const shownPops = shownWhile(talk, selection.people?.clock().mode ?? null, now);
    shownNow = shownPops;
    framePair(now, shownPops);
    // Following a conversation turns the view into its scene (T9); the two people's lines and the card
    // give way to it.
    const exchange = following && held ? exchangeOf(shownPops, held.scene.id) : null;
    scene.follow(following && held ? held.scene.id : null, shownPops);
    const scened = scene.shown(now, exchange);
    drawScene(scened);
    const inScene = new Set(scened.showing ? [held.scene.id, exchange?.other ?? scened.now.to, scened.now.speaker].filter(Boolean) : []);
    const looking = !pageShown() && !asking && !dragging && targetReachable && target.key !== held?.key && targetFrame?.headInView && seen(target, targetFrame);
    if (looking) {
      const view = subjectView(target);
      if (!view.offer && !offers.has(target.key) && readBackoff.ready(target.key, performance.now())) void entityOffer(target).catch(() => {});
      presence.look(tagWords({ who: view.who, being: view.being, doing: view.doing, model: view.chip ?? null, live: Boolean(runWatch.run && view.model), popping: shownPops.some(item => item.subjectId === target.scene.id) }), { x: targetFrame.overhead.x, y: targetFrame.overhead.y }, true);
    } else presence.look(null);
    // Chosen: the ring at its feet, drawn in the world so walls cover it as they cover the feet (J21),
    // and the card beside it while it is seen, placed from the ring's projected ellipse; both follow it.
    if (held) {
      const view = subjectView(held), { connected } = modelOf(held);
      // A chosen character: the group beside them (J30); a chosen thing keeps its card.
      const grouped = view.being ? chosenGroup(held, now) : null;
      groupActions = new Set(grouped?.rows.map(row => row.action) ?? []); groupFirst = grouped?.list?.first ?? 0;
      presence.group(grouped);
      presence.choose(view.being ? null : chosenCard({ who: view.who, being: view.being, doing: view.doing, decision: view.decision, model: view.model ?? null, decider: view.decider ?? null, deciderChose: view.deciderChose === true,
        running: Boolean(runWatch.run), connected, following: followView.active(), reading: false, thingLine: view.thingLine ?? null }));
      const heldFrame = screenFrame(held);
      const ring = heldFrame ? ringAt(heldFrame) : null;
      // The talking scene draws no ring (r24): it marks whoever speaks with its dot instead.
      if (ring && !scened.showing) groundRing.place(heldFrame.ground, PERSON_RING_METRES); else groundRing.hide();
      if (ring && seen(held, heldFrame) && !scened.showing) {
        const headY = heldFrame.headInView ? heldFrame.overhead.y : heldFrame.top;
        // The projected points run down the character's middle; its body reaches about 0.4 of the
        // ring's radius either side, so the card keeps clear of the shoulder as frame 05 does.
        const half = ring.rx * BODY_HALF_WIDTH;
        presence.place({ bounds: { left: Math.min(heldFrame.left, ring.x - half), right: Math.max(heldFrame.right, ring.x + half), top: heldFrame.top, bottom: heldFrame.bottom,
          headY, waistY: headY + (ring.y - headY) * CARD_WAIST }, prefer: awaySide(shownPops, ring.x), head: { x: heldFrame.headInView ? heldFrame.overhead.x : ring.x, y: headY } });
      } else presence.place(null);
    } else groundRing.hide();
    // Lines over whoever said one or whose mind chose something (N28 section 4, T1 to T4): within hearing,
    // 24 px over the head and never nearer an edge of the view than the edge inset; two that would
    // overlap stack, the earlier above. A line said off screen by someone the person attends to sits at
    // the view's side nearest them (T8); a line said beyond hearing names its people instead (section 5).
    const s = popScale(), inset = insetNow(), placedPops = [], beyond = [];
    const safeTop = BESIDE.top * s, safeBottom = innerHeight - BESIDE.bottom * s;
    const asked = runWatch.run ? new Set((subjectReads.models?.choices ?? []).filter(choice => choice.model).map(choice => choice.subjectId)) : null;
    for (const shown of shownPops) {
      const row = beingRow(shown.subjectId), frameOf = row && screenFrame(row);
      const listener = shown.said && shown.to && shown.to !== shown.subjectId ? beingRow(shown.to) : null;
      const heard = listener ? screenFrame(listener) : null;
      const onScreen = Boolean(frameOf?.headInView && seen(row, frameOf));
      const attended = shown.subjectId === held?.scene.id || Boolean(asked?.has(shown.subjectId)) || Boolean(heard?.headInView && seen(listener, heard));
      const how = row ? popPlacement({ onScreen, metres: reachDistance(row), chosen: shown.subjectId === held?.scene.id, attended }) : 'none';
      let part = speechParts.get(shown.subjectId);
      if (how === 'far' || how === 'none' || inScene.has(shown.subjectId)) {
        part?.away();
        if (how === 'far' && !inScene.has(shown.subjectId)) beyond.push(shown.subjectId, ...(listener ? [listener.scene.id] : []));
        continue;
      }
      if (!part) { part = speech(); beside.append(part.root); speechParts.set(shown.subjectId, part); }
      if (listener && !offers.has(listener.key) && readBackoff.ready(listener.key, now)) void entityOffer(listener).catch(() => {});
      const to = shown.said && shown.to && shown.to !== shown.subjectId ? whoOf(shown.to) : null;
      part.draw({ label: speechLabel(whoOf(shown.subjectId), to), words: shown.words, said: shown.said, earlier: shown.earlier, leaving: shown.leaving });
      const { width, height } = part.size();
      if (how === 'over') {
        const tagShown = row.key === target?.key && looking ? presence.tagTop() : null;
        const over = headOnScreen(row) ?? frameOf.overhead;
        placedPops.push({ id: shown.subjectId, part, serial: shown.serial, x: popLeft(over.x, width, innerWidth, inset), y: (tagShown ?? over.y) - height - OVER_HEAD.speech * s, width, height });
      } else {
        // Off screen (T8): the side the speaker stands on from where the camera looks, at the height a
        // line over them would take, or the safe area's middle where they stand behind the camera.
        const head = targetPoint(row, true);
        if (!head) { part.away(); continue; }
        const eye = b.camera.getPosition(), at = b.camera.camera.worldToScreen(head);
        const right = head.clone().sub(eye).dot(b.camera.right) >= 0;
        const overY = at.z > 0 && Number.isFinite(at.y) ? at.y - height - OVER_HEAD.speech * s : null;
        placedPops.push({ id: shown.subjectId, part, serial: shown.serial, ...edgePlace({ right, overY, width, height, viewWidth: innerWidth, inset, top: safeTop, bottom: safeBottom }), width, height });
      }
    }
    // Lines keep clear of the looked-at name tag over someone else, as of each other (T4).
    const tagBox = looking ? presence.tagBox() : null;
    const tops = stackPops(placedPops, STACK_GAP * s, tagBox ? [tagBox] : []);
    // Inside the area the side card keeps, under the top corners and the Running strip and above the
    // hints; one that would rise above it sits at its edge (L21).
    for (const item of placedPops) item.part.place(item.x, Math.max(safeTop, Math.min(safeBottom - item.height, tops.get(item.serial) ?? item.y)));
    for (const [subjectId, part] of speechParts) if (!shownPops.some(item => item.subjectId === subjectId)) { part.remove(); speechParts.delete(subjectId); }
    // Names over people farther off (N28 section 5): the people of a line said beyond hearing and the
    // person chosen last, seen; never one whose line shows, who carries the looked-at tag or is chosen
    // now; the person chosen last first, then the nearest, three at most.
    if (held?.scene.type === 'being') lastChosen = held.scene.id;
    const showing = new Set(placedPops.map(item => item.id));
    if (looking) showing.add(target.scene.id);
    if (held) showing.add(held.scene.id);
    for (const id of inScene) showing.add(id);
    const candidates = [];
    if (!pageShown()) {
      for (const id of new Set([...beyond, ...(lastChosen ? [lastChosen] : [])])) {
        const row = beingRow(id), frameOf = row && screenFrame(row);
        if (frameOf?.headInView && seen(row, frameOf) && frameOf.bottom - frameOf.top >= NAMED_LEAST_PX * s) candidates.push({ id, metres: reachDistance(row), last: id === lastChosen });
      }
    }
    const named = namedPeople(candidates, showing);
    // Each name is measured on its own label; names that would overlap become one label centred over them,
    // "Marco and Ines" (T10), drawn on a label of its own so no label's words change from frame to frame.
    const boxes = [], together = new Set();
    for (const id of named) {
      let part = nameParts.get(id);
      if (!part) { part = nameOver(); beside.append(part.root); nameParts.set(id, part); }
      const row = beingRow(id);
      // A name needs the person's own offer, as a listener's does; until it is read, their kind names them.
      if (!offers.has(row.key) && readBackoff.ready(row.key, now)) void entityOffer(row).catch(() => {});
      part.draw(whoOf(id).start);
      const over = headOnScreen(row) ?? screenFrame(row).overhead, { width, height } = part.size();
      boxes.push({ id, part, over, x: over.x - width / 2, y: over.y - height - OVER_HEAD.name * s, width, height });
    }
    for (const group of nameGroups(boxes)) {
      const members = group.map(id => boxes.find(box => box.id === id));
      if (members.length === 1) { members[0].part.place(members[0].x, members[0].y); continue; }
      for (const member of members) member.part.away();
      const key = group.join(' ');
      together.add(key);
      let part = togetherParts.get(key);
      if (!part) { part = nameOver(); beside.append(part.root); togetherParts.set(key, part); }
      part.draw(togetherNames(group.map((id, index) => index ? whoOf(id).within : whoOf(id).start)));
      const { width, height } = part.size(), x = members.reduce((sum, member) => sum + member.over.x, 0) / members.length;
      part.place(x - width / 2, Math.min(...members.map(member => member.over.y)) - height - OVER_HEAD.name * s);
    }
    for (const [id, part] of nameParts) if (!named.includes(id)) { part.remove(); nameParts.delete(id); }
    for (const [key, part] of togetherParts) if (!together.has(key)) { part.remove(); togetherParts.delete(key); }
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
    groundRing.dispose();
    runWatch.dispose();
    corners.dispose();
    if (pageView) { pageView.page.close(); pageView.decision?.page.close(); pageView.comparison?.page.close(); pageView = null; }
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
  // People brought in (K13) are in the world's read from then on: read it again so they can be looked at and chosen.
  corners.people.onChange(() => { if (selection.people?.clock().society === 'present') void readInventory(); });
  await readInventory();
  canvas.focus({ preventScroll: true }); frameId = requestAnimationFrame(frame);
  // Arriving (frame 02): the opening gives way, and the world's name shows once with who lives here.
  // A world Create a world just made (frame 22, N14) says so instead, with no sub-line, and its made
  // note waits until the first key or click, which still acts in the world; Blank opens in build
  // mode, with neither (N4). The handoff is read once, for this world only.
  let made = null;
  try {
    made = readMade(sessionStorage.getItem(MADE_HANDOFF_KEY), entry.entryId);
    if (made !== null) sessionStorage.removeItem(MADE_HANDOFF_KEY);
  } catch { /* No handoff: an ordinary arrival. */ }
  const opened = endOpening();
  if (made?.build) {
    // The same act as a press of B.
    build?.key(new KeyboardEvent('keydown', { code: 'KeyB', key: 'b' }));
  } else if (opened || made !== null) {
    const banner = made !== null
      ? areaBanner({ name: entry.title, over: CREATE_WORDS.madeFromYourWords })
      : areaBanner({ name: entry.title, sub: populationLine(selection.people?.clock().population ?? null) ?? undefined });
    root.append(banner.root);
    void banner.play().then(() => banner.remove());
    if (made !== null && made.columns.length > 0) {
      const note = madeNote(made.columns);
      root.append(note.root);
      const gone = new AbortController();
      lifetime.signal.addEventListener('abort', () => gone.abort(), { once: true });
      const dismiss = () => { note.dismiss(); gone.abort(); };
      window.addEventListener('keydown', dismiss, { capture: true, signal: gone.signal });
      window.addEventListener('pointerdown', dismiss, { capture: true, signal: gone.signal });
    }
  }
}
