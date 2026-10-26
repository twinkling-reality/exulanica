import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import catalog from './integrations.v1.json' with { type: 'json' };
import {
  INTEGRATIONS, INTEGRATION_WORDS, alreadyEnded, catalogRows, endable, endedState, fill, guestRow, guestState, guideAddress, handedBackLine,
  headingAnchor, joinNames, markShapes, namesFor, namesOf, refusedLine, releasedSubjects, rowState,
  severalLine, standingGrants, stepRow,
} from './integration-words.mjs';

// The page's own words, as the build sheet (BUILD-SHEETS-1024.md, the Integrations page) says them.
assert.equal(INTEGRATION_WORDS.button, 'Integrations');
assert.equal(INTEGRATION_WORDS.overLabel, 'Integrations');
assert.equal(INTEGRATION_WORDS.title, 'What your worlds connect to');
assert.equal(INTEGRATION_WORDS.sub, 'Each one says what it connects, what it reads and where anything goes. Nothing connects until you set it up, and you can end it.');
assert.equal(INTEGRATION_WORDS.small, "A person's model is chosen on their card. This page is where the models and the outside programs come from.");
assert.deepEqual([INTEGRATION_WORDS.connects, INTEGRATION_WORDS.reads, INTEGRATION_WORDS.goesTo], ['Connects', 'Reads', 'Goes to']);
// Enter opens the guide elsewhere, so it carries G2's mark for that (DESIGN's ruling of 11:16 on 25 October, point 5).
assert.deepEqual([INTEGRATION_WORDS.choose, INTEGRATION_WORDS.setUp, INTEGRATION_WORDS.back, INTEGRATION_WORDS.end], ['Choose', 'How to set it up \u2197', 'Back', 'End this grant']);

// The catalog: two groups, four rows, in the sheet's order and words; companion apps are not listed.
assert.deepEqual(catalog.groups.map(group => group.label), ['Where models run', "Outside programs, through a world's door"]);
const rows = catalogRows(catalog);
const row = key => rows.find(one => one.key === key);
assert.deepEqual(rows.map(one => one.name), ['Nebius Token Factory', 'A model on this computer', 'A game', 'An AI agent you build']);
assert.equal(row('nebius').line, 'Open models from their makers answer for your people, with your own key, usually for a fraction of a cent a decision.');
assert.equal(row('this-computer').line, 'A local model runner answers here, free, and nothing it is told leaves this computer.');
assert.equal(row('game').line, 'A game plays someone in your world, or brings its own character in, under a grant you give and can end.');
assert.equal(row('agent').line, 'Any framework, through MCP or NVIDIA NeMo Agent Toolkit, decides for someone you grant it.');
const told = "What a person's model is told at a decision, word for word as that decision's page shows it.";
const shown = "What the world's own models are shown for that person, and the world's rules in words.";
assert.deepEqual([row('nebius').connects, row('nebius').reads, row('nebius').goes_to], [
  'The open models offered with your Nebius key, each from its maker, priced per million tokens.', told,
  'Nebius Token Factory, with your key. The key stays on this computer and is sent only to them.',
]);
assert.deepEqual([row('this-computer').connects, row('this-computer').reads, row('this-computer').goes_to], [
  'The models your runner holds that this install offers, each checked here before a person may choose it.', told,
  'Nowhere else: your runner answers on this computer.',
]);
assert.deepEqual([row('game').connects, row('game').reads, row('game').goes_to], [
  'A game you admit on this install, for one of your people or a character of its own that comes in through the gate.', shown,
  'The game, under the grant you give it.',
]);
assert.deepEqual([row('agent').connects, row('agent').reads, row('agent').goes_to], [
  'An agent you run, with a key you hand it, for one of your people or a body of its own that comes in through the gate.',
  `${shown} Every line it says is shown as an AI's.`,
  "The agent you run. You can end the grant at any moment, and the person's own routine decides again.",
]);
// Only the agent's row ends a grant.
assert.deepEqual(rows.filter(one => one.ends).map(one => one.key), ['agent']);

