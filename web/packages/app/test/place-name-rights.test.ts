// @vitest-environment happy-dom
/**
 * Where a place's name can go: the browser's client, the control, and the two places it is drawn.
 *
 * The server states every word and every state; these hold the browser to relaying them. The
 * client must refuse a state it does not know rather than show a guess, send the notice back
 * exactly as shown, and name each refusal; the control must say every state in a sentence, send
 * the one decision a button stands for, and show what the server read back; and the detail pane
 * and the Companion's rail must draw it for a named place and for nothing else.
 */

import { describe, expect, it, vi } from 'vitest';
import type { EntityRecord, GraphSnapshot } from '@exulanica/graph-client';

import { CompanionAskClient, type CompanionAnswer } from '../src/companion-ask-api.js';
import { EvidenceCache } from '../src/evidence.js';
import {
  PlaceNameRightsClient,
  PlaceNameUnavailable,
  rightsOf,
  type PlaceNameRights,
  type PlaceNameRightsSource,
  type PlaceNameUseState,
} from '../src/place-name-rights-api.js';
import { buildCompanionChoiceRail } from '../src/ui/companion-choice-rail.js';
import { buildDetail } from '../src/ui/detail.js';
import { buildPlaceNameRights } from '../src/ui/place-name-rights.js';

const PLACE = '33333333-3333-4333-8333-333333333333';
const PERSON = '44444444-4444-4444-8444-444444444444';
const BASE = 'https://exulanica.test/api';
const NOTICE =
  'Exulanica may send the name you gave this place to an AI service outside Exulanica, at ' +
  'api.example.test, when it asks a model there to search your photographs. The model is ' +
  'vendor/model-one. This covers this place\'s name only.';

const json = (body: unknown, status = 200): Response => new Response(JSON.stringify(body), {
  status,
  headers: { 'content-type': 'application/json' },
});

/** One use exactly as `exulanica/api/routes/place_name_rights.py` writes it. */
function wireUse(state: PlaceNameUseState, overrides: Record<string, unknown> = {}) {
  return {
    use: 'embedding',
    purpose: 'search your photographs',
    notice: NOTICE,
    destination: 'https://api.example.test',
    models: [{
      model: { provider: 'hosted', role: 'embedding', model_id: 'vendor/model-one', revision: null },
      state: state === 'models_changed' ? 'allowed' : state,
    }],
    state,
    allowed: state === 'allowed',
    since: state === 'allowed' ? '2026-09-23T12:00:00+00:00' : null,
    until: state === 'allowed' ? '2026-12-22T12:00:00+00:00' : null,
    changed_at: state === 'not_allowed' ? null : '2026-09-23T12:00:00+00:00',
    ...overrides,
  };
}

function wire(state: PlaceNameUseState, name: string | null = 'Lantern House') {
  return { entity_id: PLACE, name, read_at: '2026-09-23T12:00:01+00:00', uses: [wireUse(state)] };
}

/** A source that answers from a script and records every call it was asked to make. */
function scripted(first: PlaceNameRights, after: () => Promise<PlaceNameRights>) {
  const calls: string[][] = [];
  const source: PlaceNameRightsSource = {
    load: async (entityId) => { calls.push(['load', entityId]); return first; },
    allow: async (entityId, use, notice) => { calls.push(['allow', entityId, use, notice]); return after(); },
    stop: async (entityId, use) => { calls.push(['stop', entityId, use]); return after(); },
  };
  return { source, calls };
}

const DATE = (iso: string): string => iso.slice(0, 10);

// -- the client -------------------------------------------------------------------------------

