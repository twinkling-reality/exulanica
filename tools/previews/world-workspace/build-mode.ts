// Build mode in the world workspace. B switches it on and off while the world keeps playing. In it,
// pointing at a thing placed in the world names it, a click selects it (its outline, a ring at its
// foot and a card beside it). Dragging it carries a see-through copy along the ground and `[` `]`
// turn it (half metres and 15 degree steps, Alt for free); the server says whether it may stand
// there while it moves and when it is let go, and Enter keeps the move, Esc puts it back. Backspace
// asks the server what removing it would do and Enter does it, and Cmd+Z takes back the world's
// newest change, and Cmd+Shift+Z does the last change taken back again. Tab and Shift+Tab choose
// the next or previous placed thing in view, so selecting needs no pointer. History, the page H
// opens, takes changes back through the same `undo` and `redo` this returns. Every write goes
// through the app's own edit path (`send`, main.ts's sendPlanned), which
// advances the saved world and redraws what changed; every write is asked of the server first as a
// preview, and only the server's answer is shown.
// In a site world (one made from a world kind) the parts made with the world (a building, a garden
// fixture, a pond or field) are chosen, moved, turned a quarter at a time and removed the same way,
// through the parts routes; after a change the made world is drawn again (main.ts).
// It is drawn with the in-world design's shared parts (world-ui.ts) and the world's corners (the
// mode word, the Back corner, the hints and the note); what a key does in each state, and every
// sentence, is build-words.mjs.
import { pointerRay } from '../../../web/packages/atlas-react/src/playcanvas/index.ts';
import { pickSiteSlot } from '/src/composition/sight.ts';
import { currentOpenSite } from '/src/composition/site-world.ts';
import { kindDocumentLabel } from '/src/composition/visitor-notices.ts';
import { buildHints, cardPrompts, createKindLabels, keepLine, keyAction, madeLine, moveWords, movedNote, nothingInView, placedLine, redoRefusalWords, redoneNote, refusalWords, removeLine, removeTitle, removedNote, snapped, thingName, titled, turned, undoRefusalWords, undoneNote } from './build-words.mjs';
import { cardWords, keyWord, nameTag, outline, path, promptColumn, promptRow, scaleOf, sideCard } from './world-ui.ts';

/** How long a carried thing rests before the server is asked about where it is, in milliseconds. */
const ASK_AFTER_MS = 180;
/** How much wider than the footprint's half diagonal the ring at a thing's foot is, so it encloses the outline's corners. */
const RING_MARGIN = 1.18;
/**
 * The chosen thing's ground ring, quieter than a character's (DESIGN's ruling L22): the outline is
 * the primary mark, so the ring is a thinner white line with no glow and no fill. Spread over the
 * ground ring's look.
 */
export const THING_RING = Object.freeze({ linePx: 1.6, glowAlpha: 0, fillAlpha: 0 });
/** What a refusal the server words for a person starts with, drawn in the refused colour. */
const NOT_HERE = 'Not here:';
/** How a made part is named where a placed thing's id would be: chosen, carried, pointed at. */
const PART = 'part:';
/** The four turns a made part can take, microradians, as the parts routes state them. */
const QUARTER_TURNS = [0, 1_570_796, 3_141_593, 4_712_389];
const quarterOf = (yaw) => Math.max(0, QUARTER_TURNS.indexOf(yaw));

