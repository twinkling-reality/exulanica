// @vitest-environment happy-dom
// The card for a person of a society of things: its kind's summary, the look it wears with who made
// it and its licence, what it holds, how it came (placed by the world's author, one of its people,
// or across from outside), and, for a visitor, that the program it came with decides for it, with
// no Change. Expected words come from the shipped catalog documents (assets/catalogs/things), the
// marks agreed with DRAW (CARD design section 3) and the words agreed with UI for outside deciders
// (coordination CARD.txt and UI.txt, 2026-10-07): "Came in from <bridge label>", and "It is not an
// AI" only where the door's entry says no AI runs the bridge.
import { readFileSync } from 'node:fs';
import { describe, expect, it, vi } from 'vitest';
import type { ThingLibrary } from '@exulanica/atlas-react/things';
import { mountThingCard, personCard } from '../src/composition/thing-card-mount.js';
import type { SelectedBeing, SelectedPerson } from '../src/composition/environment-selection.js';
import type { DoorBridge } from '../src/door-bridges-api.js';
import type { LookReference } from '../src/thing-card-api.js';
import { readKindFacts, readLookFacts } from '../src/thing-card-api.js';

const repository = `${process.cwd()}/..`;
const read = (path: string): Record<string, unknown> =>
  JSON.parse(readFileSync(`${repository}/assets/catalogs/things/${path}`, 'utf8')) as Record<string, unknown>;
const KINDS: Record<string, Record<string, unknown>> = {
  knight: read('kinds/knight.v2.json'), sword: read('kinds/sword.v3.json'), villager: read('kinds/villager.v1.json'),
};
const LOOKS: Record<string, Record<string, unknown>> = {
  'kaykit-knight': read('looks/kaykit-knight.v1.json'), 'blocky-knight': read('looks/blocky-knight.v1.json'),
  'people-catalog': read('looks/people-catalog.v1.json'),
};
const SHA = (key: string): string => (key === 'villager' ? 'b' : 'a').repeat(64);
const ref = (key: string) => ({ kind: key, version: KINDS[key]!['version'] as number, sha256: SHA(key) });
const looksOf = (key: string) => (KINDS[key]!['looks'] as { look: string; version: number; sha256: string }[]);

/** The host's library over the shipped documents, as the drawing and the card read it. */
function library(): ThingLibrary {
  return {
    list: {
      kinds: Object.keys(KINDS).map((key) => ({ ...ref(key), label: KINDS[key]!['label'], class: KINDS[key]!['class'], bodyPlan: '', looks: looksOf(key).map((look) => ({ key: look.look, version: look.version, sha256: look.sha256 })) })),
      looks: Object.entries(LOOKS).map(([key, look]) => ({ look: key, version: 1, sha256: (looksOf('knight').find((one) => one.look === key) ?? looksOf('villager')[0]!).sha256, label: look['label'], bodyPlan: '', lookKind: look['look_kind'], container: null })),
      bodyPlansSha256: 'c'.repeat(64),
    },
    kindDocument: async (named: { key: string }) => KINDS[named.key],
    lookDocument: async (named: { key: string }) => LOOKS[named.key],
  } as unknown as ThingLibrary;
}

const GAME: DoorBridge = { bridge: 'blockgame', label: 'Block Game', game: 'Block Game', runBy: 'server', ai: false };
const AGENTS: DoorBridge = { bridge: 'agents', label: 'an outside agent', game: 'any program', runBy: 'owner', ai: true };

const about = (being: SelectedBeing | undefined, running: SelectedPerson['mind'] = null): SelectedPerson => ({
  note: { title: 'Knight', description: 'A person in this world.', activity: 'Walking to the well.' } as SelectedPerson['note'],
  mind: running,
  ...(being === undefined ? {} : { being }),
});
const being = (fields: Partial<SelectedBeing>): SelectedBeing => ({
  kind: ref('knight'), cameBy: 'placed', placedId: 'knight-1', crossing: null, holding: [],
  world: { worldId: 'world:authored:saved', versionId: 'version' }, ...fields,
});
const facts = (look: string | null, holding: string | null = null) => ({
  kind: readKindFacts(KINDS['knight']), look: look === null ? null : readLookFacts(LOOKS[look]), holding,
});

