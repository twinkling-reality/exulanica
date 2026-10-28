// @vitest-environment happy-dom
// Making a creature where it will stand (tools/previews/world-workspace/world-creature.ts): the stand read is
// asked at the point 8 m ahead, the line under the field says the model's price and time, the words are made
// into a draft followed until it is kept, and the kept kind is then held at the stand by build mode, whose own keys
// place it. The server's answers are written down here; no model is asked and no 3D view is drawn.
import { readFileSync } from 'node:fs';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { CreatureDraft, CreatureOffer, SocietyStand } from '../src/creature-drafts-api.js';
import type { ReferenceNote, ReferenceRequest } from '../src/references-api.js';

const screen = async () => import('../../../../tools/previews/world-workspace/' + 'world-creature.ts');
const ui = async () => import('../../../../tools/previews/world-workspace/' + 'world-ui-creature.ts');

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
  const calls = { stand: [] as unknown[], ask: [] as string[], hold: [] as unknown[], closed: 0, released: 0, marked: [] as (SocietyStand | null)[], creatures: [] as string[] };
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
      creatures: (sha256: string) => { calls.creatures.push(sha256); },
      release: () => { calls.released += 1; },
      wait: async () => {},
    },
  };
}

const press = (key: string): KeyboardEvent => new KeyboardEvent('keydown', { key, cancelable: true });
const settle = async (): Promise<void> => { for (let turn = 0; turn < 20; turn += 1) await Promise.resolve(); };

afterEach(() => { document.body.replaceChildren(); });

