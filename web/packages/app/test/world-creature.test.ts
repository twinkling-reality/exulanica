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

  it('reads "Placing…" with its key dimmed from the moment build mode lets the creature go, and a refused place says why', async () => {
    const { openCreatureScreen } = await screen();
    const { deps, root } = world();
    type Told = (placing: { readonly placing: boolean; readonly refused: string | null }) => void;
    let told: Told | undefined;
    const opened = await openCreatureScreen({ ...deps, hold: (kind: unknown, at: unknown, heard?: Told) => { told = heard; return deps.hold(kind, at); } });
    const field = root.querySelector('textarea')!;
    field.value = 'a round yellow body';
    field.dispatchEvent(new Event('input'));
    opened.key(press('Enter'));
    await settle();
    const row = () => root.querySelector('.wu-creature-made .wu-row');
    expect(row()?.textContent).toBe('Place');
    told!({ placing: true, refused: null });
    expect(row()?.textContent).toBe('Placing…');
    expect(row()?.getAttribute('aria-disabled')).toBe('true');
    // Refused: why, in build mode's words, and Place dimmed, as build mode offers no Place for a refused placing.
    told!({ placing: false, refused: 'It cannot stand here: something is in the way.' });
    expect(row()?.textContent).toBe('Place');
    expect(row()?.getAttribute('aria-disabled')).toBe('true');
    expect(root.querySelector('.wu-creature-made .wu-refused')?.textContent).toBe('It cannot stand here: something is in the way.');
    // Where it may stand again: Place is back, and the refusal goes.
    told!({ placing: false, refused: null });
    expect(row()?.getAttribute('aria-disabled')).toBeNull();
    expect(root.querySelector('.wu-creature-made .wu-refused')).toBeNull();
  });

  it('shows a refusal in its code\'s sentence with Try again, back to the words, and Esc goes back to building', async () => {
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
    // Changed words may pass: Try again shows, and Enter goes back to the field with the words kept.
    expect(root.querySelector('.wu-creature-group [aria-keyshortcuts="Enter"]')?.textContent).toBe('Try again');
    expect(opened.key(press('Enter'))).toBe(true);
    expect(root.querySelector('textarea')?.value).toBe('a winged body that flies');
    expect(opened.key(press('Escape'))).toBe(true);
    expect(calls.closed).toBe(1);
    expect(calls.hold).toEqual([]);
  });

  it('says why a draft ended with nothing made, by its code, and offers Try again wherever making is still offered', async () => {
    const { openCreatureScreen } = await screen();
    for (const [failure, words, retry] of [
      ['drafter_unavailable', 'The AI model did not answer, so nothing was made. Try again in a minute.', true],
      ['stranded', 'Making stopped part way, so nothing was kept. Try again.', true],
      ['expired', 'Making did not start in time, so nothing was made. Try again in a few minutes.', true],
      ['not_served', 'Making creatures isn\'t offered here.', false],
      ['request_refused', 'The rules here kept your words from being sent to the model, so nothing was made.', true],
      ['reference_withdrawn', 'The picture it was to be made from was withdrawn, so nothing was made.', true],
      ['spending_suspended', 'Spending on AI models is paused here.', false],
      ['spending_refused', 'The budget for AI models here is spent.', false],
      ['a_code_served_later', 'Something went wrong while making it, so nothing was made. Try again.', true],
    ] as const) {
      const { deps, root } = world({ reads: [{ ...queued, status: 'failed', failure }] });
      const opened = await openCreatureScreen(deps);
      const field = root.querySelector('textarea')!;
      field.value = 'a round yellow body';
      field.dispatchEvent(new Event('input'));
      opened.key(press('Enter'));
      await settle();
      expect(root.querySelector('.wu-creature-step.wu-refused')?.textContent).toBe(words);
      // Nothing carries on at the server, so the small print saying it does goes; nothing was spent, so no spend.
      expect(root.textContent).not.toContain('You can leave this page');
      expect(root.textContent).not.toContain('At most');
      expect(root.textContent).not.toContain('Spent');
      expect(root.querySelector('.wu-creature-group [aria-keyshortcuts="Enter"]')?.textContent ?? null).toBe(retry ? 'Try again' : null);
      // Enter tries again only where Try again shows: back to the field, the words kept.
      expect(opened.key(press('Enter'))).toBe(retry);
      expect(root.querySelector('.wu-creature-group') === null).toBe(retry);
      if (retry) expect(root.querySelector('textarea')?.value).toBe('a round yellow body');
      document.body.replaceChildren();
    }
  });

  it('tries again from the Try again key as from Enter, and says what was spent before it stopped', async () => {
    const { openCreatureScreen } = await screen();
    const { deps, calls, root } = world({ reads: [{ ...queued, status: 'failed', failure: 'drafter_unavailable', spentUsd: '0.00020000' }, kept] });
    const opened = await openCreatureScreen(deps);
    const field = root.querySelector('textarea')!;
    field.value = 'a round yellow body';
    field.dispatchEvent(new Event('input'));
    opened.key(press('Enter'));
    await settle();
    expect(root.querySelector('.wu-creature-group .wu-creature-small')?.textContent).toBe('Spent $0.0002 before it stopped.');
    root.querySelector<HTMLButtonElement>('.wu-creature-group button[aria-keyshortcuts="Enter"]')!.click();
    expect(root.querySelector('textarea')?.value).toBe('a round yellow body');
    opened.key(press('Enter'));
    await settle();
    expect(calls.ask).toEqual(['a round yellow body', 'a round yellow body']);
    expect(root.textContent).toContain('Yellow pond wader');
  });

  it('sends the words as the server takes a line: one space for each run of white space, none at either end', async () => {
    const { openCreatureScreen, sendableWords } = await screen();
    expect(sendableWords('  a round\n\nyellow body​ \t')).toBe('a round yellow body');
    const { deps, calls, root } = world();
    const opened = await openCreatureScreen(deps);
    const field = root.querySelector('textarea')!;
    field.value = ' a round yellow body\non two short legs ';
    field.dispatchEvent(new Event('input'));
    opened.key(press('Enter'));
    await settle();
    expect(calls.ask).toEqual(['a round yellow body on two short legs']);
    expect(root.textContent).toContain('“a round yellow body on two short legs”');
    // White space alone asks nothing.
    const blank = world();
    const empty = await openCreatureScreen(blank.deps);
    const space = blank.root.querySelector('textarea')!;
    space.value = ' \n ';
    space.dispatchEvent(new Event('input'));
    empty.key(press('Enter'));
    await settle();
    expect(blank.calls.ask).toEqual([]);
  });

  it('says a draft the page stops following is taking longer, and offers nothing to press', async () => {
    const { openCreatureScreen } = await screen();
    let now = 0;
    vi.spyOn(Date, 'now').mockImplementation(() => now);
    try {
      const { deps, root } = world({ reads: Array.from({ length: 200 }, () => ({ ...queued, status: 'running' as const })) });
      const opened = await openCreatureScreen({ ...deps, wait: async (ms: number) => { now += ms; } });
      const field = root.querySelector('textarea')!;
      field.value = 'a round yellow body';
      field.dispatchEvent(new Event('input'));
      opened.key(press('Enter'));
      const late = 'This is taking longer than usual. The creature waits in Creatures when it\'s done.';
      await vi.waitFor(() => expect(root.querySelector('.wu-creature-step')?.textContent).toBe(late));
      expect(root.querySelector('.wu-refused')).toBeNull();
      // The line says it may still finish; the small print keeps only the price.
      expect(root.querySelector('.wu-creature-group .wu-creature-small')?.textContent).toBe('At most $0.37.');
      expect(opened.key(press('Enter'))).toBe(false);
    } finally {
      vi.restoreAllMocks();
    }
  });

  it('follows the draft already being made when an ask is refused for it, and otherwise says the hour is used up', async () => {
    const { openCreatureScreen } = await screen();
    const limited = Object.assign(new Error('creature_limit_reached'), { code: 'creature_limit_reached' });
    for (const running of [true, false]) {
      let listed: readonly CreatureDraft[] = [];
      const { deps, root } = world();
      const opened = await openCreatureScreen({ ...deps, client: { ...deps.client, ask: async () => { throw limited; }, drafts: async () => listed } });
      // Asked meanwhile from another page.
      listed = running ? [{ ...queued, status: 'running' }] : [];
      const field = root.querySelector('textarea')!;
      field.value = 'a round yellow body';
      field.dispatchEvent(new Event('input'));
      opened.key(press('Enter'));
      await settle();
      if (running) expect(root.textContent).toContain('Yellow pond wader');
      else expect(root.querySelector('.wu-creature-line.wu-refused')?.textContent).toBe('You\'ve made as many creatures as you can this hour. Try again later.');
      document.body.replaceChildren();
    }
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
