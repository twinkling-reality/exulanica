// Build mode's words and keys, without the page: what a placed thing is called, what each server
// answer says to a person, and what a key does in each of build mode's states. build-mode.ts acts
// on these answers; verify-build-words.mjs holds them.

/** What a placed thing is called in a sentence, from its document's kind: "well", "lamp post". */
export function thingName(document) {
  const kind = document?.kind;
  if (kind?.source === 'workspace') return 'creature you made';
  return typeof kind?.kind === 'string' && kind.kind ? kind.kind.replaceAll('_', ' ') : 'thing';
}

/** The same name as a title: "Well", "Lamp post". */
export function titled(name) {
  return name.charAt(0).toUpperCase() + name.slice(1);
}

/**
 * One sentence for a refusal, by the server's code, and the server's own sentence where it says
 * where a thing may not stand, which is written for a person. Any other code says plainly that
 * nothing changed: a server's other details are written for developers.
 */
const REFUSALS = Object.freeze({
  stale_object_base: 'Someone changed this world a moment ago. Look again and try once more.',
  stale_saved_world_entry: 'This world was saved from another window a moment ago. Reload it to see it as it is now.',
  saved_entry_reconciliation_required: 'This world was saved from another window a moment ago. Reload it to see it as it is now.',
  invalidated_source_version: 'What this world was made from changed, so it cannot be changed here.',
  unavailable_society_input: 'The people here could not take this change, so nothing changed.',
  thing_kind_erased: 'What this was made from was deleted, so it cannot be moved. You can remove it.',
  forbidden: 'This world can only be looked at here.',
  http_403: 'This world can only be looked at here.',
});

export function refusalWords(code, detail) {
  if (typeof code === 'string' && code.startsWith('thing_landing_') && typeof detail === 'string' && detail) return 'Not here: ' + detail.charAt(0).toLowerCase() + detail.slice(1);
  // A made part's refusals, and the land's under it, are the server's sentences for a person already.
  if (typeof code === 'string' && (code.startsWith('part_') || code.startsWith('landform_')) && typeof detail === 'string' && detail) return detail;
  return Object.hasOwn(REFUSALS, code) ? REFUSALS[code] : 'That could not be done. Nothing changed.';
}

/** The question before a thing is removed, the card's title. */
export function removeTitle(name) {
  return `Remove the ${name}?`;
}

/** What removing a thing will do, the line under the question. */
export function removeLine() {
  return 'Nobody can use it from the next minute.';
}

/** What was done, said after it is kept. */
export function removedNote(name) {
  return `Removed the ${name}.`;
}

/**
 * What an undo did, from its preview's `would_change`: the edit it reverses and the thing's
 * document as it stands and as the undo leaves it.
 */
export function undoneNote(change) {
  const undoes = change?.undoes?.kind;
  const name = thingName(change?.after ?? change?.before);
  if (undoes === 'remove_thing') return `Brought back the ${name}.`;
  if (undoes === 'move_thing') return `Put the ${name} back where it was.`;
  if (undoes === 'add_thing') return `Took away the ${name} that was placed.`;
  return 'Undid the last change.';
}

/**
 * What a redo did, from its preview's `would_change`: the thing's document as it stands and as the
 * redo leaves it. Read from the documents, since a redo is the undo of an undo.
 */
export function redoneNote(change) {
  const before = change?.before ?? null, after = change?.after ?? null;
  const name = thingName(after ?? before);
  if (before !== null && after !== null && !before.removed && after.removed) return `Removed the ${name} again.`;
  if ((before === null || before.removed) && after !== null && !after.removed) return `Placed the ${name} again.`;
  const a = before?.transform, b = after?.transform;
  if (a && b && (a.x_mm !== b.x_mm || a.z_mm !== b.z_mm || a.yaw_microradians !== b.yaw_microradians)) return `Moved the ${name} again.`;
  return 'Did the change again.';
}

/** The redo preview's refusal when nothing is left to do again. */
export function redoRefusalWords(code, detail) {
  return code === 'invalid_object_state' ? 'Nothing left to do again.' : refusalWords(code, detail);
}

/**
 * One line of the world's changes, from its edit log: what the edit did, by its kind and the
 * thing it names (`nameOf(thingId)`, a name or null) or the made part (`partNameOf(partId)`), an undo
 * by what it took back, and a redo (an undo of an undo) by what it did again.
 */