describe('the place name client', () => {
  it('renames the wire and keeps every word the server sent', async () => {
    const fetch = vi.fn(async () => json(wire('allowed')));
    const rights = await new PlaceNameRightsClient({ baseUrl: BASE, token: 't', fetch }).load(PLACE);
    expect(fetch).toHaveBeenCalledWith(`${BASE}/place-name-rights/${PLACE}`, expect.anything());
    expect(rights.name).toBe('Lantern House');
    const [use] = rights.uses;
    expect(use).toMatchObject({
      use: 'embedding', notice: NOTICE, state: 'allowed', allowed: true,
      since: '2026-09-23T12:00:00+00:00', until: '2026-12-22T12:00:00+00:00',
    });
    expect(use!.models[0]).toMatchObject({ modelId: 'vendor/model-one', state: 'allowed' });
    expect(Object.isFrozen(rights) && Object.isFrozen(use)).toBe(true);
  });

  it('refuses a state it does not know, and a use that contradicts itself', () => {
    expect(() => rightsOf({ ...wire('allowed'), uses: [wireUse('allowed', { state: 'maybe' })] }))
      .toThrow(PlaceNameUnavailable);
    expect(() => rightsOf({ ...wire('allowed'), uses: [wireUse('allowed', { allowed: false })] }))
      .toThrow(/says it is allowed/);
    expect(() => rightsOf({
      ...wire('allowed'),
      uses: [wireUse('allowed', { models: [{ model: wireUse('allowed').models[0]!.model, state: 'models_changed' }] })],
    })).toThrow(/names a whole use/);
  });

  it('sends the notice back exactly as shown, and a stop names only the use', async () => {
    const fetch = vi.fn(async () => json(wire('allowed'), 201));
    const client = new PlaceNameRightsClient({ baseUrl: BASE, token: 't', fetch });
    await client.allow(PLACE, 'embedding', NOTICE);
    await client.stop(PLACE, 'embedding');
    const bodies = fetch.mock.calls.map((call) => JSON.parse(String((call as unknown[])[1] && ((call as unknown[])[1] as RequestInit).body)));
    expect(fetch.mock.calls.map((call) => (call as unknown[])[0])).toEqual([
      `${BASE}/place-name-rights/${PLACE}/grants`,
      `${BASE}/place-name-rights/${PLACE}/withdrawals`,
    ]);
    expect(bodies).toEqual([{ use: 'embedding', notice: NOTICE }, { use: 'embedding' }]);
  });

  it.each([
    [404, 'unknown_reference', 'missing'],
    [403, 'not_authorised', 'forbidden'],
    [409, 'notice_changed', 'notice_changed'],
    [409, 'not_yours', 'not_yours'],
    [409, 'busy', 'busy'],
    [409, 'something_new', 'unreadable'],
    [500, 'integrity_failure', 'unreadable'],
  ])('names a %i %s refusal as %s', async (status, code, kind) => {
    const fetch = vi.fn(async () => json({ code, detail: 'said by the server' }, status));
    const refused = await new PlaceNameRightsClient({ baseUrl: BASE, token: 't', fetch })
      .allow(PLACE, 'embedding', NOTICE)
      .catch((error: unknown) => error);
    expect(refused).toBeInstanceOf(PlaceNameUnavailable);
    expect((refused as PlaceNameUnavailable).kind).toBe(kind);
  });
});

// -- the control ------------------------------------------------------------------------------

