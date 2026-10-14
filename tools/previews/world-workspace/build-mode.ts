// Build mode in the world workspace. B switches it on and off while the world keeps playing. In it,
// pointing at a thing placed in the world names it, a click selects it (a ring at its foot and a
// small card beside it). Dragging it carries a see-through copy along the ground and `[` `]` turn
// it (half metres and 15 degree steps, Alt for free); the server says whether it may stand there
// while it moves and when it is let go, and Enter keeps the move, Esc puts it back. Backspace asks
// the server what removing it would do and Enter does it, and Cmd+Z takes back the world's newest
// change, and Cmd+Shift+Z does the last change taken back again. Tab and Shift+Tab choose the
// next or previous placed thing in view, so selecting needs no pointer; H lists the world's changes. Every write goes through the app's own edit path
// (`send`, main.ts's sendPlanned), which advances the saved world and redraws what changed; every
// write is asked of the server first as a preview, and only the server's answer is shown.
// What a key does in each state, and every sentence, is build-words.mjs.
import { pointerRay } from '../../../web/packages/atlas-react/src/playcanvas/index.ts';
import { changeWords, keepLine, keyAction, moveWords, movedNote, redoRefusalWords, redoneNote, refusalWords, removeQuestion, removedNote, snapped, thingName, titled, turned, undoRefusalWords, undoneNote, whenWords } from './build-words.mjs';
import './build-mode.css';

/** How long a note of what was done stays, in milliseconds. */
const NOTE_MS = 5000;
/** How many of the world's newest changes the list shows. */
const CHANGES_SHOWN = 8;
/** How long a carried thing rests before the server is asked about where it is, in milliseconds. */
const ASK_AFTER_MS = 180;