// Each guide is a heading that exists in a document under docs/, opened from the one address the catalog names
// (the public repository), so a renamed heading fails here rather than opening the top of a page.
assert.equal(catalog.guides, 'https://github.com/twinkling-reality/exulanica/blob/main/');
const repository = new URL('../../../', import.meta.url);
for (const { key, guide } of rows) {
  assert.match(guide.document, /^docs\/[\w/-]+\.md$/u, key);
  const document = new URL(guide.document, repository);
  assert.ok(existsSync(document), `${key}: ${guide.document} exists`);
  const headings = readFileSync(document, 'utf8').split('\n').filter(line => /^#{1,6} /u.test(line)).map(line => line.replace(/^#+ /u, '').trim());
  assert.ok(headings.includes(guide.heading), `${key}: "${guide.heading}" is a heading of ${guide.document}`);
}
assert.equal(headingAnchor('Running your own install'), 'running-your-own-install');
assert.equal(headingAnchor("What the world's owner sees"), 'what-the-worlds-owner-sees');
assert.equal(guideAddress(catalog, row('agent').guide), 'https://github.com/twinkling-reality/exulanica/blob/main/docs/capabilities/outside-agents.md#on-your-own-install');
assert.equal(guideAddress(catalog, row('game').guide), 'https://github.com/twinkling-reality/exulanica/blob/main/docs/door-contract.md#bridges');

// Names as the state's one line says them: two, then the rest counted (point 3).
assert.equal(joinNames([]), '');
assert.equal(joinNames(['Uma Sorrel']), 'Uma Sorrel');
assert.equal(joinNames(['Uma Sorrel', 'Esme Oak']), 'Uma Sorrel and Esme Oak');
assert.equal(joinNames(['Uma Sorrel', 'Esme Oak', 'Bodhi Cove']), 'Uma Sorrel, Esme Oak and 1 more');
assert.equal(joinNames(['Uma Sorrel', 'Esme Oak', 'Bodhi Cove', 'Dara Stone', 'Juno Ford']), 'Uma Sorrel, Esme Oak and 3 more');
assert.equal(fill('{n} admitted', { n: 2 }), '2 admitted');

// Where models run, from GET /models: each model's provider refusal here.
const model = (provider, name, refusal = null) => ({ provider, model_id: name, name, runtime: { provider_refusal: refusal } });
const none = { bridges: [], standing: [] };
const keyed = [model('nebius_token_factory', 'Nemotron 3 Super'), model('ollama_local', 'Qwen3 4B Instruct')];
assert.deepEqual(rowState(row('nebius'), { ...none, models: keyed }), { words: 'Your key is set', on: true });
assert.deepEqual(rowState(row('this-computer'), { ...none, models: keyed }), { words: 'Running · Qwen3 4B Instruct', on: true });
const bare = [model('nebius_token_factory', 'Nemotron 3 Super', 'provider_credential_absent'), model('ollama_local', 'Qwen3 4B Instruct', 'provider_not_running')];
assert.deepEqual(rowState(row('nebius'), { ...none, models: bare }), { words: 'No key yet', on: false });
assert.deepEqual(rowState(row('this-computer'), { ...none, models: bare }), { words: 'Not running', on: false });
// A provider this install does not admit, or does not list, works nowhere here: its row is left out.
assert.equal(rowState(row('this-computer'), { ...none, models: [model('ollama_local', 'Qwen3 4B Instruct', 'provider_not_admitted')] }), null);
assert.equal(rowState(row('this-computer'), { ...none, models: [keyed[0]] }), null);
// A server that asks no model at all refuses every provider for a key; the runner's row is then not "Not running".
assert.equal(rowState(row('this-computer'), { ...none, models: [model('ollama_local', 'Qwen3 4B Instruct', 'provider_credential_absent')] }), null);

// Outside programs: the game row counts the bridges this install admits that are not AI's.
const bridge = ai => ({ bridge: ai ? 'agents' : 'a-game', label: 'x', game: 'x', run_by: 'owner', ai });
assert.deepEqual(rowState(row('game'), { models: [], bridges: [bridge(true)], standing: [] }), { words: 'None admitted on this install', on: false });
assert.deepEqual(rowState(row('game'), { models: [], bridges: [bridge(false), bridge(true), bridge(false)], standing: [] }), { words: '2 admitted', on: true });

// The agent row counts the AI grants that stand, from each world's grants read as door-grants-api.ts parses it.
const grant = (id, { ended = null, ai = true, things = [] } = {}) => ({
  grantId: id, worldId: 'world:one', bridge: 'agents', declared: null, ended, ai, versionId: 'v1', things,
});
const standing = standingGrants([grant('g1', { things: ['p1'] }), grant('g2', { ended: 'expired' }), grant('g3', { ended: 'revoked' }), grant('g4', { ai: false })]);
assert.deepEqual(standing.map(one => [one.grantId, one.ai, one.versionId, one.things]), [['g1', true, 'v1', ['p1']], ['g4', false, 'v1', []]]);
assert.deepEqual(standingGrants(null), []);
const named = (one, names) => ({ ...one, names });
assert.deepEqual(rowState(row('agent'), { models: [], bridges: [], standing: [] }), { words: 'No grant yet', on: false });
assert.deepEqual(rowState(row('agent'), { models: [], bridges: [], standing: [named(standing[1], ['Not an AI'])] }), { words: 'No grant yet', on: false });
assert.deepEqual(rowState(row('agent'), { models: [], bridges: [], standing: [named(standing[0], ['Uma Sorrel'])] }), { words: 'Deciding for Uma Sorrel', on: true });
assert.deepEqual(rowState(row('agent'), { models: [], bridges: [], standing: [named(standing[0], ['Uma Sorrel', 'Esme Oak'])] }), { words: 'Deciding for Uma Sorrel and Esme Oak', on: true });
assert.deepEqual(rowState(row('agent'), { models: [], bridges: [], standing: [named(standing[0], ['Uma Sorrel', 'Esme Oak', 'Visitor'])] }), { words: 'Deciding for Uma Sorrel, Esme Oak and 1 more', on: true });
// One grant always says whom it decides for, nobody yet included; several are counted, each with the dot (point 2).
assert.deepEqual(rowState(row('agent'), { models: [], bridges: [], standing: [named(standing[0], [])] }), { words: 'Deciding for nobody yet', on: true });
const two = [named(standing[0], ['A']), named({ ...standing[0], grantId: 'g5' }, ['B'])];
assert.deepEqual(rowState(row('agent'), { models: [], bridges: [], standing: two }), { words: '2 grants', on: true });

// Where several stand, the focused row's faint line says how each ends instead of Del (point 4), and no other row
// says it. Its "at most a day" is the door's own longest grant (exulanica/door/grants.py MINUTES_MAXIMUM), so a
// change to that constant fails here until the words change with it.
assert.equal(severalLine(row('agent'), two), 'Each grant ends by itself at most a day after it was given.');
assert.equal(severalLine(row('agent'), [two[0]]), null);
assert.equal(severalLine(row('game'), two), null);
const door = readFileSync(new URL('exulanica/door/grants.py', repository), 'utf8');
const longest = Number(/^MINUTES_MAXIMUM: Final = (\d+)$/mu.exec(door)?.[1]);
const SAID = { 1440: 'a day' };
assert.ok(Object.hasOwn(SAID, longest), `the door's longest grant, ${longest} minutes, has words`);
assert.match(row('agent').several, new RegExp(` at most ${SAID[longest]} after `, 'u'));

// Whom a grant decides for, by the name its world gives them: the people it names, then its own visitors.
const society = { state: { inhabitants: [
  { id: 'p1', display_name: 'Uma Sorrel', came_by: 'drawn' },
  { id: 'p2', display_name: 'Esme Oak', came_by: 'drawn' },
  { id: 'v1', display_name: 'Pilot', came_by: 'crossed', crossing: { bridge: 'agents', grant_id: 'g1' } },
  { id: 'v2', display_name: 'Guided', came_by: 'crossed', crossing: { bridge: 'agents', grant_id: 'g1', decided_by: 'world' } },
  { id: 'v3', display_name: 'Elsewhere', came_by: 'crossed', crossing: { bridge: 'agents', grant_id: 'g9' } },
] } };
assert.deepEqual(namesFor(society, standing[0]), ['Uma Sorrel', 'Pilot']);
assert.deepEqual(namesFor(null, standing[0]), []);
assert.deepEqual(namesOf(society, ['p2', 'gone', 'p1']), ['Esme Oak', 'Uma Sorrel']);
assert.equal(INTEGRATIONS, catalog);

// Who decides again after a grant ends, as the version's model history records it, newest first.
const history = { choices: [
  { choice_seq: 3, subjects: ['p1'], decider: { kind: 'routine' } },
  { choice_seq: 2, subjects: ['p2'], decider: { kind: 'external' } },
  { choice_seq: 1, subjects: ['p1', 'p2'], decider: { kind: 'routine' } },
] };
assert.deepEqual(releasedSubjects(history, ['p1', 'p2', 'p3']), ['p1']);
assert.deepEqual(releasedSubjects(null, ['p1']), []);
// After Del (DESIGN's pass of 11:50, fold-in c): the state says "Ended." alone, and in focus a faint line names whom
// the record shows handed back, none naming nobody.
assert.equal(endedState(row('agent')), 'Ended.');
assert.equal(handedBackLine(row('agent'), ['Uma Sorrel']), "Uma Sorrel's own routine decides again.");
assert.equal(handedBackLine(row('agent'), ['Uma Sorrel', 'Esme Oak']), 'Their own routines decide again: Uma Sorrel and Esme Oak.');
assert.equal(handedBackLine(row('agent'), ['Uma Sorrel', 'Esme Oak', 'Visitor']), 'Their own routines decide again: Uma Sorrel, Esme Oak and 1 more.');
assert.equal(handedBackLine(row('agent'), []), null);
// An end refused or not answered leaves the grant standing and says so (fold-in b); one refused because the grant had
// already ended says it ended.
assert.equal(refusedLine(row('agent')), 'It could not be ended just then; it still stands.');
assert.equal(alreadyEnded('grant_ended'), true);
assert.equal(alreadyEnded('unknown_reference'), false);
assert.equal(alreadyEnded(undefined), false);

// Del ends the one AI grant standing, on the agent row only, and nothing with none or several.
assert.equal(endable(row('agent'), [standing[0], standing[1]]), standing[0]);
assert.equal(endable(row('agent'), []), null);
assert.equal(endable(row('agent'), [standing[0], { ...standing[0], grantId: 'g5' }]), null);
assert.equal(endable(row('game'), [standing[1]]), null);
assert.equal(endable(row('nebius'), [standing[0]]), null);

// A guest's page, or a hosted account's (DESIGN's guest sheet and WORDS.md 11:16 item 1): its own title and sub, each
// row's guest words, only what this server offers, and nothing that sets anything up or ends a grant.
assert.equal(INTEGRATION_WORDS.guestTitle, 'What this server connects to');
assert.equal(INTEGRATION_WORDS.guestSub, "Each one says what it connects, what it reads and where anything goes. This server's owner set them up. On your own install, you set up your own and can end them.");
const guest = key => guestRow(row(key));
assert.deepEqual(rows.map(one => guestRow(one).name), ['Nebius Token Factory', 'A model on this server', 'A game', 'An AI agent you build']);
assert.deepEqual([guest('nebius').line, guest('nebius').connects, guest('nebius').reads, guest('nebius').goes_to], [
  "Open models from their makers answer for your people, from this server's budget, usually for a fraction of a cent a decision.",
  'The open models this server offers, each from its maker, priced per million tokens.', told,
  "Nebius Token Factory, under this server's own key.",
]);
assert.deepEqual([guest('this-computer').line, guest('this-computer').connects, guest('this-computer').reads, guest('this-computer').goes_to], [
  'A local model runner answers on this server, free.',
  "The models this server's runner holds and offers, each checked here before a person may choose it.", told,
  'Nowhere else: the runner answers on this server.',
]);
assert.deepEqual([guest('game').line, guest('game').connects, guest('game').reads, guest('game').goes_to], [row('game').line, row('game').connects, shown, 'The game, on your own install.']);
assert.deepEqual([guest('agent').line, guest('agent').connects, guest('agent').reads, guest('agent').goes_to], [row('agent').line, row('agent').connects, row('agent').reads, 'The agent you run, on your own install.']);
assert.deepEqual(guest('agent').guide, row('agent').guide);
// A provider's row only where one of its models is not refused here; the door's rows on your own install, no dot.
assert.deepEqual(guestState(guest('nebius'), keyed), { words: "This server's budget", on: true });
assert.deepEqual(guestState(guest('this-computer'), keyed), { words: 'Running \u00b7 Qwen3 4B Instruct', on: true });
assert.equal(guestState(guest('nebius'), bare), null);
assert.equal(guestState(guest('this-computer'), bare), null);
assert.equal(guestState(guest('this-computer'), [keyed[0]]), null);
assert.deepEqual(guestState(guest('game'), keyed), { words: 'On your own install', on: false });
assert.deepEqual(guestState(guest('agent'), []), { words: 'On your own install', on: false });
// No Del and no faint line of grants for a guest, whatever stands.
assert.equal(endable(guest('agent'), [standing[0]]), null);
assert.equal(severalLine(guest('agent'), two), null);

// Marks are line drawings: rects, circles and paths with their geometry, nothing else.
assert.deepEqual(markShapes(row('this-computer').mark), [
  { tag: 'rect', attributes: [['x', '5'], ['y', '5'], ['width', '14'], ['height', '10'], ['rx', '1.5']] },
  { tag: 'path', attributes: [['d', 'M3 19h18']] },
]);
for (const one of rows) assert.ok(markShapes(one.mark).length > 0, one.key);
assert.throws(() => markShapes([{ image: { href: 'logo.png' } }]), /A mark draws rect, circle, path/u);
assert.throws(() => markShapes([{ path: { d: 'M0 0', style: 'fill: red' } }]), /A mark's path has no style/u);
assert.throws(() => markShapes([{ rect: { x: 0 }, path: { d: 'M0 0' } }]), /one to a shape/u);

// ↑ and ↓ choose a row, held at either end.
assert.equal(stepRow(0, 4, 'ArrowUp'), 0);
assert.equal(stepRow(0, 4, 'ArrowDown'), 1);
assert.equal(stepRow(3, 4, 'ArrowDown'), 3);
assert.equal(stepRow(2, 4, 'Enter'), 2);

// No em dash in the page's words or its catalog.
for (const file of ['integration-words.mjs', 'integrations.v1.json']) {
  assert.doesNotMatch(readFileSync(new URL(file, import.meta.url), 'utf8'), /\u2014/u, file);
}
