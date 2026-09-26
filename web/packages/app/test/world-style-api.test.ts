import { describe, expect, it, vi } from 'vitest';
import {
  WORLD_STYLE_REGISTRY_DOCUMENT,
  WORLD_STYLE_RECIPES,
  worldStyleRecipe,
} from '@exulanica/presentation';
import { ApiError } from '@exulanica/graph-client';
import {
  StaleProposalError,
  WorldStyleClient,
  WorldStyleContractError,
  validateLocalReference,
} from '../src/world-style-api.js';
import { RESTORE_BEFORE_CHANGING } from '../src/world-style-refusals.js';

/** The world these clients are opened for. */
const TEST_WORLD = 'world:personal:test';

const json = (body: unknown, status = 200): Response => new Response(JSON.stringify(body), {
  status,
  headers: { 'content-type': 'application/json' },
});

const binding = (profileId = 'origin-landscape', profileVersion = 1) => {
  const recipe = worldStyleRecipe(profileId, profileVersion)!;
  return {
    schemaVersion: 1,
    frontendCommit: WORLD_STYLE_REGISTRY_DOCUMENT.frontend_contract.commit,
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
  contractSource: { frontendCommit: WORLD_STYLE_REGISTRY_DOCUMENT.frontend_contract.commit },
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
    // The world's open previews, read back at connect: none unless a test says otherwise.
    if (url.pathname.endsWith('/world/styles/previews') && (init.method ?? 'GET') === 'GET') {
      return json([]);
    }
    throw new Error(`unhandled request ${init.method ?? 'GET'} ${url.pathname}`);
  }) as typeof globalThis.fetch;
}