export function mountBuildMode({ b, root, state, entry, read, send, binding, canvas, guidance, worlds = null, inspecting }) {
  const lifetime = new AbortController();
  const listen = (target, type, run, options = {}) => target.addEventListener(type, run, { ...options, signal: lifetime.signal });
  const node = (tag, words = '', cls = '') => { const item = document.createElement(tag); item.textContent = String(words); item.className = cls; return item; };
  const chip = (key, verb, run, cls = 'bm-action') => {
    const item = node('button', '', cls); item.type = 'button';
    // A one-glyph key (⌫) is drawn larger than a word key, so it reads at the chip's size.
    item.append(node('kbd', key, /^[^\x00-\x7f]$/u.test(key) ? 'bm-glyph' : ''), node('span', verb)); item.onclick = run; return item;
  };
  const versionPath = '/world/versions/' + encodeURIComponent(entry.authoredVersionId);
  const worldQuery = '?world_id=' + encodeURIComponent(entry.worldId);

  const pill = node('button', '', 'bm-pill'); pill.type = 'button';
  const hints = node('p', '', 'bm-hints'); hints.hidden = true;
  const tag = node('p', '', 'bm-tag'); tag.hidden = true; tag.setAttribute('aria-hidden', 'true');
  const card = node('section', '', 'bm-card'); card.hidden = true; card.setAttribute('role', 'region');
  const note = node('p', '', 'bm-note'); note.hidden = true; note.setAttribute('role', 'status');
  const changes = node('section', '', 'bm-changes'); changes.hidden = true;
  changes.setAttribute('role', 'region'); changes.setAttribute('aria-label', 'Changes');
  root.append(pill, hints, tag, card, note, changes);

  let on = false, hovered = null, selected = null, confirming = null, busy = false, failure = '';
  /**
   * A move being made: the thing, where it stands (`from`) and where it would stand (`to`, region
   * frame: east, up, south in millimetres, yaw in microradians), the grip while it is dragged, and
   * the server's newest answer about `to` (`verdict`: checking, ready or refused, with its words).
   */
  let moving = null, asked = 0, askTimer = 0;
  let records = new Map(), pointer = null, lastPick = 0, noteTimer = 0;
  /** The version's edit log and every thing it ever placed (removed ones too), for the changes list. */
  let edits = [], everyThing = new Map(), changesOpen = false;
  /** The first read of the version's things after B, which a click made before it ends waits for. */
  let reading = null;
  const point = b.camera.getPosition().clone(), footPoint = point.clone();
  let wasInspecting = false;

  const things = () => b.__workspaceThings?.() ?? null;
  const focused = () => [pill, card, changes].some(element => element.contains(document.activeElement));
  const flags = () => ({ on, selected: selected !== null, confirming: confirming !== null, moving: moving !== null, ready: moving?.verdict.state === 'ready', busy, changes: changesOpen, focused: focused() });

  function say(words) {
    clearTimeout(noteTimer);
    note.textContent = words; note.hidden = !words;
    if (words) noteTimer = window.setTimeout(() => { note.hidden = true; }, NOTE_MS);
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

  /** The world's newest changes in words, newest first. */
  function renderChanges() {
    changes.replaceChildren(node('h2', 'Changes', 'bm-title'));
    const shown = edits.slice(-CHANGES_SHOWN).reverse();
    if (!shown.length) changes.append(node('p', 'Nothing has been changed yet.', 'bm-line'));
    else {
      const list = node('ol', '', 'bm-change-list');
      const now = Date.now();
      for (const edit of shown) {
        const item = node('li', '', 'bm-change');
        const named = (thingId) => { const thing = everyThing.get(thingId); return thing ? thingName(thing) : null; };
        item.append(node('span', changeWords(edit, edits, named)), node('span', whenWords(edit.recorded_at, now), 'bm-when'));
        list.append(item);
      }
      changes.append(list);
    }
    const actions = node('div', '', 'bm-actions');
    actions.append(chip('Esc', 'Close', closeChanges));
    changes.append(actions);
  }
  function toggleChanges() {
    changesOpen = !changesOpen; changes.hidden = !changesOpen;
    if (changesOpen) { renderChanges(); void refreshRecords().catch(() => {}); }
    render();
  }
  function closeChanges() { changesOpen = false; changes.hidden = true; render(); canvas.focus({ preventScroll: true }); }

  /** The placed things in view now, nearest first: what Tab chooses among. */
  function inView() {
    const layer = things()?.layer;
    if (!layer) return [];
    const eye = b.camera.getPosition(), seen = [];
    for (const { placedId } of layer.drawn) {
      const figure = layer.figureOf(placedId);
      if (!records.has(placedId) || !figure || !figure.root.enabled) continue;
      const screen = b.camera.camera.worldToScreen(figure.markAnchor(point));
      if (screen.z <= 0 || screen.x < 0 || screen.x > innerWidth || screen.y < 0 || screen.y > innerHeight) continue;
      seen.push({ placedId, distance: eye.distance(figure.root.getPosition()) });
    }
    return seen.sort((a, c) => a.distance - c.distance || (a.placedId < c.placedId ? -1 : 1)).map(item => item.placedId);
  }
  function cycle(step) {
    const ids = inView();
    if (!ids.length) { say('No placed things in view. Walk closer to one.'); return; }
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

  function render() {
    pill.replaceChildren();
    if (on) { pill.append(node('span', 'Building', 'bm-pill-state'), node('kbd', 'B'), node('span', 'Done')); }
    else { pill.append(node('kbd', 'B'), node('span', 'Build')); }
    pill.setAttribute('aria-pressed', String(on));
    pill.setAttribute('aria-label', on ? 'Building. B to finish' : 'B to build');
    hints.hidden = !on; guidance.hidden = on || inspecting();
    // While building, Esc is build mode's (put back, close, then done): the way out of the world
    // and its Esc show again once building is done.
    if (worlds) worlds.hidden = on;
    hints.textContent = selected === null ? 'Click or Tab to select · ⌘Z to undo · H for changes'
      : moving !== null ? 'Drag it to move · [ ] to turn · Alt for free' : 'Drag it to move · [ ] to turn · Tab for the next';
    card.replaceChildren();
    // The changes list and the card each close on Esc: one at a time, so Esc means one thing.
    card.hidden = !on || selected === null || inspecting() || changesOpen;
    if (card.hidden) return;
    const name = nameOf(selected) || 'thing';
    const title = node('h2', titled(name), 'bm-title'); title.id = 'bm-title';
    card.setAttribute('aria-labelledby', 'bm-title');
    card.append(title);
    const actions = node('div', '', 'bm-actions');
    if (busy) card.append(node('p', 'Checking…', 'bm-line'));
    else if (failure) card.append(node('p', failure, 'bm-line bm-refused'));
    if (moving !== null && !busy) {
      const where = moveWords(moving.from, moving.to);
      card.append(node('p', where.charAt(0).toUpperCase() + where.slice(1), 'bm-line bm-where'));
      const verdict = moving.verdict;
      if (verdict.state === 'checking') card.append(node('p', 'Checking…', 'bm-line'));
      else if (verdict.state === 'refused') card.append(node('p', verdict.words, 'bm-line bm-refused'));
      else card.append(node('p', verdict.words || keepLine(), 'bm-line'));
      if (verdict.state === 'ready') actions.append(chip('Enter', 'Keep', () => { void keepMove(); }));
      actions.append(chip('Esc', 'Put it back', putBack));
    } else if (confirming !== null && !busy) {
      card.append(node('p', removeQuestion(name), 'bm-line'));
      actions.append(chip('Enter', 'Remove', () => { void confirmRemove(); }), chip('Esc', 'Keep it', cancel));
    } else if (!busy) {
      if (!failure) card.append(node('p', 'Placed in this world', 'bm-line'));
      actions.append(chip('⌫', 'Remove', () => { void askRemove(); }), chip('Esc', 'Close', deselect));
    }
    card.append(actions);
  }

  function select(placedId) {
    dropMove();
    selected = placedId; confirming = null; failure = '';
    things()?.layer.setPicked({ placedId, thingId: null, subjectId: null });
    render();
  }
  function deselect() {
    dropMove();
    selected = null; confirming = null; failure = '';
    things()?.layer.setPicked(null);
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
    if (changesOpen) { changesOpen = false; changes.hidden = true; }
    on = false; hovered = null; tag.hidden = true;
    if (selected !== null) things()?.layer.setPicked(null);
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
      const answer = (await post('things.move.preview', '/things/' + encodeURIComponent(move.placedId) + '/move/preview',
        { base_state_sha256: stateBase, pose: { x_mm: to.x, y_mm: to.y, z_mm: to.z, yaw_microradians: to.yaw } })).body;
      if (request !== asked || moving !== move) return;
      move.verdict = answer.availability === 'ready'
        ? { state: 'ready', words: answer.landing?.checked === false ? 'Where it may stand is not checked in this world.' : '', base: stateBase, to }
        : { state: 'refused', words: refusalWords(answer.blocked_reason, answer.blocked_detail) };
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
      busy = false; dropMove(); render(); say(movedNote(name, moveWords(move.from, to)));
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
    const placedId = selected, asked = base();
    busy = true; failure = ''; render();
    try {
      const answer = (await post('things.remove.preview', '/things/' + encodeURIComponent(placedId) + '/remove/preview', { base_state_sha256: asked })).body;
      if (selected !== placedId) return;
      if (answer.availability === 'ready') confirming = { placedId, base: asked };
      else failure = refusalWords(answer.blocked_reason, answer.blocked_detail);
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
      busy = false; deselect(); say(removedNote(name));
    } catch (error) { busy = false; confirming = null; failure = problem(error); render(); }
    try { await refreshRecords(); } catch {}
  }

  async function redo() {
    if (busy) return;
    busy = true; render();
    try {
      const asked = base();
      const preview = (await post('things.redo.preview', '/things/redo/preview', { base_state_sha256: asked })).body;
      if (preview.availability !== 'ready') { say(redoRefusalWords(preview.blocked_reason, preview.blocked_detail)); return; }
      await post('things.redo', '/things/redo', { base_state_sha256: asked, saved_entry: savedEntry() });
      say(redoneNote(preview.would_change));
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
      const asked = base();
      const preview = (await post('things.undo.preview', '/things/undo/preview', { base_state_sha256: asked })).body;
      if (preview.availability !== 'ready') { say(undoRefusalWords(preview.blocked_reason, preview.blocked_detail)); return; }
      await post('things.undo', '/things/undo', { base_state_sha256: asked, saved_entry: savedEntry() });
      say(undoneNote(preview.would_change));
    } catch (error) { say(problem(error)); }
    finally {
      busy = false;
      try { await refreshRecords(); } catch {}
      if (selected !== null && !records.has(selected)) deselect(); else render();
    }
  }

  listen(canvas, 'pointermove', event => { pointer = { x: event.clientX, y: event.clientY }; });
  listen(canvas, 'pointerleave', () => { pointer = null; });
  pill.onclick = () => { void toggle(); };
  render();

  return {
    active: () => on,
    /** Act on a key; true when build mode took it. */
    key(event) {
      const action = keyAction(flags(), event);
      if (action === null) return false;
      event.preventDefault();
      if (action === 'toggle') void toggle();
      else if (action === 'leave') leave();
      else if (action === 'deselect') deselect();
      else if (action === 'cancel') cancel();
      else if (action === 'remove') void askRemove();
      else if (action === 'confirm') void confirmRemove();
      else if (action === 'undo') void undo();
      else if (action === 'turn-left') turn(15 * (event.altKey ? 1 / 15 : 1), event.altKey);
      else if (action === 'turn-right') turn(-15 * (event.altKey ? 1 / 15 : 1), event.altKey);
      else if (action === 'put-back') putBack();
      else if (action === 'keep') void keepMove();
      else if (action === 'redo') void redo();
      else if (action === 'next') cycle(1);
      else if (action === 'previous') cycle(-1);
      else if (action === 'changes') toggleChanges();
      else if (action === 'close-changes') closeChanges();
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
        const point = groundAt(at.clientX, at.clientY);
        if (point === null || moving !== move) return;
        moveTo({ ...move.to, x: snapped(point.xMm + move.grip.east, free), z: snapped(point.zMm + move.grip.south, free) });
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
      const place = (element, placedId, beside) => {
        // Out of view is not closed: the element keeps its state and shows again when it is in view.
        const figure = placedId === null ? null : layer?.figureOf(placedId);
        // While it is being moved, beside where it would stand.
        const to = beside && moving !== null && moving.placedId === placedId ? moving.to : null;
        const anchor = !figure ? null : to === null ? figure.markAnchor(point)
          : figure.root.parent.getWorldTransform().transformPoint(point.set(to.x / 1000, to.y / 1000 + figure.standingHeight + 0.25, to.z / 1000), point);
        const screen = anchor && (figure.root.enabled || to !== null) ? b.camera.camera.worldToScreen(anchor) : null;
        element.style.visibility = screen && screen.z > 0 ? '' : 'hidden';
        if (!screen || screen.z <= 0) return;
        let x, y;
        if (beside) {
          // Beside the thing, clear of it by about its drawn height (its top to its foot on the
          // screen), on its right where there is room, else on its left, inside the window.
          const width = element.offsetWidth, height = element.offsetHeight;
          const foot = b.camera.camera.worldToScreen(to === null ? figure.root.getPosition()
            : figure.root.parent.getWorldTransform().transformPoint(footPoint.set(to.x / 1000, to.y / 1000, to.z / 1000), footPoint));
          const clear = Math.max(32, Math.min(240, Math.abs(foot.y - screen.y) + 12));
          x = screen.x + clear + width <= innerWidth - 16 ? screen.x + clear : screen.x - clear - width;
          x = Math.max(16, Math.min(innerWidth - width - 16, x));
          y = Math.max(72, Math.min(innerHeight - height - 56, screen.y));
        } else {
          x = Math.max(16, Math.min(innerWidth - 16, screen.x));
          y = Math.max(16, Math.min(innerHeight - 16, screen.y)) - 10;
        }
        const transform = beside ? `translate3d(${x.toFixed(1)}px,${y.toFixed(1)}px,0)` : `translate3d(${x.toFixed(1)}px,${y.toFixed(1)}px,0) translate(-50%,-100%)`;
        if (element.style.transform !== transform) element.style.transform = transform;
      };
      const shownTag = hovered !== null && hovered !== selected ? hovered : null;
      tag.hidden = shownTag === null;
      if (shownTag !== null) { tag.textContent = titled(nameOf(shownTag)); place(tag, shownTag, false); }
      if (!card.hidden) place(card, selected, true);
      // Inspecting a being hides the card and the hints; closing it brings them back.
      if (inspecting() !== wasInspecting) { wasInspecting = inspecting(); render(); }
    },
    dispose() {
      lifetime.abort(); clearTimeout(noteTimer);
      if (selected !== null) things()?.layer.setPicked(null);
      canvas.style.cursor = '';
      guidance.hidden = false;
      if (worlds) worlds.hidden = false;
      pill.remove(); hints.remove(); tag.remove(); card.remove(); note.remove(); changes.remove();
    },
  };
}