describe('making a creature where it will stand', () => {
  it('marks the stand the society would take it in at, 8 m ahead, under Create\'s composer with its price and no model named', async () => {
    const { openCreatureScreen, STAND_AHEAD_MM } = await screen();
    const { deps, calls, root } = world();
    await openCreatureScreen(deps);
    expect(STAND_AHEAD_MM).toBe(8000);
    expect(calls.stand).toEqual([{ versionId: 'version-1', worldId: 'world-1', at: { xMm: 9000, zMm: 0 } }]);
    // The ring is laid at the stand, and laid there again each frame while it shows.
    expect(calls.marked.length).toBeGreaterThan(0);
    expect(calls.marked.every((marked) => marked === stand)).toBe(true);
    expect(root.textContent).toContain('The creature appears here');
    // "Make a creature" over Create's composer, its price in the foot; the model is named on the made card alone.
    expect(root.querySelector('.wu-creature-field .wu-creature-heading')?.textContent).toBe('Make a creature');
    expect(root.querySelector('.wu-creature-field .wu-composer-price')?.textContent).toBe('up to $0.38');
    expect(root.querySelector('.wu-creature-field textarea')?.getAttribute('placeholder')).toBe('What does the creature look like?');
    expect(root.textContent).not.toContain('Nemotron');
  });

  it('with no stand open marks nothing, and with no price shows none', async () => {
    const { openCreatureScreen } = await screen();
    const { deps, calls, root } = world({ stand: null, offer: { ...offer, priceUsdAtMost: null } });
    await openCreatureScreen(deps);
    expect(calls.marked).toEqual([null]);
    expect(root.textContent).not.toContain('The creature appears here');
    expect(root.querySelector<HTMLElement>('.wu-creature-field .wu-composer-price')?.hidden).toBe(true);
  });

  it('dims Make until there are words to send, and a press of Make makes as Enter does', async () => {
    const { openCreatureScreen } = await screen();
    const { deps, calls, root } = world();
    await openCreatureScreen(deps);
    const pill = root.querySelector<HTMLButtonElement>('.wu-creature-field .wu-composer-pill')!;
    expect(pill.textContent).toBe('Make↵');
    expect(pill.getAttribute('aria-disabled')).toBe('true');
    const field = root.querySelector('textarea')!;
    field.value = '  ';
    field.dispatchEvent(new Event('input'));
    expect(pill.getAttribute('aria-disabled')).toBe('true');
    field.value = 'a round yellow body';
    field.dispatchEvent(new Event('input'));
    expect(pill.getAttribute('aria-disabled')).toBeNull();
    pill.click();
    await settle();
    expect(calls.ask).toEqual(['a round yellow body']);
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
    // The made card keeps only its name, how it was made, the words, Place, and who made it for how much (ROOT's sweep).
    const card = root.querySelector('.wu-creature-made')!;
    const parts = [...card.querySelectorAll('.wu-creature-title, .wu-creature-from, .wu-creature-quote, [aria-keyshortcuts], .wu-creature-small')].map((part) => part.textContent);
    expect(parts).toEqual([
      'Yellow pond wader', 'Made from your words', '“a round yellow body with a pale flat bill on two short legs”', 'Place',
      'Made by Nemotron 3 Super 120B · spent $0.0042',
    ]);
    expect(card.textContent).toBe(parts.join(''));
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

  it('says nothing on the made card of a sketch or of where it is kept, its made look made or not', async () => {
    const { openCreatureScreen } = await screen();
    for (const lookStatus of ['queued', 'made', null]) {
      const { deps, root } = world({ reads: [{ ...kept, lookStatus }] });
      const opened = await openCreatureScreen(deps);
      const field = root.querySelector('textarea')!;
      field.value = 'a round yellow body';
      field.dispatchEvent(new Event('input'));
      opened.key(press('Enter'));
      await settle();
      expect(root.querySelector('.wu-creature-made .wu-creature-title')?.textContent).toBe('Yellow pond wader');
      expect(root.textContent).not.toContain('sketch');
      expect(root.textContent).not.toContain('kept in Creatures');
      document.body.replaceChildren();
    }
  });

  it('says under the steps what the making has spent so far of the most it may, as Create does, from each read', async () => {
    const { openCreatureScreen } = await screen();
    const line = (root: HTMLElement): string | null => {
      const small = root.querySelector<HTMLElement>('.wu-creature-group .wu-creature-small');
      return small === null || small.hidden ? null : small.textContent;
    };
    // What the draft's attempts settled at, and what its call under way holds, not known yet (Create's N10).
    const { deps, root } = world({ reads: [
      { ...queued, status: 'running', heldUsd: '0.37355520' },
      { ...queued, status: 'running', spentUsd: '0.00420000', heldUsd: '0.00000000' },
      kept,
    ] });
    const seen: (string | null)[] = [];
    const opened = await openCreatureScreen({ ...deps, wait: async () => { seen.push(line(root)); } });
    const field = root.querySelector('textarea')!;
    field.value = 'a round yellow body';
    field.dispatchEvent(new Event('input'));
    opened.key(press('Enter'));
    await settle();
    expect(seen).toEqual(['Spent $0 of up to $0.38', 'Spent $0 of up to $0.38, and up to $0.37 not known yet', 'Spent $0.0042 of up to $0.38']);
    expect(root.textContent).not.toContain('You can leave this page');
    expect(root.textContent).not.toContain('At most');
    document.body.replaceChildren();
    // A read that states no spend says none: no figure is ever made up.
    const silent = world({ reads: [{ ...queued, status: 'running', spentUsd: null }, kept] });
    const unread: (string | null)[] = [];
    const again = await openCreatureScreen({
      ...silent.deps, client: { ...silent.deps.client, ask: async () => ({ ...queued, spentUsd: null }) }, wait: async () => { unread.push(line(silent.root)); },
    });
    const words = silent.root.querySelector('textarea')!;
    words.value = 'a round yellow body';
    words.dispatchEvent(new Event('input'));
    again.key(press('Enter'));
    await settle();
    expect(unread).toEqual([null, null]);
  });

  it('has no stand where the stand is out of view: the made creature waits in Creatures, the card says how to place it, and Back goes there', async () => {
    const { openCreatureScreen } = await screen();
    const { CREATURE_WORDS } = await ui();
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
    expect(root.querySelector('[aria-keyshortcuts="Enter"]')).toBeNull();
    expect(calls.hold).toEqual([]);
    // Never a card with no next step (rehearsal run 7): where the creature is, how to place it, and Back takes the
    // person to it in Creatures; Esc does the same.
    const card = root.querySelector('.wu-creature-made')!;
    expect(card.textContent).toContain(CREATURE_WORDS.nowhereToStand);
    const back = card.querySelector<HTMLButtonElement>('button[aria-keyshortcuts="Escape"]')!;
    expect(back.textContent).toContain(CREATURE_WORDS.back);
    back.click();
    expect(calls.closed).toBe(1);
    expect(calls.creatures).toEqual([kept.kind!.sha256]);
    expect(root.querySelector('.wu-creature-made')).toBeNull();
    const again = world({ at: { x: 1020, y: 500 } });
    const second = await openCreatureScreen(again.deps);
    const words = again.root.querySelector('textarea')!;
    words.value = 'a round yellow body';
    words.dispatchEvent(new Event('input'));
    second.key(press('Enter'));
    await settle();
    second.key(press('Escape'));
    expect(again.calls.closed).toBe(1);
    expect(again.calls.creatures).toEqual([kept.kind!.sha256]);
  });

  it('stands it at the ground point ahead in a world nobody lives in yet, and nowhere where the stand read fails otherwise', async () => {
    const { openCreatureScreen } = await screen();
    const refused = (status: number, code: string): Error => Object.assign(new Error(code), { status, code });
    // A version with no society answers the stand read 404 unknown_reference (docs/synthetic-society-contract.md).
    for (const [refusal, ground] of [[refused(404, 'unknown_reference'), true], [refused(424, 'unavailable_society_input'), false], [refused(500, 'internal'), false]] as const) {
      const { deps, calls, root } = world();
      const opened = await openCreatureScreen({ ...deps, client: { ...deps.client, stand: async () => { throw refusal; } } });
      expect(root.textContent?.includes('The creature appears here')).toBe(ground);
      const field = root.querySelector('textarea')!;
      field.value = 'a round yellow body';
      field.dispatchEvent(new Event('input'));
      opened.key(press('Enter'));
      await settle();
      if (ground) {
        // Held where the tray would place it, 8 m ahead, for build mode's own Place.
        expect(calls.marked[0]).toEqual({ positionMm: [9000, 0] });
        expect(calls.hold).toEqual([{ kind: { source: 'workspace', sha256: 'a'.repeat(64) }, at: { xMm: 9000, zMm: 0 } }]);
        expect(root.querySelector('.wu-creature-made [aria-keyshortcuts="Enter"]')?.textContent).toBe('Place');
      } else {
        expect(calls.hold).toEqual([]);
        expect(root.querySelector('.wu-creature-made')?.textContent).toContain('There is no open ground ahead');
      }
      document.body.replaceChildren();
    }
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
      // Nothing carries on at the server, so the live spend goes; nothing was spent, so no spend.
      expect(root.textContent).not.toContain('of up to');
      expect(root.textContent).not.toContain('Spent');
      expect(root.querySelector('.wu-creature-group [aria-keyshortcuts="Enter"]')?.textContent ?? null).toBe(retry ? 'Try again' : null);
      // Enter tries again only where Try again shows: back to the field, the words kept.
      expect(opened.key(press('Enter'))).toBe(retry);
      expect(root.querySelector('.wu-creature-group') === null).toBe(retry);
      if (retry) expect(root.querySelector('textarea')?.value).toBe('a round yellow body');
      document.body.replaceChildren();
    }
  });

  it('ends the making in its own words, with Try again, where the draft can no longer be read: a read refused, or one that never answers', async () => {
    const { openCreatureScreen } = await screen();
    vi.useFakeTimers();
    try {
      for (const read of [
        // The read throws, as the transport does for a refused read or an answer the page cannot parse.
        () => Promise.reject(new TypeError('The server returned an invalid creature notes spend.')),
        // The read never answers, as one held back forever does.
        () => new Promise<CreatureDraft>(() => {}),
      ]) {
        const { deps, calls, root } = world();
        const reads = [{ ...queued, status: 'running' } as CreatureDraft];
        const opened = await openCreatureScreen({ ...deps, client: { ...deps.client, draft: async () => reads.shift() ?? read() } });
        const field = root.querySelector('textarea')!;
        field.value = 'a round yellow body';
        field.dispatchEvent(new Event('input'));
        opened.key(press('Enter'));
        await vi.advanceTimersByTimeAsync(60_000);
        // Not left on its making step: it says it cannot tell how the making went, where a made creature would be,
        // and offers Try again (Esc goes back to building, as from any step).
        expect(root.querySelector('.wu-creature-step.wu-refused')?.textContent)
          .toBe('This page can\'t tell how the making went. If the creature was made, it waits in Creatures.');
        expect(root.textContent).not.toContain('Making the creature');
        expect(root.querySelector('.wu-creature-group [aria-keyshortcuts="Enter"]')?.textContent).toBe('Try again');
        expect(opened.key(press('Enter'))).toBe(true);
        expect(root.querySelector('textarea')?.value).toBe('a round yellow body');
        expect(calls.ask).toEqual(['a round yellow body']);
        expect(opened.key(press('Escape'))).toBe(true);
        expect(calls.closed).toBe(1);
        document.body.replaceChildren();
      }
    } finally {
      vi.useRealTimers();
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
      // The line says it may still finish; the small print keeps the spend last read.
      expect(root.querySelector('.wu-creature-group .wu-creature-small')?.textContent).toBe('Spent $0 of up to $0.38');
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
      else expect(root.querySelector('.wu-creature-field .wu-composer-why')?.textContent).toBe('You\'ve made as many creatures as you can this hour. Try again later.');
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
      expect(refused.root.querySelector('.wu-creature-field .wu-composer-why')?.textContent).toBe(words);
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

describe('the making group beside the stand', () => {
  it('takes the left half of the view beside a stand right of the middle, and stays right otherwise', async () => {
    const { openCreatureScreen } = await screen();
    // happy-dom's window is 1024 wide: a stand at 700 is right of the middle, one at 512 is not.
    for (const [x, left] of [[700, true], [512, false]] as const) {
      const { deps, root } = world({ at: { x, y: 500 }, reads: [{ ...queued, status: 'running' }, kept] });
      let groupLeft: boolean | null = null;
      const client = { ...deps.client, draft: async () => { groupLeft ??= root.querySelector('.wu-creature-group')?.classList.contains('wu-creature-left') ?? null; return deps.client.draft(); } };
      const opened = await openCreatureScreen({ ...deps, client });
      const field = root.querySelector('textarea')!;
      field.value = 'a round yellow body';
      field.dispatchEvent(new Event('input'));
      opened.key(press('Enter'));
      await settle();
      expect(groupLeft).toBe(left);
      expect(root.querySelector('.wu-creature-made')!.classList.contains('wu-creature-left')).toBe(left);
      document.body.replaceChildren();
    }
  });
});

describe('the creature panel inside the window', () => {
  const frame = readFileSync(`${process.cwd()}/../tools/previews/world-workspace/world-page-frame.css`, 'utf8');
  const creature = readFileSync(`${process.cwd()}/../tools/previews/world-workspace/world-ui-creature.css`, 'utf8');
  /** `css`'s rules, each with the media query it stands in (these sheets nest one deep), their comments left out. */
  const rules = (css: string): { readonly media: string | null; readonly selector: string; readonly body: string }[] => {
    const found: { readonly media: string | null; readonly selector: string; readonly body: string }[] = [];
    const parts = css.replace(/\/\*[\s\S]*?\*\//g, '').split(/([{}])/);
    let media: string | null = null, selector: string | null = null;
    for (let at = 0; at < parts.length; at += 1) {
      const before = (parts[at - 1] ?? '').trim();
      if (parts[at] === '{' && before.startsWith('@media')) media = before.slice('@media'.length).trim();
      else if (parts[at] === '{') selector = before;
      else if (parts[at] === '}' && selector !== null) { found.push({ media, selector, body: before }); selector = null; }
      else if (parts[at] === '}') media = null;
    }
    return found;
  };
  /** Whether a query of max-width and max-height conditions, a comma between either, holds in a `width` by `height` window. */
  const holds = (media: string | null, width: number, height: number): boolean => media === null || media.split(',').some((query) => {
    const sides = [...query.matchAll(/\(max-(width|height):\s*(\d+)px\)/g)];
    return sides.length > 0 && sides.every(([, side, px]) => (side === 'width' ? width : height) <= Number(px));
  });
  /** What `property` comes to in `selector`'s own rules in a `width` by `height` window: the last that sets it where its query holds. */
  const value = (css: string, selector: string, property: string, width: number, height: number): string | undefined => {
    let found: string | undefined;
    for (const rule of rules(css).filter((one) => one.selector === selector && holds(one.media, width, height))) {
      for (const declaration of rule.body.split(';')) {
        const [name, ...rest] = declaration.split(':');
        if (name?.trim() === property) found = rest.join(':').trim();
      }
    }
    return found;
  };

  it("stands within the shared frame's margins at every window size, by the frame's own numbers (800x600 ran past the right edge)", () => {
    for (const [width, height] of [[1920, 1080], [1700, 900], [1699, 899], [1440, 600], [1366, 768], [1280, 720], [1279, 699], [800, 600]] as const) {
      const margins = {
        side: value(frame, '.wu-frame', 'padding', width, height)?.split(' ')[1],
        top: value(frame, '.wu-frame-head', 'padding-top', width, height),
        bottom: value(frame, '.wu-frame', 'grid-template-rows', width, height)?.split(' ').at(-1),
      };
      for (const margin of Object.values(margins)) expect(margin).toMatch(/^\d+px$/);
      expect({
        side: value(creature, '.wu-creature-layer', '--frame-side', width, height),
        top: value(creature, '.wu-creature-layer', '--frame-top', width, height),
        bottom: value(creature, '.wu-creature-layer', '--frame-bottom', width, height),
      }, `${width}x${height}`).toEqual(margins);
    }
    // The field's width, the groups' width and place, and their words' height are each held inside those margins.
    const rule = (selector: string, property: string): string | undefined => value(creature, selector, property, 1920, 1080);
    expect(rule('.wu-creature-field', 'width')).toMatch(/^min\(.+, calc\(100vw - 2 \* var\(--frame-side\)\)\)$/);
    expect(rule('.wu-creature-group', '--group-width')).toMatch(/^min\(.+, calc\(100vw - 2 \* var\(--frame-side\)\)\)$/);
    expect(rule('.wu-creature-group', 'width')).toBe('var(--group-width)');
    for (const selector of ['.wu-creature-group', '.wu-creature-group.wu-creature-left']) {
      expect(rule(selector, 'left')).toMatch(/^clamp\(var\(--frame-side\), .+, calc\(100vw - var\(--frame-side\) - var\(--group-width\)\)\)$/);
    }
    expect(rule('.wu-creature-body', 'max-height')).toMatch(/^calc\(100vh - .+ - var\(--frame-bottom\)\)$/);
    expect(rule('.wu-creature-noted .wu-creature-body', 'max-height')).toMatch(/^calc\(100vh - .+ - var\(--frame-top\)\)$/);
  });

  it("keeps the making group's and the made card's words in a part that scrolls with the frame's fades and track where they take more room than the window leaves", async () => {
    const { CREATURE_WORDS, madeGroup, makingGroup, placeRow } = await ui();
    // happy-dom lays nothing out: a part is given the height its words take and the room it has.
    const sized = (part: HTMLElement, words: number, room: number): void => {
      Object.defineProperty(part, 'scrollHeight', { configurable: true, value: words });
      Object.defineProperty(part, 'clientHeight', { configurable: true, value: room });
    };
    const making = makingGroup({ words: 'a round yellow body' });
    const group: HTMLElement = making.root;
    document.body.append(group);
    const body = group.querySelector<HTMLElement>('.wu-creature-group > .wu-frame-col > .wu-creature-body.wu-frame-scroll')!;
    const track = group.querySelector<HTMLElement>('.wu-frame-col > .wu-frame-track')!;
    expect(body.querySelector('.wu-creature-title')?.textContent).toBe(CREATURE_WORDS.making);
    // Read again as its steps come.
    sized(body, 900, 400);
    making.passed('Searching the web', '0:05');
    await vi.waitFor(() => expect(body.dataset.below).toBe('true'));
    expect(track.hidden).toBe(false);
    sized(body, 400, 400);
    making.step('Making the creature', false, '0:14');
    await vi.waitFor(() => expect(body.dataset.below).toBe('false'));
    expect(track.hidden).toBe(true);
    // The made card's words too, read again as its Place row changes.
    const made: HTMLElement = madeGroup({ label: 'yellow pond wader', words: 'a round yellow body', modelName: null, spentUsd: null, placeable: true });
    document.body.append(made);
    const madeBody = made.querySelector<HTMLElement>('.wu-creature-made > .wu-frame-col > .wu-creature-body.wu-frame-scroll')!;
    expect(madeBody.querySelector('.wu-creature-title')?.textContent).toBe('Yellow pond wader');
    sized(madeBody, 600, 400);
    placeRow(made, { placing: false, refused: 'It cannot stand here: something is in the way.' });
    await vi.waitFor(() => expect(madeBody.dataset.below).toBe('true'));
  });
});

describe('web notes before a creature is made', () => {
  const notesOffer: CreatureOffer = Object.freeze({ ...offer, priceUsdAtMost: '0.10000000', notes: { offered: true, code: null, searchesAtMost: 3, maximumUsd: '0.02000000' } });
  const step = (name: string, state: string) => ({ step: name, state, reason: null, facts: {} });
  const request = (status: string, steps: ReturnType<typeof step>[], notes: ReferenceNote[] = []): ReferenceRequest => Object.freeze({
    referenceId: 'ref-1', purpose: 'things', web: true, status, steps, notes, missed: [], failure: null,
    searches: notes.length ? [1, 2, 3].map(() => ({ source: 'tavily_search', outcome: 'sent', resultCount: 5, credits: 1, sentAt: '2026-10-26T15:00:00+00:00' })) : [],
    bundleSha256: null, cancelRequested: false, createdAt: '2026-10-26T15:00:00+00:00', finishedAt: null,
  });
  const stopped: CreatureDraft = Object.freeze({ ...queued, status: 'failed', failure: 'expired' });
  const seven: ReferenceNote[] = ['anatomy', 'anatomy', 'materials_and_colour', 'scale', 'part_layout', 'anatomy', 'scale']
    .map((aspect, at) => ({ aspect, text: `Note ${at + 1} on a round body`, basis: 'web_description' }));

  /** A world whose offer offers notes, with a notes client answering `reads` in turn after the request's own answer. */
  function noted(reads: ReferenceRequest[], draft: CreatureDraft = kept) {
    const made = world({ offer: notesOffer, reads: [draft] });
    const asked: { words: string; referenceId: string | null }[] = [], requested: unknown[] = [], cancelled: string[] = [];
    const deps = {
      ...made.deps,
      client: { ...made.deps.client, ask: async (words: string, referenceId: string | null = null) => { asked.push({ words, referenceId }); return queued; }, draft: async () => draft },
      notes: {
        request: async (body: unknown) => { requested.push(body); return request('queued', [step('plan', 'waiting'), step('search', 'waiting'), step('read', 'waiting'), step('bundle', 'waiting')]); },
        read: async () => reads.shift() ?? reads.at(-1)!,
        cancel: async (id: string) => { cancelled.push(id); return request('cancelled', []); },
      },
      key: () => 'key-1',
    };
    return { ...made, deps, asked, requested, cancelled };
  }
  const type = (root: HTMLElement, words: string): void => {
    const field = root.querySelector('textarea')!;
    field.value = words;
    field.dispatchEvent(new Event('input'));
  };
  const tick = (root: HTMLElement): void => { root.querySelector<HTMLButtonElement>('.wu-creature-field .wu-composer-chip')!.click(); };

  it('offers "Search the web" only where notes are offered here, its details on hover, and pressed, prices the whole most', async () => {
    const { openCreatureScreen } = await screen();
    const without = world();
    await openCreatureScreen(without.deps);
    expect(without.root.querySelector('.wu-composer-chip')).toBeNull();
    const { deps, root } = noted([]);
    await openCreatureScreen(deps);
    const chip = root.querySelector<HTMLButtonElement>('.wu-creature-field .wu-composer-chip')!;
    expect(chip.textContent).toBe('Search the web');
    expect(chip.getAttribute('aria-pressed')).toBe('false');
    expect(root.querySelector(`#${chip.getAttribute('aria-describedby')}`)?.textContent)
      .toBe('Looks up what such a creature looks like before it is made: up to 3 searches with Tavily, which keeps them. Adds at most $0.02.');
    const price = () => root.querySelector('.wu-creature-field .wu-composer-price')?.textContent;
    expect(price()).toBe('up to $0.10');
    tick(root);
    expect(chip.getAttribute('aria-pressed')).toBe('true');
    expect(price()).toBe('up to $0.12');
    // Nothing of the old box: no sentence on where the words go under the field, no model named.
    expect(root.textContent).not.toContain('Read the web first');
    expect(root.textContent).not.toContain('Nemotron');
  });

  it('ticked, asks for notes on the words, shows them, and asks the drafter with them; the spend counts the notes', async () => {
    const { openCreatureScreen } = await screen();
    const done = request('complete', [step('plan', 'done'), step('search', 'done'), step('read', 'done'), step('bundle', 'done')], seven);
    const { deps, root, asked, requested } = noted(
      [request('running', [step('plan', 'running'), step('search', 'waiting'), step('read', 'waiting'), step('bundle', 'waiting')]), done],
      { ...kept, spentUsd: '0.00420000', references: { referenceId: 'ref-1', state: 'used', code: null, notes: 7, searches: 3, spentUsd: '0.00110000' } },
    );
    // While it is made, the live spend counts the notes' most as not known yet until a read states what they spent.
    const seen: (string | null)[] = [];
    const small = (): string | null => { const line = root.querySelector<HTMLElement>('.wu-creature-group .wu-creature-small'); return line === null || line.hidden ? null : line.textContent; };
    const opened = await openCreatureScreen({ ...deps, wait: async () => { seen.push(small()); } });
    type(root, '  a little yellow robot duck ');
    tick(root);
    opened.key(press('Enter'));
    await settle();
    expect(seen).toEqual([null, null, 'Spent $0 of up to $0.12, and up to $0.02 not known yet']);
    expect(requested).toEqual([{ purpose: 'things', description: 'a little yellow robot duck', idempotencyKey: 'key-1' }]);
    expect(asked).toEqual([{ words: 'a little yellow robot duck', referenceId: 'ref-1' }]);
    expect(root.textContent).toContain('Made from your words and 7 notes from the web');
    expect(root.querySelector('.wu-creature-made .wu-creature-small')?.textContent).toBe('Made by Nemotron 3 Super 120B · spent $0.0053');
  });

  it('shows at most four notes in the making group, counts the rest, and says what wrote them', async () => {
    const { openCreatureScreen } = await screen();
    const done = request('partial', [step('plan', 'done'), step('search', 'done'), step('read', 'done'), step('bundle', 'done')], seven);
    // The draft ends with nothing made, so the making group with its notes stays to be read.
    const { deps, root } = noted([done], stopped);
    const opened = await openCreatureScreen(deps);
    type(root, 'a little yellow robot duck');
    tick(root);
    opened.key(press('Enter'));
    await settle();
    const notes = root.querySelector('.wu-creature-notes')!;
    expect(notes.textContent).toContain('From the web');
    expect(notes.textContent).toContain('Anatomy · Note 1 on a round body');
    expect(notes.textContent).toContain('Note 4 on a round body');
    expect(notes.textContent).not.toContain('Note 5 on a round body');
    expect(notes.textContent).toContain('And 3 more notes.');
    expect(notes.textContent).toContain('A model wrote these from 3 web searches. They help make the creature and are never facts about it.');
  });

  it('makes it from the words alone, and says why, where the notes fail or find nothing', async () => {
    const { openCreatureScreen } = await screen();
    for (const [ended, words] of [
      [request('failed', [step('plan', 'missed'), step('search', 'missed'), step('read', 'missed'), step('bundle', 'done')]), 'The web notes could not be made, so it is made from your words alone.'],
      [request('partial', [step('plan', 'done'), step('search', 'done'), step('read', 'done'), step('bundle', 'done')]), 'The searches found nothing to use, so it is made from your words alone.'],
    ] as const) {
      const { deps, root, asked } = noted([ended], stopped);
      const opened = await openCreatureScreen(deps);
      type(root, 'a little yellow robot duck');
      tick(root);
      opened.key(press('Enter'));
      await settle();
      expect(asked).toEqual([{ words: 'a little yellow robot duck', referenceId: null }]);
      expect(root.querySelector('.wu-creature-notes')!.textContent).toBe(words);
      document.body.replaceChildren();
    }
  });

  it('says no spend at all where the notes were asked for and their spend is not served', async () => {
    const { openCreatureScreen } = await screen();
    const done = request('complete', [step('plan', 'done'), step('search', 'done'), step('read', 'done'), step('bundle', 'done')], seven);
    const { deps, root } = noted([done], { ...kept, spentUsd: '0.00420000', references: { referenceId: 'ref-1', state: 'used', code: null, notes: 7, searches: null, spentUsd: null } });
    const opened = await openCreatureScreen(deps);
    type(root, 'a little yellow robot duck');
    tick(root);
    opened.key(press('Enter'));
    await settle();
    expect(root.querySelector('.wu-creature-made .wu-creature-small')?.textContent).toBe('Made by Nemotron 3 Super 120B');
    expect(root.textContent).not.toContain('spent');
  });
});
