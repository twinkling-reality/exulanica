// Build mode in the world workspace. B switches it on and off while the world keeps playing. In it,
// pointing at a thing placed in the world names it, a click selects it (its outline and a ring at its
// foot), and the group at the right names it with a large key and one word for each thing that works
// now (ruling W10). Dragging it carries a see-through copy along the ground and `[` `]` turn it (half
// metres and 15 degree steps, Alt for free); the server says whether it may stand there while it
// moves and when it is let go, and Enter or a click places it there, Esc puts it back. Delete asks
// the server what removing it would do and Enter does it; while it is being moved, Delete puts it
// back first. The tray along the bottom holds the things this world may place, as pictures: picking
// one carries its see-through copy under the pointer, asked of the server as it rests, and a click or
// Enter places it; "Make a creature" opens the page's own maker, and the page that makes one holds it at its
// stand the same way (`hold`). Cmd+Z takes back the world's newest
// change, and Cmd+Shift+Z does the last change taken back again. Tab and Shift+Tab choose the next or
// previous placed thing in view, so selecting needs no pointer. History, the page H opens, takes
// changes back through the same `undo` and `redo` this returns. Every write goes through the app's own
// edit path (`send`, main.ts's sendPlanned), which advances the saved world and redraws what changed;
// every write is asked of the server first as a preview, and only the server's answer is shown.
// In a site world (one made from a world kind) the parts made with the world (a building, a garden
// fixture, a pond or field) are chosen, moved, turned a quarter at a time and removed the same way,
// through the parts routes; after a change the made world is drawn again (main.ts).
// It is drawn with build mode's own parts (world-ui-build.ts) and the world's corners (the Building
// pill, the keys card and the note); what a key does in each state, and every sentence, is
// build-words.mjs.
import { pointerRay } from '../../../web/packages/atlas-react/src/playcanvas/index.ts';
import { pickSiteSlot } from '../../../web/packages/app/src/composition/sight.ts';
import { currentOpenSite } from '../../../web/packages/app/src/composition/site-world.ts';
import { kindDocumentLabel } from '../../../web/packages/app/src/composition/visitor-notices.ts';
import { BUSY, REDO_KEY, TRAY, UNDO_KEY, buildKeys, changeParts, createKindLabels, heldRows, keyAction, namesTogether, nothingInView, previewParts, redoRefusalWords, refusalWords, removeLine, removeTitle, snapped, thingName, titled, turned, turnedInPlace, undoRefusalWords } from './build-words.mjs';
import { youChangeWords } from './history-words.mjs';
import { keyWord, nameTag, outline, path, scaleOf } from './world-ui.ts';
import { heldGroup, namesNear, tray, type TrayTab } from './world-ui-build.ts';
import { NOTE_WORDS } from './world-words.mjs';

/** How long a carried thing rests before the server is asked about where it is, in milliseconds. */
const ASK_AFTER_MS = 180;
/** How much wider than the footprint's half diagonal the ring at a thing's foot is, so it encloses the outline's corners. */
const RING_MARGIN = 1.18;
/** How far below the eye a point grabbed on a thing is carried at most, in metres, so the pointer's ray still comes down to it. */
const GRAB_BELOW_EYE_M = 0.25;
/** How far ahead of the eye a chosen thing's footprint is cut where it reaches behind the camera, in metres. */
const MARK_NEAR_M = 0.05;
/**
 * The chosen thing's ground ring, quieter than a character's (DESIGN's ruling L22): the outline is
 * the primary mark, so the ring is a thinner white line with no glow and no fill. Spread over the
 * ground ring's look.
 */
export const THING_RING = Object.freeze({ linePx: 1.6, glowAlpha: 0, fillAlpha: 0 });
/** How a made part is named where a placed thing's id would be: chosen, carried, pointed at. */
const PART = 'part:';
/** The four turns a made part can take, microradians, as the parts routes state them. */
const QUARTER_TURNS = [0, 1_570_796, 3_141_593, 4_712_389];
const quarterOf = (yaw) => Math.max(0, QUARTER_TURNS.indexOf(yaw));
/** How near a held thing someone stands to be named over their head, and how near two stand to be named together, in metres. */
const NAMES_NEAR_M = 8;
const TOGETHER_M = 2;
/** The most names shown over people at once, nearest first, so the view stays the world's. */
const NAMES_AT_MOST = 3;
/** How often the names over people are chosen again, in milliseconds (a frame only moves them). */
const NAMES_EVERY_MS = 200;
/**
 * The tray's tile pictures, reference pixels (frame r13), never smaller than the sheet's 1440 tiles
 * (world-ui-build.css's floors), drawn at the screen's pixel density.
 */
const TILE_PICTURE = { width: 112, height: 84, leastWidth: 96, leastHeight: 72 };
/** The first tile of the tray, which opens the page's creature maker. */
const MAKE_TILE = 'make';
/** How long build mode waits before mounting the placed things' layer again after a mount left no library, in milliseconds. */
const LAYER_RETRY_MS = 5000;
/** How a hold ends: what it held placed, by the new thing's id, or let go unplaced. */
export type HoldOutcome = { readonly outcome: 'placed'; readonly thingId: string } | { readonly outcome: 'put-back' };
const PUT_BACK: HoldOutcome = Object.freeze({ outcome: 'put-back' });

