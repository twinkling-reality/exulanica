import { describe, expect, it, vi } from 'vitest';
import {
  WORLD_STYLE_CONTRACT_COMMIT,
  WORLD_STYLE_RECIPES,
  worldStyleRecipe,
} from '@exulanica/presentation';
import { ApiError } from '@exulanica/graph-client';
import {
  WorldStyleClient,
  WorldStyleContractError,
  validateLocalReference,
} from '../src/world-style-api.js';

const json = (body: unknown, status = 200): Response => new Response(JSON.stringify(body), {
  status,
  headers: { 'content-type': 'application/json' },
});

const binding = (profileId = 'origin-landscape', profileVersion = 1) => {
  const recipe = worldStyleRecipe(profileId, profileVersion)!;
  return {
    schemaVersion: 1,
    frontendCommit: WORLD_STYLE_CONTRACT_COMMIT,
    availability: recipe.availability,
    origin: recipe.origin,
    profileId,
    profileVersion,
    modules: [...recipe.modules],
    capabilityMapping: Object.fromEntries(
      recipe.controls.map((control) => [control.key, control.capability]),
    ),
  };
};

const catalog = () => ({
  schemaVersion: 1,
  contractSource: { frontendCommit: WORLD_STYLE_CONTRACT_COMMIT },
  defaultProfile: {
    profileId: 'origin-landscape', profileVersion: 1,
    parameters: validateLocalReference({ profileId: 'origin-landscape', profileVersion: 1 }).parameters,
  },
  profiles: WORLD_STYLE_RECIPES.map((recipe) => ({
    profileId: recipe.profile.profileId,
    profileVersion: recipe.profile.profileVersion,
    displayName: recipe.profile.displayName,
    description: recipe.profile.description,
    compatibilityKey: recipe.profile.compatibilityKey,
    status: recipe.availability === 'product' ? 'supported' : 'experimental',
    recipeBinding: binding(recipe.profile.profileId, recipe.profile.profileVersion),
    controls: structuredClone(recipe.controls),
  })),
});

const reference = (vitality = 0.82) => ({
  profile_id: 'origin-landscape',
  profile_version: 1,
  parameters: {
    ...validateLocalReference({ profileId: 'origin-landscape', profileVersion: 1 }).parameters,
    vitality,
  },
});

const version = (id: string, revision: number, vitality = 0.82) => ({
  version_id: id,
  revision,
  parent_version_id: revision === 0 ? null : `v${revision - 1}`,
  topology_digest: 'topology-a',
  global_style: reference(vitality),
  region_styles: [],
  applied_from_proposal_id: revision === 0 ? null : `proposal-${revision}`,
  rollback_target_version_id: null,
  provenance: revision === 0 ? null : {
    origin: 'settings', actor: 'actor-1', origin_reference: 'appearance-panel',
  },
  created_at: `2026-08-31T12:0${revision}:00Z`,
  warnings: [],
  recipe_binding: binding(),
  capability_mapping: binding().capabilityMapping,
  reference_ids: [],
  model_id: null,
  prompt_version: null,
  refines_proposal_id: null,
});

const state = (id = 'v0', revision = 0, vitality = 0.82) => ({
  current_topology_digest: 'topology-a',
  current: version(id, revision, vitality),
});

const preview = (previewId: string, proposalId: string, baseRevision = 0, vitality = 0.4) => ({
  preview_id: previewId,
  proposal_id: proposalId,
  candidate: {
    ...version(`candidate-${proposalId}`, baseRevision, vitality),
    applied_from_proposal_id: proposalId,
  },
  created_at: '2026-08-31T12:10:00Z',
});

function connectedFetch(handler?: (
  url: URL,
  init: RequestInit,
) => Response | Promise<Response> | undefined): typeof globalThis.fetch {
  return vi.fn(async (input: string | URL | Request, init: RequestInit = {}) => {
    const url = new URL(String(input));
    const custom = await handler?.(url, init);
    if (custom !== undefined) return custom;
    if (url.pathname.endsWith('/world/styles/catalog')) return json(catalog());
    if (url.pathname.endsWith('/world/styles/current')) return json(state());
    if (url.pathname.endsWith('/world/styles/versions')) return json([version('v0', 0)]);
    throw new Error(`unhandled request ${init.method ?? 'GET'} ${url.pathname}`);
  }) as typeof globalThis.fetch;
}