describe('world style API boundary', () => {
  it('commits appearance through the observed saved-entry cursor without a second pointer write', async () => {
    let appliedBody: Record<string, unknown> | null = null;
    const fetch = connectedFetch((url, init) => {
      if (url.pathname.endsWith('/world/styles/previews') && init.method === 'POST') {
        return json(preview('preview-1', '11111111-1111-4111-8111-111111111111'));
      }
      if (url.pathname.endsWith('/apply') && init.method === 'POST') {
        appliedBody = JSON.parse(String(init.body)) as Record<string, unknown>;
        return json(version('v1', 1, 0.4));
      }
      return undefined;
    });
    const savedEntry = {
      entryId: '22222222-2222-4222-8222-222222222222',
      revision: 4,
      authoredStateSha256: 'a'.repeat(64),
      authoredEditSeq: 7,
      styleVersionId: 'v0',
    };
    const onSavedEntryAdvanced = vi.fn();
    const client = new WorldStyleClient({
      worldId: TEST_WORLD,
      baseUrl: 'https://exulanica.test/api', token: 'private', fetch,
      ids: () => '11111111-1111-4111-8111-111111111111',
      savedEntry: () => savedEntry,
      onSavedEntryAdvanced,
    });
    await client.connect();
    await client.previewSettings({
      profileId: 'origin-landscape', profileVersion: 1, parameters: { vitality: 0.4 },
    });
    await client.applyActive();
    expect(appliedBody).toMatchObject({
      saved_entry: {
        entry_id: savedEntry.entryId,
        base_revision: 4,
        authored_state_sha256: savedEntry.authoredStateSha256,
        authored_edit_seq: 7,
        style_version_id: 'v0',
      },
    });
    expect(onSavedEntryAdvanced).toHaveBeenCalledWith(
      expect.objectContaining({ versionId: 'v1' }), savedEntry,
    );
  });

  it('renders the pinned historical style while retaining the live authority base for edits', async () => {
    const urls: URL[] = [];
    const bodies: Record<string, unknown>[] = [];
    const fetch = connectedFetch((url, init) => {
      urls.push(url);
      if (url.pathname.endsWith('/world/styles/current')) return json({
        ...state('v2', 2, 0.9),
        current_topology_digest: 'topology-live',
        current: { ...version('v2', 2, 0.9), topology_digest: 'topology-live' },
      });
      if (url.pathname.endsWith('/world/styles/versions')) {
        return json([
          version('v0', 0),
          { ...version('v1', 1, 0.4), topology_digest: 'topology-saved' },
          { ...version('v2', 2, 0.9), topology_digest: 'topology-live' },
        ]);
      }
      if (url.pathname.endsWith('/world/styles/rollback') && init.method === 'POST') {
        bodies.push(JSON.parse(String(init.body)) as Record<string, unknown>);
        return json(version('v3', 3, 0.4));
      }
      return undefined;
    });
    const client = new WorldStyleClient({
      baseUrl: 'https://exulanica.test/api', token: 'private', fetch,
      worldId: 'world:family-garden',
    });
    const opened = await client.connect('v1');
    expect(opened.state.current.versionId).toBe('v1');
    expect(opened.state.currentTopologyDigest).toBe('topology-saved');
    expect(client.state()?.currentTopologyDigest).toBe('topology-live');
    expect(client.state()?.current.versionId).toBe('v2');
    await expect(client.previewSettings({
      profileId: 'origin-landscape', profileVersion: 1, parameters: { vitality: 0.5 },
    })).rejects.toMatchObject({ code: 'saved_style_reconciliation_required' });
    expect(bodies).toEqual([]);
    const restored = await client.rollback('v1');
    expect(restored).toMatchObject({ kind: 'applied', version: { versionId: 'v3' } });
    expect(bodies).toEqual([expect.objectContaining({
      targetVersionId: 'v1', baseStyleVersionId: 'v2',
    })]);
    // The reviewed catalog is the same for every world and names none; every other read and write
    // names the saved world.
    const catalog = urls.filter((url) => url.pathname.endsWith('/world/styles/catalog'));
    const world = urls.filter((url) => !url.pathname.endsWith('/world/styles/catalog'));
    expect(catalog.map((url) => url.searchParams.get('world_id'))).toEqual([null]);
    expect(world.length).toBeGreaterThan(0);
    expect(world.every((url) => url.searchParams.get('world_id') === 'world:family-garden')).toBe(true);
  });
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
      worldId: TEST_WORLD,
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
      const client = new WorldStyleClient({ worldId: TEST_WORLD, baseUrl: 'https://exulanica.test/api', token: 't', fetch });
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
      worldId: TEST_WORLD,
      baseUrl: 'https://exulanica.test/api', token: 't', fetch: unknownCurrent,
    }).connect()).rejects.toMatchObject({ code: 'unknown_profile_version' });
  });

  it('compares the served payload with the shared registry rather than a commit label', async () => {
    const refused = async (broken: unknown, code: string) => {
      const fetch = connectedFetch((url) =>
        url.pathname.endsWith('/world/styles/catalog') ? json(broken) : undefined);
      await expect(new WorldStyleClient({ worldId: TEST_WORLD, baseUrl: 'https://exulanica.test/api', token: 't', fetch })
        .connect()).rejects.toMatchObject({ code });
    };
    // The drift measured on 2026-09-16: the browser described Aeroheart in its own words while
    // carrying the same commit label as the server. The label agreed; the payload did not.
    const described = catalog();
    described.profiles[0]!.description =
      'A clear memory field shaped by diffuse colour entering from its edges.';
    await refused(described, 'catalog_contract_mismatch');
    const promoted = catalog();
    promoted.profiles[1]!.status = 'supported';
    await refused(promoted, 'catalog_contract_mismatch');
    // A matching label no longer vouches for anything, and a different one is just a different
    // payload.
    const relabelled = catalog();
    relabelled.profiles[0]!.recipeBinding.frontendCommit = '0'.repeat(40);
    await refused(relabelled, 'recipe_binding_mismatch');
    expect(catalog().profiles[0]!.description).toBe(
      WORLD_STYLE_REGISTRY_DOCUMENT.profiles[0]!.description,
    );
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
      worldId: TEST_WORLD,
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
      worldId: TEST_WORLD,
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
      worldId: TEST_WORLD,
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
    const client = new WorldStyleClient({ worldId: TEST_WORLD, baseUrl: 'https://exulanica.test/api', token: 't', fetch });
    await client.connect();
    expect((await client.rollback('v0')).kind).toBe('stale');
    expect(client.state()?.current.versionId).toBe('v1');

    const offline = new WorldStyleClient({
      worldId: TEST_WORLD,
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
    const client = new WorldStyleClient({ worldId: TEST_WORLD, baseUrl: 'https://exulanica.test/api', token: 't', fetch });
    await client.connect();
    await client.previewSettings({ profileId: 'origin-landscape', profileVersion: 1 })
      .catch((error: ApiError) => expect(error.code).toBe('protected_topology_conflict'));
  });
});


/** A Companion proposal as the inbox hands it to the client. */
const COMPANION_PROPOSAL = {
  origin: 'companion' as const,
  originReference: 'companion-utterance:0f2c',
  profile: { profileId: 'origin-landscape', profileVersion: 1, parameters: { vitality: 0.3 } },
  referenceIds: ['evidence-span-1'],
  modelId: 'reviewed-personalizer-v1',
  promptVersion: 'world-style-proposal-v1',
};

