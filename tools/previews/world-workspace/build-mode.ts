// Build mode in the world workspace. B switches it on and off while the world keeps playing. In it,
// pointing at a thing placed in the world names it, a click selects it (a ring at its foot and a
// small card beside it), Backspace asks the server what removing it would do and Enter does it, and
// Cmd+Z takes back the world's newest change. Every write goes through the app's own edit path
// (`send`, main.ts's sendPlanned), which advances the saved world and redraws what changed; every
// write is asked of the server first as a preview, and only the server's answer is shown.
// What a key does in each state, and every sentence, is build-words.mjs.
import { pointerRay } from '../../../web/packages/atlas-react/src/playcanvas/index.ts';
import { keyAction, refusalWords, removeQuestion, removedNote, thingName, titled, undoRefusalWords, undoneNote } from './build-words.mjs';
import './build-mode.css';

/** How long a note of what was done stays, in milliseconds. */
const NOTE_MS = 5000;

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
  root.append(pill, hints, tag, card, note);

  let on = false, hovered = null, selected = null, confirming = null, busy = false, failure = '';
  let records = new Map(), pointer = null, lastPick = 0, noteTimer = 0;
  /** The first read of the version's things after B, which a click made before it ends waits for. */
  let reading = null;
  const point = b.camera.getPosition().clone();
  let wasInspecting = false;

  const things = () => b.__workspaceThings?.() ?? null;
  const flags = () => ({ on, selected: selected !== null, confirming: confirming !== null, busy });

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
    hints.textContent = selected === null ? 'Drag to look · Click to select · ⌘Z to undo' : 'Drag to look · ⌘Z to undo';
    card.replaceChildren();
    card.hidden = !on || selected === null || inspecting();
    if (card.hidden) return;
    const name = nameOf(selected) || 'thing';
    const title = node('h2', titled(name), 'bm-title'); title.id = 'bm-title';
    card.setAttribute('aria-labelledby', 'bm-title');
    card.append(title);
    const actions = node('div', '', 'bm-actions');
    if (busy) card.append(node('p', 'Checking…', 'bm-line'));
    else if (failure) card.append(node('p', failure, 'bm-line bm-refused'));
    if (confirming !== null && !busy) {
      card.append(node('p', removeQuestion(name), 'bm-line'));
      actions.append(chip('Enter', 'Remove', () => { void confirmRemove(); }), chip('Esc', 'Keep it', cancel));
    } else if (!busy) {
      if (!failure) card.append(node('p', 'Placed in this world', 'bm-line'));
      actions.append(chip('⌫', 'Remove', () => { void askRemove(); }), chip('Esc', 'Close', deselect));
    }
    card.append(actions);
  }

  function select(placedId) {
    selected = placedId; confirming = null; failure = '';
    things()?.layer.setPicked({ placedId, thingId: null, subjectId: null });
    render();
  }
  function deselect() {
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
    on = false; hovered = null; tag.hidden = true;
    if (selected !== null) things()?.layer.setPicked(null);
    selected = null; confirming = null; failure = '';
    render(); canvas.focus({ preventScroll: true });
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
        hovered = pointer && !inspecting() ? placedAt(pointer.x, pointer.y) : null;
        canvas.style.cursor = hovered !== null ? 'pointer' : '';
      }
      const layer = things()?.layer;
      const place = (element, placedId, beside) => {
        // Out of view is not closed: the element keeps its state and shows again when it is in view.
        const figure = placedId === null ? null : layer?.figureOf(placedId);
        const screen = figure && figure.root.enabled ? b.camera.camera.worldToScreen(figure.markAnchor(point)) : null;
        element.style.visibility = screen && screen.z > 0 ? '' : 'hidden';
        if (!screen || screen.z <= 0) return;
        let x, y;
        if (beside) {
          // Beside the thing, clear of it by about its drawn height (its top to its foot on the
          // screen), on its right where there is room, else on its left, inside the window.
          const width = element.offsetWidth, height = element.offsetHeight;
          const foot = b.camera.camera.worldToScreen(figure.root.getPosition());
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
      pill.remove(); hints.remove(); tag.remove(); card.remove(); note.remove();
    },
  };
}