describe('world style API boundary', () => {
  it('joins the exact reviewed catalog and completes a preview/apply/discard lifecycle', async () => {
    const bodies: Record<string, unknown>[] = [];
    const methods: string[] = [];
    let previewCount = 0;
    const fetch = connectedFetch((url, init) => {
      if (url.pathname.endsWith('/world/styles/previews') && init.method === 'POST') {
        const body = JSON.parse(String(init.body)) as Record<string, unknown>;
        bodies.push(body);
        previewCount += 1;
        return json(preview(`preview-${previewCount}`, String(body['proposalId'])), 201);
      }
      if (url.pathname.endsWith('/apply')) return json(version('v1', 1, 0.4));
      if (url.pathname.includes('/world/styles/previews/') && init.method === 'DELETE') {
        methods.push(init.method);
        return new Response(null, { status: 204 });
      }
      return undefined;
    });
    const ids = ['proposal-1', 'proposal-2'];
    const client = new WorldStyleClient({
      baseUrl: 'https://exulanica.test/api', token: 'secret', fetch,
      ids: () => ids.shift()!,
    });
    const connected = await client.connect();
    expect(connected.state.current.versionId).toBe('v0');

    await client.previewSettings({
      profileId: 'origin-landscape', profileVersion: 1, parameters: { vitality: 0.4 },
    });
    expect(bodies[0]).toMatchObject({
      proposalId: 'proposal-1',
      origin: 'settings',
      originReference: 'appearance-panel',
      baseStyleVersionId: 'v0',
      baseTopologyDigest: 'topology-a',
      profile: { profileId: 'origin-landscape', profileVersion: 1 },
    });
    expect((bodies[0]!['profile'] as { parameters: object }).parameters).toMatchObject({
      vitality: 0.4, 'surface-finish': 'source-paper',
    });
    const applied = await client.applyActive();
    expect(applied.kind).toBe('applied');
    expect(client.state()?.current.versionId).toBe('v1');

    await client.previewSettings({
      profileId: 'origin-landscape', profileVersion: 1, parameters: { vitality: 0.5 },
    });
    await client.discardActive();
    expect(methods).toEqual(['DELETE']);
    expect(client.activePreview()).toBeNull();
  });

  it('fails closed for an unknown catalog version, module/capability binding, or profile', async () => {
    for (const broken of [
      { ...catalog(), schemaVersion: 2 },
      (() => {
        const value = catalog();
        value.profiles[0]!.recipeBinding.modules = ['unknown-module-v1'];
        return value;
      })(),
      (() => {
        const value = catalog();
        value.profiles[0]!.recipeBinding.capabilityMapping.vitality = 'unknown.capability';
        return value;
      })(),
    ]) {
      const fetch = connectedFetch((url) =>
        url.pathname.endsWith('/world/styles/catalog') ? json(broken) : undefined);
      const client = new WorldStyleClient({ baseUrl: 'https://exulanica.test/api', token: 't', fetch });
      await expect(client.connect()).rejects.toBeInstanceOf(WorldStyleContractError);
    }
    expect(() => validateLocalReference({
      profileId: 'future-style', profileVersion: 9, parameters: {},
    })).toThrow('Unknown reviewed world profile');
    expect(() => validateLocalReference({
      profileId: 'origin-landscape', profileVersion: 1,
      parameters: { 'remote-texture-url': 'https://example.test/private.jpg' },
    })).toThrow('Unknown parameter');

    const unknownCurrent = connectedFetch((url) => {
      if (!url.pathname.endsWith('/world/styles/current')) return undefined;
      const value = state();
      value.current.global_style.profile_id = 'future-style';
      value.current.global_style.profile_version = 9;
      return json(value);
    });
    await expect(new WorldStyleClient({
      baseUrl: 'https://exulanica.test/api', token: 't', fetch: unknownCurrent,
    }).connect()).rejects.toMatchObject({ code: 'unknown_profile_version' });
  });

  it('recovers a stale preview by refreshing and linking a new refinement proposal', async () => {
    const bodies: Record<string, unknown>[] = [];
    let currentReads = 0;
    let previewWrites = 0;
    const fetch = connectedFetch((url, init) => {
      if (url.pathname.endsWith('/world/styles/current')) {
        currentReads += 1;
        return json(currentReads === 1 ? state() : state('v1', 1, 0.6));
      }
      if (url.pathname.endsWith('/world/styles/previews') && init.method === 'POST') {
        const body = JSON.parse(String(init.body)) as Record<string, unknown>;
        bodies.push(body);
        previewWrites += 1;
        return previewWrites === 1
          ? json({ code: 'stale_style_version', detail: 'another writer won' }, 409)
          : json(preview('preview-2', String(body['proposalId']), 1, 0.4), 201);
      }
      return undefined;
    });
    const ids = ['proposal-stale', 'proposal-rebased'];
    const client = new WorldStyleClient({
      baseUrl: 'https://exulanica.test/api', token: 't', fetch, ids: () => ids.shift()!,
    });
    await client.connect();
    const recovered = await client.previewSettings({
      profileId: 'origin-landscape', profileVersion: 1, parameters: { vitality: 0.4 },
    });
    expect(recovered.recoveredFromStale).toBe(true);
    expect(bodies[1]).toMatchObject({
      proposalId: 'proposal-rebased',
      baseStyleVersionId: 'v1',
      refinesProposalId: 'proposal-stale',
    });
  });

  it('does not silently apply after a competing writer; it returns a fresh preview for review', async () => {
    const bodies: Record<string, unknown>[] = [];
    let currentReads = 0;
    let previewWrites = 0;
    const fetch = connectedFetch((url, init) => {
      if (url.pathname.endsWith('/world/styles/current')) {
        currentReads += 1;
        return json(currentReads === 1 ? state() : state('v1', 1, 0.55));
      }
      if (url.pathname.endsWith('/world/styles/previews') && init.method === 'POST') {
        const body = JSON.parse(String(init.body)) as Record<string, unknown>;
        bodies.push(body);
        previewWrites += 1;
        return json(preview(`preview-${previewWrites}`, String(body['proposalId']), previewWrites - 1), 201);
      }
      if (url.pathname.endsWith('/apply')) {
        return json({ code: 'stale_style_version', detail: 'another writer won' }, 409);
      }
      return undefined;
    });
    const ids = ['proposal-1', 'proposal-2'];
    const client = new WorldStyleClient({
      baseUrl: 'https://exulanica.test/api', token: 't', fetch, ids: () => ids.shift()!,
    });
    await client.connect();
    await client.previewSettings({
      profileId: 'origin-landscape', profileVersion: 1, parameters: { vitality: 0.4 },
    });
    const result = await client.applyActive();
    expect(result.kind).toBe('stale-recovered');
    expect(client.state()?.current.versionId).toBe('v1');
    expect(bodies[1]).toMatchObject({
      baseStyleVersionId: 'v1', refinesProposalId: 'proposal-1',
    });
  });

  it('preserves Companion provenance and explicit refinement lineage', async () => {
    let proposalBody: Record<string, unknown> | null = null;
    const fetch = connectedFetch((url, init) => {
      if (url.pathname.endsWith('/world/styles/previews') && init.method === 'POST') {
        proposalBody = JSON.parse(String(init.body)) as Record<string, unknown>;
        return json(preview('preview-c', String(proposalBody['proposalId'])), 201);
      }
      return undefined;
    });
    const client = new WorldStyleClient({
      baseUrl: 'https://exulanica.test/api', token: 't', fetch, ids: () => 'proposal-refined',
    });
    await client.connect();
    await client.previewUpstream({
      origin: 'companion',
      originReference: 'companion-world-design',
      profile: { profileId: 'origin-landscape', profileVersion: 1, parameters: { vitality: 0.3 } },
      referenceIds: ['evidence-span-1'],
      modelId: 'reviewed-personalizer-v1',
      promptVersion: 'world-style-proposal-v1',
      refinesProposalId: 'proposal-original',
    });
    expect(proposalBody).toMatchObject({
      origin: 'companion',
      referenceIds: ['evidence-span-1'],
      modelId: 'reviewed-personalizer-v1',
      promptVersion: 'world-style-proposal-v1',
      refinesProposalId: 'proposal-original',
    });
    expect(() => client.previewUpstream({
      origin: 'companion',
      profile: { profileId: 'origin-landscape', profileVersion: 1 },
    })).toThrow('require an origin reference');
  });

  it('refreshes instead of retrying a stale rollback and preserves network failures', async () => {
    let currentReads = 0;
    const fetch = connectedFetch((url) => {
      if (url.pathname.endsWith('/world/styles/current')) {
        currentReads += 1;
        return json(currentReads === 1 ? state() : state('v1', 1));
      }
      if (url.pathname.endsWith('/world/styles/rollback')) {
        return json({ code: 'stale_style_version', detail: 'another writer won' }, 409);
      }
      return undefined;
    });
    const client = new WorldStyleClient({ baseUrl: 'https://exulanica.test/api', token: 't', fetch });
    await client.connect();
    expect((await client.rollback('v0')).kind).toBe('stale');
    expect(client.state()?.current.versionId).toBe('v1');

    const offline = new WorldStyleClient({
      baseUrl: 'https://exulanica.test/api', token: 't',
      fetch: vi.fn(async () => { throw new TypeError('network offline'); }),
    });
    await expect(offline.connect()).rejects.toThrow('network offline');
    await expect(client.inspectProposal('missing')).rejects.toBeInstanceOf(Error);
  });

  it('surfaces server problem codes without replacing them with HTTP status guesses', async () => {
    const fetch = connectedFetch((url, init) => {
      if (url.pathname.endsWith('/world/styles/previews') && init.method === 'POST') {
        return json({ code: 'protected_topology_conflict', detail: 'topology changed' }, 409);
      }
      return undefined;
    });
    const client = new WorldStyleClient({ baseUrl: 'https://exulanica.test/api', token: 't', fetch });
    await client.connect();
    await client.previewSettings({ profileId: 'origin-landscape', profileVersion: 1 })
      .catch((error: ApiError) => expect(error.code).toBe('protected_topology_conflict'));
  });
});


