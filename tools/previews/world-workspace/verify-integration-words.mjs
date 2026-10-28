// The Integrations page's rows (integration-words.mjs), from stand-in reads: each row's name, line and mark are the
// served catalog's and nothing of a service is the page's own; each state and action comes from what the server
// answers, the owner's figures from their spending, a guest's from the host's allowance.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { INTEGRATION_WORDS, dollars, guideAddress, integrationRows, joinNames, markShapes, namesFor, standingGrants } from './integration-words.mjs';

const mark = [{ circle: { cx: 12, cy: 12, r: 3 } }];
const CATALOG = {
  profile: 'exulanica.integrations/v1', version: 1, guides: 'https://example.test/blob/main/',
  entries: [
    { key: 'nebius_token_factory', kind: 'provider', local: false, name: 'Nebius Token Factory', line: 'Open models answer for your people.', mark, guide: { document: 'docs/development-setup.md', heading: 'Your own key' } },
    { key: 'ollama_local', kind: 'provider', local: true, name: 'Ollama', line: 'Runs open models on this computer.', mark, guide: { document: 'docs/development-setup.md', heading: 'A runner' } },
    { key: 'tavily_search', kind: 'web', name: 'Tavily', line: 'Searches the web before something is made.', mark, guide: { document: 'docs/reference-notes-contract.md', heading: 'Web notes' } },
    { key: 'github', kind: 'github', name: 'GitHub', line: 'Keeps a world’s versions in a repository.', mark },
    { key: 'door', kind: 'door', name: 'Agents and games', line: 'Act for people you grant them, through MCP.', mark, guide: { document: 'docs/capabilities/outside-agents.md', heading: 'On your own install' } },
    { key: 'door.agent', kind: 'grant', ai: true, name: 'AI agents', line: 'Decide for people you grant them, through MCP.', mark: [{ circle: { cx: 5, cy: 6, r: 1.8 } }] },
    { key: 'door.game', kind: 'grant', ai: false, name: 'Games', line: 'Play people you grant them, or bring their own.', mark: [{ path: { d: 'M7 9h10' } }] },
  ],
};
const model = (provider, name, refusal = null) => ({ provider, model_id: name, name, runtime: { provider_refusal: refusal } });
const worlds = new Map([['w1', 'Fishing village'], ['w2', 'Night market']]);
const chosen = { worldId: 'w1', versionId: 'v1' };
const owner = {
  catalog: CATALOG, guest: false, worlds, chosen, ended: new Map(), connected: null,
  models: [model('nebius_token_factory', 'Nemotron 3 Super'), model('ollama_local', 'Qwen3 4B', 'provider_not_running')],
  notes: { offered: true, code: null, searches_at_most: 3 }, allowance: null,
  spending: [{ provider: 'nebius_token_factory', available_usd: '3.20000000', available_calls: 400 }],
  keeping: { kept_here: true, on_github: 0 },
  bridges: [{ bridge: 'agents', label: 'AI agents', ai: true }, { bridge: 'blockgame', label: 'Block Game', ai: false }],
  standing: [
    { grantId: 'g1', worldId: 'w1', versionId: 'v1', bridge: 'agents', named: 'Claude Code', ai: true, things: ['p1', 'p2'], names: ['Ada', 'Theo'] },
    { grantId: 'g2', worldId: 'w2', versionId: 'v2', bridge: 'blockgame', named: null, ai: false, things: ['p3'], names: ['Mira'] },
  ],
};
const view = rows => rows.map(row => [row.name, row.line, row.state?.words ?? null, row.state?.kind ?? null, row.action?.word ?? null]);

