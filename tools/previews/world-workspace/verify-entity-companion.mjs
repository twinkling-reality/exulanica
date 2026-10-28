// Ask's own words reach the page (ROOT's sweep of 27 October): each reason entity-companion.mjs gives for showing no
// answer is marked plain, so contextual-world.ts shows it as it is; a failed read keeps the page's one failure line.
import assert from 'node:assert/strict';
import { askEntityCompanion } from './entity-companion.mjs';

const entry = { worldId: 'world:w', authoredVersionId: 'v1' };
const row = { key: 'r1', scene: { type: 'being', id: 'p1' } };
const fresh = { row, inventory: { world_id: 'world:w', version_id: 'v1' } };
const answer = { clauses: [], calls: [], simulation: [{ versionId: 'v1' }] };
const ask = (over = {}) => askEntityCompanion({
  aspect: 'doing', entry, row, client: { ask: async () => answer }, refresh: async () => fresh, current: () => true, ...over,
});
const refused = async (over) => { try { await ask(over); } catch (error) { return error; } return null; };

assert.deepEqual((await ask()).answer, answer, 'an answer of this world is returned');
for (const [over, words] of [
  [{ aspect: 'how' }, 'This question is unavailable here.'],
  [{ refresh: async () => ({ ...fresh, inventory: { ...fresh.inventory, version_id: 'v2' } }) }, 'The world changed a moment ago. Ask again.'],
  [{ client: { ask: async () => ({ ...answer, calls: [{}] }) } }, 'This answer could not be checked against this world, so it is not shown.'],
  [{ client: { ask: async () => ({ ...answer, simulation: [{ versionId: 'v0' }] }) } }, 'This answer could not be checked against this world, so it is not shown.'],
]) {
  const error = await refused(over);
  assert.equal(error?.message, words);
  assert.equal(error?.plain, true, words);
}
// Closed while the question was asked: its own words too, though the page no longer shows them.
let open = true;
const closed = await refused({ client: { ask: async () => { open = false; return answer; } }, current: () => open });
assert.deepEqual([closed?.message, closed?.plain], ['The question is no longer open.', true]);
// A read that failed is not Ask's own words: the page says its one failure line.
const failed = await refused({ client: { ask: async () => { throw new Error('fetch failed'); } } });
assert.equal(failed?.plain, undefined);
console.log('entity companion: ok');
