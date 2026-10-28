import { describe, expect, it, vi } from 'vitest';
import { CreatureDraftsClient, draftEnded, parseCreatureDraft, parseCreatureOffer, parseSocietyStand } from '../src/creature-drafts-api.js';

/*
 * The creature routes' answers as exulanica/api/routes/thing_creatures.py writes them, written here
 * by hand: the offer before anyone types, a kept draft naming its kind by digest, and a refused one
 * carrying its code's fixed sentence.
 */

const offer = {
  profile: 'exulanica.creature-offer/v1',
  offered: false,
  code: 'creatures_not_run_here',
  timing: { record: 'docs/evaluation/2026-10-07-creature-drafter-timings-2.json', call_p50_seconds: 18, call_longest_seconds: 25, call_timeout_seconds: 50 },
  codes: { refused: ['creature_movement_unbuilt'], failed: ['expired'], cancelled: ['workspace_deleted'] },
};

const kept = {
  profile: 'exulanica.creature-draft/v1',
  draft_id: '0f9d1b7e-0000-4000-8000-000000000001',
  status: 'kept',
  label: 'hill walker',
  kind: { kind: 'hill_walker', version: 1, sha256: 'a'.repeat(64) },
  look: { look: 'hill_walker_sketch', version: 1, sha256: 'b'.repeat(64) },
  model: { model_id: 'nvidia/nemotron-3-super-120b-a12b', name: 'Nemotron 3 Super' },
  refusal: null,
  failure: null,
  created_at: '2026-10-09T20:00:00+00:00',
  started_at: '2026-10-09T20:00:01+00:00',
  finished_at: '2026-10-09T20:00:18+00:00',
};