describe('the place name control', () => {
  const STATES: readonly PlaceNameUseState[] = [
    'allowed', 'not_allowed', 'withdrawn', 'ended', 'name_changed', 'notice_changed',
    'models_changed',
  ];

  it.each(STATES)('says what %s means, with the notice and one button', async (state) => {
    const { source } = scripted(rightsOf(wire(state)), async () => rightsOf(wire(state)));
    const control = buildPlaceNameRights(PLACE, source, { formatDate: DATE });
    await control.ready;
    const row = control.root.querySelector<HTMLElement>('.place-name-use')!;
    expect(row.dataset['state']).toBe(state);
    expect(row.querySelector('.place-name-notice')!.textContent).toBe(NOTICE);
    const sentence = row.querySelector('.place-name-state')!.textContent ?? '';
    expect(sentence.length).toBeGreaterThan(10);
    expect(sentence).toMatch(state === 'allowed' ? /can be sent/ : /not sent/);
    const buttons = row.querySelectorAll('button');
    expect(buttons).toHaveLength(1);
    expect(buttons[0]!.textContent).toBe(state === 'allowed' ? 'Stop sending' : 'Allow');
    expect(control.root.querySelector('.place-name-title')!.textContent).toContain('Lantern House');
    expect(control.root.querySelector('.place-name-status')!.textContent).toBe('');
  });

  it('allows against the exact notice shown and draws what the server read back', async () => {
    const { source, calls } = scripted(
      rightsOf(wire('not_allowed')),
      async () => rightsOf(wire('allowed')),
    );
    const control = buildPlaceNameRights(PLACE, source, { formatDate: DATE });
    await control.ready;
    control.root.querySelector<HTMLButtonElement>('.place-name-allow')!.click();
    await vi.waitFor(() => {
      expect(control.root.querySelector<HTMLElement>('.place-name-use')!.dataset['state']).toBe('allowed');
    });
    expect(calls).toEqual([['load', PLACE], ['allow', PLACE, 'embedding', NOTICE]]);
    expect(control.root.querySelector('.place-name-state')!.textContent).toContain('2026-12-22');
    expect(control.root.querySelector('.place-name-lede')!.textContent).toBe(
      'The name you gave this place can be sent for the use below, and for nothing else.',
    );
    expect(control.root.querySelector('.place-name-status')!.textContent).toMatch(/^Allowed/);
  });

  it('stops an allowed use and says so', async () => {
    const { source, calls } = scripted(
      rightsOf(wire('allowed')),
      async () => rightsOf(wire('withdrawn')),
    );
    const control = buildPlaceNameRights(PLACE, source, { formatDate: DATE });
    await control.ready;
    control.root.querySelector<HTMLButtonElement>('.place-name-stop')!.click();
    await vi.waitFor(() => {
      expect(control.root.querySelector<HTMLElement>('.place-name-use')!.dataset['state']).toBe('withdrawn');
    });
    expect(calls.at(-1)).toEqual(['stop', PLACE, 'embedding']);
    expect(control.root.querySelector('.place-name-status')!.textContent).toMatch(/^Stopped/);
  });

  it('reads the words again when they changed under the person, and records nothing', async () => {
    let reads = 0;
    const source: PlaceNameRightsSource = {
      load: async () => {
        reads += 1;
        return rightsOf(reads === 1 ? wire('not_allowed') : {
          ...wire('not_allowed'), uses: [wireUse('not_allowed', { notice: `${NOTICE} Reworded.` })],
        });
      },
      allow: async () => { throw new PlaceNameUnavailable('notice_changed', 'changed'); },
      stop: async () => { throw new Error('not asked'); },
    };
    const control = buildPlaceNameRights(PLACE, source, { formatDate: DATE });
    await control.ready;
    control.root.querySelector<HTMLButtonElement>('.place-name-allow')!.click();
    await vi.waitFor(() => {
      expect(control.root.querySelector('.place-name-notice')!.textContent).toContain('Reworded.');
    });
    expect(reads).toBe(2);
    expect(control.root.querySelector('.place-name-status')!.textContent).toMatch(/wording changed/);
    expect(control.root.querySelector<HTMLButtonElement>('.place-name-allow')!.disabled).toBe(false);
  });

  it('keeps the buttons as they were and says why when a decision is refused', async () => {
    const source: PlaceNameRightsSource = {
      load: async () => rightsOf(wire('not_allowed')),
      allow: async () => { throw new PlaceNameUnavailable('not_yours', 'refused'); },
      stop: async () => { throw new Error('not asked'); },
    };
    const control = buildPlaceNameRights(PLACE, source, { formatDate: DATE });
    await control.ready;
    control.root.querySelector<HTMLButtonElement>('.place-name-allow')!.click();
    await vi.waitFor(() => {
      expect(control.root.querySelector('.place-name-status')!.textContent).toMatch(/named this place/);
    });
    expect(control.root.querySelector<HTMLButtonElement>('.place-name-allow')!.disabled).toBe(false);
  });

  it('offers nothing to allow for a place with no name', async () => {
    const { source } = scripted(rightsOf(wire('name_changed', null)), async () => { throw new Error('not asked'); });
    const control = buildPlaceNameRights(PLACE, source, { formatDate: DATE });
    await control.ready;
    expect(control.root.querySelector('.place-name-title')!.textContent).toMatch(/no name/);
    expect(control.root.querySelector<HTMLButtonElement>('.place-name-allow')!.disabled).toBe(true);
  });

  it('draws nothing for an id that is not a place when asked to stay quiet, and says so otherwise', async () => {
    const source: PlaceNameRightsSource = {
      load: async () => { throw new PlaceNameUnavailable('missing', 'no such place'); },
      allow: async () => { throw new Error('not asked'); },
      stop: async () => { throw new Error('not asked'); },
    };
    const quiet = buildPlaceNameRights(PERSON, source, { quietWhenMissing: true });
    await quiet.ready;
    expect(quiet.root.hidden).toBe(true);
    expect(quiet.root.textContent).toBe('');
    const loud = buildPlaceNameRights(PERSON, source);
    await loud.ready;
    expect(loud.root.hidden).toBe(false);
    expect(loud.root.textContent).toMatch(/not in your library/);
  });
});

// -- where it is drawn ------------------------------------------------------------------------

const NO_EVIDENCE = new EvidenceCache({ evidenceBytes: () => Promise.reject(new Error('none')) });
const HANDLERS = {
  onName: () => undefined,
  onEvidenceOpened: () => undefined,
  onLocate: () => undefined,
  onClose: () => undefined,
};

