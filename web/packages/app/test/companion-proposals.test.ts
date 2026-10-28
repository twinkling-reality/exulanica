// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';
import {
  WORLD_STYLE_REGISTRY_DOCUMENT,
  WORLD_STYLE_RECIPES,
  worldStyleRecipe,
} from '@exulanica/presentation';
import {
  CompanionProposalClient,
  PROPOSAL_OUTCOMES,
  REFUSAL_CODES,
} from '../src/companion-ask-api.js';
import { mountAppearance } from '../src/composition/appearance.js';
import type { AppEnvironment, SessionState } from '../src/composition/session-state.js';
import { DEFAULT_PREFERENCES } from '../src/preferences.js';
import { say } from '../src/ui/copy.js';
import { WorldStyleClient, validateLocalReference } from '../src/world-style-api.js';
import { WorldStyleProposalOutcomes } from '../src/world-style-proposals.js';

/** The world these clients are opened for. */
const TEST_WORLD = 'world:personal:test';

/**
 * A sentence somebody typed, turned into a change nobody has agreed to yet: what the proposal
 * route's answer is read as, what a page finds still open when it opens a world, and a look saved
 * through the same authority.
 *
 * The authority here is a scripted fetch rather than a stub client, so what is asserted is the
 * BODY the browser actually sends and the requests it makes, which a stubbed client would let
 * drift.
 */

const PROFILE = { profileId: 'origin-landscape', profileVersion: 1 } as const;
const PARAMETERS = validateLocalReference(PROFILE).parameters;

const json = (body: unknown, status = 200): Response =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });

const binding = (profile: { profileId: string; profileVersion: number } = PROFILE) => {
  const recipe = worldStyleRecipe(profile.profileId, profile.profileVersion)!;
  return {
    schemaVersion: 1,
    frontendCommit: WORLD_STYLE_REGISTRY_DOCUMENT.frontend_contract.commit,
    availability: recipe.availability,
    origin: recipe.origin,
    profileId: profile.profileId,
    profileVersion: profile.profileVersion,
    modules: [...recipe.modules],
    capabilityMapping: Object.fromEntries(
      recipe.controls.map((control) => [control.key, control.capability]),
    ),
  };
};

const catalog = () => ({
  schemaVersion: 1,
  contractSource: { frontendCommit: WORLD_STYLE_REGISTRY_DOCUMENT.frontend_contract.commit },
  defaultProfile: { ...PROFILE, parameters: PARAMETERS },
  profiles: WORLD_STYLE_RECIPES.map((recipe) => ({
    profileId: recipe.profile.profileId,
    profileVersion: recipe.profile.profileVersion,
    displayName: recipe.profile.displayName,
    description: recipe.profile.description,
    compatibilityKey: recipe.profile.compatibilityKey,
    status: recipe.availability === 'product' ? 'supported' : 'experimental',
    recipeBinding: {
      ...binding(),
      profileId: recipe.profile.profileId,
      profileVersion: recipe.profile.profileVersion,
      availability: recipe.availability,
      origin: recipe.origin,
      modules: [...recipe.modules],
      capabilityMapping: Object.fromEntries(
        recipe.controls.map((control) => [control.key, control.capability]),
      ),
    },
    controls: structuredClone(recipe.controls),
  })),
});

const version = (id: string, revision: number, softness = 0.46, over: object = {}) => ({
  version_id: id,
  revision,
  parent_version_id: revision === 0 ? null : `v${revision - 1}`,
  topology_digest: 'topology-a',
  global_style: {
    profile_id: PROFILE.profileId,
    profile_version: PROFILE.profileVersion,
    parameters: { ...PARAMETERS, 'horizon-softness': softness },
  },
  region_styles: [],
  applied_from_proposal_id: null,
  rollback_target_version_id: null,
  provenance: null,
  created_at: '2026-09-10T09:00:00Z',
  warnings: [],
  recipe_binding: binding(),
  capability_mapping: binding().capabilityMapping,
  reference_ids: [],
  model_id: null,
  model_name: null,
  prompt_version: null,
  refines_proposal_id: null,
  ...over,
});

