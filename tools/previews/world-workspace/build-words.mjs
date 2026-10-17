// Build mode's words and keys, without the page: what a placed thing is called, what each server
// answer says to a person, and what a key does in each of build mode's states. build-mode.ts acts
// on these answers; verify-build-words.mjs holds them.
import { createReadBackoff } from './read-backoff.mjs';

/**
 * What a placed thing is called in a sentence, from its document's kind: "well", "lamp post". A
 * creature its workspace made is called by its own label, its maker's words, as its tag, its
 * character page and History call it ("two legged two armed creature"), read by `kindLabel(kind)`;
 * until the label is read, or where the workspace no longer holds the kind, "creature" (rulings J20
 * and J23). Every name build mode and History say comes from here.
 */
export function thingName(document, kindLabel = () => null) {
  const kind = document?.kind;
  if (kind?.source === 'workspace') {
    // A thing whose kind its workspace no longer holds is read as gone: no label to ask for.
    const label = document.gone === true ? null : kindLabel(kind);
    return typeof label === 'string' && label.trim() ? inSentence(label.trim()) : 'creature';
  }
  return typeof kind?.kind === 'string' && kind.kind ? kind.kind.replaceAll('_', ' ') : 'thing';
}

/**
 * The labels of the kinds a workspace made, read by digest through `read(path)` (the page's own read
 * of GET /things/kinds/{sha256}) and `labelOf(document)`, for `thingName`'s reader: `label(kind)` is
 * null until its read lands, then the label from memory. A read that fails is asked again only once
 * the page's quiet-read pause has passed (read-backoff.mjs), so a passing failure never leaves
 * "creature" where the tag says the label; `listen(listener)` is told each label that lands, so a page
 * draws its names again (build mode, History). One reader per page part is enough: each read is one
 * small document.
 */
export function createKindLabels(read, labelOf, { now = () => Date.now(), backoff = createReadBackoff() } = {}) {
  const labels = new Map(), reading = new Set(), listeners = new Set();
  function label(kind) {
    const digest = typeof kind?.sha256 === 'string' && /^[0-9a-f]{64}$/u.test(kind.sha256) ? kind.sha256 : null;
    if (digest === null) return null;
    if (labels.has(digest)) return labels.get(digest);
    if (!reading.has(digest) && backoff.ready(digest, now())) {
      reading.add(digest);
      Promise.resolve()
        .then(() => read('/things/kinds/' + digest))
        .then(
          (document) => {
            backoff.succeeded(digest);
            labels.set(digest, labelOf(document));
            for (const listener of listeners) listener(digest);
          },
          () => { backoff.failed(digest, now()); },
        )
        .finally(() => { reading.delete(digest); });
    }
    return null;
  }
  return {
    label,
    /** Be told each label that lands; answers the function that stops telling. */
    listen(listener) { listeners.add(listener); return () => { listeners.delete(listener); }; },
  };
}