export function changeWords(edit, edits, nameOf, partNameOf = () => null) {
  const byId = new Map(edits.map(each => [each.edit_id, each]));
  const plain = (one) => {
    // A part made with the world: named by its parts read, its change stored as an element's.
    if (typeof one.element_id === 'string' && one.element_id.startsWith('part:')) {
      const name = partNameOf(one.element_id.slice('part:'.length));
      const part = name ? `the ${name}` : 'a part of the world';
      if (one.kind === 'suppress_element') return `Removed ${part}`;
      if (one.kind === 'transform_element') return `Moved ${part}`;
    }
    const name = one.thing_id ? nameOf(one.thing_id) : null;
    const thing = name ? `the ${name}` : 'a thing';
    if (one.kind === 'add_thing') return `Placed ${thing}`;
    if (one.kind === 'move_thing') return `Moved ${thing}`;
    if (one.kind === 'remove_thing') return `Removed ${thing}`;
    if (/_object$/.test(one.kind)) return one.kind.startsWith('add') ? 'Placed an object' : one.kind.startsWith('move') ? 'Moved an object' : one.kind.startsWith('remove') ? 'Removed an object' : 'Changed an object';
    return 'Changed the world';
  };
  if (edit.kind !== 'undo') return plain(edit);
  const undone = byId.get(edit.undone_edit_id);
  if (!undone) return 'Took back a change';
  if (undone.kind === 'undo') {
    const again = byId.get(undone.undone_edit_id);
    return again ? `${plain(again)} again` : 'Did a change again';
  }
  const words = plain(undone);
  return `Took back: ${words.charAt(0).toLowerCase()}${words.slice(1)}`;
}

const MONTHS = Object.freeze(['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']);

/** The day a change was recorded, as History's list heads it: "Today", else "13 Oct". */
export function dayWords(recordedAt, now) {
  const at = new Date(Date.parse(recordedAt)), today = new Date(now);
  if (!Number.isFinite(at.getTime())) return '';
  const same = at.getFullYear() === today.getFullYear() && at.getMonth() === today.getMonth() && at.getDate() === today.getDate();
  return same ? HISTORY.today : `${at.getDate()} ${MONTHS[at.getMonth()]}`;
}

/** When a change was recorded, as History's time column says it: the clock time, "18:02". */
export function clockWords(recordedAt) {
  const at = Date.parse(recordedAt);
  if (!Number.isFinite(at)) return '';
  const time = new Date(at);
  return `${String(time.getHours()).padStart(2, '0')}:${String(time.getMinutes()).padStart(2, '0')}`;
}

/** The undo preview's refusal when nothing is left to take back. */
export function undoRefusalWords(code, detail) {
  return code === 'invalid_object_state' ? 'Nothing left to undo.' : refusalWords(code, detail);
}

/** Whole metres where whole, else to a tenth: "6.5", "2". */
const metres = mm => { const value = Math.round(Math.abs(mm) / 100) / 10; return String(value); };

/**
 * A move in words, from where a thing stands to where it would stand (region frame: east, south,
 * millimetres; a yaw in microradians): "6.5 m east, 2 m north, turned 45°", or "where it was".
 */
export function moveWords(from, to) {
  const parts = [];
  const east = to.x - from.x, south = to.z - from.z;
  if (Math.abs(east) >= 50) parts.push(`${metres(east)} m ${east > 0 ? 'east' : 'west'}`);
  if (Math.abs(south) >= 50) parts.push(`${metres(south)} m ${south > 0 ? 'south' : 'north'}`);
  const turn = Math.round(((((to.yaw - from.yaw) / 1e6) * 180 / Math.PI) % 360 + 540) % 360 - 180);
  if (turn !== 0 && Math.abs(turn) !== 180) parts.push(`turned ${Math.abs(turn)}°`);
  else if (Math.abs(turn) === 180) parts.push('turned round');
  return parts.length ? parts.join(', ') : 'where it was';
}

/**
 * What a kept move did, from its words (moveWords): "Moved the bench 3.5 m west, turned 15°.", and
 * a turn alone "Turned the bench 90°." or "Turned the bench round.".
 */
export function movedNote(name, words) {
  return words.startsWith('turned ') ? `Turned the ${name} ${words.slice('turned '.length)}.` : `Moved the ${name} ${words}.`;
}

/** The card's line for a thing a person placed. */
export function placedLine() {
  return 'Placed in this world';
}

/** The card's line for a part made with the world, with the area it stands in when it names one. */
export function madeLine(area) {
  return typeof area === 'string' && area ? `Made with this world · ${titled(area)}` : 'Made with this world';
}

/** What keeping a move will do, said before it is kept. */
export function keepLine() {
  return 'People who use it go to the new spot from the next minute.';
}

/** Said when Tab finds nothing to choose. */
export function nothingInView() {
  return 'No placed things in view. Walk closer to one.';
}

/** The History page while it lists only build mode's changes (until it shows runs and models too). */
export const HISTORY = Object.freeze({ title: 'History', today: 'Today', empty: 'Nothing has been changed yet.' });

/**
 * The keys build mode offers in its state `{ moving }`, as its hints draw them, bottom left: each
 * the caps drawn, its word and the shortcut a reader is told.
 */
export function buildHints(state) {
  if (state.moving) {
    return [
      { keys: 'mouse', word: 'Drag to move' },
      { keys: ['[', ']'], word: 'Turn', shortcut: '[ ]' },
      { keys: ['Alt'], word: 'Free', shortcut: 'Alt' },
    ];
  }
  return [
    { keys: 'mouse-click', word: 'Select' },
    { keys: ['Tab'], word: 'Next', shortcut: 'Tab' },
    { keys: ['⌘Z'], word: 'Undo', shortcut: 'Meta+Z' },
    { keys: ['H'], word: 'History', shortcut: 'H' },
  ];
}

