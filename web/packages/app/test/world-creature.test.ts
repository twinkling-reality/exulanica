// @vitest-environment happy-dom
// Making a creature where it will stand (tools/previews/world-workspace/world-creature.ts): the stand read is
// asked at the point 8 m ahead, the line under the field says the model's price and time, the words are made
// into a draft followed until it is kept, and the kept kind is then held at the stand by build mode, whose own keys
// place it. The server's answers are written down here; no model is asked and no 3D view is drawn.
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { CreatureDraft, CreatureOffer, SocietyStand } from '../src/creature-drafts-api.js';

const screen = async () => import('../../../../tools/previews/world-workspace/' + 'world-creature.ts');

const offer: CreatureOffer = Object.freeze({
  offered: true, code: null, timing: { typicalSeconds: 18, longestSeconds: 25, timeoutSeconds: 50 },
  model: { modelId: 'nvidia/nemotron-3-super-120b-a12b', name: 'Nemotron 3 Super 120B' }, priceUsdAtMost: '0.37355520',
});
const queued: CreatureDraft = Object.freeze({
  draftId: 'draft-1', status: 'queued', label: null, kind: null, look: null, model: null, refusal: null, failure: null, spentUsd: '0.00000000',
});
const kept: CreatureDraft = Object.freeze({
  ...queued, status: 'kept', label: 'yellow pond wader', kind: { key: 'yellow_pond_wader', version: 1, sha256: 'a'.repeat(64) },
  model: { modelId: 'nvidia/nemotron-3-super-120b-a12b', name: 'Nemotron 3 Super 120B' }, spentUsd: '0.00420000',
});
const stand: SocietyStand = Object.freeze({ nodeId: 'n-7', positionMm: [4200, -1800] as const });

function world(answers: { readonly offer?: CreatureOffer; readonly drafts?: readonly CreatureDraft[]; readonly stand?: SocietyStand | null; readonly reads?: CreatureDraft[]; readonly at?: { readonly x: number; readonly y: number } } = {}) {
  const root = document.createElement('div');
  document.body.append(root);
  const calls = { stand: [] as unknown[], ask: [] as string[], hold: [] as unknown[], closed: 0, released: 0, marked: [] as (SocietyStand | null)[] };
  // A hold ends when the person places the creature or puts it back: here, when the test says so.
  const holds: ((outcome: { readonly outcome: 'placed'; readonly thingId: string }) => void)[] = [];
  const reads = [...(answers.reads ?? [kept])];
  return {
    root,
    calls,
    placed: () => { for (const settle of holds.splice(0)) settle({ outcome: 'placed', thingId: 'thing-1' }); },
    deps: {
      root,
      client: {
        offer: async () => answers.offer ?? offer,
        drafts: async () => answers.drafts ?? [],
        ask: async (words: string) => { calls.ask.push(words); return queued; },
        draft: async () => reads.shift() ?? kept,
        stand: async (versionId: string, worldId: string, at: unknown) => { calls.stand.push({ versionId, worldId, at }); return answers.stand === undefined ? stand : answers.stand; },
      },
      version: () => ({ versionId: 'version-1', worldId: 'world-1' }),
      ahead: (millimetres: number) => ({ xMm: 1000 + millimetres, zMm: 0 }),
      mark: (found: SocietyStand | null) => { calls.marked.push(found); return found === null ? null : answers.at ?? { x: 512, y: 500 }; },
      head: () => ({ x: 400, y: 300 }),
      hold: (kind: unknown, at: unknown) => { calls.hold.push({ kind, at }); return new Promise<{ readonly outcome: 'placed'; readonly thingId: string }>((settle) => { holds.push(settle); }); },
      close: () => { calls.closed += 1; },
      release: () => { calls.released += 1; },
      wait: async () => {},
    },
  };
}

const press = (key: string): KeyboardEvent => new KeyboardEvent('keydown', { key, cancelable: true });
const settle = async (): Promise<void> => { for (let turn = 0; turn < 20; turn += 1) await Promise.resolve(); };

afterEach(() => { document.body.replaceChildren(); });