/** A label as a sentence says it: its first letter lowered, unless its first word is all capitals. */
function inSentence(label) {
  const first = label.split(/\s/u)[0];
  return first.length > 1 && first === first.toUpperCase() ? label : label.charAt(0).toLowerCase() + label.slice(1);
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
/** What a change the server could not take up yet says (a 503, its place still being made): not a refusal (W11). */
export const BUSY = 'The world is busy with another change. Try again in a moment.';

const REFUSALS = Object.freeze({
  kind_work_overran: BUSY,
  kind_work_busy: BUSY,
  kind_work_unavailable: BUSY,
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

/**
 * An undone change as changeWords says it, without the full stop: by the kind of the edit it reverses and
 * what that edit changed ("the bench").
 */
function undoneWords(kind, what, storeysBack) {
  // A storeys change taken back says the storeys it leaves (null: as the world made the building).
  if (storeysBack !== undefined) {
    return storeysBack === null
      ? `Put ${what} back to the storeys it was made with`
      : `Put ${what} back to ${storeysWords(storeysBack)}`;
  }
  if (kind === 'remove_thing' || kind === 'suppress_element') return `Brought back ${what}`;
  if (kind === 'move_thing' || kind === 'transform_element') return `Put ${what} back where it was`;
  if (kind === 'add_thing') return `Took away ${what} that was placed`;
  return 'Undid the last change';
}

/** A count of storeys: "1 storey", "4 storeys". */
const storeysWords = (count) => `${count} ${count === 1 ? 'storey' : 'storeys'}`;

/** The storeys a made part's document states, null where it states none (as the world made it). */
const storeysOf = (document) => (Number.isInteger(document?.storeys) ? document.storeys : null);

/**
 * A storeys change, as what was done (ruling W6): "Raised the tea house to 4 storeys", "Lowered the
 * tea house to 1 storey", or "Set the tea house to 4 storeys" where it stood as the world made it.
 */
function storeysDone(what, before, after) {
  if (before === null) return `Set ${what} to ${storeysWords(after)}`;
  return `${after > before ? 'Raised' : 'Lowered'} ${what} to ${storeysWords(after)}`;
}

/** How a change names a made part (`partNameOf(partId)`, a name or null): "the pond". */
const partCalled = (partId, partNameOf) => {
  const name = partNameOf(partId);
  return name ? `the ${name}` : 'a part of the world';
};

/**
 * What an undo or a redo will do, from its preview's `would_change`, as History's parts (changeParts reads it as
 * the edits it makes, so the note says what History's row will): the undo and the edit it takes back, by that
 * edit's kind and subject; a redo's first edit is read from the documents, since a redo is the undo of an undo.
 * A thing is named as `thingName` names it (with `kindLabel`), a made part by `partNameOf`.
 */
export function previewParts(change, redo, partNameOf = () => null, kindLabel = () => null) {
  const subject = change?.subject_id;
  const part = typeof subject === 'string' && subject.startsWith('part:');
  const before = change?.before ?? null, after = change?.after ?? null;
  const name = thingName(after ?? before, kindLabel);
  const of = part ? { element_id: subject } : { thing_id: typeof subject === 'string' && subject ? subject : 'thing' };
  const was = storeysOf(before), now = storeysOf(after);
  const edit = (kind, more = {}) => ({ edit_id: 'done', kind, ...of, ...more });
  let done = null;
  if (!redo) {
    // The edit an undo takes back, as it was made: a storeys change from what the undo leaves to what stands now.
    const kind = change?.undoes?.kind;
    done = part && kind === 'transform_element' && was !== now ? edit(kind, { storeys: { before: now, after: was } })
      : typeof kind === 'string' ? edit(kind) : null;
  } else if (part) {
    if (now !== null && was !== now) done = edit('transform_element', { storeys: { before: was, after: now } });
    else if (after?.suppressed === true && before?.suppressed !== true) done = edit('suppress_element');
    else if (JSON.stringify(before?.transform ?? null) !== JSON.stringify(after?.transform ?? null)) done = edit('transform_element');
  } else {
    const a = before?.transform, b = after?.transform;
    if (before !== null && after !== null && !before.removed && after.removed) done = edit('remove_thing');
    else if ((before === null || before.removed) && after !== null && !after.removed) done = edit('add_thing');
    else if (a && b && (a.x_mm !== b.x_mm || a.z_mm !== b.z_mm || a.yaw_microradians !== b.yaw_microradians)) done = edit('move_thing');
  }
  const undo = { edit_id: 'undo', kind: 'undo', ...(done ? { undone_edit_id: 'done' } : {}) };
  const edits = redo ? [...(done ? [done] : []), undo, { edit_id: 'redo', kind: 'undo', undone_edit_id: 'undo' }] : [...(done ? [done] : []), undo];
  return changeParts(edits[edits.length - 1], edits, () => name, partNameOf);
}

/** The redo preview's refusal when nothing is left to do again. */
export function redoRefusalWords(code, detail) {
  return code === 'invalid_object_state' ? 'Nothing left to do again.' : refusalWords(code, detail);
}

/**
 * One line of the world's changes, from its edit log: what the edit did, by its kind and the
 * thing it names (`nameOf(thingId)`, a name or null) or the made part (`partNameOf(partId)`), an undo
 * by what it took back as its note said it, and a redo (an undo of an undo) by what it did again.
 */
export function changeWords(edit, edits, nameOf, partNameOf = () => null) {
  const byId = new Map(edits.map(each => [each.edit_id, each]));
  // A part made with the world is named by its parts read, its change stored as an element's.
  const isPart = (one) => typeof one.element_id === 'string' && one.element_id.startsWith('part:');
  const called = (one) => {
    if (isPart(one)) return partCalled(one.element_id.slice('part:'.length), partNameOf);
    const name = one.thing_id ? nameOf(one.thing_id) : null;
    return name ? `the ${name}` : 'a thing';
  };
  // A building's storeys change, as the version read states it on its row ({before, after}).
  const storeys = (one) => (Number.isInteger(one.storeys?.after) ? one.storeys : null);
  const plain = (one) => {
    if (isPart(one)) {
      if (one.kind === 'suppress_element') return `Removed ${called(one)}`;
      if (one.kind === 'transform_element' && storeys(one) !== null) {
        return storeysDone(called(one), storeys(one).before ?? null, storeys(one).after);
      }
      if (one.kind === 'transform_element') return `Moved ${called(one)}`;
    }
    const thing = called(one);
    if (one.kind === 'add_thing') return `Placed ${thing}`;
    if (one.kind === 'move_thing') return `Moved ${thing}`;
    if (one.kind === 'remove_thing') return `Removed ${thing}`;
    if (/_object$/.test(one.kind)) return one.kind.startsWith('add') ? 'Placed an object' : one.kind.startsWith('move') ? 'Moved an object' : one.kind.startsWith('remove') ? 'Removed an object' : 'Changed an object';
    return 'Changed the world';
  };
  if (edit.kind !== 'undo') return plain(edit);
  const undone = byId.get(edit.undone_edit_id);
  if (!undone) return undoneWords(null, null);
  if (undone.kind === 'undo') {
    const again = byId.get(undone.undone_edit_id);
    return again ? `${plain(again)} again` : 'Did a change again';
  }
  const back = isPart(undone) && storeys(undone) !== null ? storeys(undone).before ?? null : undefined;
  return undoneWords(undone.kind, called(undone), back);
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

/** The card's line for a thing a person placed. */
export function placedLine() {
  return 'Placed in this world';
}

/** Said when Tab finds nothing to choose. */
export function nothingInView() {
  return 'No placed things in view. Walk closer to one.';
}

/** History's words: its title, the heading of today's changes and its line when nothing has changed. */
export const HISTORY = Object.freeze({ title: 'History', today: 'Today', empty: 'Nothing has been changed yet.' });

/**
 * Every key build mode has, as the keys card at the bottom right lists them (ruling W10): each the caps
 * drawn, its word and the shortcut a reader is told.
 */
export function buildKeys() {
  return [
    { keys: 'mouse', word: 'Move' },
    { keys: ['[', ']'], word: 'Turn', shortcut: '[ ]' },
    { keys: ['Alt'], word: 'Free', shortcut: 'Alt' },
    { keys: ['Del'], word: 'Remove', shortcut: 'Delete' },
    { keys: ['Tab'], word: 'Next', shortcut: 'Tab' },
    { keys: ['⌘Z'], word: 'Undo', shortcut: 'Meta+Z' },
    { keys: ['B'], word: 'Done', shortcut: 'B' },
    { keys: ['H'], word: 'History', shortcut: 'H' },
    { keys: ['Esc'], word: 'Back', shortcut: 'Escape' },
  ];
}

/**
 * The held group's rows at the right in build mode's state `{ placing, moving, ready, refused,
 * confirming, removeRefused }` (ruling W10, the building sheet's section 3), each where it works: its
 * key, one word, the shortcut a reader is told and the action pressing it does (keyAction's names;
 * none for a row that only says how).
 * - Held (a new thing from the tray being placed, or a placed thing being moved): Place (the mouse: a
 *   click, or Enter; dimmed until the server says it may stand there), Turn, Remove (a thing already
 *   in the world only) and Put back (a moved thing to where it stood, a new one to the tray).
 * - Refused (the server refused the spot): Put back alone, under the refusal's sentence.
 * - Asking (before a removal): Remove and Keep.
 * - Chosen: Move (a drag), Turn and Remove, not Remove once a removal was refused: it would only be
 *   refused again.
 */
export function heldRows(state) {
  if (state.confirming) {
    return [
      { key: 'Enter', word: 'Remove', shortcut: 'Enter', action: 'confirm' },
      { key: 'Esc', word: 'Keep', shortcut: 'Escape', action: 'cancel' },
    ];
  }
  const turn = { key: '[ ]', word: 'Turn', shortcut: '[ ]', action: 'turn-right' };
  const remove = { key: 'Del', word: 'Remove', shortcut: 'Delete', action: 'remove' };
  if (state.placing || state.moving) {
    const back = { key: 'Esc', word: 'Put back', shortcut: 'Escape', action: 'put-back' };
    if (state.refused) return [back];
    return [
      { key: 'mouse-click', word: 'Place', shortcut: 'Enter', action: 'place', disabled: !state.ready },
      turn,
      ...(state.placing ? [] : [remove]),
      back,
    ];
  }
  return [{ key: 'mouse-click', word: 'Move' }, turn, ...(state.removeRefused ? [] : [remove])];
}

/** The tray's words: its two tabs, its first tile, and what an empty tab says (ruling W10, B12). */
export const TRAY = Object.freeze({
  label: 'Things to place',
  things: 'Things',
  creatures: 'Creatures',
  make: 'Make a creature',
  noThings: "This world's kit has nothing to place.",
  noCreatures: 'No creatures made yet.',
});

/**
 * The names over people standing together near what is held (frame r13, ruling W11), each a person's
 * own name or null for someone the world has not named: "Teo", "Teo and Ines", "Teo, Ines and
 * Marco", and from four on the first and how many more ("Teo and 3 more"). Someone unnamed among
 * named people is "the resident" (two unnamed among three are counted instead: "Teo and 2 more");
 * people none of whom is named get no words ("").
 */
export function namesTogether(names) {
  const named = names.filter((name) => typeof name === 'string' && name);
  if (!named.length) return '';
  const unnamed = names.length - named.length;
  const said = [...named, ...Array.from({ length: unnamed }, () => 'the resident')];
  if (said.length >= 4 || unnamed > 1) return `${said[0]} and ${said.length - 1} more`;
  if (said.length === 3) return `${said[0]}, ${said[1]} and ${said[2]}`;
  return said.length === 2 ? `${said[0]} and ${said[1]}` : said[0];
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
 * What a key does in build mode's state `{ on, selected, placing, confirming, moving, ready, refused,
 * busy, removeRefused, focused }`: an action, 'held' for a key build mode takes and does nothing with
 * now (a held-down B, Backspace with nothing selected), or null when it leaves the key to the page.
 * B switches build mode on and off; Esc puts a question away, puts a held thing back (a moved one
 * where it stood, a new one in the tray), lets go of what is selected, then leaves build mode;
 * Backspace or Delete asks to remove what is selected, and while it is being moved puts it back
 * first (a new thing from the tray is not in the world, so it has nothing to remove); `[` and `]`
 * turn it, Alt for a free turn; Enter answers yes to a question, or places what is held where the
 * server said it may stand; Cmd+Z or Ctrl+Z takes back the world's newest change, with Shift does the
 * last one taken back again; Tab and Shift+Tab choose the next or previous placed thing in view,
 * and Tab past the last moves into the tray. While a control of build mode has the focus (a row or a
 * tile), Tab, Enter and Space are that control's and Esc gives the focus back to the world.
 * After the server refused removing what is chosen (`removeRefused`), or the spot a held thing is
 * at (`refused`), Backspace and Delete do nothing: the rows offer what still works. H is the page's:
 * it opens History from anywhere. While a request is on its way only B acts: nothing is sent twice,
 * and Esc does not seem to call back a change already sent.
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
  const held = state.placing || state.moving;
  if (state.focused && ['Tab', 'Enter', 'Space'].includes(event.code)) return null;
  if (state.focused && event.code === 'Escape' && !state.confirming && !held) return 'unfocus';
  if (event.code === 'Escape') return state.confirming ? 'cancel' : held ? 'put-back' : state.selected ? 'deselect' : 'leave';
  // Tab chooses the next placed thing in view, Shift+Tab the one before.
  if (event.code === 'Tab') return state.confirming || held ? null : event.shiftKey ? 'previous' : 'next';
  if (['Backspace', 'Delete'].includes(event.code)) {
    const removable = state.selected && !state.confirming && !state.placing && !state.refused && !state.removeRefused;
    return removable ? 'remove' : 'held';
  }
  if (turn !== null) return (state.selected || state.placing) && !state.confirming ? turn : 'held';
  if (event.code === 'Enter') return state.confirming ? 'confirm' : held ? (state.ready ? 'place' : 'held') : null;
  return null;
}

/**
 * What an edit of the world's log did, as parts, for pages that word changes in their own forms (History's "You
 * placed the bench"): `form` with what it names, read exactly as changeWords reads the edit (its kind, the thing by
 * `nameOf(thingId)` or the made part by `partNameOf(partId)`, an undo by what it took back, a redo, an undo of an
 * undo, as `{ form: 'again', again }`). Forms: placed, moved, removed, storeys_set, storeys_raised, storeys_lowered,
 * placed_object, moved_object, removed_object, changed_object, changed_world, undid, did_again, brought_back,
 * back_where_it_was, took_away, back_to_made_storeys, back_to_storeys.
 */
export function changeParts(edit, edits, nameOf, partNameOf = () => null) {
  const byId = new Map(edits.map(each => [each.edit_id, each]));
  const isPart = (one) => typeof one.element_id === 'string' && one.element_id.startsWith('part:');
  const called = (one) => {
    if (isPart(one)) return partCalled(one.element_id.slice('part:'.length), partNameOf);
    const name = one.thing_id ? nameOf(one.thing_id) : null;
    return name ? `the ${name}` : 'a thing';
  };
  const storeys = (one) => (Number.isInteger(one.storeys?.after) ? one.storeys : null);
  const plain = (one) => {
    if (isPart(one)) {
      if (one.kind === 'suppress_element') return { form: 'removed', what: called(one) };
      if (one.kind === 'transform_element' && storeys(one) !== null) {
        const { before = null, after } = storeys(one);
        if (before === null) return { form: 'storeys_set', what: called(one), after };
        return { form: after > before ? 'storeys_raised' : 'storeys_lowered', what: called(one), before, after };
      }
      if (one.kind === 'transform_element') return { form: 'moved', what: called(one) };
    }
    const what = called(one);
    if (one.kind === 'add_thing') return { form: 'placed', what };
    if (one.kind === 'move_thing') return { form: 'moved', what };
    if (one.kind === 'remove_thing') return { form: 'removed', what };
    if (/_object$/.test(one.kind)) {
      return { form: one.kind.startsWith('add') ? 'placed_object' : one.kind.startsWith('move') ? 'moved_object' : one.kind.startsWith('remove') ? 'removed_object' : 'changed_object' };
    }
    return { form: 'changed_world' };
  };
  if (edit.kind !== 'undo') return plain(edit);
  const undone = byId.get(edit.undone_edit_id);
  if (!undone) return { form: 'undid' };
  if (undone.kind === 'undo') {
    const again = byId.get(undone.undone_edit_id);
    return again ? { form: 'again', again: plain(again) } : { form: 'did_again' };
  }
  const what = called(undone);
  if (isPart(undone) && storeys(undone) !== null) {
    const back = storeys(undone).before ?? null;
    return back === null ? { form: 'back_to_made_storeys', what } : { form: 'back_to_storeys', what, before: back };
  }
  if (undone.kind === 'remove_thing' || undone.kind === 'suppress_element') return { form: 'brought_back', what };
  if (undone.kind === 'move_thing' || undone.kind === 'transform_element') return { form: 'back_where_it_was', what };
  if (undone.kind === 'add_thing') return { form: 'took_away', what };
  return { form: 'undid' };
}