/**
 * The prompts on the chosen thing's card in build mode's state `{ moving, ready, confirming }`, each
 * with the action pressing it does (keyAction's names; none for a prompt that only says how):
 * chosen, Drag to move, Turn and Remove (not Remove once a removal was refused: it would only be
 * refused again); moving, Keep (dimmed until the server says it may stand there) and Put it back;
 * refused, Put it back alone; a question, Remove and Keep it.
 */
export function cardPrompts(state) {
  if (state.confirming) {
    return [
      { keys: ['Enter'], word: 'Remove', shortcut: 'Enter', action: 'confirm' },
      { keys: ['Esc'], word: 'Keep it', shortcut: 'Escape', action: 'cancel' },
    ];
  }
  if (state.moving) {
    const back = { keys: ['Esc'], word: 'Put it back', shortcut: 'Escape', action: 'put-back' };
    if (state.refused) return [back];
    return [{ keys: ['Enter'], word: 'Keep', shortcut: 'Enter', action: 'keep', disabled: !state.ready }, back];
  }
  return [
    { keys: 'mouse', word: 'Drag to move' },
    { keys: ['[', ']'], word: 'Turn', shortcut: '[ ]', action: 'turn-right' },
    ...(state.removeRefused ? [] : [{ keys: ['Del'], word: 'Remove', shortcut: 'Delete', action: 'remove' }]),
  ];
}

/** The largest yaw a pose may state (one revolution, in microradians, as the server bounds it). */
export const MAX_YAW = 6_283_185;

/**
 * A yaw turned by `degrees`, in microradians within one revolution; snapped to whole steps of
 * `degrees` unless `free`.
 */
export function turned(yaw, degrees, free) {
  const step = degrees * Math.PI / 180 * 1e6;
  let next = yaw + step;
  if (!free) next = Math.round(next / Math.abs(step)) * Math.abs(step);
  const turn = 2 * Math.PI * 1e6;
  next = ((next % turn) + turn) % turn;
  return Math.min(MAX_YAW, Math.round(next));
}

/** A ground point snapped to half metres unless `free` (millimetres). */
export function snapped(mm, free) {
  return free ? Math.round(mm) : Math.round(mm / 500) * 500;
}

/**
 * What a key does in build mode's state `{ on, selected, confirming, moving, ready, busy }`: an
 * action, 'held' for a key build mode takes and does nothing with now (a held-down B, Backspace with
 * nothing selected), or null when it leaves the key to the page. B switches build mode on and off;
 * Esc puts a question away, puts a moved thing back, lets go of what is selected, then leaves build
 * mode; Backspace or Delete asks to remove what is selected; `[` and `]` turn it, Alt for a free
 * turn; Enter answers yes to a question or keeps a move the server said may be kept; Cmd+Z or
 * Ctrl+Z takes back the world's newest change, with Shift does the last one taken back again; Tab
 * and Shift+Tab choose the next or previous placed thing in view; H shows the world's changes, and
 * Esc closes them first. While a request is on its way only B acts: nothing
 * is sent twice, and Esc does not seem to call back a change already sent.
 */
export function keyAction(state, event) {
  const command = event.metaKey || event.ctrlKey;
  if (command) return state.on && event.code === 'KeyZ' && !event.altKey && !state.busy && !event.repeat ? (event.shiftKey ? 'redo' : 'undo') : null;
  // By the key's place, and by its character where a keyboard reports no place.
  const turn = event.code === 'BracketLeft' || (!event.code && event.key === '[') ? 'turn-left'
    : event.code === 'BracketRight' || (!event.code && event.key === ']') ? 'turn-right' : null;
  if (event.altKey && turn === null) return null;
  if (event.code === 'KeyB') return event.repeat ? 'held' : 'toggle';
  if (!state.on) return null;
  if (state.busy) return turn !== null || ['Escape', 'Backspace', 'Delete', 'Enter'].includes(event.code) ? 'held' : null;
  if (event.code === 'Escape') return state.changes ? 'close-changes' : state.confirming ? 'cancel' : state.moving ? 'put-back' : state.selected ? 'deselect' : 'leave';
  if (event.code === 'KeyH') return event.repeat ? 'held' : 'changes';
  // Tab chooses the next placed thing in view, Shift+Tab the one before, unless a control of
  // build mode has the focus, where Tab moves the focus as anywhere else.
  if (event.code === 'Tab') return state.focused || state.confirming || state.moving ? null : event.shiftKey ? 'previous' : 'next';
  if (['Backspace', 'Delete'].includes(event.code)) return state.selected && !state.confirming && !state.moving ? 'remove' : 'held';
  if (turn !== null) return state.selected && !state.confirming ? turn : 'held';
  if (event.code === 'Enter') return state.confirming ? 'confirm' : state.moving ? (state.ready ? 'keep' : 'held') : null;
  return null;
}
