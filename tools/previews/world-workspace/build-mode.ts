// Build mode in the world workspace. B switches it on and off while the world keeps playing. In it,
// pointing at a thing placed in the world names it, a click selects it (its outline, a ring at its
// foot and a card beside it). Dragging it carries a see-through copy along the ground and `[` `]`
// turn it (half metres and 15 degree steps, Alt for free); the server says whether it may stand
// there while it moves and when it is let go, and Enter keeps the move, Esc puts it back. Backspace
// asks the server what removing it would do and Enter does it, and Cmd+Z takes back the world's
// newest change, and Cmd+Shift+Z does the last change taken back again. Tab and Shift+Tab choose
// the next or previous placed thing in view, so selecting needs no pointer; H shows the world's
// History. Every write goes through the app's own edit path (`send`, main.ts's sendPlanned), which
// advances the saved world and redraws what changed; every write is asked of the server first as a
// preview, and only the server's answer is shown.
// It is drawn with the in-world design's shared parts (world-ui.ts) and the world's corners (the
// mode word, the Back corner, the hints and the note); what a key does in each state, and every
// sentence, is build-words.mjs.
import { pointerRay } from '../../../web/packages/atlas-react/src/playcanvas/index.ts';
import { HISTORY, buildHints, cardPrompts, changeWords, clockWords, dayWords, keepLine, keyAction, moveWords, movedNote, nothingInView, placedLine, redoRefusalWords, redoneNote, refusalWords, removeLine, removeTitle, removedNote, snapped, thingName, titled, turned, undoRefusalWords, undoneNote } from './build-words.mjs';
import { cardWords, keyWord, label, nameTag, outline, page, path, promptColumn, promptRow, ring, scaleOf, sideCard } from './world-ui.ts';

/** How many of the world's newest changes History lists. */
const CHANGES_SHOWN = 8;
/** How long a carried thing rests before the server is asked about where it is, in milliseconds. */
const ASK_AFTER_MS = 180;
/** How much wider than the footprint's drawn extent the ring at a thing's foot is. */
const RING_MARGIN = 1.18;
/** What a refusal the server words for a person starts with, drawn in the refused colour. */
const NOT_HERE = 'Not here:';

