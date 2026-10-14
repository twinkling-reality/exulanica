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
  return Object.hasOwn(REFUSALS, code) ? REFUSALS[code] : 'That could not be done. Nothing changed.';
}

/** What removing a thing will do, said before it is done. */
export function removeQuestion(name) {
  return `Remove the ${name}? Nobody can use it from the next minute.`;
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

/** What a kept move did. */
export function movedNote(name, words) {
  return `Moved the ${name} ${words}.`;
}

/** What keeping a move will do, said before it is kept. */
export function keepLine() {
  return 'People who use it go to the new spot from the next minute.';
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
 * Ctrl+Z takes back the world's newest change. While a request is on its way only B acts: nothing
 * is sent twice, and Esc does not seem to call back a change already sent.
 */
export function keyAction(state, event) {
  const command = event.metaKey || event.ctrlKey;
  if (command) return state.on && event.code === 'KeyZ' && !event.shiftKey && !event.altKey && !state.busy && !event.repeat ? 'undo' : null;
  // By the key's place, and by its character where a keyboard reports no place.
  const turn = event.code === 'BracketLeft' || (!event.code && event.key === '[') ? 'turn-left'
    : event.code === 'BracketRight' || (!event.code && event.key === ']') ? 'turn-right' : null;
  if (event.altKey && turn === null) return null;
  if (event.code === 'KeyB') return event.repeat ? 'held' : 'toggle';
  if (!state.on) return null;
  if (state.busy) return turn !== null || ['Escape', 'Backspace', 'Delete', 'Enter'].includes(event.code) ? 'held' : null;
  if (event.code === 'Escape') return state.confirming ? 'cancel' : state.moving ? 'put-back' : state.selected ? 'deselect' : 'leave';
  if (['Backspace', 'Delete'].includes(event.code)) return state.selected && !state.confirming && !state.moving ? 'remove' : 'held';
  if (turn !== null) return state.selected && !state.confirming ? turn : 'held';
  if (event.code === 'Enter') return state.confirming ? 'confirm' : state.moving ? (state.ready ? 'keep' : 'held') : null;
  return null;
}
