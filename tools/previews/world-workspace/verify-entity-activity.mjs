import assert from 'node:assert/strict';
import { readEntityActivity } from './entity-execution.mjs';

// The activity view's "Recent actions" are a being's newest recorded events, newest first. The
// events read answers the society's newest events a page at a time: minutes newest first and,
// within a minute, events in the order the engine gave them. These clients answer as the routes do.
const entry = { worldId: 'world', authoredVersionId: 'version' };
const event = (subject, tick, order) => ({ event_id: `${subject}-${tick}-${order}`, subject_id: subject, tick, event_kind: 'action_completed',
  document: { synthetic: true, order, summary: `${subject} at minute ${tick}, event ${order}` } });
const read = async (page, choicesRead = null) => readEntityActivity({
  modelsClient: { read: async () => ({ societyId: 'society', latest: [], choices: [] }) },
  controlClient: { read: async () => ({ versionId: 'version', societyId: 'society', mode: 'paused' }) },
  societyClient: {
    read: async () => ({ versionId: 'version', societyId: 'society', currentTick: 28, state: { inhabitants: [{ id: 'duck' }, { id: 'knight' }] } }),
    events: async () => page,
  },
  entry, subjectId: 'duck', current: () => true, read: choicesRead,
});
const ids = activity => activity.events.map(one => one.event_id);

// Nine of the duck's events from minute 3 to minute 28, the knight's among them.
const page = [event('knight', 28, 0), event('duck', 28, 1), event('duck', 27, 0), event('duck', 27, 1), event('duck', 27, 2),
  event('knight', 27, 3), event('duck', 20, 0), event('duck', 12, 0), event('duck', 9, 0), event('duck', 6, 0), event('duck', 3, 0)];
assert.deepEqual(ids(await read(page)), ['duck-28-1', 'duck-27-2', 'duck-27-1', 'duck-27-0', 'duck-20-0', 'duck-12-0']);
// Fewer than six: every one of them, newest first.
assert.deepEqual(ids(await read(page.slice(0, 4))), ['duck-28-1', 'duck-27-1', 'duck-27-0']);
// None of its own: none.
assert.deepEqual(ids(await read([event('knight', 28, 0)])), []);
// Its choices come from the events read kept to applied decisions, so a town's routine events
// never push them out of the window; only its own are kept.
const applied = (subject, tick) => ({ ...event(subject, tick, 0), event_kind: 'decision_applied' });
let asked = null;
const chosen = await read([event('duck', 28, 0)], async path => { asked = path; return { events: [applied('duck', 27), applied('knight', 26), applied('duck', 20)] }; });
assert.match(asked, /\/world\/versions\/version\/society\/events\?world_id=world&kinds=decision_applied&limit=\d+$/);
assert.deepEqual(chosen.choices.map(one => one.event_id), ['duck-27-0', 'duck-20-0']);
assert.deepEqual((await read([applied('duck', 28), event('duck', 27, 0)])).choices.map(one => one.event_id), ['duck-28-0']);
console.log('Entity activity checks passed: the six newest of the being\'s own events, newest first, also within a minute; its choices from the applied decisions read.');