export function mountBuildMode({ b, root, state, entry, read, send, binding, canvas, corners, inspecting, groundRing = null, people = null, makeCreature = null }) {
  const lifetime = new AbortController();
  const listen = (target, type, run, options = {}) => target.addEventListener(type, run, { ...options, signal: lifetime.signal });
  const scale = () => scaleOf(root);
  const versionPath = '/world/versions/' + encodeURIComponent(entry.authoredVersionId);
  const worldQuery = '?world_id=' + encodeURIComponent(entry.worldId);

  const tag = nameTag({ scale });
  const group = heldGroup();
  const names = namesNear();
  const trayView = tray({
    words: { label: TRAY.label, things: TRAY.things, creatures: TRAY.creatures },
    onTab: (tab) => { trayTab = tab; if (tab === 'creatures') void readCreatures(); render(); },
    onPick: (tile) => pick(tile),
  });
  const chosen = outline(), copy = outline({ form: 'copy' }), origin = outline({ form: 'origin' }), trail = path();
  root.append(origin.root, trail.root, chosen.root, copy.root, names.root, tag.root, group.root, trayView.root);
  // The note stands 12 above the tray, whatever the tray's height at this size.
  const trayHeight = new ResizeObserver(() => {
    if (trayView.root.hidden) return;
    root.style.setProperty('--wu-tray-top', `${(trayView.root.offsetHeight + 32 * scale()).toFixed(1)}px`);
  });
  trayHeight.observe(trayView.root);

  let on = false, hovered = null, selected = null, confirming = null, busy = false, failure = '';
  /** Whether the server refused removing what is chosen: its rows then offer moving it only. */
  let removeRefused = false;
  /**
   * A move being made: the thing, where it stands (`from`) and where it would stand (`to`, region
   * frame: east, up, south in millimetres, yaw in microradians), the grip while it is dragged, and
   * the server's newest answer about `to` (`verdict`: checking, ready or refused, with its words).
   */
  let moving = null, asked = 0, askTimer = 0;
  /**
   * A new thing being placed from the tray: its tile, its kind as a placed thing names it, its name,
   * the region and id it would be placed under, where it would stand (`to`, as a move's) and the
   * server's newest answer about it (`verdict`, as a move's); `settle`, for one held by `hold`, is told
   * how it ended.
   */
  let placing = null;
  let records = new Map(), pointer = null, lastPick = 0, lastNames = 0;
  /** A site world's made parts as the parts read gives them, by `part:<id>`; none in any other world. */
  let parts = new Map();
  /**
   * The version's changes to its parts by part id, as the parts read states them: a move's pose
   * is turned from how the part was made, so its turns as the version stands are the change's
   * (`quarter_turns`), none where it has no change; the read's own turns are the part's turns in all.
   */
  let partChanges = new Map();
  const turnsNow = (id) => partChanges.get(id.slice(PART.length))?.quarter_turns ?? 0;
  const isPart = (id) => typeof id === 'string' && id.startsWith(PART);
  const partOf = (id) => parts.get(id) ?? null;
  const exists = (id) => (isPart(id) ? parts.has(id) : records.has(id));
  // A site's made parts are its structured drawing's slots; a terrain drawing has none.
  const siteDrawing = () => { const drawing = currentOpenSite()?.drawing() ?? null; return drawing !== null && 'slots' in drawing ? drawing : null; };
  const slotOf = (id) => siteDrawing()?.slots?.find(slot => slot.identity === id.slice(PART.length)) ?? null;
  /** The region a made world is drawn in, where new things are placed; null in a world drawn otherwise, which offers no tray. */
  const placingRegion = () => entry.generatedSite?.regionId ?? entry.generatedGround?.regionId ?? null;
  const regionRoot = (regionId = entry.generatedSite?.regionId ?? null) => (regionId ? b.regionRoots?.get(regionId) ?? null : null);
  /** The first read of the version's things after B, which a click made before it ends waits for. */
  let reading = null;
  /** The tray's open tab, the made creatures as GET /things/kinds lists them (null until read), and whether the server could be read. */
  let trayTab: TrayTab = 'things', creatures = null, creaturesRead = null, offline = false;
  /**
   * The placed things' layer, which the tray reads the library through and draws its pictures and
   * copies with: the page mounts it once something is placed, and build mode mounts it itself in a
   * world where nothing is yet (`__workspaceMountThings`, the mount a society uses). A mount that
   * leaves no library is asked again after a pause; until then the Things tab says the world's own
   * offline line.
   */
  let layerMounting = null, layerUnread = false, layerAskedAt = -Infinity;
  /** Each tile's picture once drawn, by tile id. */
  const pictures = new Map();
  /** What the tray and the held group were last drawn with, so an unchanged state draws nothing again (a drag renders every move). */
  let trayDrawn = '', groupDrawn = '';
  /** What the corners show now, so they are told only when it changes. */
  let cornersShow = '';
  /**
   * The projected points the marks were last placed at, so a still view places nothing; cleared
   * whenever the group is drawn again.
   */
  let lastPlacedKey = '';
  const point = b.camera.getPosition().clone(), seen = point.clone(), feet = point.clone(), heldAt = point.clone();
  let wasInspecting = false;

  const things = () => b.__workspaceThings?.() ?? null;
  const focused = () => group.root.contains(document.activeElement) || trayView.root.contains(document.activeElement);
  const flags = () => ({
    on, selected: selected !== null, placing: placing !== null, confirming: confirming !== null, moving: moving !== null,
    ready: (placing ?? moving)?.verdict.state === 'ready', refused: (placing ?? moving)?.verdict.state === 'refused',
    busy, removeRefused, focused: focused(),
  });

  /** The note above the tray; a change it reports can be taken back from it, and an undo done again (W12.3). */
  function say(words, { undoable = false, redoable = false } = {}) {
    if (!words) { corners.notes.clear(); return; }
    const prompt = undoable ? keyWord({ ...UNDO_KEY, small: true, onPress: () => { void undo(); } })
      : redoable ? keyWord({ ...REDO_KEY, small: true, onPress: () => { void redo(); } }) : null;
    corners.notes.show(words, prompt ? { prompt } : {});
  }
  function problem(error) {
    const detail = typeof error?.code === 'string' && typeof error.message === 'string' && error.message.startsWith(error.code + ': ') ? error.message.slice(error.code.length + 2) : '';
    return refusalWords(error?.code ?? null, detail);
  }

  /** The version's placed things as the server holds them now, by their placed id. */
  async function refreshRecords() {
    const version = await read(versionPath + worldQuery);
    if (version.version_id !== entry.authoredVersionId || version.world_id !== entry.worldId) throw Error('This world changed. Reload it before building.');
    records = new Map((version.things || []).filter(thing => !thing.removed).map(thing => [thing.thing_id, thing]));
    await refreshParts();
  }

  /** A site world's made parts as they stand; a world not made from a kind has none, and while its worker is busy the last read stands. */
  async function refreshParts() {
    if (!entry.generatedSite) return;
    try {
      const answered = await read(versionPath + '/parts' + worldQuery);
      parts = new Map((answered.parts || []).map(part => [PART + part.part_id, part]));
      partChanges = new Map((answered.changes || []).map(change => [change.identity, change]));
    } catch { /* Read again after the next change. */ }
  }

  /** The placed things in view now, nearest first: what Tab chooses among. */
  function inView() {
    const layer = things()?.layer;
    if (!layer) return [];
    const eye = b.camera.getPosition(), found = [];
    for (const { placedId } of layer.drawn) {
      const figure = layer.figureOf(placedId);
      if (!records.has(placedId) || !figure || !figure.root.enabled) continue;
      const screen = b.camera.camera.worldToScreen(figure.markAnchor(point));
      if (screen.z <= 0 || screen.x < 0 || screen.x > innerWidth || screen.y < 0 || screen.y > innerHeight) continue;
      found.push({ placedId, distance: eye.distance(figure.root.getPosition()) });
    }
    const site = regionRoot();
    if (site) for (const [id, part] of parts) {
      const slot = slotOf(id);
      site.getWorldTransform().transformPoint(point.set(part.centre_mm[0] / 1000, (slot?.positionMm[2] ?? 0) / 1000 + 1, -part.centre_mm[1] / 1000), point);
      const distance = eye.distance(point);
      const screen = b.camera.camera.worldToScreen(point, seen);
      if (screen.z <= 0 || screen.x < 0 || screen.x > innerWidth || screen.y < 0 || screen.y > innerHeight) continue;
      found.push({ placedId: id, distance });
    }
    return found.sort((a, c) => a.distance - c.distance || (a.placedId < c.placedId ? -1 : 1)).map(item => item.placedId);
  }
  function cycle(step) {
    const ids = inView();
    const at = selected === null ? -1 : ids.indexOf(selected);
    // Past the last thing in view, Tab moves into the tray: its open tab, then its tiles.
    const tab = trayView.root.hidden ? null : trayView.root.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]');
    if (step > 0 && tab && (ids.length === 0 || at === ids.length - 1)) { tab.focus(); return; }
    if (!ids.length) { say(nothingInView()); return; }
    select(ids[at === -1 ? (step > 0 ? 0 : ids.length - 1) : (at + step + ids.length) % ids.length]);
  }

  /**
   * The placed thing or made part a screen point meets first, or null: a person or an object in front
   * hides it, and a part is met by its box in the drawing the world shows now.
   */
  function placedAt(x, y) {
    return pickedAt(x, y)?.id ?? null;
  }
  /** What `placedAt` meets, with how far along the pointer's ray (metres) and the ray itself, or null. */
  function pickedAt(x, y) {
    if (!b.__workspacePick) return null;
    const ray = pointerRay(b, x, y); if (!ray) return null;
    const hit = b.__workspacePick(ray.origin, ray.direction);
    if (hit?.inhabitantId) return null;
    const thingId = hit?.thing?.pick?.placedId ?? null;
    const thing = thingId !== null && records.has(thingId) ? { id: thingId, distance: hit.thing.distance, ray } : null;
    const drawing = parts.size ? siteDrawing() : null;
    const part = drawing ? pickSiteSlot(drawing, ray.origin, ray.direction, (id) => parts.has(PART + id)) : null;
    if (part !== null && (thing === null || part.distance < thing.distance)) return { id: PART + part.identity, distance: part.distance, ray };
    return thing;
  }

  /**
   * A creature its workspace made is called by its kind's own label (rulings J20, J23), read once by
   * digest and again after a failed read's pause; until it arrives build mode says "creature", and
   * draws its group again when it does.
   */
  const kindLabels = createKindLabels(read, kindDocumentLabel);
  kindLabels.listen(() => { if (on && !lifetime.signal.aborted) render(); });
  const kindLabel = (kind) => kindLabels.label(kind);
  function nameOf(id) { return isPart(id) ? partOf(id)?.label ?? 'part' : thingName(records.get(id), kindLabel); }

  // ---------- The tray ----------

  /** The kinds this world may place as tiles: the shipped library's objects, the latest version of each, in its order. */
  function thingTiles() {
    const library = things()?.layer?.maker?.library ?? null;
    if (library === null) { mountLayer(); return layerUnread && layerMounting === null ? [] : null; }
    layerUnread = false;
    const latest = new Map();
    for (const kind of library.list.kinds) {
      if (kind.class === 'object' && (latest.get(kind.kind)?.version ?? 0) < kind.version) latest.set(kind.kind, kind);
    }
    return [...latest.values()].map(kind => {
      const named = { kind: kind.kind, version: kind.version, sha256: kind.sha256 };
      return { id: 'kind:' + kind.kind, name: titled(thingName({ kind: named })), kind: named, picture: pictures.get('kind:' + kind.kind) ?? null };
    });
  }
  /** Mount the placed things' layer where nothing placed has mounted it, once a pause, and draw the tray again after. */
  function mountLayer() {
    if (layerMounting !== null || performance.now() - layerAskedAt < LAYER_RETRY_MS) return;
    if (typeof b.__workspaceMountThings !== 'function') { layerUnread = true; return; }
    layerAskedAt = performance.now();
    layerMounting = Promise.resolve()
      .then(() => b.__workspaceMountThings())
      .then(() => {}, () => {})
      .finally(() => {
        layerMounting = null;
        layerUnread = !things()?.layer?.maker?.library;
        if (lifetime.signal.aborted || !on) return;
        render();
        if (layerUnread) window.setTimeout(() => { if (on && !lifetime.signal.aborted) render(); }, LAYER_RETRY_MS);
      });
  }
  /** The creatures this workspace made as tiles, newest first, each by its own label. */
  function creatureTiles() {
    if (creatures === null) return null;
    return creatures.map(made => {
      const named = { source: 'workspace', sha256: made.sha256 };
      return { id: 'made:' + made.sha256, name: titled(thingName({ kind: named }, () => made.label)), kind: named, picture: pictures.get('made:' + made.sha256) ?? null };
    });
  }
  /** The made creatures, read when their tab first opens and again after one is placed. */
  async function readCreatures(again = false) {
    if (creaturesRead !== null && !again) return creaturesRead;
    creaturesRead = (async () => {
      try {
        const listed = await read('/things/kinds');
        // Each kind the workspace holds once, its newest version (the listing is newest first), placed by its
        // digest alone as a workspace kind: never by a key its maker's words made.
        const seenKinds = new Set();
        creatures = (listed.kinds || []).filter(kind => {
          if (typeof kind?.sha256 !== 'string' || !/^[0-9a-f]{64}$/u.test(kind.sha256)) return false;
          const key = typeof kind.kind === 'string' ? kind.kind : kind.sha256;
          if (seenKinds.has(key)) return false;
          seenKinds.add(key);
          return true;
        }).map(kind => ({ sha256: kind.sha256, label: typeof kind.label === 'string' ? kind.label : '' }));
        offline = false;
      } catch { creatures ??= []; offline = true; creaturesRead = null; }
      if (on && !lifetime.signal.aborted) render();
    })();
    return creaturesRead;
  }
  /** The tile of what is held: a new thing's, or a moved thing's own kind. */
  function heldTile() {
    if (placing !== null) return placing.tileId;
    const kind = moving === null || isPart(moving.placedId) ? null : records.get(moving.placedId)?.kind;
    if (!kind) return null;
    return kind.source === 'workspace' ? 'made:' + kind.sha256 : 'kind:' + kind.kind;
  }
  function drawTray() {
    if (!on || inspecting() || placingRegion() === null) { trayView.hide(); trayDrawn = ''; return; }
    const tiles = trayTab === 'things' ? thingTiles() : creatureTiles();
    const make = makeCreature ? [{ id: MAKE_TILE, name: TRAY.make, picture: null, make: true }] : [];
    // The library could not be read: the world's own offline line, the tiles dimmed, until it can.
    const unread = trayTab === 'things' && tiles !== null && layerUnread;
    const drawn = { tab: trayTab, tiles: tiles === null ? null : [...make, ...tiles], held: heldTile(), offline: offline || unread, empty: unread ? NOTE_WORDS.offline : trayTab === 'things' ? TRAY.noThings : TRAY.noCreatures };
    const key = JSON.stringify([drawn.tab, drawn.tiles?.map(tile => [tile.id, tile.name]) ?? null, drawn.held, drawn.offline, drawn.empty]);
    if (key !== trayDrawn || trayView.root.hidden) { trayDrawn = key; trayView.set(drawn); }
    if (tiles !== null) drawPictures(tiles);
  }
  /** Each tile's picture, drawn once by the world's own renderer and kept for the page's life. */
  function drawPictures(tiles) {
    const layer = things()?.layer;
    if (!layer?.drawKindPicture) return;
    const density = globalThis.devicePixelRatio || 1;
    const size = {
      width: Math.round(Math.max(TILE_PICTURE.leastWidth, TILE_PICTURE.width * scale()) * density),
      height: Math.round(Math.max(TILE_PICTURE.leastHeight, TILE_PICTURE.height * scale()) * density),
    };
    for (const tile of tiles) {
      if (pictures.has(tile.id)) continue;
      pictures.set(tile.id, null);
      void layer.drawKindPicture(tile.kind, size).then(url => {
        if (typeof url !== 'string' || lifetime.signal.aborted) return;
        pictures.set(tile.id, url);
        trayView.picture(tile.id, url);
      }, () => {});
    }
  }

  /** A tile picked: its thing carried under the pointer (or stood at the ground point `at`) to be placed, or the creature maker opened. */
  function pick(tile, at = null) {
    if (!on || busy) return;
    if (tile.make) { putBack(); deselect(); makeCreature?.(); return; }
    if (placing?.tileId === tile.id) { putBack(); return; }
    const regionId = placingRegion();
    if (regionId === null) return;
    dropMove(); dropPlacing();
    selected = null; confirming = null; failure = ''; removeRefused = false;
    const name = tile.kind.source === 'workspace' ? thingName({ kind: tile.kind }, () => creatures?.find(made => made.sha256 === tile.kind.sha256)?.label ?? null) : thingName({ kind: tile.kind });
    placing = { tileId: tile.id, kind: tile.kind, name, regionId, thingId: newThingId(tile.kind), to: null, box: null, verdict: { state: 'checking', words: '' }, letGo: false };
    const held = placing;
    void kindBox(tile.kind).then(box => { held.box = box; });
    const pointed = pointer ?? { x: innerWidth / 2, y: innerHeight / 2 };
    const ground = at ?? groundAt(pointed.x, pointed.y);
    if (ground !== null) placeTo(ground, false);
    render();
    canvas.focus({ preventScroll: true });
  }
  /** A kind's footprint as its document states it (millimetres across and deep), for the ring under its copy; null where unread. */
  async function kindBox(kind) {
    const library = things()?.layer?.maker?.library;
    if (!library) return null;
    try {
      const document = await library.kindDocument(kind.source === 'workspace' ? kind : { key: kind.kind, version: kind.version, sha256: kind.sha256 });
      const box = document?.body?.box_mm;
      return Number.isFinite(box?.width) && Number.isFinite(box?.depth) ? { width: box.width, depth: box.depth } : null;
    } catch { return null; }
  }
  /** A new thing's id: its kind's key, or "creature", and a short random part the server has not seen. */
  function newThingId(kind) {
    const random = Array.from(crypto.getRandomValues(new Uint8Array(4)), byte => byte.toString(16).padStart(2, '0')).join('');
    return `${kind.source === 'workspace' ? 'creature' : kind.kind}:${random}`;
  }
  /** How high the ground stands at a point of the region, millimetres: on land, the land's height; else level. */
  function groundHeightMm(x, z) {
    const height = b.authoredSociety?.groundHeightAt;
    return typeof height === 'function' ? Math.round(height(x / 1000, z / 1000) * 1000) : 0;
  }
  /** Stand the new thing's copy at a ground point, turned as it is. */
  function placeTo(ground, free) {
    if (placing === null) return;
    const x = snapped(ground.xMm, free), z = snapped(ground.zMm, free);
    standNew({ x, y: groundHeightMm(x, z), z, yaw: placing.to?.yaw ?? 0 });
  }
  /** Stand the new thing's copy at `to` and ask the server about it once it rests. */
  function standNew(to) {
    if (placing === null) return;
    if (placing.to && placing.to.x === to.x && placing.to.z === to.z && placing.to.yaw === to.yaw) return;
    placing.to = to;
    placing.verdict = { state: 'checking', words: '' };
    // Turned or stood elsewhere after a click let it go: that click is taken back.
    placing.letGo = false;
    showKindCopy(placing, false);
    clearTimeout(askTimer);
    askTimer = window.setTimeout(() => { void askPlace(); }, ASK_AFTER_MS);
    render();
  }
  /** The server's placing preview for where the copy stands now; an older answer is dropped. */
  async function askPlace() {
    if (placing === null || placing.to === null) return;
    const request = ++asked, held = placing, to = { ...held.to }, stateBase = base();
    try {
      const answered = (await post('things.place.preview', '/things/preview', { base_state_sha256: stateBase, ...placingBody(held, to) })).body;
      if (request !== asked || placing !== held) return;
      if (answered.availability === 'ready') {
        // Stood at the height the ground says it rests at there, so its copy, its ring and the kept pose agree (W12.6).
        const at = restingAt(answered, to);
        held.to = at;
        held.verdict = { state: 'ready', words: answered.landing?.checked === false ? 'Where it may stand is not checked in this world.' : '', base: stateBase, to: at };
      } else held.verdict = { state: 'refused', words: refusalWords(answered.blocked_reason, answered.blocked_detail) };
    } catch (error) {
      if (request !== asked || placing !== held) return;
      held.verdict = { state: 'refused', words: problem(error) };
    }
    showKindCopy(held, held.verdict.state === 'refused');
    render();
    // Let go here while it was asked about: placed now that the server says it may stand here, else carried on.
    if (held.letGo) { held.letGo = false; if (held.verdict.state === 'ready') void placeNew(); }
  }
  /** `to` at the height a ready preview says the thing rests at (`landing.rest_y_mm`), where it says one. */
  const restingAt = (answered, to) => (Number.isFinite(answered.landing?.rest_y_mm) && answered.landing.rest_y_mm !== to.y ? { ...to, y: answered.landing.rest_y_mm } : to);
  const placingBody = (held, to) => ({
    thing_id: held.thingId, kind: held.kind, region_id: held.regionId,
    pose: { x_mm: to.x, y_mm: to.y, z_mm: to.z, yaw_microradians: to.yaw }, origin_role: 'fictional',
  });
  function showKindCopy(held, refused) {
    const to = held.to; if (to === null) return;
    void things()?.layer?.setKindGhost?.({ kind: held.kind, regionId: held.regionId, xMm: to.x, yMm: to.y, zMm: to.z, yawMicroradians: to.yaw, refused });
  }
  /** Place the new thing where the server said it may stand: the placing's own base and pose. */
  async function placeNew() {
    if (placing === null || busy) return;
    // Still asked about where it stands: let go there, and placed when the answer says it may stand (askPlace).
    if (placing.verdict.state === 'checking') { if (placing.to !== null) placing.letGo = true; return; }
    if (placing.verdict.state !== 'ready') return;
    const held = placing, verdict = held.verdict, name = held.name;
    busy = true; render();
    try {
      await post('things.place', '/things', { base_state_sha256: verdict.base, ...placingBody(held, verdict.to), saved_entry: savedEntry() });
      busy = false; dropPlacing({ outcome: 'placed', thingId: held.thingId });
      try { await refreshRecords(); } catch {}
      if (records.has(held.thingId)) selected = held.thingId;
      render(); say(youDid('add_thing', held.thingId, name), { undoable: true });
      if (held.kind.source === 'workspace') void readCreatures(true);
      return;
    } catch (error) {
      busy = false;
      if (placing === held) held.verdict = { state: 'refused', words: problem(error) };
      showKindCopy(held, true);
      render();
    }
    try { await refreshRecords(); } catch {}
  }
  /** The new thing being placed let go (put back in the tray unless `outcome` says it was placed): its copy goes. */
  function dropPlacing(outcome: HoldOutcome = PUT_BACK) {
    if (placing === null) return;
    const held = placing;
    placing = null; ++asked; clearTimeout(askTimer);
    void things()?.layer?.setKindGhost?.(null);
    held.settle?.(outcome);
  }

  // ---------- The held group, the corners and the marks ----------

  /** Tells the corners what building shows now: the Building pill, the keys card and no hints. */
  function renderCorners() {
    const question = confirming !== null || moving !== null || placing !== null;
    const show = !on ? 'off' : `on:${question}`;
    if (show === cornersShow) return;
    const was = cornersShow;
    cornersShow = show;
    if (!on) {
      if (!was || was === 'off') return;
      corners.mode(null); corners.hints(null); corners.keys?.(null); corners.back('Your worlds'); corners.notes.place('world');
      return;
    }
    if (!was.startsWith('on:')) {
      corners.mode('Building', keyWord({ keys: ['B'], word: 'Done', shortcut: 'B', onPress: () => { void toggle(); } }));
      corners.hints(null);
      corners.keys?.(buildKeys());
      corners.notes.place('build');
    }
    // A question shows its own Esc; the Back corner hides while it does.
    corners.back(question ? null : 'Back');
  }

  /** The group's words and rows for the state build mode is in, each row pressing what its key does. */
  function groupWords() {
    const rowsOf = (state) => heldRows(state).map(row => ({
      key: row.key, word: row.word, shortcut: row.shortcut, disabled: busy || row.disabled === true,
      onPress: row.action ? () => act(row.action, false) : undefined,
    }));
    if (placing !== null) {
      const verdict = placing.verdict;
      const line = verdict.state === 'refused' ? { words: verdict.words, refused: verdict.words !== BUSY } : verdict.words ? { words: verdict.words } : null;
      return { title: titled(placing.name), line, rows: rowsOf({ placing: true, ready: verdict.state === 'ready', refused: verdict.state === 'refused' }) };
    }
    const name = nameOf(selected) || 'thing';
    if (confirming !== null) return { title: removeTitle(name), line: { words: removeLine() }, rows: rowsOf({ confirming: true }) };
    if (moving !== null) {
      const verdict = moving.verdict;
      const line = verdict.state === 'refused' ? { words: verdict.words, refused: verdict.words !== BUSY } : verdict.words ? { words: verdict.words } : null;
      return { title: titled(name), line, rows: rowsOf({ moving: true, ready: verdict.state === 'ready', refused: verdict.state === 'refused' }) };
    }
    return { title: titled(name), line: failure ? { words: failure, refused: failure !== BUSY } : null, rows: rowsOf({ removeRefused }) };
  }

  function render() {
    renderCorners();
    lastPlacedKey = '';
    drawTray();
    if (!groupShows()) { group.hide(); groupDrawn = ''; hideMarks(); return; }
    const words = groupWords();
    const key = JSON.stringify([words.title, words.line, words.rows.map(row => [row.key, row.word, row.disabled])]);
    if (key !== groupDrawn) { groupDrawn = key; group.set(words); }
  }

  function hideMarks() { chosen.hide(); copy.hide(); origin.hide(); trail.hide(); groundRing?.hide(); names.hide(); }
  /** Whether the held group and the marks show: building, something chosen or held, nothing over them. */
  const groupShows = () => on && (selected !== null || placing !== null) && !inspecting();

  function select(placedId) {
    dropMove(); dropPlacing();
    selected = placedId; confirming = null; failure = ''; removeRefused = false;
    render();
  }
  function deselect() {
    dropMove(); dropPlacing();
    selected = null; confirming = null; failure = ''; removeRefused = false;
    render(); canvas.focus({ preventScroll: true });
  }
  function cancel() { confirming = null; failure = ''; removeRefused = false; render(); }

  async function toggle() {
    if (on) { leave(); return; }
    on = true; say(''); render();
    reading = refreshRecords().catch(error => { say(error.message); });
    await reading; reading = null;
    render();
  }
  function leave() {
    dropMove(); dropPlacing();
    on = false; hovered = null; tag.hide();
    selected = null; confirming = null; failure = ''; removeRefused = false;
    render(); canvas.focus({ preventScroll: true });
  }

  /** The move under way, if any, ended without keeping it: the copy goes, nothing was written. */
  function dropMove() {
    if (moving === null) return;
    moving = null; ++asked; clearTimeout(askTimer);
    things()?.layer.setGhost(null);
    things()?.layer.setBoxGhost?.(null);
  }
  /** What is held put back: a moved thing where it stood, a new one in the tray. */
  function putBack() { dropMove(); dropPlacing(); render(); canvas.focus({ preventScroll: true }); }

  /**
   * The ground point under a screen point (region frame, millimetres), or null off the ground; with `lift`, the point
   * of the ground under where the pointer's ray passes that many metres above it, where a thing grabbed that high is
   * carried.
   */
  function groundAt(x, y, lift = 0) {
    const ray = pointerRay(b, x, y); if (!ray) return null;
    const origin = lift > 0 ? [ray.origin[0], ray.origin[1] - lift, ray.origin[2]] : ray.origin;
    return b.authoredSociety?.groundPoint(origin, ray.direction) ?? null;
  }
  /**
   * How high above its foot (`footMm`, the region's up) a press met a thing, in metres, from the pick's distance along
   * the pointer's ray; never above the eye less GRAB_BELOW_EYE_M, and 0 where the region or the distance is unknown.
   */
  function grabHeight(met, footMm) {
    const rootY = b.authoredSociety?.root?.getPosition?.().y;
    if (!Number.isFinite(rootY) || !Number.isFinite(met?.distance) || !Number.isFinite(footMm)) return 0;
    const eye = b.camera.getPosition().y, foot = rootY + footMm / 1000;
    return Math.max(0, Math.min(eye + met.ray.direction[1] * met.distance - foot, eye - foot - GRAB_BELOW_EYE_M));
  }

  /** Start a move of the selected thing from where it stands, or keep the one under way. */
  function beginMove() {
    if (moving !== null || selected === null) return moving;
    if (isPart(selected)) {
      // A part stands where the parts read says, turned as it says; on the ground it is moved over.
      const part = partOf(selected); if (!part) return null;
      const from = { x: part.centre_mm[0], y: slotOf(selected)?.positionMm[2] ?? 0, z: -part.centre_mm[1], yaw: QUARTER_TURNS[turnsNow(selected) % 4] };
      moving = { placedId: selected, from, to: { ...from }, grip: null, verdict: { state: 'checking', words: '' }, letGo: false };
      return moving;
    }
    const record = records.get(selected); if (!record) return null;
    const t = record.transform;
    const from = { x: t.x_mm, y: t.y_mm, z: t.z_mm, yaw: t.yaw_microradians };
    moving = { placedId: selected, from, to: { ...from }, grip: null, verdict: { state: 'checking', words: '' }, letGo: false };
    return moving;
  }

  /** Stand the copy where the move would put it and ask the server about it once it rests. */
  function moveTo(to) {
    if (moving === null) return;
    moving.to = to;
    moving.verdict = { state: 'checking', words: '' };
    // Carried or turned again after a click let it go: that click is taken back.
    moving.letGo = false;
    showCopy(moving, to, false);
    clearTimeout(askTimer);
    askTimer = window.setTimeout(() => { void askMove(); }, ASK_AFTER_MS);
    render();
  }

  /** The server's move preview for where the copy stands now; an older answer is dropped. */
  async function askMove() {
    if (moving === null) return;
    const request = ++asked, move = moving, to = { ...move.to }, stateBase = base();
    try {
      const answered = (await post(actionOf(move.placedId, 'move.preview'), routeOf(move.placedId) + '/move/preview',
        { base_state_sha256: stateBase, pose: poseOf(move.placedId, to) })).body;
      if (request !== asked || moving !== move) return;
      if (answered.availability === 'ready') {
        // A thing stands at the height its ground says it rests at there; a made part keeps its floor.
        const at = isPart(move.placedId) ? to : restingAt(answered, to);
        move.to = at;
        move.verdict = { state: 'ready', words: answered.landing?.checked === false ? 'Where it may stand is not checked in this world.' : '', base: stateBase, to: at };
      } else move.verdict = { state: 'refused', words: refusalWords(answered.blocked_reason, answered.blocked_detail) };
    } catch (error) {
      if (request !== asked || moving !== move) return;
      move.verdict = { state: 'refused', words: problem(error) };
    }
    showCopy(move, move.to, move.verdict.state === 'refused');
    render();
    // Let go here while it was asked about: kept now that the server says it may stand here, else carried on.
    if (move.letGo) { move.letGo = false; if (move.verdict.state === 'ready') void keepMove(); }
  }

  /** The see-through copy where a move would put what it carries: a thing's own, a made part's box. */
  function showCopy(move, to, refused) {
    const layer = things()?.layer;
    if (!isPart(move.placedId)) { layer?.setGhost({ placedId: move.placedId, xMm: to.x, yMm: to.y, zMm: to.z, yawMicroradians: to.yaw, refused }); return; }
    const slot = slotOf(move.placedId), regionId = entry.generatedSite?.regionId;
    if (!slot || !regionId) return;
    const turns = slot.yawQuarterTurns + quarterOf(to.yaw) - quarterOf(move.from.yaw);
    layer?.setBoxGhost({ regionId, xMm: to.x, yMm: to.y, zMm: to.z, sizeMm: slot.boxMm, quarterTurns: ((turns % 4) + 4) % 4, refused });
  }

  /** The route and the pose a carried thing or part is asked about and moved by. */
  const routeOf = (id) => (isPart(id) ? '/parts/' + encodeURIComponent(id.slice(PART.length)) : '/things/' + encodeURIComponent(id));
  const actionOf = (id, what) => (isPart(id) ? 'parts.' : 'things.') + what;
  const poseOf = (id, to) => ({ x_mm: to.x, y_mm: isPart(id) ? 0 : to.y, z_mm: to.z, yaw_microradians: to.yaw });

  function turn(degrees, free) {
    if (placing !== null) {
      if (placing.to !== null) standNew({ ...placing.to, yaw: turned(placing.to.yaw, degrees, free) });
      return;
    }
    const move = beginMove(); if (move === null) return;
    // A made part turns a quarter at a time, the only turns it can take.
    if (isPart(move.placedId)) { moveTo({ ...move.to, yaw: QUARTER_TURNS[(quarterOf(move.to.yaw) + (degrees > 0 ? 1 : 3)) % 4] }); return; }
    moveTo({ ...move.to, yaw: turned(move.to.yaw, degrees, free) });
  }

  async function keepMove() {
    if (moving === null || busy) return;
    // Still asked about where it would stand: let go there, and kept when the answer says it may stand (askMove).
    if (moving.verdict.state === 'checking') { moving.letGo = true; return; }
    if (moving.verdict.state !== 'ready') return;
    const move = moving, verdict = move.verdict, name = nameOf(move.placedId);
    busy = true; render();
    try {
      // The pose and the base the server's answer was about: anything since is refused as stale.
      const to = verdict.to;
      await post(actionOf(move.placedId, 'move'), routeOf(move.placedId) + '/move',
        { base_state_sha256: verdict.base, pose: poseOf(move.placedId, to), saved_entry: savedEntry() });
      busy = false; dropMove(); render(); say(youDid(isPart(move.placedId) ? 'transform_element' : 'move_thing', move.placedId, name, { turned_in_place: turnedInPlace(poseOf(move.placedId, move.from), poseOf(move.placedId, to)) }), { undoable: true });
    } catch (error) {
      busy = false;
      if (moving === move) move.verdict = { state: 'refused', words: problem(error) };
      render();
    }
    try { await refreshRecords(); } catch {}
  }

  function savedEntry() {
    const bound = binding();
    return { entry_id: bound.entryId, base_revision: bound.revision, authored_state_sha256: bound.authoredStateSha256, authored_edit_seq: bound.authoredEditSeq };
  }
  const base = () => state.activeWorldEntry?.authoredStateSha256;
  const post = (actionId, tail, body) => send({ actionId, stepIndex: 0, method: 'POST', path: versionPath + tail, body });

  async function askRemove() {
    // While it is being moved, it is put back first and then asked about where it stands.
    if (moving !== null) dropMove();
    if (selected === null || busy) return;
    const placedId = selected, stateBase = base();
    busy = true; failure = ''; removeRefused = false; render();
    try {
      const answered = (await post(actionOf(placedId, 'remove.preview'), routeOf(placedId) + '/remove/preview', { base_state_sha256: stateBase })).body;
      if (selected !== placedId) return;
      if (answered.availability === 'ready') confirming = { placedId, base: stateBase };
      else { failure = refusalWords(answered.blocked_reason, answered.blocked_detail); removeRefused = true; }
    } catch (error) { failure = problem(error); }
    finally { busy = false; render(); }
  }

  async function confirmRemove() {
    if (confirming === null || busy) return;
    const { placedId } = confirming, name = nameOf(placedId);
    busy = true; render();
    try {
      // Against the state the preview read: a change in between is refused as stale, never kept.
      await post(actionOf(placedId, 'remove'), routeOf(placedId) + '/remove', { base_state_sha256: confirming.base, saved_entry: savedEntry() });
      busy = false; deselect(); say(youDid(isPart(placedId) ? 'suppress_element' : 'remove_thing', placedId, name), { undoable: true });
    } catch (error) { busy = false; confirming = null; failure = problem(error); render(); }
    try { await refreshRecords(); } catch {}
  }

  /** A made part's name by its id, from the parts read: what an undone part change names. */
  const partNamed = (partId) => parts.get(PART + partId)?.label ?? null;
  /** A change build mode made, in History's words ("You moved the bench"): the edit it made, by its kind and subject (a thing's turn alone on it). */
  const youDid = (kind, id, name, turn = {}) => youChangeWords(changeParts(isPart(id) ? { kind, element_id: id } : { kind, thing_id: id, ...turn }, [], () => name, partNamed));

  /**
   * Does again the last change taken back (Cmd+Shift+Z here and in History). Resolves, once the
   * version is read again, with the sentence it said, or null when a request was already on its way.
   */
  async function redo() {
    if (busy) return null;
    busy = true; render();
    let said, again = null;
    try {
      const stateBase = base();
      const preview = (await post('things.redo.preview', '/things/redo/preview', { base_state_sha256: stateBase })).body;
      if (preview.availability !== 'ready') say(said = redoRefusalWords(preview.blocked_reason, preview.blocked_detail));
      else {
        await post('things.redo', '/things/redo', { base_state_sha256: stateBase, saved_entry: savedEntry() });
        say(said = youChangeWords(previewParts(preview.would_change, true, partNamed, kindLabel)), { undoable: true });
        again = placedAgain(preview.would_change);
      }
    } catch (error) { say(said = problem(error)); }
    busy = false;
    try { await refreshRecords(); } catch {}
    // A thing the redo placed again is chosen, as after a place (W12.8).
    if (on && again !== null && records.has(again)) select(again);
    else if (selected !== null && !exists(selected)) deselect(); else render();
    return said;
  }

  /** The placed thing a redo's change puts back into the world, or null: absent or removed before it, standing after. */
  function placedAgain(change) {
    const subject = change?.subject_id;
    if (typeof subject !== 'string' || subject.startsWith('part:') || !change.after || change.after.removed) return null;
    return change.before == null || change.before.removed ? subject : null;
  }

  /**
   * Takes back the world's newest change (Cmd+Z here, the note's Undo and History's). Resolves,
   * once the version is read again, with the sentence it said, or null when a request was already
   * on its way.
   */
  async function undo() {
    if (busy) return null;
    busy = true; render();
    let said;
    try {
      const stateBase = base();
      const preview = (await post('things.undo.preview', '/things/undo/preview', { base_state_sha256: stateBase })).body;
      if (preview.availability !== 'ready') say(said = undoRefusalWords(preview.blocked_reason, preview.blocked_detail));
      else {
        await post('things.undo', '/things/undo', { base_state_sha256: stateBase, saved_entry: savedEntry() });
        say(said = youChangeWords(previewParts(preview.would_change, false, partNamed, kindLabel)), { redoable: true });
      }
    } catch (error) { say(said = problem(error)); }
    busy = false;
    try { await refreshRecords(); } catch {}
    if (selected !== null && !exists(selected)) deselect(); else render();
    return said;
  }

  /** What a key or a pressed row asks for, by keyAction's name; `free` is Alt held. */
  function act(action, free) {
    if (action === 'toggle') void toggle();
    else if (action === 'leave') leave();
    else if (action === 'deselect') deselect();
    else if (action === 'cancel') cancel();
    else if (action === 'remove') void askRemove();
    else if (action === 'confirm') void confirmRemove();
    else if (action === 'undo') void undo();
    else if (action === 'turn-left') turn(15 * (free ? 1 / 15 : 1), free);
    else if (action === 'turn-right') turn(-15 * (free ? 1 / 15 : 1), free);
    else if (action === 'put-back') putBack();
    else if (action === 'place') void (placing !== null ? placeNew() : keepMove());
    else if (action === 'redo') void redo();
    else if (action === 'next') cycle(1);
    else if (action === 'previous') cycle(-1);
    else if (action === 'unfocus') canvas.focus({ preventScroll: true });
  }

  /**
   * A drawn thing's pick volume on the screen, standing where it stands or at `to` (its copy):
   * its footprint's ground corners in order and the box around what of its eight corners is ahead;
   * null when none of its footprint is ahead of the camera (shapeOnScreen).
   */
  function onScreen(figure, to) {
    const volume = figure.pickVolume; if (!volume) return null;
    const box = volume.kind === 'box'
      ? { x0: volume.min[0], x1: volume.max[0], z0: volume.min[2], z1: volume.max[2], top: volume.max[1] }
      : { x0: volume.centre[0] - volume.radius, x1: volume.centre[0] + volume.radius, z0: volume.centre[2] - volume.radius, z1: volume.centre[2] + volume.radius, top: volume.centre[1] + volume.radius };
    const frame = to === null ? figure.root.getWorldTransform() : figure.root.parent.getWorldTransform();
    const size = figure.root.getLocalScale();
    const yaw = to === null ? 0 : to.yaw / 1e6, cos = Math.cos(yaw), sin = Math.sin(yaw);
    const world = (x, y, z) => {
      if (to === null) point.set(x, y, z);
      else {
        // Where the copy stands: turned about its own up axis, then moved, in its parent's frame.
        const across = x * size.x, along = z * size.z;
        point.set(to.x / 1000 + cos * across + sin * along, to.y / 1000 + y * size.y, to.z / 1000 - sin * across + cos * along);
      }
      frame.transformPoint(point, point);
      return { x: point.x, y: point.y, z: point.z };
    };
    const corners = [[box.x0, box.z0], [box.x1, box.z0], [box.x1, box.z1], [box.x0, box.z1]];
    return shapeOnScreen(corners.map(([x, z]) => world(x, 0, z)), corners.map(([x, z]) => world(x, box.top, z)));
  }

  /**
   * A footprint and its top on the screen, from their world corners in order (metres): the footprint cut where it
   * reaches behind the camera, so the part in view is marked and the screen's edge clips the rest (DESIGN's W12.5),
   * and the box around what of it is ahead; null when none of the footprint is ahead of the camera.
   */
  function shapeOnScreen(feet, tops) {
    const eye = b.camera.getPosition(), ahead = b.camera.forward;
    const depth = (c) => (c.x - eye.x) * ahead.x + (c.y - eye.y) * ahead.y + (c.z - eye.z) * ahead.z - MARK_NEAR_M;
    const kept = [];
    feet.forEach((a, index) => {
      const c = feet[(index + 1) % feet.length], da = depth(a), dc = depth(c);
      if (da > 0) kept.push(a);
      if ((da > 0) !== (dc > 0)) { const t = da / (da - dc); kept.push({ x: a.x + (c.x - a.x) * t, y: a.y + (c.y - a.y) * t, z: a.z + (c.z - a.z) * t }); }
    });
    if (kept.length < 3) return null;
    const screen = (c) => { const at = b.camera.camera.worldToScreen(point.set(c.x, c.y, c.z), seen); return at.z > 0 ? { x: at.x, y: at.y } : null; };
    const ground = kept.map(screen);
    if (ground.some((at) => at === null)) return null;
    let left = Infinity, right = -Infinity, top = Infinity, bottom = -Infinity;
    for (const at of [...ground, ...tops.filter((c) => depth(c) > 0).map(screen).filter((at) => at !== null)]) {
      left = Math.min(left, at.x); right = Math.max(right, at.x); top = Math.min(top, at.y); bottom = Math.max(bottom, at.y);
    }
    return { ground, bounds: { left, right, top, bottom, headY: top, waistY: (top + bottom) / 2 } };
  }

  /**
   * A made part on the screen, standing where the parts read says or at `to` (its copy): its
   * footprint's ground corners in order and the box around it with its height, from the region's
   * frame through the region root; null when the world or part is not drawn or none of its footprint
   * is ahead of the camera (shapeOnScreen).
   */
  function partOnScreen(id, to) {
    const part = partOf(id), site = regionRoot();
    if (part === null || site === null) return null;
    const slot = slotOf(id);
    const floor = to?.y ?? slot?.positionMm[2] ?? 0, height = Math.max(slot?.boxMm[2] ?? 0, 300);
    let [width, depth] = part.size_mm;
    // Turned an odd number of quarters from how it stands now, its sides swap.
    if (to !== null && Math.abs(quarterOf(to.yaw) - turnsNow(id)) % 2 === 1) [width, depth] = [depth, width];
    const east = to === null ? part.centre_mm[0] : to.x, north = to === null ? part.centre_mm[1] : -to.z;
    const frame = site.getWorldTransform();
    const world = (x, y, n) => { frame.transformPoint(point.set(x / 1000, y / 1000, -n / 1000), point); return { x: point.x, y: point.y, z: point.z }; };
    const corners = [[east - width / 2, north - depth / 2], [east + width / 2, north - depth / 2], [east + width / 2, north + depth / 2], [east - width / 2, north + depth / 2]];
    return shapeOnScreen(corners.map(([x, n]) => world(x, floor, n)), corners.map(([x, n]) => world(x, floor + height, n)));
  }

  /**
   * The ring at a chosen thing's foot, on the ground in the world (the ground ring, ruling L20), so a
   * wall or what stands in front covers it as it covers the thing: centred on its footprint and a
   * little wider than its half diagonal, so it never crosses the outline.
   */
  function ringUnder(id) {
    const footprint = groundRing === null ? null : footprintInWorld(id);
    if (footprint === null) { groundRing?.hide(); return; }
    const mean = (axis) => footprint.reduce((sum, corner) => sum + corner[axis], 0) / footprint.length;
    const half = (a, c) => Math.hypot(a.x - c.x, a.z - c.z) / 2;
    groundRing.place({ x: mean('x'), y: mean('y'), z: mean('z') }, Math.hypot(half(footprint[0], footprint[1]), half(footprint[1], footprint[2])) * RING_MARGIN);
  }

  /** A chosen thing's or made part's footprint as it stands: its four ground corners, world metres. */
  function footprintInWorld(id) {
    let frame, sides;
    if (isPart(id)) {
      const part = partOf(id), site = regionRoot();
      if (part === null || site === null) return null;
      const floor = (slotOf(id)?.positionMm[2] ?? 0) / 1000, [width, depth] = part.size_mm, [east, north] = part.centre_mm;
      frame = site.getWorldTransform();
      sides = { x0: (east - width / 2) / 1000, x1: (east + width / 2) / 1000, z0: -(north - depth / 2) / 1000, z1: -(north + depth / 2) / 1000, y: floor };
    } else {
      const figure = things()?.layer?.figureOf(id), volume = figure?.pickVolume;
      if (!figure || !volume || !figure.root.enabled) return null;
      frame = figure.root.getWorldTransform();
      sides = volume.kind === 'box'
        ? { x0: volume.min[0], x1: volume.max[0], z0: volume.min[2], z1: volume.max[2], y: 0 }
        : { x0: volume.centre[0] - volume.radius, x1: volume.centre[0] + volume.radius, z0: volume.centre[2] - volume.radius, z1: volume.centre[2] + volume.radius, y: 0 };
    }
    return [[sides.x0, sides.z0], [sides.x1, sides.z0], [sides.x1, sides.z1], [sides.x0, sides.z1]].map(([x, z]) => {
      frame.transformPoint(point.set(x, sides.y, z), point);
      return { x: point.x, y: point.y, z: point.z };
    });
  }
  const middle = (ground) => ({ x: ground.reduce((sum, corner) => sum + corner.x, 0) / ground.length, y: ground.reduce((sum, corner) => sum + corner.y, 0) / ground.length });

  /** Where what is held stands in the world now (metres), or null: a new thing's or a moved one's copy, else the chosen thing. */
  function heldInWorld() {
    if (placing?.to) {
      const at = regionRoot(placing.regionId);
      if (at === null) return null;
      at.getWorldTransform().transformPoint(heldAt.set(placing.to.x / 1000, placing.to.y / 1000, placing.to.z / 1000), heldAt);
      return heldAt;
    }
    const footprint = selected === null ? null : footprintInWorld(selected);
    if (footprint === null) return null;
    return heldAt.set(footprint.reduce((sum, corner) => sum + corner.x, 0) / 4, footprint[0].y, footprint.reduce((sum, corner) => sum + corner.z, 0) / 4);
  }

  /**
   * The names over people near what is held (frame r13): who stands within a few metres of it,
   * nearest first, two standing together named together, at most a few names, each over the
   * highest head of its people.
   */
  function placeNames() {
    const held = people === null ? null : heldInWorld();
    if (held === null) { names.hide(); return; }
    people.refresh?.();
    // Everyone near, named or not: someone unnamed is said with the named people beside them.
    const near = [];
    for (const id of people.ids()) {
      if (!people.groundOf(id, feet)) continue;
      const distance = feet.distance(held);
      if (distance > NAMES_NEAR_M) continue;
      near.push({ name: people.name(id) || null, id, distance, x: feet.x, y: feet.y + (people.heightOf(id) ?? 1.7), z: feet.z });
    }
    near.sort((a, c) => a.distance - c.distance || (a.id < c.id ? -1 : 1));
    const groups = [];
    for (const one of near) {
      const together = groups.find(group => Math.hypot(group[0].x - one.x, group[0].z - one.z) <= TOGETHER_M);
      if (together) together.push(one); else groups.push([one]);
    }
    const placed = [];
    for (const together of groups.filter(group => group.some(one => one.name !== null)).slice(0, NAMES_AT_MOST)) {
      const top = together.reduce((high, one) => (one.y > high.y ? one : high));
      const centre = together.reduce((sum, one) => ({ x: sum.x + one.x / together.length, z: sum.z + one.z / together.length }), { x: 0, z: 0 });
      const at = b.camera.camera.worldToScreen(point.set(centre.x, top.y, centre.z), seen);
      if (at.z <= 0) continue;
      placed.push({ words: namesTogether(together.map(one => one.name)), x: at.x, y: at.y });
    }
    names.place(placed, scale());
  }

  listen(canvas, 'pointermove', event => { pointer = { x: event.clientX, y: event.clientY, free: event.altKey }; });
  listen(canvas, 'pointerleave', () => { pointer = null; });
  render();

  return {
    active: () => on,
    undo,
    redo,
    /**
     * Holds the made kind `kind` ({ source: 'workspace', sha256 }) at the ground point `at` ({ xMm, zMm }, the
     * region frame's east and south in millimetres) to be placed, as picking its creatures tile does, switching
     * build mode on first. Resolves { outcome: 'placed', thingId } once the server keeps it, { outcome: 'put-back' }
     * when it is let go unplaced (put back, another tile picked, build mode left or closed), or null when nothing
     * can be held here (no region to place in, or a write under way).
     */
    async hold(kind, at): Promise<HoldOutcome | null> {
      if (kind?.source !== 'workspace' || typeof kind.sha256 !== 'string' || !Number.isFinite(at?.xMm) || !Number.isFinite(at?.zMm)) return null;
      if (!on) await toggle();
      // Held from its creatures tab, read again first when it is newer than the tab's list (its name is the list's).
      trayTab = 'creatures';
      if (!creatures?.some(made => made.sha256 === kind.sha256)) await readCreatures(true);
      if (!on || busy || lifetime.signal.aborted) return null;
      dropMove(); dropPlacing();
      pick({ id: 'made:' + kind.sha256, kind: { source: 'workspace', sha256: kind.sha256 } }, { xMm: at.xMm, zMm: at.zMm });
      const held = placing;
      if (held === null) return null;
      return new Promise<HoldOutcome>((settle) => { held.settle = settle; });
    },
    /**
     * The made kinds' labels as build mode reads them (`label(kind)`, and `listen` to be told when one
     * lands), for History's rows to name creatures with the same reads; a page with no build mode
     * makes its own with `createKindLabels`.
     */
    kindLabels,
    /** Act on a key; true when build mode took it. */
    key(event) {
      // While the server is asked about where the held thing stands, Enter lets it go there, as a click does.
      const now = flags(), asking = (placing ?? moving)?.verdict.state === 'checking';
      const action = keyAction(asking ? { ...now, ready: true } : now, event);
      if (action === null) return false;
      event.preventDefault();
      act(action, event.altKey);
      return true;
    },
    /**
     * A press on the world: true when it picks up the selected thing to carry it (build mode then
     * follows the pointer until it is let go); false leaves the press to looking around.
     */
    pointerDown(event) {
      if (!on || busy || event.button !== 0 || selected === null || confirming !== null || placing !== null) return false;
      const met = pickedAt(event.clientX, event.clientY);
      if (met?.id !== selected) return false;
      const flat = groundAt(event.clientX, event.clientY);
      const move = flat === null ? null : beginMove();
      if (move === null) return false;
      // Carried by the point the press met, at its height above the thing's foot, so that point stays under the
      // pointer: the ground behind a tall thing lies metres beyond it.
      const raised = grabHeight(met, move.to.y);
      const high = raised > 0 ? groundAt(event.clientX, event.clientY, raised) : null;
      const lift = high === null ? 0 : raised, ground = high ?? flat;
      move.grip = { east: move.to.x - ground.xMm, south: move.to.z - ground.zMm };
      const carry = (at, free) => {
        const where = groundAt(at.clientX, at.clientY, lift);
        if (where === null || moving !== move) return;
        moveTo({ ...move.to, x: snapped(where.xMm + move.grip.east, free), z: snapped(where.zMm + move.grip.south, free) });
      };
      const follow = new AbortController();
      document.addEventListener('mousemove', at => carry(at, at.altKey), { signal: follow.signal });
      document.addEventListener('mouseup', at => { carry(at, at.altKey); follow.abort(); if (moving === move) move.grip = null; }, { signal: follow.signal, capture: true });
      lifetime.signal.addEventListener('abort', () => follow.abort());
      canvas.style.cursor = 'grabbing';
      render();
      return true;
    },
    /** A click on the world, not a drag: true when build mode took it. */
    click(x, y) {
      if (!on || busy) return false;
      if (reading !== null) { void reading.then(() => { if (on) this.click(x, y); }); return true; }
      // While something is held, a click places it where the server said it may stand, as Enter does.
      // While it is asked about, the click lets it go there and the answer places it (placeNew, keepMove).
      if (placing !== null || moving !== null) { if ((placing ?? moving).verdict.state !== 'refused') act('place', false); return true; }
      const placedId = placedAt(x, y);
      if (placedId === null) { if (selected !== null) deselect(); return true; }
      if (placedId !== selected) select(placedId);
      return true;
    },
    frame(now) {
      if (!on) return;
      if (now - lastPick >= 50) {
        lastPick = now;
        hovered = pointer && !inspecting() && moving?.grip == null && placing === null ? placedAt(pointer.x, pointer.y) : null;
        canvas.style.cursor = moving?.grip != null ? 'grabbing' : placing !== null ? 'crosshair' : hovered !== null ? (hovered === selected ? 'grab' : 'pointer') : '';
        // A new thing's copy follows the pointer over the ground, until a click lets it go.
        if (placing !== null && !placing.letGo && pointer && !inspecting()) { const ground = groundAt(pointer.x, pointer.y); if (ground !== null) placeTo(ground, pointer.free); }
      }
      const layer = things()?.layer;
      // The name of what the pointer is on, above it; the held group names what is chosen instead.
      let head = null;
      if (hovered !== null && hovered !== selected && moving === null) {
        if (isPart(hovered)) {
          const shape = partOnScreen(hovered, null);
          head = shape === null ? null : { x: (shape.bounds.left + shape.bounds.right) / 2, y: shape.bounds.top, z: 1 };
        } else {
          const named = layer?.figureOf(hovered);
          head = named && named.root.enabled ? b.camera.camera.worldToScreen(named.markAnchor(point), seen) : null;
        }
      }
      if (head && head.z > 0) { tag.set({ name: titled(nameOf(hovered)) }); tag.place(head.x, head.y); }
      else tag.hide();
      if (!groupShows()) { hideMarks(); lastPlacedKey = ''; }
      else {
        if (now - lastNames >= NAMES_EVERY_MS || moving !== null || placing !== null) { lastNames = now; placeNames(); }
        if (placing !== null) {
          // The ring follows the new thing's copy, a little wider than its footprint's half diagonal.
          chosen.hide(); copy.hide(); origin.hide(); trail.hide();
          const at = placing.box === null ? null : heldInWorld();
          if (at === null || groundRing === null) groundRing?.hide();
          else groundRing.place({ x: at.x, y: at.y, z: at.z }, Math.hypot(placing.box.width, placing.box.depth) / 2000 * RING_MARGIN);
        }
        else {
          // Out of view is not let go: what is chosen stays chosen and its marks show again in view.
          const figure = isPart(selected) ? null : layer?.figureOf(selected) ?? null;
          const carrying = moving !== null && moving.placedId === selected;
          const standing = isPart(selected) ? partOnScreen(selected, null) : figure && figure.root.enabled ? onScreen(figure, null) : null;
          const carried = !carrying ? null : isPart(selected) ? partOnScreen(selected, moving.to) : figure ? onScreen(figure, moving.to) : null;
          const key = [standing, carried].map(shape => shape === null ? '-' : [...shape.ground.flatMap(p => [p.x, p.y]), shape.bounds.left, shape.bounds.right, shape.bounds.top, shape.bounds.bottom].map(v => v.toFixed(1)).join(',')).join('|') + (moving?.verdict.state ?? '');
          if (key === lastPlacedKey) { /* Nothing moved on the screen: everything stays where it is. */ }
          else if (carried === null && standing === null) { lastPlacedKey = key; chosen.hide(); copy.hide(); origin.hide(); trail.hide(); groundRing?.hide(); }
          else {
            lastPlacedKey = key;
            if (moving !== null) {
              // The copy where it would go, its spot dashed where it stands, and the way between.
              chosen.hide(); groundRing?.hide();
              if (carried) { copy.form(moving.verdict.state === 'refused' ? 'refused' : 'copy'); copy.place(carried.ground); } else copy.hide();
              if (standing && carried) { origin.place(standing.ground); trail.place(middle(standing.ground), middle(carried.ground)); }
              else { origin.hide(); trail.hide(); }
            } else {
              copy.hide(); origin.hide(); trail.hide();
              if (standing) { chosen.place(standing.ground); ringUnder(selected); } else { chosen.hide(); groundRing?.hide(); }
            }
          }
        }
      }
      // Inspecting a being hides the group and the tray; closing it brings them back.
      if (inspecting() !== wasInspecting) { wasInspecting = inspecting(); render(); }
    },
    dispose() {
      lifetime.abort();
      trayHeight.disconnect();
      dropPlacing();
      if (on) { on = false; renderCorners(); }
      canvas.style.cursor = '';
      for (const part of [origin.root, trail.root, chosen.root, copy.root, names.root, tag.root, group.root, trayView.root]) part.remove();
      groundRing?.dispose();
    },
  };
}