export function mountBuildMode({ b, root, state, entry, read, send, binding, canvas, corners, inspecting }) {
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
  const foot = ring();
  const history = page({ form: 'full' });
  history.root.setAttribute('aria-label', HISTORY.title);
  // The page's title at the top, its list from the sections' line (spec 5.7); the timeline goes above
  // the list when History holds runs and models too.
  const historyTitle = node('h1', HISTORY.title, 'wu-page-title');
  historyTitle.style.cssText = 'position:absolute;left:calc(120 * var(--u));top:calc(96 * var(--u))';
  const historyBody = node('div');
  historyBody.style.cssText = 'position:absolute;left:calc(120 * var(--u));top:calc(300 * var(--u));width:calc(620 * var(--u))';
  history.content.prepend(historyTitle, historyBody);
  // Undo works while History is open from build mode, so it is drawn, before Back (frame 23).
  history.keys.append(
    keyWord({ keys: ['⌘Z'], word: 'Undo', shortcut: 'Meta+Z', onPress: () => { void undo(); } }),
    keyWord({ keys: ['Esc'], word: 'Back', shortcut: 'Escape', onPress: () => closeChanges() }),
  );
  root.append(origin.root, trail.root, chosen.root, copy.root, foot.root, tag.root, card.root);

  let on = false, hovered = null, selected = null, confirming = null, busy = false, failure = '';
  /**
   * A move being made: the thing, where it stands (`from`) and where it would stand (`to`, region
   * frame: east, up, south in millimetres, yaw in microradians), the grip while it is dragged, and
   * the server's newest answer about `to` (`verdict`: checking, ready or refused, with its words).
   */
  let moving = null, asked = 0, askTimer = 0;
  let records = new Map(), pointer = null, lastPick = 0;
  /** The version's edit log and every thing it ever placed (removed ones too), for History. */
  let edits = [], everyThing = new Map(), changesOpen = false;
  /** The first read of the version's things after B, which a click made before it ends waits for. */
  let reading = null;
  /** What the corners show now, so they are told only when it changes (a hint's fade restarts when told). */
  let cornersShow = '';
  const point = b.camera.getPosition().clone(), seen = point.clone();
  let wasInspecting = false;

  const things = () => b.__workspaceThings?.() ?? null;
  const focused = () => [card.root, history.root].some(element => element.contains(document.activeElement));
  const flags = () => ({ on, selected: selected !== null, confirming: confirming !== null, moving: moving !== null, ready: moving?.verdict.state === 'ready', busy, changes: changesOpen, focused: focused() });

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
    everyThing = new Map((version.things || []).map(thing => [thing.thing_id, thing]));
    edits = Array.isArray(version.edits) ? version.edits : [];
    if (changesOpen) renderChanges();
  }

  /** History while it lists only build mode's changes: the world's newest changes in words, newest first. */
  function renderChanges() {
    const shown = edits.slice(-CHANGES_SHOWN).reverse();
    const list = [];
    if (!shown.length) list.push(label(HISTORY.today), node('p', HISTORY.empty, 'wu-small-text'));
    const named = (thingId) => { const thing = everyThing.get(thingId); return thing ? thingName(thing) : null; };
    const now = Date.now();
    let day = null;
    for (const edit of shown) {
      // Today's changes under "Today", each earlier day's under its date.
      const heading = dayWords(edit.recorded_at, now);
      if (heading !== day) { day = heading; list.push(label(heading)); }
      const row = node('div', '', 'wu-list-row');
      row.append(node('span', clockWords(edit.recorded_at), 'wu-time'), node('div', changeWords(edit, edits, named), 'wu-what'));
      list.push(row);
    }
    historyBody.replaceChildren(...list);
  }
  function toggleChanges() {
    if (changesOpen) { closeChanges(); return; }
    changesOpen = true; renderChanges(); history.open(root);
    void refreshRecords().catch(() => {});
    render();
  }
  function closeChanges() { changesOpen = false; history.close(); render(); canvas.focus({ preventScroll: true }); }

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
    return found.sort((a, c) => a.distance - c.distance || (a.placedId < c.placedId ? -1 : 1)).map(item => item.placedId);
  }
  function cycle(step) {
    const ids = inView();
    if (!ids.length) { say(nothingInView()); return; }
    const at = selected === null ? -1 : ids.indexOf(selected);
    select(ids[at === -1 ? (step > 0 ? 0 : ids.length - 1) : (at + step + ids.length) % ids.length]);
  }

  /** The placed thing a screen point meets first, or null: a person or an object in front hides it. */
  function placedAt(x, y) {
    if (!b.__workspacePick) return null;
    const ray = pointerRay(b, x, y); if (!ray) return null;
    const hit = b.__workspacePick(ray.origin, ray.direction);
    const placedId = hit?.inhabitantId ? null : hit?.thing?.pick?.placedId ?? null;
    return placedId !== null && records.has(placedId) ? placedId : null;
  }

  function nameOf(placedId) { return thingName(records.get(placedId)); }

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
    const items = cardPrompts({ moving: moving !== null, ready: verdict === 'ready', refused: verdict === 'refused', confirming: confirming !== null });
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
      body.push(cardWords({ title: titled(name), lines: [placedLine()] }));
      if (busy) body.push(answer('Checking…'));
      else if (failure) body.push(answer(failure));
    }
    body.push(prompts());
    card.body.replaceChildren(...body);
    card.body.querySelector('.wu-card-title')?.setAttribute('id', 'bm-title');
  }

  function hideMarks() { chosen.hide(); copy.hide(); origin.hide(); trail.hide(); foot.hide(); }
  /** Whether the chosen thing's card and marks show: building, something chosen, nothing over them. */
  const cardShows = () => on && selected !== null && !inspecting() && !changesOpen;

  function select(placedId) {
    dropMove();
    selected = placedId; confirming = null; failure = '';
    render();
  }
  function deselect() {
    dropMove();
    selected = null; confirming = null; failure = '';
    render(); canvas.focus({ preventScroll: true });
  }
  function cancel() { confirming = null; failure = ''; render(); }

  async function toggle() {
    if (on) { leave(); return; }
    on = true; say(''); render();
    reading = refreshRecords().catch(error => { say(error.message); });
    await reading; reading = null;
  }
  function leave() {
    dropMove();
    if (changesOpen) { changesOpen = false; history.close(); }
    on = false; hovered = null; tag.hide();
    selected = null; confirming = null; failure = '';
    render(); canvas.focus({ preventScroll: true });
  }

  /** The move under way, if any, ended without keeping it: the copy goes, nothing was written. */
  function dropMove() {
    if (moving === null) return;
    moving = null; ++asked; clearTimeout(askTimer);
    things()?.layer.setGhost(null);
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
    things()?.layer.setGhost({ placedId: moving.placedId, xMm: to.x, yMm: to.y, zMm: to.z, yawMicroradians: to.yaw, refused: false });
    clearTimeout(askTimer);
    askTimer = window.setTimeout(() => { void askMove(); }, ASK_AFTER_MS);
    render();
  }

  /** The server's move preview for where the copy stands now; an older answer is dropped. */
  async function askMove() {
    if (moving === null) return;
    const request = ++asked, move = moving, to = { ...move.to }, stateBase = base();
    try {
      const answered = (await post('things.move.preview', '/things/' + encodeURIComponent(move.placedId) + '/move/preview',
        { base_state_sha256: stateBase, pose: { x_mm: to.x, y_mm: to.y, z_mm: to.z, yaw_microradians: to.yaw } })).body;
      if (request !== asked || moving !== move) return;
      move.verdict = answered.availability === 'ready'
        ? { state: 'ready', words: answered.landing?.checked === false ? 'Where it may stand is not checked in this world.' : '', base: stateBase, to }
        : { state: 'refused', words: refusalWords(answered.blocked_reason, answered.blocked_detail) };
    } catch (error) {
      if (request !== asked || moving !== move) return;
      move.verdict = { state: 'refused', words: problem(error) };
    }
    things()?.layer.setGhost({ placedId: move.placedId, xMm: to.x, yMm: to.y, zMm: to.z, yawMicroradians: to.yaw, refused: move.verdict.state === 'refused' });
    render();
  }

  function turn(degrees, free) {
    const move = beginMove(); if (move === null) return;
    moveTo({ ...move.to, yaw: turned(move.to.yaw, degrees, free) });
  }

  async function keepMove() {
    if (moving === null || busy || moving.verdict.state !== 'ready') return;
    const move = moving, verdict = move.verdict, name = nameOf(move.placedId);
    busy = true; render();
    try {
      // The pose and the base the server's answer was about: anything since is refused as stale.
      const to = verdict.to;
      await post('things.move', '/things/' + encodeURIComponent(move.placedId) + '/move',
        { base_state_sha256: verdict.base, pose: { x_mm: to.x, y_mm: to.y, z_mm: to.z, yaw_microradians: to.yaw }, saved_entry: savedEntry() });
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
    busy = true; failure = ''; render();
    try {
      const answered = (await post('things.remove.preview', '/things/' + encodeURIComponent(placedId) + '/remove/preview', { base_state_sha256: stateBase })).body;
      if (selected !== placedId) return;
      if (answered.availability === 'ready') confirming = { placedId, base: stateBase };
      else failure = refusalWords(answered.blocked_reason, answered.blocked_detail);
    } catch (error) { failure = problem(error); }
    finally { busy = false; render(); }
  }

  async function confirmRemove() {
    if (confirming === null || busy) return;
    const { placedId } = confirming, name = nameOf(placedId);
    busy = true; render();
    try {
      // Against the state the preview read: a change in between is refused as stale, never kept.
      await post('things.remove', '/things/' + encodeURIComponent(placedId) + '/remove', { base_state_sha256: confirming.base, saved_entry: savedEntry() });
      busy = false; deselect(); say(removedNote(name), { undoable: true });
    } catch (error) { busy = false; confirming = null; failure = problem(error); render(); }
    try { await refreshRecords(); } catch {}
  }

  async function redo() {
    if (busy) return;
    busy = true; render();
    try {
      const stateBase = base();
      const preview = (await post('things.redo.preview', '/things/redo/preview', { base_state_sha256: stateBase })).body;
      if (preview.availability !== 'ready') { say(redoRefusalWords(preview.blocked_reason, preview.blocked_detail)); return; }
      await post('things.redo', '/things/redo', { base_state_sha256: stateBase, saved_entry: savedEntry() });
      say(redoneNote(preview.would_change), { undoable: true });
    } catch (error) { say(problem(error)); }
    finally {
      busy = false;
      try { await refreshRecords(); } catch {}
      if (selected !== null && !records.has(selected)) deselect(); else render();
    }
  }

  async function undo() {
    if (busy) return;
    busy = true; render();
    try {
      const stateBase = base();
      const preview = (await post('things.undo.preview', '/things/undo/preview', { base_state_sha256: stateBase })).body;
      if (preview.availability !== 'ready') { say(undoRefusalWords(preview.blocked_reason, preview.blocked_detail)); return; }
      await post('things.undo', '/things/undo', { base_state_sha256: stateBase, saved_entry: savedEntry() });
      say(undoneNote(preview.would_change));
    } catch (error) { say(problem(error)); }
    finally {
      busy = false;
      try { await refreshRecords(); } catch {}
      if (selected !== null && !records.has(selected)) deselect(); else render();
    }
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
    else if (action === 'changes') toggleChanges();
    else if (action === 'close-changes') closeChanges();
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

  /** The ring at a footprint's foot: centred on it, a little wider than it is drawn. */
  function ringAround(ground) {
    const xs = ground.map(corner => corner.x), ys = ground.map(corner => corner.y);
    const rx = (Math.max(...xs) - Math.min(...xs)) / 2 * RING_MARGIN, ry = (Math.max(...ys) - Math.min(...ys)) / 2 * RING_MARGIN;
    foot.place((Math.max(...xs) + Math.min(...xs)) / 2, (Math.max(...ys) + Math.min(...ys)) / 2, rx, ry);
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
      const named = hovered !== null && hovered !== selected && moving === null && !changesOpen ? layer?.figureOf(hovered) : null;
      const head = named && named.root.enabled ? b.camera.camera.worldToScreen(named.markAnchor(point), seen) : null;
      if (head && head.z > 0) { tag.set({ name: titled(nameOf(hovered)) }); tag.place(head.x, head.y); }
      else tag.hide();
      if (!cardShows()) { hideMarks(); }
      else {
        // Out of view is not closed: the card keeps its state and shows again when it is in view.
        const figure = layer?.figureOf(selected) ?? null;
        const standing = figure && figure.root.enabled ? onScreen(figure, null) : null;
        const carried = figure && moving !== null && moving.placedId === selected ? onScreen(figure, moving.to) : null;
        if (carried === null && standing === null) { card.root.style.visibility = 'hidden'; hideMarks(); }
        else {
          card.root.style.visibility = '';
          // While a copy is carried, the card stands beside the copy and the spot it left together,
          // its connector to the copy (ruling L11).
          if (carried && standing) card.place(around(carried.bounds, standing.bounds), { connect: carried.bounds });
          else card.place((carried ?? standing).bounds);
          if (moving !== null) {
            // The copy where it would go, its spot dashed where it stands, and the way between.
            chosen.hide(); foot.hide();
            if (carried) { copy.form(moving.verdict.state === 'refused' ? 'refused' : 'copy'); copy.place(carried.ground); } else copy.hide();
            if (standing && carried) { origin.place(standing.ground); trail.place(middle(standing.ground), middle(carried.ground)); }
            else { origin.hide(); trail.hide(); }
          } else {
            copy.hide(); origin.hide(); trail.hide();
            if (standing) { chosen.place(standing.ground); ringAround(standing.ground); } else { chosen.hide(); foot.hide(); }
          }
        }
      }
      // Inspecting a being hides the card and the hints; closing it brings them back.
      if (inspecting() !== wasInspecting) { wasInspecting = inspecting(); render(); }
    },
    dispose() {
      lifetime.abort();
      if (on) { on = false; renderCorners(); }
      if (changesOpen) history.close();
      canvas.style.cursor = '';
      for (const part of [origin.root, trail.root, chosen.root, copy.root, foot.root, tag.root, card.root]) part.remove();
    },
  };
}