describe('reviewed historical recipe bindings', () => {
  const historicalVersion = () => {
    const saved = version('historical-v0', 0);
    const old = worldStyleRecipe('origin-landscape', 1)!.readCompatibleBindings![0]!;
    saved.recipe_binding = { ...saved.recipe_binding, modules: [...old.modules], capabilityMapping: { ...old.capabilityMapping } };
    saved.capability_mapping = { ...old.capabilityMapping };
    for (const key of ['source-hue', 'source-warmth', 'source-depth', 'source-light']) delete (saved.global_style.parameters as Record<string, unknown>)[key];
    return saved;
  };
  it('opens an exact historical binding without rewriting it and keeps new previews strict', async () => {
    const saved = historicalVersion();
    const original = structuredClone(saved);
    const fetch = connectedFetch(url => {
      if (url.pathname.endsWith('/current')) return json({ current_topology_digest: 'topology-a', current: saved });
      if (url.pathname.endsWith('/versions')) return json([saved]);
      if (url.pathname.endsWith('/previews')) return json({ ...preview('p', 'proposal'), candidate: saved }, 201);
      return undefined;
    });
    const client = new WorldStyleClient({baseUrl:'https://exulanica.test',token:'fixture',fetch});
    const connected = await client.connect();
    expect(connected.state.current.recipeBinding.modules).toEqual(saved.recipe_binding.modules);
    expect(connected.state.current.globalStyle.parameters['source-hue']).toBe(0.6);
    expect(saved).toEqual(original);
    await expect(client.previewSettings({profileId:'origin-landscape',profileVersion:1,parameters:{vitality:0.5}})).rejects.toThrow('not executable');
  });
  it('refuses an unreviewed historical module subset', async () => {
    const saved = historicalVersion();
    saved.recipe_binding.modules.pop();
    const fetch = connectedFetch(url => url.pathname.endsWith('/current')
      ? json({current_topology_digest:'topology-a',current:saved}) : undefined);
    await expect(new WorldStyleClient({baseUrl:'https://exulanica.test',token:'fixture',fetch}).connect()).rejects.toThrow('not executable');
  });
});
