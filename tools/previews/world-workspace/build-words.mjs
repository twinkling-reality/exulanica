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

/**
 * What a key does in build mode's state `{ on, selected, confirming, busy }`: an action, 'held'
 * for a key build mode takes and does nothing with now (a held-down B, Backspace with nothing
 * selected), or null when it leaves the key to the page. B switches build mode on and off; Esc
 * puts a question away, then lets go of what is selected, then leaves build mode; Backspace or
 * Delete asks to remove what is selected; Enter answers yes; Cmd+Z or Ctrl+Z takes back the
 * world's newest change.
 * While a request is on its way only B acts: nothing is sent twice, and Esc does not seem to call
 * back a change already sent.
 */
export function keyAction(state, event) {
  const command = event.metaKey || event.ctrlKey;
  if (command) return state.on && event.code === 'KeyZ' && !event.shiftKey && !event.altKey && !state.busy && !event.repeat ? 'undo' : null;
  if (event.altKey) return null;
  if (event.code === 'KeyB') return event.repeat ? 'held' : 'toggle';
  if (!state.on) return null;
  if (state.busy) return ['Escape', 'Backspace', 'Delete', 'Enter'].includes(event.code) ? 'held' : null;
  if (event.code === 'Escape') return state.confirming ? 'cancel' : state.selected ? 'deselect' : 'leave';
  if (['Backspace', 'Delete'].includes(event.code)) return state.selected && !state.confirming ? 'remove' : 'held';
  if (event.code === 'Enter') return state.confirming ? 'confirm' : null;
  return null;
}