export function mountBuildMode({ b, root, state, entry, read, send, binding, canvas, corners, inspecting, groundRing = null }) {
  const lifetime = new AbortController();
  const listen = (target, type, run, options = {}) => target.addEventListener(type, run, { ...options, signal: lifetime.signal });
  const node = (tag, words = '', cls = '') => { const item = document.createElement(tag); item.textContent = String(words); item.className = cls; return item; };
  const scale = () => scaleOf(root);
  const versionPath = '/world/versions/' + encodeURIComponent(entry.authoredVersionId);
  const worldQuery = '?world_id=' + encodeURIComponent(entry.worldId);

  const tag = nameTag({ scale });
  const card = sideCard({ build: true, scale });
  card.body.setAttribute('role', 'region'); card.body.setAttribute('aria-labelledby', 'bm-title');
  const chosen = outline(), copy = outline({ form: 'copy' }), origin = outline({ form: 'origin' }), trail = path();
  root.append(origin.root, trail.root, chosen.root, copy.root, tag.root, card.root);

  let on = false, hovered = null, selected = null, confirming = null, busy = false, failure = '';
  /** Whether the server refused removing what is chosen: its card then offers moving it only. */
  let removeRefused = false;
  /**
   * A move being made: the thing, where it stands (`from`) and where it would stand (`to`, region
   * frame: east, up, south in millimetres, yaw in microradians), the grip while it is dragged, and
   * the server's newest answer about `to` (`verdict`: checking, ready or refused, with its words).
   */
  let moving = null, asked = 0, askTimer = 0;
  let records = new Map(), pointer = null, lastPick = 0;
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
  const siteDrawing = () => currentOpenSite()?.drawing() ?? null;
  const slotOf = (id) => siteDrawing()?.slots?.find(slot => slot.identity === id.slice(PART.length)) ?? null;
  const regionRoot = () => (entry.generatedSite ? b.regionRoots?.get(entry.generatedSite.regionId) ?? null : null);
  /** The first read of the version's things after B, which a click made before it ends waits for. */
  let reading = null;
  /** What the corners show now, so they are told only when it changes (a hint's fade restarts when told). */
  let cornersShow = '';
  /**
   * The projected points the card and marks were last placed at, so a still view places nothing
   * (placing the card reads its size, which lays the page out); cleared whenever the card is redrawn.
   */
  let lastPlacedKey = '';
  const point = b.camera.getPosition().clone(), seen = point.clone();
  let wasInspecting = false;

  const things = () => b.__workspaceThings?.() ?? null;
  const focused = () => card.root.contains(document.activeElement);
  const flags = () => ({ on, selected: selected !== null, confirming: confirming !== null, moving: moving !== null, ready: moving?.verdict.state === 'ready', busy, removeRefused, focused: focused() });

  /** A note at the bottom centre; a change it reports can be taken back from it. */
  function say(words, { undoable = false } = {}) {
    if (!words) { corners.notes.clear(); return; }
    corners.notes.show(words, undoable ? { prompt: keyWord({ keys: ['⌘Z'], word: 'Undo', shortcut: 'Meta+Z', onPress: () => { void undo(); } }) } : {});
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
    const root = regionRoot();
    if (root) for (const [id, part] of parts) {
      const slot = slotOf(id);
      root.getWorldTransform().transformPoint(point.set(part.centre_mm[0] / 1000, (slot?.positionMm[2] ?? 0) / 1000 + 1, -part.centre_mm[1] / 1000), point);
      const distance = eye.distance(point);
      const screen = b.camera.camera.worldToScreen(point, seen);
      if (screen.z <= 0 || screen.x < 0 || screen.x > innerWidth || screen.y < 0 || screen.y > innerHeight) continue;
      found.push({ placedId: id, distance });
    }
    return found.sort((a, c) => a.distance - c.distance || (a.placedId < c.placedId ? -1 : 1)).map(item => item.placedId);
  }
  function cycle(step) {
    const ids = inView();
    if (!ids.length) { say(nothingInView()); return; }
    const at = selected === null ? -1 : ids.indexOf(selected);
    select(ids[at === -1 ? (step > 0 ? 0 : ids.length - 1) : (at + step + ids.length) % ids.length]);
  }

  /**
   * The placed thing or made part a screen point meets first, or null: a person or an object in front
   * hides it, and a part is met by its box in the drawing the world shows now.
   */
  function placedAt(x, y) {
    if (!b.__workspacePick) return null;
    const ray = pointerRay(b, x, y); if (!ray) return null;
    const hit = b.__workspacePick(ray.origin, ray.direction);
    if (hit?.inhabitantId) return null;
    const thingId = hit?.thing?.pick?.placedId ?? null;
    const thing = thingId !== null && records.has(thingId) ? { id: thingId, distance: hit.thing.distance } : null;
    const drawing = parts.size ? siteDrawing() : null;
    const part = drawing ? pickSiteSlot(drawing, ray.origin, ray.direction, (id) => parts.has(PART + id)) : null;
    if (part !== null && (thing === null || part.distance < thing.distance)) return PART + part.identity;
    return thing?.id ?? null;
  }

  /**
   * A creature its workspace made is called by its kind's own label (rulings J20, J23), read once by
   * digest and again after a failed read's pause; until it arrives build mode says "creature", and
   * draws its card again when it does.
   */
  const kindLabels = createKindLabels(read, kindDocumentLabel);
  kindLabels.listen(() => { if (on && !lifetime.signal.aborted) render(); });
  const kindLabel = (kind) => kindLabels.label(kind);
  function nameOf(id) { return isPart(id) ? partOf(id)?.label ?? 'part' : thingName(records.get(id), kindLabel); }

  /** The card's answer line: the server's sentence, its "Not here:" drawn as a refusal. */
  function answer(words) {
    const line = node('p', '', 'wu-card-answer');
    if (words.startsWith(NOT_HERE)) line.append(node('span', NOT_HERE, 'wu-refused'), ' ' + words.slice(NOT_HERE.length).trimStart());
    else line.textContent = words;
    return line;
  }

  /** The card's prompts for the state build mode is in: a column while chosen, an answer pair in one row. */
  function prompts() {
    const verdict = moving?.verdict.state ?? null;
    const items = cardPrompts({ moving: moving !== null, ready: verdict === 'ready', refused: verdict === 'refused', confirming: confirming !== null, removeRefused });
    const made = items.map(item => keyWord({
      keys: item.keys, word: item.word, shortcut: item.shortcut, disabled: busy || item.disabled === true,
      onPress: item.action ? () => act(item.action, false) : undefined,
    }));
    return moving !== null || confirming !== null ? promptRow(made) : promptColumn(made);
  }

  /** Tells the corners what building shows now: its mode word, the Back corner and its hints. */
  function renderCorners() {
    const question = confirming !== null || moving !== null;
    const show = !on ? 'off' : `on:${moving !== null}:${question}`;
    if (show === cornersShow) return;
    const was = cornersShow;
    cornersShow = show;
    if (!on) {
      if (!was || was === 'off') return;
      corners.mode(null); corners.hints(null); corners.back('Your worlds'); corners.notes.place('world');
      return;
    }
    if (!was.startsWith('on:')) {
      corners.mode('Building', keyWord({ keys: ['B'], word: 'Done', shortcut: 'B', onPress: () => { void toggle(); } }));
      corners.notes.place('build');
    }
    // A question shows its own Esc; the Back corner hides while it does.
    corners.back(question ? null : 'Back');
    corners.hints(buildHints({ moving: moving !== null }), { vertical: true });
  }

  function render() {
    renderCorners();
    lastPlacedKey = '';
    if (!cardShows()) { card.hide(); hideMarks(); return; }
    const name = nameOf(selected) || 'thing';
    const body = [];
    if (confirming !== null && !busy) {
      body.push(cardWords({ title: removeTitle(name) }), answer(removeLine()));
    } else if (moving !== null && !busy) {
      const where = moveWords(moving.from, moving.to);
      body.push(cardWords({ title: titled(name), lines: [where.charAt(0).toUpperCase() + where.slice(1)] }));
      const verdict = moving.verdict;
      body.push(answer(verdict.state === 'checking' ? 'Checking…' : verdict.words || keepLine()));
    } else {
      body.push(cardWords({ title: titled(name), lines: [isPart(selected) ? madeLine(partOf(selected)?.zone_label) : placedLine()] }));
      if (busy) body.push(answer('Checking…'));
      else if (failure) body.push(answer(failure));
    }
    body.push(prompts());
    card.body.replaceChildren(...body);
    card.body.querySelector('.wu-card-title')?.setAttribute('id', 'bm-title');
  }

  function hideMarks() { chosen.hide(); copy.hide(); origin.hide(); trail.hide(); groundRing?.hide(); }
  /** Whether the chosen thing's card and marks show: building, something chosen, nothing over them. */
  const cardShows = () => on && selected !== null && !inspecting();

  function select(placedId) {
    dropMove();
    selected = placedId; confirming = null; failure = ''; removeRefused = false;
    render();
  }
  function deselect() {
    dropMove();
    selected = null; confirming = null; failure = ''; removeRefused = false;
    render(); canvas.focus({ preventScroll: true });
  }
  function cancel() { confirming = null; failure = ''; removeRefused = false; render(); }

  async function toggle() {
    if (on) { leave(); return; }
    on = true; say(''); render();
    reading = refreshRecords().catch(error => { say(error.message); });
    await reading; reading = null;
  }
  function leave() {
    dropMove();
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
  function putBack() { dropMove(); render(); canvas.focus({ preventScroll: true }); }

  /** The ground point under a screen point (region frame, millimetres), or null off the ground. */
  function groundAt(x, y) {
    const ray = pointerRay(b, x, y); if (!ray) return null;
    return b.authoredSociety?.groundPoint(ray.origin, ray.direction) ?? null;
  }

  /** Start a move of the selected thing from where it stands, or keep the one under way. */
  function beginMove() {
    if (moving !== null || selected === null) return moving;
    if (isPart(selected)) {
      // A part stands where the parts read says, turned as it says; on the ground it is moved over.
      const part = partOf(selected); if (!part) return null;
      const from = { x: part.centre_mm[0], y: slotOf(selected)?.positionMm[2] ?? 0, z: -part.centre_mm[1], yaw: QUARTER_TURNS[turnsNow(selected) % 4] };
      moving = { placedId: selected, from, to: { ...from }, grip: null, verdict: { state: 'checking', words: '' } };
      return moving;
    }
    const record = records.get(selected); if (!record) return null;
    const t = record.transform;
    const from = { x: t.x_mm, y: t.y_mm, z: t.z_mm, yaw: t.yaw_microradians };
    moving = { placedId: selected, from, to: { ...from }, grip: null, verdict: { state: 'checking', words: '' } };
    return moving;
  }

  /** Stand the copy where the move would put it and ask the server about it once it rests. */
  function moveTo(to) {
    if (moving === null) return;
    moving.to = to;
    moving.verdict = { state: 'checking', words: '' };
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
      move.verdict = answered.availability === 'ready'
        ? { state: 'ready', words: answered.landing?.checked === false ? 'Where it may stand is not checked in this world.' : '', base: stateBase, to }
        : { state: 'refused', words: refusalWords(answered.blocked_reason, answered.blocked_detail) };
    } catch (error) {
      if (request !== asked || moving !== move) return;
      move.verdict = { state: 'refused', words: problem(error) };
    }
    showCopy(move, to, move.verdict.state === 'refused');
    render();
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
    const move = beginMove(); if (move === null) return;
    // A made part turns a quarter at a time, the only turns it can take.
    if (isPart(move.placedId)) { moveTo({ ...move.to, yaw: QUARTER_TURNS[(quarterOf(move.to.yaw) + (degrees > 0 ? 1 : 3)) % 4] }); return; }
    moveTo({ ...move.to, yaw: turned(move.to.yaw, degrees, free) });
  }

  async function keepMove() {
    if (moving === null || busy || moving.verdict.state !== 'ready') return;
    const move = moving, verdict = move.verdict, name = nameOf(move.placedId);
    busy = true; render();
    try {
      // The pose and the base the server's answer was about: anything since is refused as stale.
      const to = verdict.to;
      await post(actionOf(move.placedId, 'move'), routeOf(move.placedId) + '/move',
        { base_state_sha256: verdict.base, pose: poseOf(move.placedId, to), saved_entry: savedEntry() });
      busy = false; dropMove(); render(); say(movedNote(name, moveWords(move.from, to)), { undoable: true });
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
      busy = false; deselect(); say(removedNote(name), { undoable: true });
    } catch (error) { busy = false; confirming = null; failure = problem(error); render(); }
    try { await refreshRecords(); } catch {}
  }

  /** A made part's name by its id, from the parts read: what an undone part change names. */
  const partNamed = (partId) => parts.get(PART + partId)?.label ?? null;

  /**
   * Does again the last change taken back (Cmd+Shift+Z here and in History). Resolves, once the
   * version is read again, with the sentence it said, or null when a request was already on its way.
   */
  async function redo() {
    if (busy) return null;
    busy = true; render();
    let said;
    try {
      const stateBase = base();
      const preview = (await post('things.redo.preview', '/things/redo/preview', { base_state_sha256: stateBase })).body;
      if (preview.availability !== 'ready') say(said = redoRefusalWords(preview.blocked_reason, preview.blocked_detail));
      else {
        await post('things.redo', '/things/redo', { base_state_sha256: stateBase, saved_entry: savedEntry() });
        say(said = redoneNote(preview.would_change, partNamed, kindLabel), { undoable: true });
      }
    } catch (error) { say(said = problem(error)); }
    busy = false;
    try { await refreshRecords(); } catch {}
    if (selected !== null && !exists(selected)) deselect(); else render();
    return said;
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
        say(said = undoneNote(preview.would_change, partNamed, kindLabel));
      }
    } catch (error) { say(said = problem(error)); }
    busy = false;
    try { await refreshRecords(); } catch {}
    if (selected !== null && !exists(selected)) deselect(); else render();
    return said;
  }

  /** What a key or a pressed prompt asks for, by keyAction's name; `free` is Alt held. */
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
    else if (action === 'keep') void keepMove();
    else if (action === 'redo') void redo();
    else if (action === 'next') cycle(1);
    else if (action === 'previous') cycle(-1);
  }

  /**
   * A drawn thing's pick volume on the screen, standing where it stands or at `to` (its copy):
   * its footprint's four ground corners in order and the box around all eight corners; null when
   * any of them is behind the camera.
   */
  function onScreen(figure, to) {
    const volume = figure.pickVolume; if (!volume) return null;
    const box = volume.kind === 'box'
      ? { x0: volume.min[0], x1: volume.max[0], z0: volume.min[2], z1: volume.max[2], top: volume.max[1] }
      : { x0: volume.centre[0] - volume.radius, x1: volume.centre[0] + volume.radius, z0: volume.centre[2] - volume.radius, z1: volume.centre[2] + volume.radius, top: volume.centre[1] + volume.radius };
    const frame = to === null ? figure.root.getWorldTransform() : figure.root.parent.getWorldTransform();
    const size = figure.root.getLocalScale();
    const yaw = to === null ? 0 : to.yaw / 1e6, cos = Math.cos(yaw), sin = Math.sin(yaw);
    const ground = [];
    let left = Infinity, right = -Infinity, top = Infinity, bottom = -Infinity;
    for (const [x, z] of [[box.x0, box.z0], [box.x1, box.z0], [box.x1, box.z1], [box.x0, box.z1]]) {
      for (const y of [0, box.top]) {
        if (to === null) point.set(x, y, z);
        else {
          // Where the copy stands: turned about its own up axis, then moved, in its parent's frame.
          const across = x * size.x, along = z * size.z;
          point.set(to.x / 1000 + cos * across + sin * along, to.y / 1000 + y * size.y, to.z / 1000 - sin * across + cos * along);
        }
        frame.transformPoint(point, point);
        const at = b.camera.camera.worldToScreen(point, seen);
        if (at.z <= 0) return null;
        if (y === 0) ground.push({ x: at.x, y: at.y });
        left = Math.min(left, at.x); right = Math.max(right, at.x); top = Math.min(top, at.y); bottom = Math.max(bottom, at.y);
      }
    }
    return { ground, bounds: { left, right, top, bottom, headY: top, waistY: (top + bottom) / 2 } };
  }

  /**
   * A made part on the screen, standing where the parts read says or at `to` (its copy): its
   * footprint's ground corners in order and the box around it with its height, from the region's
   * frame through the region root; null when the world or part is not drawn or a corner is behind
   * the camera.
   */
  function partOnScreen(id, to) {
    const part = partOf(id), root = regionRoot();
    if (part === null || root === null) return null;
    const slot = slotOf(id);
    const base = to?.y ?? slot?.positionMm[2] ?? 0, height = Math.max(slot?.boxMm[2] ?? 0, 300);
    let [width, depth] = part.size_mm;
    // Turned an odd number of quarters from how it stands now, its sides swap.
    if (to !== null && Math.abs(quarterOf(to.yaw) - turnsNow(id)) % 2 === 1) [width, depth] = [depth, width];
    const east = to === null ? part.centre_mm[0] : to.x, north = to === null ? part.centre_mm[1] : -to.z;
    const frame = root.getWorldTransform();
    const ground = [];
    let left = Infinity, right = -Infinity, top = Infinity, bottom = -Infinity;
    for (const [x, n] of [[east - width / 2, north - depth / 2], [east + width / 2, north - depth / 2], [east + width / 2, north + depth / 2], [east - width / 2, north + depth / 2]]) {
      for (const y of [base, base + height]) {
        frame.transformPoint(point.set(x / 1000, y / 1000, -n / 1000), point);
        const at = b.camera.camera.worldToScreen(point, seen);
        if (at.z <= 0) return null;
        if (y === base) ground.push({ x: at.x, y: at.y });
        left = Math.min(left, at.x); right = Math.max(right, at.x); top = Math.min(top, at.y); bottom = Math.max(bottom, at.y);
      }
    }
    return { ground, bounds: { left, right, top, bottom, headY: top, waistY: (top + bottom) / 2 } };
  }

  /**
   * The ring at a chosen thing's foot, on the ground in the world (the ground ring, ruling L20), so a
   * wall or what stands in front covers it as it covers the thing: centred on its footprint and a
   * little wider than its half diagonal, so it never crosses the outline.
   */
  function ringUnder(id) {
    const corners = groundRing === null ? null : footprintInWorld(id);
    if (corners === null) { groundRing?.hide(); return; }
    const mean = (axis) => corners.reduce((sum, corner) => sum + corner[axis], 0) / corners.length;
    const half = (a, c) => Math.hypot(a.x - c.x, a.z - c.z) / 2;
    groundRing.place({ x: mean('x'), y: mean('y'), z: mean('z') }, Math.hypot(half(corners[0], corners[1]), half(corners[1], corners[2])) * RING_MARGIN);
  }

  /** A chosen thing's or made part's footprint as it stands: its four ground corners, world metres. */
  function footprintInWorld(id) {
    let frame, sides;
    if (isPart(id)) {
      const part = partOf(id), region = regionRoot();
      if (part === null || region === null) return null;
      const base = (slotOf(id)?.positionMm[2] ?? 0) / 1000, [width, depth] = part.size_mm, [east, north] = part.centre_mm;
      frame = region.getWorldTransform();
      sides = { x0: (east - width / 2) / 1000, x1: (east + width / 2) / 1000, z0: -(north - depth / 2) / 1000, z1: -(north + depth / 2) / 1000, y: base };
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
  /** The screen box around two subjects, the first's head and waist kept for the card's height. */
  const around = (first, second) => ({
    left: Math.min(first.left, second.left), right: Math.max(first.right, second.right),
    top: Math.min(first.top, second.top), bottom: Math.max(first.bottom, second.bottom),
    headY: first.headY, waistY: first.waistY,
  });
  const middle = (ground) => ({ x: ground.reduce((sum, corner) => sum + corner.x, 0) / ground.length, y: ground.reduce((sum, corner) => sum + corner.y, 0) / ground.length });

  listen(canvas, 'pointermove', event => { pointer = { x: event.clientX, y: event.clientY }; });
  listen(canvas, 'pointerleave', () => { pointer = null; });
  render();

  return {
    active: () => on,
    undo,
    redo,
    /**
     * The made kinds' labels as build mode reads them (`label(kind)`, and `listen` to be told when one
     * lands), for History's rows to name creatures with the same reads; a page with no build mode
     * makes its own with `createKindLabels`.
     */
    kindLabels,
    /** Act on a key; true when build mode took it. */
    key(event) {
      const action = keyAction(flags(), event);
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
      if (!on || busy || event.button !== 0 || selected === null || confirming !== null) return false;
      if (placedAt(event.clientX, event.clientY) !== selected) return false;
      const ground = groundAt(event.clientX, event.clientY);
      const move = ground === null ? null : beginMove();
      if (move === null) return false;
      move.grip = { east: move.to.x - ground.xMm, south: move.to.z - ground.zMm };
      const carry = (at, free) => {
        const where = groundAt(at.clientX, at.clientY);
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
      const placedId = placedAt(x, y);
      if (placedId === null) { if (selected !== null) deselect(); return true; }
      if (placedId !== selected) select(placedId);
      return true;
    },
    frame(now) {
      if (!on) return;
      if (now - lastPick >= 50) {
        lastPick = now;
        hovered = pointer && !inspecting() && moving?.grip == null ? placedAt(pointer.x, pointer.y) : null;
        canvas.style.cursor = moving?.grip != null ? 'grabbing' : hovered !== null ? (hovered === selected ? 'grab' : 'pointer') : '';
      }
      const layer = things()?.layer;
      // The name of what the pointer is on, above it; the chosen thing's card names it instead, and
      // a carried copy's card speaks for where it is going.
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
      if (!cardShows()) { hideMarks(); lastPlacedKey = ''; }
      else {
        // Out of view is not closed: the card keeps its state and shows again when it is in view.
        const figure = isPart(selected) ? null : layer?.figureOf(selected) ?? null;
        const carrying = moving !== null && moving.placedId === selected;
        const standing = isPart(selected) ? partOnScreen(selected, null) : figure && figure.root.enabled ? onScreen(figure, null) : null;
        const carried = !carrying ? null : isPart(selected) ? partOnScreen(selected, moving.to) : figure ? onScreen(figure, moving.to) : null;
        const key = [standing, carried].map(shape => shape === null ? '-' : [...shape.ground.flatMap(p => [p.x, p.y]), shape.bounds.left, shape.bounds.right, shape.bounds.top, shape.bounds.bottom].map(v => v.toFixed(1)).join(',')).join('|') + (moving?.verdict.state ?? '');
        if (key === lastPlacedKey) { /* Nothing moved on the screen: everything stays where it is. */ }
        else if (carried === null && standing === null) { lastPlacedKey = key; card.root.style.visibility = 'hidden'; hideMarks(); }
        else {
          lastPlacedKey = key;
          card.root.style.visibility = '';
          // While a copy is carried, the card stands beside the copy and the spot it left together,
          // its connector to the copy (ruling L11).
          if (carried && standing) card.place(around(carried.bounds, standing.bounds), { connect: carried.bounds });
          else card.place((carried ?? standing).bounds);
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
      // Inspecting a being hides the card and the hints; closing it brings them back.
      if (inspecting() !== wasInspecting) { wasInspecting = inspecting(); render(); }
    },
    dispose() {
      lifetime.abort();
      if (on) { on = false; renderCorners(); }
      canvas.style.cursor = '';
      for (const part of [origin.root, trail.root, chosen.root, copy.root, tag.root, card.root]) part.remove();
      groundRing?.dispose();
    },
  };
}
