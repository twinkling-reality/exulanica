import { describe, expect, it } from 'vitest';
import { draftEnded, parseCreatureDraft, parseCreatureOffer } from '../src/creature-drafts-api.js';

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
    });
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