describe('making a creature where it will stand', () => {
  it('marks the stand the society would take it in at, 8 m ahead, and says the price and time under the field', async () => {
    const { openCreatureScreen, STAND_AHEAD_MM } = await screen();
    const { deps, calls, root } = world();
    await openCreatureScreen(deps);
    expect(STAND_AHEAD_MM).toBe(8000);
    expect(calls.stand).toEqual([{ versionId: 'version-1', worldId: 'world-1', at: { xMm: 9000, zMm: 0 } }]);
    // The ring is laid at the stand, and laid there again each frame while it shows.
    expect(calls.marked.length).toBeGreaterThan(0);
    expect(calls.marked.every((marked) => marked === stand)).toBe(true);
    expect(root.textContent).toContain('The creature appears here');
    expect(root.textContent).toContain('An AI model makes the creature from your words: at most $0.37, about 18 seconds.');
  });

  it('with no stand open marks nothing, and with no price says only what makes it', async () => {
    const { openCreatureScreen } = await screen();
    const { deps, calls, root } = world({ stand: null, offer: { ...offer, priceUsdAtMost: null } });
    await openCreatureScreen(deps);
    expect(calls.marked).toEqual([null]);
    expect(root.textContent).not.toContain('The creature appears here');
    expect(root.textContent).toContain('An AI model makes the creature from your words.');
    expect(root.textContent).not.toContain('seconds');
  });

  it('makes the words into a draft, follows it until kept, and holds the kind at the stand for build mode to place', async () => {
    const { openCreatureScreen } = await screen();
    const { deps, calls, root, placed } = world({ reads: [{ ...queued, status: 'running' }, kept] });
    const opened = await openCreatureScreen(deps);
    const field = root.querySelector('textarea')!;
    field.value = 'a round yellow body with a pale flat bill on two short legs';
    field.dispatchEvent(new Event('input'));
    expect(opened.key(press('Enter'))).toBe(true);
    await settle();
    expect(calls.ask).toEqual(['a round yellow body with a pale flat bill on two short legs']);
    expect(root.textContent).toContain('Yellow pond wader');
    expect(root.textContent).toContain('Made by Nemotron 3 Super 120B · spent $0.0042 · kept in Creatures');
    // Its made look is not made yet, so it wears its sketch, said by its name.
    expect(root.textContent).toContain('Yellow pond wader wears a sketch until the made look is ready.');
    // Made, it is held at the stand at once and the keys go back to build mode, which places it; the step then ends.
    expect(calls.hold).toEqual([{ kind: { source: 'workspace', sha256: 'a'.repeat(64) }, at: { xMm: 4200, zMm: -1800 } }]);
    expect(calls.released).toBe(1);
    expect(calls.marked.at(-1)).toBeNull();
    expect(root.textContent).not.toContain('The creature appears here');
    expect(calls.closed).toBe(0);
    placed();
    await settle();
    expect(calls.closed).toBe(1);
    expect(root.querySelector('.wu-creature-layer')).toBeNull();
  });

  it('says nothing of a sketch once the made look is made', async () => {
    const { openCreatureScreen } = await screen();
    const { deps, root } = world({ reads: [{ ...kept, lookStatus: 'made' }] });
    const opened = await openCreatureScreen(deps);
    const field = root.querySelector('textarea')!;
    field.value = 'a round yellow body';
    field.dispatchEvent(new Event('input'));
    opened.key(press('Enter'));
    await settle();
    expect(root.textContent).toContain('Yellow pond wader');
    expect(root.textContent).not.toContain('wears a sketch');
  });

  it('has no stand where the stand is out of view: no ring, no label, and the made creature waits in Creatures', async () => {
    const { openCreatureScreen } = await screen();
    // Past the window's side inset (happy-dom's window is 1024 wide).
    const { deps, calls, root } = world({ at: { x: 1020, y: 500 } });
    const opened = await openCreatureScreen(deps);
    expect(calls.marked.at(-1)).toBeNull();
    expect(root.textContent).not.toContain('The creature appears here');
    const field = root.querySelector('textarea')!;
    field.value = 'a round yellow body';
    field.dispatchEvent(new Event('input'));
    opened.key(press('Enter'));
    await settle();
    expect(root.textContent).toContain('Yellow pond wader');
    expect(root.textContent).not.toContain('Place');
    expect(calls.hold).toEqual([]);
  });

  it('says where the creature appears while it is described, and no longer once it is being made', async () => {
    const { openCreatureScreen } = await screen();
    const { deps, root } = world({ reads: [{ ...queued, status: 'running' }, { ...queued, status: 'running' }, kept] });
    // What shows while it is being made, a frame after the making began (the stand is followed each frame).
    let reads = 0, labelWhileMaking: boolean | null = null;
    const client = {
      ...deps.client,
      draft: async (_id: string) => {
        reads += 1;
        if (reads === 1) {
          await new Promise((resolve) => { requestAnimationFrame(resolve); });
          labelWhileMaking = (root.textContent ?? '').includes('The creature appears here');
        }
        return deps.client.draft();
      },
    };
    const opened = await openCreatureScreen({ ...deps, client });
    expect(root.textContent).toContain('The creature appears here');
    const field = root.querySelector('textarea')!;
    field.value = 'a round yellow body';
    field.dispatchEvent(new Event('input'));
    opened.key(press('Enter'));
    await settle();
    await vi.waitFor(() => expect(labelWhileMaking).not.toBeNull());
    expect(labelWhileMaking).toBe(false);
  });

  it("draws the made card's leader to the held creature's head", async () => {
    const { openCreatureScreen } = await screen();
    const { deps, root } = world();
    const opened = await openCreatureScreen(deps);
    const field = root.querySelector('textarea')!;
    field.value = 'a round yellow body';
    field.dispatchEvent(new Event('input'));
    opened.key(press('Enter'));
    await settle();
    await new Promise((resolve) => { requestAnimationFrame(resolve); });
    const line = root.querySelector('.wu-creature-leader line');
    expect(line).not.toBeNull();
    expect([line!.getAttribute('x1'), line!.getAttribute('y1')]).toEqual(['400', '300']);
  });

  it('asks nothing with the field empty or where creatures are not offered', async () => {
    const { openCreatureScreen } = await screen();
    const empty = world();
    const opened = await openCreatureScreen(empty.deps);
    opened.key(press('Enter'));
    await settle();
    expect(empty.calls.ask).toEqual([]);
    const refused = world({ offer: { ...offer, offered: false, code: 'creatures_not_run_here' } });
    const closed = await openCreatureScreen(refused.deps);
    expect(refused.root.textContent).toContain('Making creatures isn\'t offered here.');
    const field = refused.root.querySelector('textarea')!;
    field.value = 'a round yellow body';
    field.dispatchEvent(new Event('input'));
    closed.key(press('Enter'));
    await settle();
    expect(refused.calls.ask).toEqual([]);
  });

  it('shows a refusal in its code\'s sentence, and Esc goes back to building', async () => {
    const { openCreatureScreen } = await screen();
    const refusal = { code: 'creature_movement_unbuilt', field: 'moves_fly', detail: 'This world has no flying creatures yet.' };
    const { deps, calls, root } = world({ reads: [{ ...queued, status: 'refused', refusal }] });
    const opened = await openCreatureScreen(deps);
    const field = root.querySelector('textarea')!;
    field.value = 'a winged body that flies';
    field.dispatchEvent(new Event('input'));
    opened.key(press('Enter'));
    await settle();
    expect(root.textContent).toContain('This world has no flying creatures yet.');
    expect(opened.key(press('Escape'))).toBe(true);
    expect(calls.closed).toBe(1);
    expect(calls.hold).toEqual([]);
  });

  it('says spending is paused, not spent, by the served code, before anyone types and after Make (N34)', async () => {
    const { openCreatureScreen } = await screen();
    for (const [code, words] of [
      ['spending_suspended', 'Spending on AI models is paused here.'],
      ['budget_exceeded', 'The budget for AI models here is spent.'],
    ] as const) {
      const refused = world({ offer: { ...offer, offered: false, code } });
      await openCreatureScreen(refused.deps);
      expect(refused.root.querySelector('.wu-refused')?.textContent).toBe(words);
    }
    // Held closed after Make: the draft fails paused, and says so rather than spent.
    const { deps, root } = world({ reads: [{ ...queued, status: 'failed', failure: 'spending_suspended' }] });
    const opened = await openCreatureScreen(deps);
    const field = root.querySelector('textarea')!;
    field.value = 'a round yellow body';
    field.dispatchEvent(new Event('input'));
    opened.key(press('Enter'));
    await settle();
    expect(root.textContent).toContain('Spending on AI models is paused here.');
    expect(root.textContent).not.toContain('The budget for AI models here is spent.');
  });
});