/** The name the server serves beside a model's identifier (`Manifest.model_name`). */
const servedName = (modelId: string): string =>
  modelId === 'Qwen/Qwen3-235B-A22B-Instruct-2507' ? 'Qwen3 235B Instruct' : modelId;

/** What `POST /selection/appearance` answers with, in the route's own snake-case. */
const wireProposal = (over: object = {}) => ({
  classification: 'appearance',
  proposal: {
    profile: {
      profile_id: PROFILE.profileId,
      profile_version: PROFILE.profileVersion,
      parameters: { ...PARAMETERS, 'horizon-softness': 0.8 },
      modules: ['aeroheart-optics-v1'],
      changed: ['horizon-softness'],
    },
    reference_ids: ['00000000-0000-0000-0000-000000000001'],
    model_id: 'Qwen/Qwen3-235B-A22B-Instruct-2507',
    prompt_version: 'proposal-1',
    spoken: 'The horizon will sit softer, so the far edge reads as distance.',
    base_style_version_id: 'v0',
    base_topology_digest: 'topology-a',
  },
  refusal: null,
  execution: {
    prompt_version: 'proposal-1',
    calls: [call('Qwen/Qwen3-235B-A22B-Instruct-2507', 1200), call('Qwen/Qwen3-235B-A22B-Instruct-2507', 2300)],
  },
  ...over,
});

const call = (model: string, latency: number) => ({
  role: 'structured_extraction',
  requested_model: 'Qwen/Qwen3-235B-A22B-Instruct-2507',
  served_model: model,
  used_fallback: false,
  attempts: 1,
  latency_ms: latency,
  prompt_tokens: 900,
  completion_tokens: 120,
  reasoning_tokens: null,
});

// -- the client for the new route -------------------------------------------------------------