// The owner's own install, as the mock draws it: the key set and what is left, the runner not running, web search on
// with its searches a making, GitHub not connected, and each grant that stands as its own row with End.
assert.deepEqual(view(integrationRows(owner)), [
  ['Nebius Token Factory', 'Open models answer for your people.', 'Key set · $3.20 left', 'on', 'Models'],
  ['Ollama', 'Runs open models on this computer.', 'Not running', 'off', 'Guide'],
  ['Tavily', 'Searches the web before something is made.', 'Up to 3 searches a making', 'on', 'Guide'],
  ['GitHub', 'Keeps a world’s versions in a repository.', 'Not connected', 'off', 'Connect'],
  ['Claude Code', 'Decides for Ada and Theo in Fishing village.', 'Deciding', 'on', 'End'],
  ['Block Game', 'Plays Mira in Night market.', 'Playing', 'on', 'End'],
]);
const rows = integrationRows(owner);
// Marks are the catalog's, a grant's by its kind; each action carries what it acts on.
assert.deepEqual(rows[4].mark, CATALOG.entries[5].mark);
assert.deepEqual(rows[5].mark, CATALOG.entries[6].mark);
assert.deepEqual({ ...rows[4].action }, { kind: 'end', word: 'End', grantId: 'g1', worldId: 'w1' });
assert.deepEqual({ ...rows[3].action }, { kind: 'connect', word: 'Connect', worldId: 'w1', versionId: 'v1' });
assert.deepEqual(rows[1].action.guide, CATALOG.entries[1].guide);
assert.equal(guideAddress(CATALOG, rows[1].action.guide), 'https://example.test/blob/main/docs/development-setup.md#a-runner');

// Every name, line and mark is the catalog's: another catalog's words are the page's words, and an entry it does not
// list draws no row.
const renamed = { ...CATALOG, entries: CATALOG.entries.filter(entry => entry.key !== 'github').map(entry => (entry.key === 'ollama_local' ? { ...entry, name: 'A runner here', line: 'Answers on this machine.' } : entry)) };
const again = integrationRows({ ...owner, catalog: renamed });
assert.deepEqual(again.map(row => row.name), ['Nebius Token Factory', 'A runner here', 'Tavily', 'Claude Code', 'Block Game']);
assert.equal(again[1].line, 'Answers on this machine.');
assert.deepEqual(integrationRows({ ...owner, catalog: null }), []);

// States follow the reads: no key, a runner running, the budget spent, web notes off by their reason, worlds on GitHub.
assert.equal(integrationRows({ ...owner, models: [model('nebius_token_factory', 'N', 'provider_credential_absent'), model('ollama_local', 'Q')] })
  .map(row => row.state?.words).slice(0, 2).join(' | '), 'No key | Running');
assert.equal(integrationRows({ ...owner, models: [model('nebius_token_factory', 'N', 'process_budget_spent')] })[0].state.words, 'Budget spent');
assert.equal(integrationRows({ ...owner, notes: { offered: false, code: 'references_not_configured', searches_at_most: 3 } })[2].state.words, 'No key');
assert.deepEqual({ ...integrationRows({ ...owner, keeping: { kept_here: true, on_github: 2 } })[3].state }, { words: '2 worlds on GitHub', kind: 'on' });
assert.deepEqual({ ...integrationRows({ ...owner, keeping: { kept_here: false, on_github: 0 } })[3].state }, { words: 'Not on this server', kind: 'na' });
// A provider with no model listed here is not on this server; with no world chosen, Models and Connect are not offered.
assert.deepEqual({ ...integrationRows({ ...owner, models: [model('nebius_token_factory', 'N')] })[1].state }, { words: 'Not on this server', kind: 'na' });
assert.equal(integrationRows({ ...owner, chosen: null })[0].action, null);
assert.equal(integrationRows({ ...owner, chosen: null })[3].action, null);
// A read not answered yet draws no state, never a guess.
assert.equal(integrationRows({ ...owner, models: null })[0].state, null);
assert.equal(integrationRows({ ...owner, keeping: null })[3].state, null);
assert.equal(integrationRows({ ...owner, standing: null }).at(-1).name, 'Agents and games');
assert.equal(integrationRows({ ...owner, standing: null }).at(-1).state, null);
// With no grant standing, the door's own row: none granted where it admits programs, not on this server where none.
assert.deepEqual(view(integrationRows({ ...owner, standing: [] })).at(-1), ['Agents and games', 'Act for people you grant them, through MCP.', 'None granted', 'off', 'Guide']);
assert.deepEqual(view(integrationRows({ ...owner, standing: [], bridges: [] })).at(-1), ['Agents and games', 'Act for people you grant them, through MCP.', 'Not on this server', 'na', null]);