describe('a person of a society of things, on the card', () => {
  it('a visitor a person plays: marked by its game, decided from outside, with no Change', () => {
    const card = personCard('visitor-1', about(being({ cameBy: 'crossed', placedId: null, crossing: { bridge: 'blockgame', entry: GAME } })), null, facts(null, 'a sword'));
    expect(card.mark).toEqual({ kind: 'from', text: 'from Block Game', label: 'A person playing Block Game' });
    expect(card.mind).toMatchObject({ name: 'A person playing Block Game', line: 'Decided from outside, through Block Game. It is not an AI.', choices: [] });
    expect(card.summary).toBe(KINDS['knight']!['summary']);
    expect(card.holding).toBe('a sword');
    expect(card.cameFrom).toBe('Came in from Block Game.');
  });

  it('a visitor an outside agent runs wears the AI mark and is not called a person', () => {
    const card = personCard('visitor-2', about(being({ cameBy: 'crossed', placedId: null, crossing: { bridge: 'agents', entry: AGENTS } })), null);
    expect(card.mark).toEqual({ kind: 'ai', text: 'AI', label: 'An outside AI agent' });
    expect(card.mind?.line).toBe('Decided from outside, through an outside agent. It is not one of this world\'s own minds.');
    expect(card.mind?.line).not.toContain('not an AI');
  });

  it('a visitor through a bridge the door does not list claims nothing about who runs it', () => {
    const card = personCard('visitor-3', about(being({ cameBy: 'crossed', placedId: null, crossing: { bridge: 'elsewhere', entry: null } })), null);
    expect(card.mind?.line).toBe('Decided from outside this world.');
    expect(card.cameFrom).toBe('Came in from outside this world.');
  });

  it('a being its author placed says so and what its kind is; one of the people says that', () => {
    const placed = personCard('knight-0', about(being({})), null, facts('kaykit-knight'));
    expect(placed.cameFrom).toBe('You placed it here. A knight is one of Exulanica\'s own kinds.');
    expect(placed.looks?.name).toBe('Armoured knight');
    expect(placed.holding).toBeNull();
    const villager = personCard('person-0', about(being({ kind: ref('villager'), cameBy: 'populated', placedId: null })), null);
    expect(villager.cameFrom).toBe('One of the people who live in this world.');
  });
});

function mount(worn: ReadonlyMap<string, LookReference> = new Map()) {
  const shell = document.createElement('div');
  document.body.replaceChildren(shell);
  const lookReads: string[] = [];
  const card = mountThingCard({
    selection: { decide: vi.fn(), models: () => null, openDecides: vi.fn() }, compare: null,
    shell, credentials: { baseUrl: 'https://example.test', token: 't' },
    library: async () => library(),
    looks: async (_world, versionId) => { lookReads.push(versionId); return worn; },
  });
  shell.append(card.view.root);
  return { card, root: card.view.root, lookReads };
}
const settle = async () => { for (let i = 0; i < 6; i += 1) await new Promise((resolve) => setTimeout(resolve, 0)); };
const rowText = (root: HTMLElement, heading: string) =>
  [...root.querySelectorAll('.thing-card-row')].find((row) => row.querySelector('h4')?.textContent === heading)?.textContent ?? null;

describe('the mounted card for a being', () => {
  it('reads its kind, the look chosen for it by its own id, and what it holds, then shows them', async () => {
    const blocky = looksOf('knight')[1]!;
    const { card, root, lookReads } = mount(new Map([['visitor-1', { key: blocky.look, version: blocky.version, sha256: blocky.sha256 }]]));
    const visitor = being({ cameBy: 'crossed', placedId: null, crossing: { bridge: 'blockgame', entry: GAME }, holding: [{ id: 'sword-1', kind: ref('sword') }] });
    card.view.show('visitor-1', about(visitor));
    await settle();
    expect(root.querySelector('.thing-card-summary')?.textContent).toBe(KINDS['knight']!['summary']);
    expect(rowText(root, 'Looks like')).toContain('Blocky knight');
    expect(rowText(root, 'Holding')).toBe('Holdinga sword');
    expect(rowText(root, 'Came from')).toBe('Came fromCame in from Block Game.');
    expect(root.querySelector('[data-action="card.mind.change"]')).toBeNull();
    // Shown again the next minute, it reads nothing again.
    card.view.show('visitor-1', about(visitor));
    await settle();
    expect(lookReads).toEqual(['version']);
    expect(rowText(root, 'Holding')).toBe('Holdinga sword');
  });

  it('keeps its rows while the look choices are read again after a minute', async () => {
    const { card, root, lookReads } = mount();
    const knight = being({});
    let now = 1_000;
    const clock = vi.spyOn(performance, 'now').mockImplementation(() => now);
    try {
      card.view.show('knight-0', about(knight));
      await settle();
      now += 61_000;
      card.view.show('knight-0', about(knight));
      // Drawn at once from what was read before, not emptied while the read is out.
      expect(rowText(root, 'Looks like')).toContain('Armoured knight');
      await settle();
      expect(lookReads).toEqual(['version', 'version']);
    } finally {
      clock.mockRestore();
    }
  });

  it('wears its kind\'s first look with no choice, and no look row where it is drawn as one of the people', async () => {
    const { card, root } = mount();
    card.view.show('knight-0', about(being({})));
    await settle();
    expect(rowText(root, 'Looks like')).toContain('Armoured knight');
    card.view.show('person-0', about(being({ kind: ref('villager'), cameBy: 'populated', placedId: null })));
    await settle();
    expect(rowText(root, 'Looks like')).toBeNull();
    expect(root.querySelector('.thing-card-summary')?.textContent).toBe(KINDS['villager']!['summary']);
  });
});