describe('the appearance proposal client', () => {
  it('reads a proposal with the model that drew it and the prompt it was drawn under', async () => {
    const fetch = vi.fn(async () => json(wireProposal())) as unknown as typeof globalThis.fetch;
    const client = new CompanionProposalClient({
      worldId: TEST_WORLD,
      baseUrl: 'https://exulanica.test/api',
      token: 'secret',
      fetch,
    });

    const outcome = await client.propose('could the horizon be softer');

    expect(outcome.classification).toBe('appearance');
    expect(outcome.proposal).toMatchObject({
      profileId: 'origin-landscape',
      profileVersion: 1,
      changed: ['horizon-softness'],
      modelId: 'Qwen/Qwen3-235B-A22B-Instruct-2507',
      promptVersion: 'proposal-1',
    });
    // Complete, never a diff: the preview route fills an omitted control from its DEFAULT, so a
    // diff posted there would reset every control the request never mentioned.
    expect(Object.keys(outcome.proposal!.parameters).sort()).toEqual(Object.keys(PARAMETERS).sort());
    expect(outcome.proposal!.parameters['horizon-softness']).toBe(0.8);
    expect(outcome.calls).toHaveLength(2);
  });

  it('carries a refusal code through rather than collapsing it into one refusal', async () => {
    const fetch = vi.fn(async () =>
      json(
        wireProposal({
          proposal: null,
          refusal: { code: 'not_in_catalogue', detail: 'a different typeface for the menus' },
        }),
      ),
    ) as unknown as typeof globalThis.fetch;
    const client = new CompanionProposalClient({
      worldId: TEST_WORLD,
      baseUrl: 'https://exulanica.test/api',
      token: 'secret',
      fetch,
    });

    const outcome = await client.propose('use a serif typeface');

    expect(outcome.refusal).toEqual({
      code: 'not_in_catalogue',
      detail: 'a different typeface for the menus',
    });
    expect(outcome.proposal).toBeNull();
  });

  it('says the most general true thing about a refusal this client has no words for', async () => {
    const fetch = vi.fn(async () =>
      json(wireProposal({ proposal: null, refusal: { code: 'invented_later', detail: 'x' } })),
    ) as unknown as typeof globalThis.fetch;
    const client = new CompanionProposalClient({
      worldId: TEST_WORLD,
      baseUrl: 'https://exulanica.test/api',
      token: 'secret',
      fetch,
    });

    // A key nobody wrote renders as the key, so an unrecognised code must not reach the table.
    expect((await client.propose('x')).refusal!.code).toBe('not_drafted');
  });

  it('treats every failure as a question, so it can never be why one goes unanswered', async () => {
    const failures = [
      async () => {
        throw new Error('the network is down');
      },
      async () => json({ code: 'unauthenticated', detail: 'no' }, 401),
      async () => json({ code: 'model_refused', detail: 'no' }, 502),
    ];
    for (const fetch of failures) {
      const client = new CompanionProposalClient({
      worldId: TEST_WORLD,
        baseUrl: 'https://exulanica.test/api',
        token: 'secret',
        fetch: fetch as unknown as typeof globalThis.fetch,
      });

      const outcome = await client.propose('could the horizon be softer');

      expect(outcome.classification).toBe('question');
      expect([outcome.proposal, outcome.refusal]).toEqual([null, null]);
    }
  });

  it('does not ask the classifier to answer a question it already said was one', async () => {
    const fetch = vi.fn(async () =>
      json({ classification: 'question', proposal: null, refusal: null, execution: null }),
    ) as unknown as typeof globalThis.fetch;
    const client = new CompanionProposalClient({
      worldId: TEST_WORLD,
      baseUrl: 'https://exulanica.test/api',
      token: 'secret',
      fetch,
    });

    expect((await client.propose('who is in these?')).classification).toBe('question');
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});

// -- the inbox and its return channel ----------------------------------------------------------

describe('the proposal outcome channel', () => {
  it('reports to whoever is listening and says when nobody was', () => {
    const outcomes = new WorldStyleProposalOutcomes();
    const listener = vi.fn();

    expect(outcomes.report({ originReference: 'a', kind: 'accepted', detail: 'x' })).toBe(false);
    const stop = outcomes.subscribe(listener);
    expect(outcomes.report({ originReference: 'a', kind: 'accepted', detail: 'x' })).toBe(true);
    expect(listener).toHaveBeenCalledWith({
      originReference: 'a',
      kind: 'accepted',
      detail: 'x',
    });
    stop();
    expect(outcomes.report({ originReference: 'a', kind: 'discarded', detail: 'x' })).toBe(false);
  });
});

// -- the appearance authority a page opens -----------------------------------------------------

interface Harness {
  readonly bodies: Record<string, unknown>[];
  readonly applied: string[];
  readonly deleted: string[];
  readonly mounted: ReturnType<typeof mountAppearance>;
  readonly client: WorldStyleClient;
  readonly gets: string[];
  readonly open: unknown[];
}

async function harness(over: {
  /** The world's open previews, as GET /world/styles/previews answers at connect. */
  open?: unknown[];
  /** The world the page opens, for a page that opens another world. */
  worldId?: string;
  /** A status the read-back answers with instead of the open previews. */
  openStatus?: number;
  /** How many open previews the server says it could not read. */
  unreadable?: number;
  /** Every apply is answered as made against a version that is no longer current. */
  applyStale?: boolean;
} = {}): Promise<Harness> {
  const bodies: Record<string, unknown>[] = [];
  const applied: string[] = [];
  const deleted: string[] = [];
  const gets: string[] = [];
  /** The world's open previews, oldest first, as the authority holds them. */
  const open: unknown[] = [...(over.open ?? [])].reverse();
  /** The version the authority holds as current. Previews and applies on another base are stale. */
  let current = version('v0', 0);
  /** The world's history as the authority serves it, oldest first. */
  const known: ReturnType<typeof version>[] = [version('v0', 0)];
  const remember = (next: ReturnType<typeof version>): void => {
    const at = known.findIndex((item) => item.version_id === next.version_id);
    if (at >= 0) known.splice(at, 1);
    known.push(next);
  };
  const stale = () => json({ code: 'stale_style_version', detail: 'the world changed' }, 409);
  const close = (id: string): void => {
    const at = open.findIndex((row) => (row as { preview: { preview_id: string } }).preview.preview_id === id);
    if (at >= 0) open.splice(at, 1);
  };
  const fetch = vi.fn(async (input: string | URL | Request, init: RequestInit = {}) => {
    const url = new URL(String(input));
    if ((init.method ?? 'GET') === 'GET') gets.push(`${url.pathname}${url.search}`);
    if (url.pathname.endsWith('/world/styles/catalog')) return json(catalog());
    if (url.pathname.endsWith('/world/styles/current')) {
      return json({ current_topology_digest: 'topology-a', current });
    }
    if (url.pathname.endsWith('/world/styles/versions')) return json(known);
    if (url.pathname.endsWith('/world/styles/previews') && (init.method ?? 'GET') === 'GET') {
      if (over.openStatus !== undefined) return json({ code: 'invalid_preview_state', detail: 'no' }, over.openStatus);
      return json({ previews: [...open].reverse(), unreadable: over.unreadable ?? 0 });
    }
    if (url.pathname.endsWith('/world/styles/previews') && init.method === 'POST') {
      const body = JSON.parse(String(init.body)) as Record<string, unknown>;
      bodies.push(body);
      if (body['baseStyleVersionId'] !== current.version_id) return stale();
      const previewId = `preview-${bodies.length}`;
      open.push(openFromBody(previewId, body));
      return json(
        {
          preview_id: previewId,
          proposal_id: String(body['proposalId']),
          candidate: version('candidate-1', 0, 0.8, {
            // Echoed from the body. A candidate that ignored what was posted made every
            // assertion about what was previewed an assertion about this fixture.
            global_style: {
              profile_id: PROFILE.profileId,
              profile_version: PROFILE.profileVersion,
              parameters: (body['profile'] as Record<string, unknown>)['parameters'],
            },
            model_id: body['modelId'],
            // As the server serves it: Manifest.model_name of the model that drew it.
            model_name: body['modelId'] == null ? null : servedName(String(body['modelId'])),
            prompt_version: body['promptVersion'],
            reference_ids: body['referenceIds'],
            provenance: {
              origin: body['origin'],
              actor: 'actor-1',
              origin_reference: body['originReference'],
            },
          }),
          created_at: '2026-09-10T09:01:00Z',
        },
        201,
      );
    }
    if (url.pathname.endsWith('/apply')) {
      applied.push(url.pathname);
      const id = decodeURIComponent(url.pathname.split('/').at(-2) ?? '');
      const body = JSON.parse(String(init.body)) as Record<string, unknown>;
      // Refused by its own base check, as the authority checks it, it closes the preview in the
      // same transaction. This page holds no saved world entry, so no entry check answers first.
      if (over.applyStale === true || body['baseStyleVersionId'] !== current.version_id) {
        close(id);
        return stale();
      }
      close(id);
      current = version('v1', 1, 0.8);
      remember(current);
      return json(current);
    }
    if (url.pathname.includes('/world/styles/previews/') && init.method === 'DELETE') {
      deleted.push(url.pathname);
      close(decodeURIComponent(url.pathname.split('/').at(-1) ?? ''));
      return new Response(null, { status: 204 });
    }

    throw new Error(`unhandled ${init.method ?? 'GET'} ${url.pathname}`);
  }) as unknown as typeof globalThis.fetch;

  const client = new WorldStyleClient({
      worldId: over.worldId ?? TEST_WORLD,
    baseUrl: 'https://exulanica.test/api',
    token: 'secret',
    fetch,
    ids: () => 'proposal-1',
  });
  const connection = await client.connect();
  const state = {
    preferences: DEFAULT_PREFERENCES,
    atlas: null,
    worldStyles: client,
    worldStyleConnection: connection,
    worldStyleFailure: null,
    interactionPolicies: null,
  } as unknown as SessionState;
  const env = {
    shell: document.createElement('div'),
    systemAppearance: { matches: false },
    systemReducedMotion: { matches: false },
    previewArtProfile: null,
  } as unknown as AppEnvironment;

  const mounted = mountAppearance({
    env,
    state,
    applyProofLens: vi.fn(),
    setCompanionAppearance: vi.fn(),
  });
  return { bodies, applied, deleted, mounted, client, gets, open };
}

const COMPANION = {
  origin: 'companion' as const,
  originReference: 'companion-utterance:0f2c',
  scope: { kind: 'global' as const },
  profile: { ...PROFILE, parameters: { ...PARAMETERS, 'horizon-softness': 0.8 } },
  referenceIds: ['00000000-0000-0000-0000-000000000001'],
  modelId: 'Qwen/Qwen3-235B-A22B-Instruct-2507',
  promptVersion: 'proposal-1',
};

// -- a proposal the page finds open when it opens ----------------------------------------------

/** One open preview as GET /world/styles/previews answers, with the proposal it was made from. */
const openPreview = (over: {
  id: string;
  origin?: 'companion' | 'settings';
  reference?: string;
  base?: string;
  softness?: number;
}) => {
  const origin = over.origin ?? 'companion';
  const companion = origin === 'companion';
  const provenance = {
    origin,
    actor: 'actor-1',
    origin_reference: companion ? (over.reference ?? `companion-utterance:${over.id}`) : 'appearance-panel',
  };
  const parameters = { ...PARAMETERS, 'horizon-softness': over.softness ?? 0.8 };
  return {
    preview: {
      preview_id: `preview-${over.id}`,
      proposal_id: `proposal-${over.id}`,
      candidate: version(`candidate-${over.id}`, 0, over.softness ?? 0.8, {
        provenance,
        model_id: companion ? COMPANION.modelId : null,
        model_name: companion ? servedName(COMPANION.modelId) : null,
        prompt_version: companion ? COMPANION.promptVersion : null,
        reference_ids: companion ? COMPANION.referenceIds : [],
      }),
      created_at: '2026-09-10T09:01:00Z',
    },
    proposal: {
      proposal_id: `proposal-${over.id}`,
      provenance,
      scope: { kind: 'global', region_id: null },
      base_style_version_id: over.base ?? 'v0',
      base_topology_digest: 'topology-a',
      profile: { profile_id: PROFILE.profileId, profile_version: PROFILE.profileVersion, parameters },
      reference_ids: companion ? COMPANION.referenceIds : [],
      model_id: companion ? COMPANION.modelId : null,
        model_name: companion ? servedName(COMPANION.modelId) : null,
      prompt_version: companion ? COMPANION.promptVersion : null,
      refines_proposal_id: null,
      recipe_binding: binding(),
      capability_mapping: binding().capabilityMapping,
      status: 'previewed',
      validation_issues: [],
      created_at: '2026-09-10T09:01:00Z',
      updated_at: '2026-09-10T09:01:00Z',
    },
  };
};

/** The open-preview row the authority holds for one preview the page posted. */
function openFromBody(previewId: string, body: Record<string, unknown>) {
  const origin = body['origin'] as 'companion' | 'settings';
  const profile = body['profile'] as Record<string, unknown>;
  const row = openPreview({
    id: previewId.replace(/^preview-/, ''),
    origin,
    reference: String(body['originReference'] ?? ''),
    base: String(body['baseStyleVersionId']),
  });
  const parameters = profile['parameters'];
  row.preview.preview_id = previewId;
  (row.preview.candidate.global_style as { parameters: unknown }).parameters = parameters;
  (row.proposal.profile as { parameters: unknown }).parameters = parameters;
  row.proposal.proposal_id = String(body['proposalId']);
  row.preview.proposal_id = String(body['proposalId']);
  return row;
}

describe('a proposal the page finds open when it opens', () => {
  it('takes up the newest on the current version and closes nothing', async () => {
    const { client, deleted, open } = await harness({
      open: [
        openPreview({ id: 'new', softness: 0.8 }),
        openPreview({ id: 'panel', origin: 'settings', softness: 0.3 }),
        openPreview({ id: 'old', softness: 0.6 }),
      ],
    });

    expect(deleted).toEqual([]);
    expect(open).toHaveLength(3);
    expect(client.activePreview()?.preview.previewId).toBe('preview-new');
  });

  it('takes up no settings preview another page left open, and leaves it open', async () => {
    const { client, deleted } = await harness({
      open: [openPreview({ id: 'panel', origin: 'settings' })],
    });

    expect(deleted).toEqual([]);
    expect(client.activePreview()).toBeNull();
  });

  it('reads the open previews of the world the page opens, after a switch as on a reload', async () => {
    const { gets, client } = await harness({
      worldId: 'world:personal:second',
      open: [openPreview({ id: 'b' })],
    });

    expect(gets).toContain(
      `/api/world/styles/previews?world_id=${encodeURIComponent('world:personal:second')}`,
    );
    expect(client.activePreview()?.preview.previewId).toBe('preview-b');
  });

  it('still opens the world when the read-back fails, and takes nothing up', async () => {
    const { client, deleted } = await harness({ openStatus: 409 });

    expect(deleted).toEqual([]);
    expect(client.activePreview()).toBeNull();
  });

  it('skips a row it cannot parse, and one the server could not read, and takes up the next', async () => {
    const broken = { preview: { preview_id: 'preview-broken' }, proposal: { provenance: 'nonsense' } };
    const { client, deleted } = await harness({
      unreadable: 2,
      open: [broken, openPreview({ id: 'good', softness: 0.8 })],
    });

    expect(deleted).toEqual([]);
    expect(client.activePreview()?.preview.previewId).toBe('preview-good');
  });
});

// -- what the words say ------------------------------------------------------------------------

describe('the words a refusal is said in', () => {
  it('has a reviewed sentence for every refusal code the client can produce', () => {
    // The CLIENT's own list, not a copy of it. Enumerating a copy passed while a code added to
    // the client reached a person as a raw key, which is what an unmapped key renders as.
    expect(REFUSAL_CODES.length).toBeGreaterThan(0);
    for (const code of REFUSAL_CODES) {
      const sentence = say(`proposal.refused.${code}`);
      expect(sentence, code).not.toBe(`proposal.refused.${code}`);
      expect(sentence.endsWith('.'), code).toBe(true);
    }
  });

  it('has a reviewed sentence for every outcome a staged proposal can reach', () => {
    for (const kind of PROPOSAL_OUTCOMES) {
      const sentence = say(`proposal.outcome.${kind}`);
      expect(sentence, kind).not.toBe(`proposal.outcome.${kind}`);
    }
  });

  it('says that nothing has changed yet, because that is the fact a person cannot see', () => {
    expect(say('proposal.staged')).toContain('Nothing has changed yet');
    expect(say('proposal.staged')).toContain('Design');
  });

  it('never says a refused value was moved to the nearest one it could have been', () => {
    expect(say('proposal.refused.out_of_range')).toContain('refused');
    expect(say('proposal.refused.out_of_range')).toContain('rather than moved');
  });
});

describe('a look chosen in the Look sheet', () => {
  const TOON = { packId: 'exulanica.toon-town', version: 1, manifestSha256: 'a'.repeat(64) };

  it('is saved as a new appearance version naming the pack, through one preview and Apply', async () => {
    const h = await harness();
    const result = await h.mounted.useStylePack(TOON);
    expect(result).toEqual({ saved: true, words: 'Saved as revision 1 of this world\'s appearance.' });
    expect(h.bodies).toHaveLength(1);
    expect(h.bodies[0]!['stylePack']).toEqual(TOON);
    expect(h.bodies[0]!['origin']).toBe('settings');
    expect(h.applied).toHaveLength(1);
    expect(h.client.activePreview()).toBeNull();
  });

  it('is never saved over a design another writer changed: the remade preview is thrown away', async () => {
    const h = await harness({ applyStale: true });
    const result = await h.mounted.useStylePack(TOON);
    expect(result.saved).toBe(false);
    expect(result.words).toBe('This world\'s design changed elsewhere, so nothing was changed. Choose the look again.');
    // The client made the preview again on the newer version; it was discarded, never applied.
    expect(h.applied).toHaveLength(1);
    expect(h.client.activePreview()).toBeNull();
    expect(h.open).toHaveLength(0);
  });

  it('waits for a change already open in Design, and sends nothing', async () => {
    const h = await harness();
    await h.client.previewSettings(PROFILE);
    const sent = h.bodies.length;
    const result = await h.mounted.useStylePack(TOON);
    expect(result).toEqual({
      saved: false,
      words: 'A change to this world\'s design is waiting in Design. Apply it or undo it there, then choose the look.',
    });
    expect(h.bodies).toHaveLength(sent);
    expect(h.applied).toHaveLength(0);
  });
});