describe('a proposal from another origin than Settings', () => {
  /** The world as the first read finds it, then as another writer has left it. */
  const movedOn = () => {
    let currentReads = 0;
    return () => {
      currentReads += 1;
      return json(currentReads === 1 ? state() : state('v1', 1, 0.55));
    };
  };

  it('is never made again after a competing writer: Apply says stale and the client lets it go', async () => {
    const bodies: Record<string, unknown>[] = [];
    const current = movedOn();
    const fetch = connectedFetch((url, init) => {
      if (url.pathname.endsWith('/world/styles/current')) return current();
      if (url.pathname.endsWith('/world/styles/previews') && init.method === 'POST') {
        const body = JSON.parse(String(init.body)) as Record<string, unknown>;
        bodies.push(body);
        return json(preview(`preview-${bodies.length}`, String(body['proposalId'])), 201);
      }
      if (url.pathname.endsWith('/apply')) {
        return json({ code: 'stale_style_version', detail: 'another writer won' }, 409);
      }
      return undefined;
    });
    const client = new WorldStyleClient({
      worldId: TEST_WORLD,
      baseUrl: 'https://exulanica.test/api', token: 't', fetch, ids: () => 'proposal-companion',
    });
    await client.connect();
    await client.previewUpstream(COMPANION_PROPOSAL);

    const result = await client.applyActive();

    // The live appearance is no longer the one this page shows (v0), and the result says so.
    expect(result).toMatchObject({
      kind: 'stale', state: { current: { versionId: 'v1' } }, reconciliationRequired: true,
    });
    // Its candidate is the whole design as drafted against v0: made again on v1, a second Apply
    // would save it over every control the other writer changed.
    expect(bodies).toHaveLength(1);
    expect(client.activePreview()).toBeNull();
    expect(client.state()?.current.versionId).toBe('v1');
    // Every change after it is refused before any request until the saved version is restored.
    expect(client.requiresReconciliation()).toBe(true);
    await expect(client.previewUpstream({
      ...COMPANION_PROPOSAL, originReference: 'companion-utterance:77aa',
    })).rejects.toMatchObject({ code: 'saved_style_reconciliation_required' });
    expect(bodies).toHaveLength(1);
  });

  it('keeps a version it wrote while its history was being read', async () => {
    let versionReads = 0;
    const late: { answer?: () => void } = {};
    const fetch = connectedFetch((url) => {
      if (url.pathname.endsWith('/world/styles/versions')) {
        versionReads += 1;
        if (versionReads === 1) return undefined;
        // Asked before the restore below and answered after it, with the history as it was asked.
        return new Promise<Response>((resolve) => {
          late.answer = () => resolve(json([version('v0', 0), version('v1', 1, 0.55)]));
        });
      }
      if (url.pathname.endsWith('/world/styles/rollback')) return json(version('v2', 2));
      return undefined;
    });
    const client = new WorldStyleClient({
      worldId: TEST_WORLD, baseUrl: 'https://exulanica.test/api', token: 't', fetch,
    });
    await client.connect();
    const read = client.refreshVersions();
    await vi.waitFor(() => expect(late.answer).toBeDefined());
    expect((await client.rollback('v0')).kind).toBe('applied');
    late.answer?.();

    await read;

    expect(client.versions().map((listed) => listed.versionId)).toEqual(['v0', 'v1', 'v2']);
  });

  it('is let go before the world is read again, so a failed read leaves nothing held', async () => {
    let currentReads = 0;
    const fetch = connectedFetch((url, init) => {
      if (url.pathname.endsWith('/world/styles/current')) {
        currentReads += 1;
        return currentReads === 1 ? json(state()) : json({ code: 'internal_error', detail: 'no' }, 500);
      }
      if (url.pathname.endsWith('/world/styles/previews') && init.method === 'POST') {
        const body = JSON.parse(String(init.body)) as Record<string, unknown>;
        return json(preview('preview-1', String(body['proposalId'])), 201);
      }
      if (url.pathname.endsWith('/apply')) {
        return json({ code: 'stale_style_version', detail: 'another writer won' }, 409);
      }
      return undefined;
    });
    const client = new WorldStyleClient({
      worldId: TEST_WORLD,
      baseUrl: 'https://exulanica.test/api', token: 't', fetch, ids: () => 'proposal-companion',
    });
    await client.connect();
    await client.previewUpstream(COMPANION_PROPOSAL);

    await expect(client.applyActive()).rejects.toMatchObject({ code: 'internal_error' });

    expect(currentReads).toBe(2);
    expect(client.activePreview()).toBeNull();
  });

  it('is refused, not made on the newer version, when its preview meets a stale base', async () => {
    const bodies: Record<string, unknown>[] = [];
    const current = movedOn();
    const fetch = connectedFetch((url, init) => {
      if (url.pathname.endsWith('/world/styles/current')) return current();
      if (url.pathname.endsWith('/world/styles/previews') && init.method === 'POST') {
        const body = JSON.parse(String(init.body)) as Record<string, unknown>;
        bodies.push(body);
        // The first is made; by the second, another writer has moved the world on.
        return bodies.length === 1
          ? json(preview('preview-1', String(body['proposalId'])), 201)
          : json({ code: 'stale_style_version', detail: 'another writer won' }, 409);
      }
      return undefined;
    });
    const ids = ['proposal-first', 'proposal-second'];
    const client = new WorldStyleClient({
      worldId: TEST_WORLD,
      baseUrl: 'https://exulanica.test/api', token: 't', fetch, ids: () => ids.shift()!,
    });
    await client.connect();
    const first = await client.previewUpstream(COMPANION_PROPOSAL);

    const refused = client.previewUpstream({
      ...COMPANION_PROPOSAL, originReference: 'companion-utterance:77aa',
    });
    await expect(refused).rejects.toBeInstanceOf(StaleProposalError);
    await expect(refused).rejects.toMatchObject({ code: 'stale_proposal', reconciliationRequired: true });
    await expect(refused).rejects.toThrow(RESTORE_BEFORE_CHANGING);

    // The draft names no base, so this client cannot tell a draft of v0 from one of v1.
    expect(bodies).toHaveLength(2);
    // A refused request leaves the previous one staged. The live appearance moved from the one
    // this page shows, so the next is refused before any request until the saved version is
    // restored.
    expect(client.activePreview()).toBe(first);
    expect(client.state()?.current.versionId).toBe('v1');
    await expect(client.previewUpstream({
      ...COMPANION_PROPOSAL, originReference: 'companion-utterance:3c3c',
    })).rejects.toMatchObject({ code: 'saved_style_reconciliation_required' });
    expect(bodies).toHaveLength(2);
  });

  it('is let go when the authority says it expired, from either origin, and nothing is made again', async () => {
    for (const origin of ['settings', 'companion'] as const) {
      const bodies: Record<string, unknown>[] = [];
      const fetch = connectedFetch((url, init) => {
        if (url.pathname.endsWith('/world/styles/previews') && init.method === 'POST') {
          const body = JSON.parse(String(init.body)) as Record<string, unknown>;
          bodies.push(body);
          return json(preview('preview-1', String(body['proposalId'])), 201);
        }
        if (url.pathname.endsWith('/apply')) {
          return json({ code: 'preview_expired', detail: 'world preview preview-1 expired' }, 409);
        }
        return undefined;
      });
      const client = new WorldStyleClient({
        worldId: TEST_WORLD,
        baseUrl: 'https://exulanica.test/api', token: 't', fetch, ids: () => `proposal-${origin}`,
      });
      await client.connect();
      if (origin === 'settings') {
        await client.previewSettings({
          profileId: 'origin-landscape', profileVersion: 1, parameters: { vitality: 0.4 },
        });
      } else {
        await client.previewUpstream(COMPANION_PROPOSAL);
      }

      const result = await client.applyActive();

      // The world did not move, so this page may change it again at once.
      expect(result, origin).toMatchObject({ kind: 'expired', reconciliationRequired: false });
      expect(bodies, origin).toHaveLength(1);
      expect(client.activePreview(), origin).toBeNull();
    }
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
    const fetch = connectedFetch((url, init) => {
      if (url.pathname.endsWith('/current')) return json({ current_topology_digest: 'topology-a', current: saved });
      if (url.pathname.endsWith('/versions')) return json([saved]);
      if (url.pathname.endsWith('/previews') && init.method === 'POST') {
        return json({ ...preview('p', 'proposal'), candidate: saved }, 201);
      }
      return undefined;
    });
    const client = new WorldStyleClient({ worldId: TEST_WORLD,baseUrl:'https://exulanica.test',token:'fixture',fetch});
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
    await expect(new WorldStyleClient({ worldId: TEST_WORLD,baseUrl:'https://exulanica.test',token:'fixture',fetch}).connect()).rejects.toThrow('not executable');
  });
});
