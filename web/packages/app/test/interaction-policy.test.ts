import { describe, expect, it, vi } from 'vitest';
import { DEFAULT_PREFERENCES } from '../src/preferences.js';
import {
  InteractionPolicyClient,
  preferencesFromInteractionPolicy,
} from '../src/interaction-policy.js';

/** The world these clients are opened for. */
const TEST_WORLD = 'world:personal:test';

const json = (body: unknown, status = 200): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });

const emptyState = {
  current: null,
  parameters: {
    'comfort.field-of-view-degrees': 70,
    'comfort.look-sensitivity-milli': 1000,
    'comfort.vignette': 'subtle',
    'comfort.camera-bob': false,
    'navigation.turn-mode': 'smooth',
    'navigation.transition-style': 'motion',
    'disclosure.provenance-detail': 'standard',
    'initiative.mode': 'normal',
  },
  base_structure_snapshot_id: '00000000-0000-7000-8000-000000000001',
  base_topology_sha256: 'a'.repeat(64),
};

describe('reviewed interaction policy client', () => {
  it('sends only the setting the person changed through preview then apply', async () => {
    const requests: { url: string; init?: RequestInit }[] = [];
    const fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = String(input);
      requests.push({ url, ...(init === undefined ? {} : { init }) });
      if (new URL(url).pathname.endsWith('/current')) return json(emptyState);
      if (new URL(url).pathname.endsWith('/previews')) return json({ preview_id: 'preview-1' }, 201);
      return json({ version_id: 'version-1' });
    });
    const client = new InteractionPolicyClient({
      worldId: TEST_WORLD,
      baseUrl: 'https://exulanica.test/api',
      token: 'secret',
      fetch: fetch as typeof globalThis.fetch,
      ids: () => 'proposal-1',
    });

    await client.syncSettings(
      DEFAULT_PREFERENCES,
      { ...DEFAULT_PREFERENCES, fieldOfView: 82 },
      false,
    );

    expect(requests.map(({ url }) => new URL(url).pathname)).toEqual([
      '/api/world/interactions/current',
      '/api/world/interactions/previews',
      '/api/world/interactions/previews/preview-1/apply',
    ]);
    // Interaction settings belong to a world, and every request names the one this client serves.
    expect(requests.map(({ url }) => new URL(url).searchParams.get('world_id')))
      .toEqual([TEST_WORLD, TEST_WORLD, TEST_WORLD]);
    const proposal = JSON.parse(String(requests[1]!.init!.body));
    expect(proposal).toMatchObject({
      proposal_id: 'proposal-1',
      origin: 'settings',
      origin_reference: 'options-panel',
      base_policy_version_id: null,
      base_structure_snapshot_id: emptyState.base_structure_snapshot_id,
      base_topology_sha256: emptyState.base_topology_sha256,
      capability_patch: { 'comfort.field-of-view-degrees': 82 },
      proposal_input: { control_ids: ['fieldOfView'] },
      reference_ids: [],
      model_id: null,
      prompt_version: null,
    });
    expect(requests[1]!.init!.headers).toMatchObject({ authorization: 'Bearer secret' });
  });

  it('does not write when a device-only setting changes or the server already has the value', async () => {
    const fetch = vi.fn(async () => json(emptyState));
    const client = new InteractionPolicyClient({
      worldId: TEST_WORLD,
      baseUrl: 'https://exulanica.test/api', token: 'secret',
      fetch: fetch as typeof globalThis.fetch,
    });
    await client.syncSettings(
      DEFAULT_PREFERENCES,
      { ...DEFAULT_PREFERENCES, companionSide: 'left' },
      false,
    );
    await client.syncSettings(
      DEFAULT_PREFERENCES,
      { ...DEFAULT_PREFERENCES, fieldOfView: 70 },
      false,
    );
    expect(fetch).not.toHaveBeenCalled();
  });

  it('attributes Companion suggestions to their model, prompt, and evidence references', async () => {
    const bodies: unknown[] = [];
    const fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = String(input);
      if (new URL(url).pathname.endsWith('/current')) return json(emptyState);
      if (new URL(url).pathname.endsWith('/previews')) {
        bodies.push(JSON.parse(String(init!.body)));
        return json({ preview_id: 'preview-c' }, 201);
      }
      return json({ version_id: 'version-c' });
    });
    const client = new InteractionPolicyClient({
      worldId: TEST_WORLD,
      baseUrl: 'https://exulanica.test/api', token: 'secret',
      fetch: fetch as typeof globalThis.fetch, ids: () => 'proposal-c',
    });
    const review = await client.proposeCompanion({
      capabilityPatch: { 'initiative.mode': 'minimal' },
      explanation: 'Recent explicit skips support offering fewer interruptions.',
      referenceIds: ['interaction-event:skip-1'],
      modelId: 'reviewed-personalizer-v1',
      promptVersion: 'interaction-proposal-v3',
      originReference: 'companion-settings-suggestion',
      proposalInput: { observed_choice: 'skip' },
    });
    expect(bodies[0]).toMatchObject({
      origin: 'companion',
      reference_ids: ['interaction-event:skip-1'],
      model_id: 'reviewed-personalizer-v1',
      prompt_version: 'interaction-proposal-v3',
      proposal_input: { observed_choice: 'skip' },
    });
    expect(fetch).toHaveBeenCalledTimes(2);
    await client.applyCompanionReview(review!);
    expect(fetch).toHaveBeenCalledTimes(3);
  });

  it('hydrates durable controls while preserving device-only presentation', () => {
    const hydrated = preferencesFromInteractionPolicy(
      { ...DEFAULT_PREFERENCES, contrast: 'high', companionSide: 'left' },
      {
        ...emptyState.parameters,
        'comfort.field-of-view-degrees': 88,
        'comfort.look-sensitivity-milli': 1500,
        'navigation.transition-style': 'fade',
        'initiative.mode': 'off',
      },
    );
    expect(hydrated).toMatchObject({
      contrast: 'high',
      companionSide: 'left',
      fieldOfView: 88,
      mouseSensitivity: 1.5,
      transition: 'fade',
      companionInitiative: 'off',
    });
  });
});