// After End: ended with no action; refused, said in its place with End still there; after Connect, the world asked for.
const ended = integrationRows({ ...owner, ended: new Map([['g1', 'ended'], ['g2', 'refused']]) });
assert.deepEqual(view(ended).slice(4), [
  ['Claude Code', 'Decides for Ada and Theo in Fishing village.', 'Ended', 'off', null],
  ['Block Game', 'Plays Mira in Night market.', 'It could not be ended. Try again.', 'refused', 'End'],
]);
assert.deepEqual(view(integrationRows({ ...owner, connected: 'Fishing village' }))[3].slice(2), ['Asked to keep Fishing village', 'off', null]);
assert.deepEqual(view(integrationRows({ ...owner, connected: 'refused' }))[3].slice(2), ['It could not be asked. Try again.', 'refused', 'Connect']);

// A guest on a hosted server sees the host's key and what is left of their allowance, and "Not on this server" for what
// they cannot use, with no action; their page reads no door, GitHub or spending.
const guest = {
  catalog: CATALOG, guest: true, worlds, chosen, ended: new Map(), connected: null,
  models: [model('nebius_token_factory', 'Nemotron 3 Super')], notes: { offered: true, code: null, searches_at_most: 3 },
  allowance: [{ provider: 'nebius_token_factory', state: 'active', available_usd: '0.48000000', available_calls: 20 }, { provider: 'tavily_search', state: 'active', available_usd: '0.00000000', available_calls: 15 }],
  spending: null, keeping: null, bridges: null, standing: null,
};
assert.deepEqual(view(integrationRows(guest)), [
  ['Nebius Token Factory', 'Open models answer for your people.', 'Host’s key · $0.48 left', 'on', 'Models'],
  ['Ollama', 'Runs open models on this computer.', 'Not on this server', 'na', null],
  ['Tavily', 'Searches the web before something is made.', 'Up to 3 searches a making · 15 left', 'on', null],
  ['GitHub', 'Keeps a world’s versions in a repository.', 'Not on this server', 'na', null],
  ['Agents and games', 'Act for people you grant them, through MCP.', 'Not on this server', 'na', null],
]);
assert.equal(integrationRows({ ...guest, notes: { offered: false, code: 'references_operator_only' } })[2].state.words, 'Not on this server');
assert.equal(integrationRows({ ...guest, allowance: null })[0].state.words, 'Host’s key');

// The helpers: figures, names, the grants that stand and whom each decides for, and marks drawn only as plain shapes.
assert.deepEqual([dollars('3.2'), dollars('0.0042'), dollars('0'), dollars('x')], ['$3.20', '$0.0042', '$0.00', null]);
assert.deepEqual([joinNames(['Ada']), joinNames(['Ada', 'Theo']), joinNames(['Ada', 'Theo', 'Mira', 'Uma'])], ['Ada', 'Ada and Theo', 'Ada, Theo and 2 more']);
const read = [{ grantId: 'g1', worldId: 'w1', versionId: 'v1', bridge: 'agents', declared: { name: 'Claude Code', maker: 'Anthropic', mind: null }, ended: null, ai: true, things: ['p1'] },
  { grantId: 'g0', worldId: 'w1', versionId: 'v1', bridge: 'agents', declared: null, ended: 'revoked', ai: true, things: [] }];
assert.deepEqual(standingGrants(read).map(grant => [grant.grantId, grant.named]), [['g1', 'Claude Code']]);
const society = { state: { inhabitants: [{ id: 'p1', display_name: 'Ada', came_by: 'drawn' }, { id: 'v9', display_name: 'Visitor', came_by: 'crossed', crossing: { grant_id: 'g1', decided_by: 'program' } }] } };
assert.deepEqual([...namesFor(society, standingGrants(read)[0])], ['Ada', 'Visitor']);
assert.deepEqual(markShapes(mark).map(shape => shape.tag), ['circle']);
assert.throws(() => markShapes([{ image: { href: 'x' } }]), /A mark draws/u);
assert.throws(() => markShapes([{ path: { d: 'M0 0', onload: 'x' } }]), /has no onload/u);

// The page's own words are its states and actions alone, and no em dash anywhere.
for (const words of Object.values(INTEGRATION_WORDS)) {
  if (typeof words === 'string') assert.doesNotMatch(words, /\u2014|Nebius|Ollama|Tavily|GitHub|MCP/u, words);
}
assert.doesNotMatch(readFileSync(new URL('integration-words.mjs', import.meta.url), 'utf8'), /\u2014|nebius_token_factory|ollama_local|tavily/u);
console.log('Integrations rows: every row from the served catalog and the live reads, the owner’s figures and a guest’s.');