function entity(overrides: Partial<EntityRecord>): EntityRecord {
  return {
    entityId: PLACE,
    kind: 'place',
    displayName: 'Lantern House',
    status: 'confirmed',
    occurrenceCount: 1,
    islandIds: ['isl'],
    firstSeenMs: null,
    lastSeenMs: null,
    confidence: 'high',
    openQuestionCount: 0,
    citingAnswerCount: 0,
    assertions: [],
    relations: [],
    contradictions: [],
    history: [],
    mergedInto: null,
    ...overrides,
  } as EntityRecord;
}

function snapshot(record: EntityRecord): GraphSnapshot {
  return {
    stateVersion: 1,
    entities: [record],
    occurrences: [],
    islands: [],
    matchProposals: [],
    neverSame: [],
    deletedEntityIds: [],
  } as unknown as GraphSnapshot;
}

describe('the detail pane', () => {
  it('shows where a named place can go, directly under its name', async () => {
    const { source, calls } = scripted(rightsOf(wire('not_allowed')), async () => rightsOf(wire('allowed')));
    const detail = buildDetail(NO_EVIDENCE, HANDLERS, { placeNames: source });
    const place = entity({});
    detail.showEntity(snapshot(place), place);
    const control = detail.root.querySelector('.place-name-rights');
    expect(control).not.toBeNull();
    expect(control!.previousElementSibling!.classList.contains('detail-identity')).toBe(true);
    await vi.waitFor(() => expect(calls).toEqual([['load', PLACE]]));
  });

  it.each([
    ['a person', { kind: 'person' as const, entityId: PERSON }],
    ['an unnamed place', { displayName: null }],
  ])('shows nothing for %s', (_label, overrides) => {
    const { source, calls } = scripted(rightsOf(wire('not_allowed')), async () => rightsOf(wire('allowed')));
    const detail = buildDetail(NO_EVIDENCE, HANDLERS, { placeNames: source });
    const record = entity(overrides);
    detail.showEntity(snapshot(record), record);
    expect(detail.root.querySelector('.place-name-rights')).toBeNull();
    expect(calls).toEqual([]);
  });

  it('shows nothing without a source, as in the read-only preview', () => {
    const detail = buildDetail(NO_EVIDENCE, HANDLERS, { preview: true });
    const place = entity({});
    detail.showEntity(snapshot(place), place);
    expect(detail.root.querySelector('.place-name-rights')).toBeNull();
  });
});

describe('a Companion answer', () => {
  it('lists each place it is about once, from placeholders, the plan and content rows', async () => {
    const other = '55555555-5555-4555-8555-555555555555';
    const fetch = vi.fn(async () => json({
      answer: { clauses: [{ text: 'The sign at [place A] reads LANTERN.', type: 'historical', citations: [], value_refs: [] }] },
      plan: { intent: 'captures', place: { ids: [PLACE, other] } },
      citations: {},
      abstained: null,
      deterministic: false,
      repaired: false,
      execution: { prompt_version: 'selection-5', calls: [] },
      names: { '[place A]': PLACE, '[person A]': PERSON },
    }));
    const answer = await new CompanionAskClient({ baseUrl: BASE, token: 't', worldId: 'world:test', fetch })
      .ask('What does the sign say?');
    expect(answer.places).toEqual([PLACE, other]);
  });

  it('draws the control for each place in the rail, and nothing without a source', async () => {
    const { source, calls } = scripted(rightsOf(wire('not_allowed')), async () => rightsOf(wire('allowed')));
    const answer = {
      question: 'q',
      clauses: [],
      text: '',
      abstained: null,
      deterministic: true,
      repaired: false,
      evidence: [],
      places: [PLACE],
      provenance: { composed: 'search', servedModel: null, plannedBy: null, latencyMs: 0, usedFallback: false },
      promptVersion: 'selection-5',
      calls: [],
    } as CompanionAnswer;
    const handlers = { onSelect: () => undefined, onSubmit: () => undefined, onSay: () => undefined, onEvidence: () => undefined };
    const rail = buildCompanionChoiceRail(handlers, { placeNames: source });
    rail.renderAnswer(answer, () => undefined);
    expect(rail.root.querySelectorAll('.place-name-rights')).toHaveLength(1);
    await vi.waitFor(() => expect(calls).toEqual([['load', PLACE]]));

    const bare = buildCompanionChoiceRail(handlers);
    bare.renderAnswer(answer, () => undefined);
    expect(bare.root.querySelector('.place-name-rights')).toBeNull();
  });
});
