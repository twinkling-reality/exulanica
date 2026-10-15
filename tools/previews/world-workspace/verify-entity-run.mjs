import assert from 'node:assert/strict';
import { modelAskers, openRun, startRun, stopRun } from './entity-execution.mjs';
import { defaultRunLimits } from './run-words.mjs';

// Starting and stopping a run, against clients that answer as the routes do: a run is a living
// session, opened on the paused read with the limits shown, and confirmed open by a fresh read.
const entry = { worldId: 'world', authoredVersionId: 'version' };
const nano = { provider: 'nebius_token_factory', modelId: 'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B', name: 'Nemotron 3 Nano 30B' };
const fresh = { row: { scene: { id: 'duck' }, roleInstances: [] }, inventory: { world_id: 'world', version_id: 'version', roles: [] }, offer: {} };
const open = { sessionId: 'run-1', state: 'open', endsBy: '2026-10-14T17:30:00Z', limits: {}, used: { decisions: 0, usd: '0.00000000', unresolved: { count: 0, usd: '0.00000000' } } };
const paused = { versionId: 'version', societyId: 'society', mode: 'paused', speed: 1, revision: 3, currentTick: 6, stateSha256: 'a'.repeat(64), playEligible: true, hostPlayback: { running: true, intervalMs: 60_000 }, modelMinds: null, livingSession: null };

function world({ control = paused, choices = [{ subjectId: 'duck', model: nano }], refusal = null, refuse = null } = {}) {
  const sent = [];
  let now = control;
  return {
    sent,
    modelsClient: { read: async () => ({ societyId: 'society', choices, hostRefusal: refusal, latest: [] }) },
    controlClient: {
      read: async () => now,
      openSession: async (read, limits, requestId) => {
        sent.push(['open', read.revision, read.currentTick, limits, requestId]);
        if (refuse) throw Object.assign(Error(refuse + ': refused'), { code: refuse });
        now = { ...read, mode: 'playing', livingSession: open };
        return { sessionId: 'run-1', state: 'open' };
      },
      stopSession: async (versionId, sessionId) => {
        sent.push(['stop', versionId, sessionId]);
        now = { ...now, mode: 'paused', livingSession: { ...now.livingSession, state: 'closed', closedReasonWords: 'Someone stopped the run.' } };
        return { sessionId, state: 'closed' };
      },
    },
  };
}
const start = (held, extra = {}) => startRun({
  modelsClient: held.modelsClient, controlClient: held.controlClient, entry, subjectId: 'duck', expectedModel: nano,
  current: () => true, refresh: async () => fresh, requestId: 'key-1',
  limitsFor: (control, models) => defaultRunLimits(control.hostPlayback.intervalMs, modelAskers(models)), ...extra,
});
// The entity offers its model choice for the people role it is in, as the inventory and offer read do.
fresh.inventory.roles = [{ key: 'people', subject: 'person', available: true, capability: { permitted: true, state: 'available' } }];
fresh.row.roleInstances = [{ role_key: 'people', subject_id: 'duck' }];
fresh.offer = { actions: [{ id: 'minds.choose', state: 'available', permitted: true, runs_by: { bind: { role_key: 'people', subject_id: 'duck', version_id: 'version' } } }] };

// A paused world: one session, the default limits for one character at real time, under the key.
const one = world();
const started = await start(one);
assert.deepEqual(one.sent, [['open', 3, 6, { wallSeconds: 600, minutes: 10, decisions: 20, usd: '0.05000000', calls: 40 }, 'key-1']]);
assert.equal(openRun(started).sessionId, 'run-1');

// Already in a run: that run, and nothing sent.
const running = world({ control: { ...paused, mode: 'playing', livingSession: open } });
assert.equal(openRun(await start(running)).sessionId, 'run-1');
assert.deepEqual(running.sent, []);

// Not connected: the readiness words, and nothing sent.
const unplugged = world({ refusal: 'provider_credential_absent' });
await assert.rejects(start(unplugged), /The AI service is not connected\./);
assert.deepEqual(unplugged.sent, []);

// Refused by the server: its code comes back for the page to word.
const playing = world({ control: { ...paused, mode: 'playing' }, refuse: 'society_not_paused' });
await assert.rejects(start(playing), error => error.code === 'society_not_paused');

// Two characters with a model: room for both to be asked.
const pair = world({ choices: [{ subjectId: 'duck', model: nano }, { subjectId: 'knight', model: nano }, { subjectId: 'ari', model: null }] });
await start(pair);
assert.equal(pair.sent[0][3].decisions, 40);

// Stop: the open run is stopped by its id; with none open, nothing is sent.
const stop = world({ control: { ...paused, mode: 'playing', livingSession: open } });
const stopped = await stopRun({ controlClient: stop.controlClient, entry, current: () => true });
assert.deepEqual(stop.sent, [['stop', 'version', 'run-1']]);
assert.equal(openRun(stopped), null);
const idle = world();
await stopRun({ controlClient: idle.controlClient, entry, current: () => true });
assert.deepEqual(idle.sent, []);

console.log('Entity run checks passed: a run opens once on the paused read with the shown limits, refusals keep their code, and Stop closes it.');