describe('a creature from words, as the server answers it', () => {
  it('reads the offer: whether a world may ask here, why not by code, and how long a draft takes', () => {
    expect(parseCreatureOffer(offer)).toEqual({
      offered: false, code: 'creatures_not_run_here', timing: { typicalSeconds: 18, longestSeconds: 25, timeoutSeconds: 50 },
      model: null, priceUsdAtMost: null, notes: null,
    });
  });

  it('reads the web notes a draft may be asked with, and asks with a reference only when one is given', async () => {
    const noted = parseCreatureOffer({ ...offer, notes: { offered: true, code: null, searches_at_most: 3, maximum_usd: '0.02000000' } });
    expect(noted.notes).toEqual({ offered: true, code: null, searchesAtMost: 3, maximumUsd: '0.02000000' });
    expect(() => parseCreatureOffer({ ...offer, notes: { offered: 'yes', code: null, searches_at_most: 3, maximum_usd: null } })).toThrow(TypeError);
    const used = parseCreatureDraft({ ...kept, references: { reference_id: 'ref-1', state: 'used', code: null, notes: 7, bundle_sha256: 'c'.repeat(64), basis: ['web_description'], searches: 3, spent_usd: '0.00110000' } });
    expect(used.references).toEqual({ referenceId: 'ref-1', state: 'used', code: null, notes: 7, searches: 3, spentUsd: '0.00110000' });
    // A server before the notes' figures states neither.
    expect(parseCreatureDraft({ ...kept, references: { reference_id: 'ref-1', state: 'pending' } }).references).toMatchObject({ notes: 0, searches: null, spentUsd: null });

    const posting = vi.fn(async (_url: unknown, _init?: RequestInit) => new Response(JSON.stringify({ ...kept, status: 'queued', kind: null, look: null, model: null }), { status: 202, headers: { 'content-type': 'application/json' } }));
    const client = new CreatureDraftsClient({ baseUrl: 'https://example.test', token: 'token', fetch: posting as typeof fetch });
    await client.ask('a little yellow robot duck');
    await client.ask('a little yellow robot duck', 'ref-1');
    expect(posting.mock.calls.map((call) => JSON.parse(String(call[1]?.body)))).toEqual([
      { words: 'a little yellow robot duck' }, { words: 'a little yellow robot duck', reference_id: 'ref-1' },
    ]);
  });

  it('reads the model a draft asks first and the most it may be charged, and what a draft spent', () => {
    const priced = parseCreatureOffer({
      ...offer, offered: true, code: null,
      model: { model_id: 'nvidia/nemotron-3-super-120b-a12b', name: 'Nemotron 3 Super 120B' },
      price: { usd_at_most: '0.37355520', provider: 'nebius_token_factory', provider_description: 'Nebius Token Factory', basis: { kind: 'full_context_ceiling' } },
    });
    expect(priced.model).toEqual({ modelId: 'nvidia/nemotron-3-super-120b-a12b', name: 'Nemotron 3 Super 120B' });
    expect(priced.priceUsdAtMost).toBe('0.37355520');
    expect(parseCreatureDraft({ ...kept, spend: { spent_usd: '0.00420000', held_usd: '0.00000000' } }).spentUsd).toBe('0.00420000');
    // What its calls under way hold, not known yet, as the making view counts it (Create's line).
    expect(parseCreatureDraft({ ...kept, spend: { spent_usd: '0.00000000', held_usd: '0.37355520' } }).heldUsd).toBe('0.37355520');
    expect(parseCreatureDraft({ ...kept, spend: { spent_usd: '0.00420000' } }).heldUsd).toBeNull();
    expect(parseCreatureDraft({ ...kept, spend: null }).spentUsd).toBeNull();
    expect(parseCreatureDraft({ ...kept, spend: null }).heldUsd).toBeNull();
    expect(parseCreatureDraft(kept).spentUsd).toBeNull();
    expect(() => parseCreatureDraft({ ...kept, spend: { spent_usd: '0.00420000', held_usd: 0.37 } })).toThrow(TypeError);
    expect(parseCreatureDraft(kept).lookStatus).toBeNull();
    expect(parseCreatureDraft({ ...kept, look_job: { profile: 'exulanica.creature-look/v1', status: 'made' } }).lookStatus).toBe('made');
    expect(() => parseCreatureOffer({ ...offer, price: { usd_at_most: 0.37 } })).toThrow(TypeError);
    expect(() => parseCreatureDraft({ ...kept, spend: { spent_usd: '4E-3' } })).toThrow(TypeError);
  });

  it('reads where a creature put down at a point would stand, or that nowhere is open there', () => {
    const profile = 'exulanica.society-stand/v1';
    expect(parseSocietyStand({ profile, stand: { node_id: 'n-12', position_mm: [4200, -1800] } })).toEqual({ nodeId: 'n-12', positionMm: [4200, -1800] });
    expect(parseSocietyStand({ profile, stand: null })).toBeNull();
    expect(() => parseSocietyStand({ profile: 'exulanica.society-stand/v0', stand: null })).toThrow(TypeError);
    expect(() => parseSocietyStand({ profile, stand: { node_id: 'n-12', position_mm: [4200.5, 0] } })).toThrow(TypeError);
  });

  it('reads a kept draft naming its kind and sketch by digest, and the model that drafted it', () => {
    const draft = parseCreatureDraft(kept);
    expect(draft.kind).toEqual({ key: 'hill_walker', version: 1, sha256: 'a'.repeat(64) });
    expect(draft.model).toEqual({ modelId: 'nvidia/nemotron-3-super-120b-a12b', name: 'Nemotron 3 Super' });
    expect(draftEnded(draft)).toBe(true);
    expect(draftEnded(parseCreatureDraft({ ...kept, status: 'running', kind: null, look: null, model: null }))).toBe(false);
  });

  it('reads a refusal by its code, field and fixed sentence', () => {
    const refused = parseCreatureDraft({
      ...kept, status: 'refused', label: null, kind: null, look: null, model: null,
      refusal: { code: 'creature_movement_unbuilt', field: 'moves', detail: 'This world has no flying creatures yet.' },
    });
    expect(refused.refusal).toEqual({ code: 'creature_movement_unbuilt', field: 'moves', detail: 'This world has no flying creatures yet.' });
  });

  it('refuses an answer of another profile or status, and a digest that is not one', () => {
    expect(() => parseCreatureDraft({ ...kept, profile: 'exulanica.creature-draft/v2' })).toThrow(TypeError);
    expect(() => parseCreatureDraft({ ...kept, status: 'done' })).toThrow(TypeError);
    expect(() => parseCreatureDraft({ ...kept, kind: { ...kept.kind, sha256: 'A'.repeat(64) } })).toThrow(TypeError);
    expect(() => parseCreatureOffer({ ...offer, profile: 'exulanica.creature-offer/v0' })).toThrow(TypeError);
  });
});
