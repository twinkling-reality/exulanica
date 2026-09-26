// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  WORLD_STYLE_REGISTRY_DOCUMENT,
  WORLD_STYLE_RECIPES,
  worldStyleRecipe,
} from '@exulanica/presentation';
import type { CompanionSession, Turn } from '@exulanica/companion-runtime';
import {
  CompanionProposalClient,
  PROPOSAL_OUTCOMES,
  REFUSAL_CODES,
  type CompanionAnswer,
  type CompanionProposal,
} from '../src/companion-ask-api.js';
import { mountAppearance } from '../src/composition/appearance.js';
import { mountCompanion, type MountedCompanion } from '../src/composition/companion.js';
import type { AppEnvironment, SessionState } from '../src/composition/session-state.js';
import { DEFAULT_PREFERENCES } from '../src/preferences.js';
import type { ConfirmPanel } from '../src/ui/confirm.js';
import { say } from '../src/ui/copy.js';
import { WorldStyleClient, validateLocalReference } from '../src/world-style-api.js';
import { RESTORE_BEFORE_CHANGING } from '../src/world-style-refusals.js';
import {
  WorldStyleProposalOutcomes,
  worldStyleProposalInbox,
  worldStyleProposalOutcomes,
} from '../src/world-style-proposals.js';

/** The world these clients are opened for. */
const TEST_WORLD = 'world:personal:test';

/**
 * A sentence somebody typed, turned into a change nobody has agreed to yet.
 *
 * The thing under test is the ORDER, and the assertion that matters most in this file is the one
 * that counts zero applies. A proposal reaches the inbox, the inbox reaches the authority, the
 * authority answers with a candidate, and the world is exactly as it was until somebody presses
 * Apply on the surface that is showing it to them.
 *
 * The authority here is a scripted fetch rather than a stub client, so what is asserted is the
 * BODY the browser actually sends: `origin: companion` with a model, a prompt version and at
 * least one reference id is the whole of what makes this different from a slider, and a stubbed
 * client would let a body missing all three pass.
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
  prompt_version: null,
  refines_proposal_id: null,
  ...over,
});

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

// -- the whole path through the appearance surface ---------------------------------------------

interface Harness {
  readonly bodies: Record<string, unknown>[];
  readonly applied: string[];
  readonly deleted: string[];
  readonly mounted: ReturnType<typeof mountAppearance>;
  readonly outcomes: { originReference: string; kind: string; detail: string }[];
  readonly stop: () => void;
  readonly client: WorldStyleClient;
  readonly gets: string[];
  readonly open: unknown[];
  /** Move the world to another version behind this page's back, as another tab applying. */
  readonly setCurrent: (next: ReturnType<typeof version>) => void;
  readonly restored: Record<string, unknown>[];
}

async function harness(over: {
  previewStatus?: number;
  previewBody?: unknown;
  /** Which POSTs to the preview route the authority refuses, by their 1-based order. */
  refuse?: (post: number) => boolean;
  /** The world's open previews, as GET /world/styles/previews answers at connect. */
  open?: unknown[];
  /** The world the page opens, for a page that opens another world. */
  worldId?: string;
  /** A status the read-back answers with instead of the open previews. */
  openStatus?: number;
  /** How many open previews the server says it could not read. */
  unreadable?: number;
  /** A status every discard answers with instead of 204. */
  deleteStatus?: number;
  /** The open previews of another tab's harness, so two tabs look at one world. */
  shared?: unknown[];
  /** Every apply is answered as made against a version that is no longer current. */
  applyStale?: boolean;
  /** Every apply is answered as a preview that outlived the authority's lifetime for one. */
  applyExpired?: boolean;
  /** A status the n-th read of the current version answers with instead of the version, 1-based. */
  currentStatus?: (read: number) => number | undefined;
  /** Every restore meets a saved world another page advanced, as the authority answers it. */
  restoreEntryMoved?: boolean;
  /** The version the world holds when the page opens, for a page opened after another change. */
  start?: ReturnType<typeof version>;
} = {}): Promise<Harness> {
  const bodies: Record<string, unknown>[] = [];
  const applied: string[] = [];
  const deleted: string[] = [];
  const gets: string[] = [];
  /** The world's open previews, oldest first, as the authority holds them: shared by every tab. */
  const open: unknown[] = over.shared ?? [...(over.open ?? [])].reverse();
  /** The version the authority holds as current. Previews and applies on another base are stale. */
  let current = over.start ?? version('v0', 0);
  /** The world's history as the authority serves it, oldest first. */
  const known: ReturnType<typeof version>[] = [version('v0', 0)];
  const remember = (next: ReturnType<typeof version>): void => {
    const at = known.findIndex((item) => item.version_id === next.version_id);
    if (at >= 0) known.splice(at, 1);
    known.push(next);
  };
  if (over.start !== undefined) remember(over.start);
  let currentReads = 0;
  /** The restores (rollbacks) the page asked for. */
  const restored: Record<string, unknown>[] = [];
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
      currentReads += 1;
      const status = over.currentStatus?.(currentReads);
      if (status !== undefined) return json({ code: 'internal_error', detail: 'the read failed' }, status);
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
      if (over.refuse?.(bodies.length) === true) {
        return json({ code: 'invalid_style_data', detail: 'the authority refused this one' }, 422);
      }
      if (over.previewStatus !== undefined) {
        return json(over.previewBody ?? { code: 'invalid_style_data', detail: 'no' }, over.previewStatus);
      }
      if (body['baseStyleVersionId'] !== current.version_id) return stale();
      const previewId = `preview-${bodies.length}`;
      open.push(openFromBody(previewId, body));
      return json(
        {
          preview_id: previewId,
          proposal_id: String(body['proposalId']),
          candidate: version('candidate-1', 0, 0.8, {
            // Echoed from the body. A candidate that ignored what was posted made every
            // assertion about what reached the panel an assertion about this fixture.
            global_style: {
              profile_id: PROFILE.profileId,
              profile_version: PROFILE.profileVersion,
              parameters: (body['profile'] as Record<string, unknown>)['parameters'],
            },
            model_id: body['modelId'],
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
      // Refused by its age, then by its own base check, as the authority checks them, it closes the
      // preview in the same transaction. This page holds no saved world entry, so no entry check
      // answers first.
      if (over.applyExpired === true) {
        close(id);
        return json({ code: 'preview_expired', detail: `world preview ${id} expired` }, 409);
      }
      if (over.applyStale === true || body['baseStyleVersionId'] !== current.version_id) {
        close(id);
        return stale();
      }
      close(id);
      current = version('v1', 1, 0.8);
      remember(current);
      return json(current);
    }
    if (url.pathname.endsWith('/world/styles/rollback') && init.method === 'POST') {
      const body = JSON.parse(String(init.body)) as Record<string, unknown>;
      restored.push(body);
      if (over.restoreEntryMoved === true) {
        return json({ code: 'stale_saved_world_entry', detail: 'the resume point moved' }, 409);
      }
      if (body['baseStyleVersionId'] !== current.version_id) return stale();
      // Every version this page knows carries the saved design, so the restored one does too.
      current = version(`restored-${restored.length}`, current.revision + 1, 0.46, {
        rollback_target_version_id: body['targetVersionId'],
      });
      remember(current);
      return json(current);
    }
    if (url.pathname.includes('/world/styles/previews/') && init.method === 'DELETE') {
      deleted.push(url.pathname);
      if (over.deleteStatus !== undefined) {
        return json({ code: 'internal_error', detail: 'the discard failed' }, over.deleteStatus);
      }
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
  const binding = {
    discardArtProfilePreview: vi.fn(),
    previewArtProfile: vi.fn(() => ({ sessionId: 'preview-session', validation: { ok: true } })),
    setArtProfile: vi.fn(),
    setFieldOfView: vi.fn(),
    setSensitivityMultiplier: vi.fn(),
    setTheme: vi.fn(),
  };
  const state = {
    preferences: DEFAULT_PREFERENCES,
    atlas: { binding },
    worldStyles: client,
    worldStyleConnection: connection,
    worldStyleFailure: null,
    settingsStylePreviewId: null,
    interactionPolicies: null,
    stopWorldStyleProposalInbox: null,
  } as unknown as SessionState;
  const env = {
    shell: document.createElement('div'),
    systemAppearance: { matches: false },
    systemReducedMotion: { matches: false },
    previewArtProfile: null,
  } as unknown as AppEnvironment;

  const outcomes: { originReference: string; kind: string; detail: string }[] = [];
  const stop = worldStyleProposalOutcomes.subscribe((outcome) => {
    outcomes.push({ ...outcome });
  });
  const mounted = mountAppearance({
    env,
    state,
    applyProofLens: vi.fn(),
    setCompanionAppearance: vi.fn(),
    onCloseOptions: vi.fn(),
    onShowControls: vi.fn(),
    onCloseControls: vi.fn(),
    onShowCustomize: vi.fn(),
  });
  // Appended, because `settle` waits on what the panel is SAYING and a detached panel says it
  // to nobody. It is also what a person would be looking at.
  document.body.replaceChildren(mounted.options.root);
  cleanups.push(stop, () => mounted.dispose());
  return {
    bodies, applied, deleted, mounted, outcomes, stop, client, gets, open, restored,
    setCurrent: (next) => {
      current = next;
      remember(next);
    },
  };
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

/**
 * Wait for the inbox listener to finish, rather than for a fixed number of microtasks.
 *
 * `submit` settles only after its listeners, but most tests here do not await it, and the
 * listener makes a real request through the transport. A fixed flush left the panel showing
 * "Validating the upstream proposal" and every assertion after it measuring a half-finished
 * turn.
 */
const IN_FLIGHT = ['Validating the upstream proposal', 'Applying the reviewed preview', 'Checking'];

const settle = async (): Promise<void> => {
  await vi.waitFor(() => {
    const lifecycle = document.querySelector('.world-style-lifecycle')?.textContent ?? '';
    if (IN_FLIGHT.some((phrase) => lifecycle.includes(phrase))) {
      throw new Error(`still working: ${lifecycle}`);
    }
  });
  for (let turn = 0; turn < 4; turn += 1) await Promise.resolve();
};

/**
 * Torn down in `beforeEach` rather than at the end of each test, because a FAILING test never
 * reaches its own cleanup and the outcome channel is a module singleton: one unstopped listener
 * made the next test see two of every outcome and fail for a reason that had nothing to do with
 * it.
 */
const cleanups: (() => void)[] = [];

describe('a Companion proposal through the appearance surface', () => {
  beforeEach(() => {
    while (cleanups.length > 0) cleanups.pop()?.();
    document.body.replaceChildren();
  });

  it('reaches the authority as a companion-origin preview carrying its full provenance', async () => {
    const { bodies } = await harness();

    await expect(worldStyleProposalInbox.submit(COMPANION)).resolves.toBe(true);
    await settle();

    expect(bodies).toHaveLength(1);
    expect(bodies[0]).toMatchObject({
      origin: 'companion',
      originReference: 'companion-utterance:0f2c',
      baseStyleVersionId: 'v0',
      baseTopologyDigest: 'topology-a',
      modelId: 'Qwen/Qwen3-235B-A22B-Instruct-2507',
      promptVersion: 'proposal-1',
      referenceIds: ['00000000-0000-0000-0000-000000000001'],
    });
    const profile = bodies[0]?.['profile'] as Record<string, unknown>;
    expect(profile['parameters']).toMatchObject({ 'horizon-softness': 0.8 });
  });

  it('shows the proposal on the confirmation surface and changes nothing until Apply', async () => {
    const { applied, mounted } = await harness();

    worldStyleProposalInbox.submit(COMPANION);
    await settle();

    // The surface is showing it, with the provenance that makes it reviewable: who proposed it,
    // which model drew it, and how much evidence it named.
    const review = mounted.options.root.querySelector<HTMLElement>(
      '.world-style-proposal-review',
    )!;
    expect(review.hidden).toBe(false);
    expect(review.textContent).toContain('companion proposal ready for review');
    expect(review.textContent).toContain('1 provenance references');
    expect(review.textContent).toContain('Qwen/Qwen3-235B-A22B-Instruct-2507');
    expect(review.textContent).toContain('proposal-1');
    // And this is the assertion the file exists for.
    expect(applied).toEqual([]);
  });

  it('applies only when the surface asks it to, and says so on the return channel', async () => {
    const { applied, outcomes, mounted } = await harness();
    worldStyleProposalInbox.submit(COMPANION);
    await settle();
    expect(outcomes.map((outcome) => outcome.kind)).toEqual(['previewed']);

    // The person's own button, on the panel that is showing it to them. Disabled until there is
    // a draft to accept, which is the whole reason a proposal is staged into the controls.
    const apply = mounted.options.root.querySelector<HTMLButtonElement>('.world-style-apply')!;
    expect(apply.disabled).toBe(false);
    apply.click();
    await settle();

    expect(applied).toHaveLength(1);
    expect(outcomes.map((outcome) => outcome.kind)).toEqual(['previewed', 'accepted']);
    expect(outcomes.at(-1)).toMatchObject({ originReference: 'companion-utterance:0f2c' });
  });

  it('reports a refusal from the authority instead of leaving the proposal in limbo', async () => {
    const { applied, outcomes } = await harness({ previewStatus: 422 });

    worldStyleProposalInbox.submit(COMPANION);
    await settle();

    expect(applied).toEqual([]);
    expect(outcomes).toHaveLength(1);
    expect(outcomes[0]).toMatchObject({
      originReference: 'companion-utterance:0f2c',
      kind: 'refused',
    });
    expect(outcomes[0]?.detail ?? '').toContain('reviewed profile');
  });

  it('refuses a regional proposal in words rather than previewing it as a global change', async () => {
    const { bodies, outcomes } = await harness();

    worldStyleProposalInbox.submit({ ...COMPANION, scope: { kind: 'region', islandId: 'region-a' } });
    await settle();

    expect(bodies).toEqual([]);
    expect(outcomes[0]).toMatchObject({ kind: 'refused' });
  });

  it('says nothing on the channel about a Settings change, which nobody is waiting to hear', async () => {
    const { bodies, outcomes, mounted } = await harness();

    const softness = mounted.options.root.querySelector<HTMLInputElement>(
      '[aria-label="Horizon softness"]',
    )!;
    softness.value = '0.6';
    softness.dispatchEvent(new Event('input', { bubbles: true }));
    // Waited for the SETTINGS PREVIEW to exist, not for a fixed number of microtasks. The panel
    // debounces its server preview by 220 ms, so an assertion taken before that fired proved
    // only that nothing had happened yet, which would have been true of a broken channel too.
    await vi.waitFor(() => {
      expect(bodies.some((body) => body['origin'] === 'settings')).toBe(true);
    }, { timeout: 2000 });
    await settle();

    expect(outcomes).toEqual([]);
  });

  it('says a staged proposal was discarded when a Settings change replaces it', async () => {
    const { bodies, outcomes, mounted } = await harness();
    worldStyleProposalInbox.submit(COMPANION);
    await settle();
    expect(outcomes.map((outcome) => outcome.kind)).toEqual(['previewed']);

    const vitality = mounted.options.root.querySelector<HTMLInputElement>(
      '[aria-label="Color vitality"]',
    )!;
    vitality.value = '0.3';
    vitality.dispatchEvent(new Event('input', { bubbles: true }));
    await vi.waitFor(() => {
      expect(bodies.some((body) => body['origin'] === 'settings')).toBe(true);
    }, { timeout: 2000 });
    await settle();

    // The proposal is gone and the Companion is told, so its memory does not hold a proposal
    // with no outcome for ever.
    expect(outcomes.map((outcome) => outcome.kind)).toEqual(['previewed', 'discarded']);
    expect(outcomes.at(-1)).toMatchObject({ originReference: 'companion-utterance:0f2c' });
  });

  it('stages every control a proposal moves, not just the first', async () => {
    // The panel re-renders on each reported change and rewrites every style input from its own
    // draft, so writing all the values and dispatching afterwards staged exactly one control and
    // silently dropped the rest. The live run proposed five at once.
    const { bodies, mounted } = await harness();
    worldStyleProposalInbox.submit({
      ...COMPANION,
      profile: {
        ...PROFILE,
        parameters: {
          ...PARAMETERS,
          'horizon-softness': 0.8,
          vitality: 0.3,
          glass: 0.4,
        },
      },
    });
    await settle();

    expect(bodies).toHaveLength(1);
    const value = (label: string): string =>
      mounted.options.root.querySelector<HTMLInputElement>(`[aria-label="${label}"]`)!.value;
    expect(value('Horizon softness')).toBe('0.8');
    expect(value('Color vitality')).toBe('0.3');
    expect(value('Veil clarity')).toBe('0.4');
    const apply = mounted.options.root.querySelector<HTMLButtonElement>('.world-style-apply')!;
    expect(apply.disabled).toBe(false);
  });

  it('refuses rather than applying a value the control would silently rewrite', async () => {
    /*
     * A real range input rounds its value to the declared step: 0.51 on a step of 0.05 becomes
     * 0.50, and the person would apply a value the authority never validated. happy-dom clamps
     * to min and max but does NOT snap to step, so the DOM behaviour this guards against cannot
     * be produced here. The guard's own logic is what is tested: a control that reports back
     * something other than what it was given refuses the staging rather than proceeding.
     *
     * The other half of the pair is enforced where it can be: the drafter's generated schema
     * carries each control's step, so an off-step value cannot be proposed at all. That is
     * asserted in tests/test_selection_proposal.py.
     */
    const { outcomes, mounted } = await harness();
    const softness = mounted.options.root.querySelector<HTMLInputElement>(
      '[aria-label="Horizon softness"]',
    )!;
    Object.defineProperty(softness, 'value', {
      configurable: true,
      get: () => '0.5',
      set: () => undefined,
    });

    worldStyleProposalInbox.submit(COMPANION);
    await settle();

    // No 'previewed' at all: the reviewed preview is discarded before anybody is told there is
    // something to confirm, so the Companion never says "nothing has changed yet" about a
    // change the panel could not show.
    expect(outcomes.map((outcome) => outcome.kind)).toEqual(['refused']);
    expect(outcomes.at(-1)?.detail).toContain('cannot be shown on this panel');
    const apply = mounted.options.root.querySelector<HTMLButtonElement>('.world-style-apply')!;
    expect(apply.disabled).toBe(true);
  });
});

// -- a staged proposal waits for the person ----------------------------------------------------

/** A request the Companion drew a change for, as the proposal route's client hands it over. */
const DRAWN: CompanionProposal = {
  utterance: 'could the horizon be softer in here',
  classification: 'appearance',
  proposal: {
    ...PROFILE,
    parameters: { ...PARAMETERS, 'horizon-softness': 0.8 },
    modules: ['aeroheart-optics-v1'],
    changed: ['horizon-softness'],
    referenceIds: ['00000000-0000-0000-0000-000000000001'],
    modelId: 'Qwen/Qwen3-235B-A22B-Instruct-2507',
    promptVersion: 'proposal-1',
    spoken: 'The horizon will sit softer, so the far edge reads as distance.',
  },
  refusal: null,
  promptVersion: 'proposal-1',
  calls: [],
};

/** A turn with nothing to attach a change to, so free text is asked or proposed. */
const ACKNOWLEDGE = {
  turnId: 'turn-ack',
  intent: 'acknowledge',
  subjectEntityId: null,
  subjectAnchorId: null,
  utteranceKey: 'utterance.acknowledge',
  utterance: null,
  evidence: [],
  choiceSet: null,
  freeTextAllowed: true,
  escapes: [],
  stateVersion: 1,
} as unknown as Turn;

/**
 * The Companion over the appearance surface `harness` mounts, drawing `DRAWN` for any sentence.
 * Mounted after `harness`, which replaces the document's children.
 */
function companionOver(): { mounted: MountedCompanion; remembered: CompanionAnswer[] } {
  Object.defineProperty(document, 'pointerLockElement', { value: null, configurable: true });
  (document as unknown as { exitPointerLock: () => void }).exitPointerLock = () => undefined;
  const remembered: CompanionAnswer[] = [];
  const mounted = mountCompanion({
    state: { preferences: DEFAULT_PREFERENCES } as unknown as SessionState,
    engine: {
      advance: () => ACKNOWLEDGE,
      say: () => ({ kind: 'refused', reasonKey: 'refused.couldNotParse' }),
      adoptPersistedMemory: () => undefined,
      lastAnswer: null,
    } as unknown as CompanionSession,
    evidence: { open: vi.fn() } as never,
    ask: async () => {
      throw new Error('a request to change the world is not asked as a question');
    },
    proposeAppearance: async () => DRAWN,
    rememberAnswer: async (answer) => {
      remembered.push(answer);
    },
    confirm: () => ({ show: vi.fn(), hide: vi.fn(), reportFailure: vi.fn() }) as unknown as
      ConfirmPanel,
    reflectShell: vi.fn(),
    onAnswered: vi.fn(),
    isSystemSurfaceOpen: () => false,
  });
  cleanups.push(() => mounted.dispose());
  return { mounted, remembered };
}

describe('what the Companion says of a proposal, once the authority has answered it', () => {
  beforeEach(() => {
    while (cleanups.length > 0) cleanups.pop()?.();
    document.body.replaceChildren();
  });

  it('says one refusal, keeps one row and never says Open Customize when it is refused', async () => {
    const { bodies, outcomes } = await harness({ refuse: () => true });
    const { mounted, remembered } = companionOver();
    mounted.summon();

    mounted.controller.say(DRAWN.utterance);
    await vi.waitFor(() => expect(mounted.controller.answer()).not.toBeNull());
    await settle();

    expect(bodies).toHaveLength(1);
    expect(outcomes.map((outcome) => outcome.kind)).toEqual(['refused']);
    const spoken = mounted.panel.root.textContent ?? '';
    expect(spoken).toContain(say('proposal.outcome.refused'));
    // The surface's own words for the refusal, as it reported them, under the reviewed sentence.
    expect(outcomes[0]?.detail).not.toBe('');
    expect(spoken).toContain(outcomes[0]?.detail);
    expect(spoken).not.toContain('Open Customize');
    expect(spoken).not.toContain(DRAWN.proposal!.spoken);
    expect(mounted.controller.answer()?.provenance.composed).toBe('unshown');
    expect(remembered).toHaveLength(1);
  });

  it('says the change waits in Customize once the authority has shown it there', async () => {
    const { outcomes, mounted: surface } = await harness();
    const { mounted, remembered } = companionOver();
    mounted.summon();

    mounted.controller.say(DRAWN.utterance);
    await vi.waitFor(() => expect(mounted.controller.answer()).not.toBeNull());
    await settle();

    expect(outcomes.map((outcome) => outcome.kind)).toEqual(['previewed']);
    expect(
      surface.options.root.querySelector<HTMLElement>('.world-style-proposal-review')?.hidden,
    ).toBe(false);
    const spoken = mounted.panel.root.textContent ?? '';
    expect(spoken).toContain(DRAWN.proposal!.spoken);
    expect(spoken).toContain(say('proposal.staged'));
    expect(mounted.controller.answer()?.provenance.composed).toBe('proposed');
    expect(remembered).toHaveLength(1);
  });
});

describe('a staged Companion proposal until the person decides', () => {
  beforeEach(() => {
    while (cleanups.length > 0) cleanups.pop()?.();
    document.body.replaceChildren();
  });

  const lifecycle = (): string | undefined =>
    document.querySelector<HTMLElement>('.world-style-lifecycle')?.dataset['state'];
  const reviewShown = (mounted: Harness['mounted']): boolean =>
    !mounted.options.root.querySelector<HTMLElement>('.world-style-proposal-review')!.hidden;

  it('survives the shell hiding Customize, as closing the Companion does', async () => {
    const { deleted, outcomes, mounted, applied } = await harness();
    worldStyleProposalInbox.submit(COMPANION);
    await settle();
    expect(outcomes.map((outcome) => outcome.kind)).toEqual(['previewed']);

    // What reflectShell does on every shell change: Customize is not the primary surface.
    mounted.options.setVisible(false);
    mounted.options.setVisible(false);
    await settle();

    expect(deleted).toEqual([]);
    expect(outcomes.map((outcome) => outcome.kind)).toEqual(['previewed']);
    expect(lifecycle()).toBe('ready');
    expect(reviewShown(mounted)).toBe(true);

    // Opened later, it is still there to accept.
    mounted.options.setVisible(true);
    const apply = mounted.options.root.querySelector<HTMLButtonElement>('.world-style-apply')!;
    expect(apply.disabled).toBe(false);
    apply.click();
    await settle();
    expect(applied).toHaveLength(1);
    expect(outcomes.map((outcome) => outcome.kind)).toEqual(['previewed', 'accepted']);
  });

  it('survives the person closing Customize without deciding', async () => {
    const { deleted, outcomes, mounted } = await harness();
    worldStyleProposalInbox.submit(COMPANION);
    await settle();
    mounted.options.setVisible(true);
    mounted.options.root.querySelector<HTMLButtonElement>('.overlay-close')!.click();
    await settle();

    expect(deleted).toEqual([]);
    expect(outcomes.map((outcome) => outcome.kind)).toEqual(['previewed']);
    expect(reviewShown(mounted)).toBe(true);
  });

  it('is thrown away when the person undoes it in Customize', async () => {
    const { deleted, outcomes, mounted } = await harness();
    worldStyleProposalInbox.submit(COMPANION);
    await settle();
    [...mounted.options.root.querySelectorAll('button')]
      .find((button) => button.textContent === 'Undo preview')!
      .click();
    await settle();
    // Reported once the authority has answered the discard, which is a request of its own.
    await vi.waitFor(() => expect(outcomes).toHaveLength(2));

    expect(deleted).toHaveLength(1);
    expect(outcomes.map((outcome) => outcome.kind)).toEqual(['previewed', 'discarded']);
    expect(lifecycle()).toBe('idle');
  });

  it('gives way to another proposal, which is the one the panel then holds', async () => {
    const { outcomes, mounted, applied, bodies } = await harness();
    worldStyleProposalInbox.submit(COMPANION);
    await settle();
    const second = {
      ...COMPANION,
      originReference: 'companion-utterance:77aa',
      profile: { ...PROFILE, parameters: { ...PARAMETERS, vitality: 0.5 } },
    };
    worldStyleProposalInbox.submit(second);
    await settle();
    mounted.options.setVisible(false);
    await settle();

    expect(outcomes.map((o) => [o.originReference, o.kind])).toEqual([
      ['companion-utterance:0f2c', 'previewed'],
      ['companion-utterance:0f2c', 'discarded'],
      ['companion-utterance:77aa', 'previewed'],
    ]);
    const draft = mounted.options.preferences().worldStyleParameters;
    expect(draft['vitality']).toBe(0.5);
    expect(draft['horizon-softness']).toBe(PARAMETERS['horizon-softness']);
    mounted.options.root.querySelector<HTMLButtonElement>('.world-style-apply')!.click();
    await settle();
    expect(applied).toHaveLength(1);
    expect(bodies.every((body) => body['origin'] === 'companion')).toBe(true);
    expect(outcomes.at(-1)).toMatchObject({
      originReference: 'companion-utterance:77aa', kind: 'accepted',
    });
  });

  it('still throws away the panel\'s own draft when the panel is hidden', async () => {
    const { bodies, deleted, mounted } = await harness();
    // A person moves a control on the open panel.
    mounted.options.setVisible(true);
    const vitality = mounted.options.root.querySelector<HTMLInputElement>(
      '[aria-label="Color vitality"]',
    )!;
    vitality.value = '0.3';
    vitality.dispatchEvent(new Event('input', { bubbles: true }));
    await vi.waitFor(() => {
      expect(bodies.some((body) => body['origin'] === 'settings')).toBe(true);
    }, { timeout: 2000 });
    await settle();
    expect(mounted.options.preferences().worldStyleParameters['vitality']).toBe(0.3);

    mounted.options.setVisible(false);
    await settle();

    expect(deleted).toHaveLength(1);
    expect(mounted.options.preferences().worldStyleParameters['vitality'])
      .toBe(DEFAULT_PREFERENCES.worldStyleParameters['vitality']);
  });
});

// -- a refused second proposal, and a staged proposal across a reload -----------------------------

const SECOND = {
  ...COMPANION,
  originReference: 'companion-utterance:77aa',
  profile: { ...PROFILE, parameters: { ...PARAMETERS, vitality: 0.5 } },
};

/** A third, asked after a refusal. */
const THIRD = {
  ...COMPANION,
  originReference: 'companion-utterance:3c3c',
  profile: { ...PROFILE, parameters: { ...PARAMETERS, glass: 0.5 } },
};

/** One open preview as GET /world/styles/previews answers, with the proposal it was made from. */
const openPreview = (over: {
  id: string;
  origin?: 'companion' | 'settings';
  reference?: string;
  base?: string;
  softness?: number;
  /** Another reviewed profile than the world's, which this panel cannot show. */
  profile?: { readonly profileId: string; readonly profileVersion: number };
}) => {
  const origin = over.origin ?? 'companion';
  const companion = origin === 'companion';
  const provenance = {
    origin,
    actor: 'actor-1',
    origin_reference: companion ? (over.reference ?? `companion-utterance:${over.id}`) : 'appearance-panel',
  };
  const profile = over.profile ?? PROFILE;
  const parameters = over.profile === undefined
    ? { ...PARAMETERS, 'horizon-softness': over.softness ?? 0.8 }
    : validateLocalReference(over.profile).parameters;
  const other = over.profile === undefined ? {} : {
    global_style: { profile_id: profile.profileId, profile_version: profile.profileVersion, parameters },
    recipe_binding: binding(profile),
    capability_mapping: binding(profile).capabilityMapping,
  };
  return {
    preview: {
      preview_id: `preview-${over.id}`,
      proposal_id: `proposal-${over.id}`,
      candidate: version(`candidate-${over.id}`, 0, over.softness ?? 0.8, {
        provenance,
        model_id: companion ? COMPANION.modelId : null,
        prompt_version: companion ? COMPANION.promptVersion : null,
        reference_ids: companion ? COMPANION.referenceIds : [],
        ...other,
      }),
      created_at: '2026-09-10T09:01:00Z',
    },
    proposal: {
      proposal_id: `proposal-${over.id}`,
      provenance,
      scope: { kind: 'global', region_id: null },
      base_style_version_id: over.base ?? 'v0',
      base_topology_digest: 'topology-a',
      profile: { profile_id: profile.profileId, profile_version: profile.profileVersion, parameters },
      reference_ids: companion ? COMPANION.referenceIds : [],
      model_id: companion ? COMPANION.modelId : null,
      prompt_version: companion ? COMPANION.promptVersion : null,
      refines_proposal_id: null,
      recipe_binding: binding(profile),
      capability_mapping: binding(profile).capabilityMapping,
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

describe('a second proposal the authority refuses', () => {
  beforeEach(() => {
    while (cleanups.length > 0) cleanups.pop()?.();
    document.body.replaceChildren();
  });

  it('leaves the first staged, says the second was refused, and applies the first as its own', async () => {
    const { deleted, outcomes, mounted, applied, bodies } = await harness({
      refuse: (post) => post === 2,
    });
    worldStyleProposalInbox.submit(COMPANION);
    await settle();
    worldStyleProposalInbox.submit(SECOND);
    await settle();

    expect(deleted).toEqual([]);
    expect(outcomes.map((o) => [o.originReference, o.kind])).toEqual([
      ['companion-utterance:0f2c', 'previewed'],
      ['companion-utterance:77aa', 'refused'],
    ]);
    expect(mounted.options.preferences().worldStyleParameters['horizon-softness']).toBe(0.8);

    mounted.options.root.querySelector<HTMLButtonElement>('.world-style-apply')!.click();
    await settle();
    expect(applied).toHaveLength(1);
    expect(bodies.every((body) => body['origin'] === 'companion')).toBe(true);
    expect(outcomes.at(-1)).toMatchObject({
      originReference: 'companion-utterance:0f2c', kind: 'accepted',
    });
  });

  it('never applies a proposal\'s values as a Settings change once its preview is gone', async () => {
    const { mounted, applied, bodies, client } = await harness();
    worldStyleProposalInbox.submit(COMPANION);
    await settle();
    // The authority no longer holds it, behind the panel's back.
    await client.discardActive();

    mounted.options.root.querySelector<HTMLButtonElement>('.world-style-apply')!.click();
    await settle();

    expect(applied).toEqual([]);
    expect(bodies.some((body) => body['origin'] === 'settings')).toBe(false);
    expect(document.querySelector<HTMLElement>('.world-style-lifecycle')?.dataset['state'])
      .toBe('failed');
  });
});

describe('a staged proposal the page finds when it opens', () => {
  beforeEach(() => {
    while (cleanups.length > 0) cleanups.pop()?.();
    document.body.replaceChildren();
  });

  const reviewShown = (mounted: Harness['mounted']): boolean =>
    !mounted.options.root.querySelector<HTMLElement>('.world-style-proposal-review')!.hidden;
  const lifecycle = (): string | undefined =>
    document.querySelector<HTMLElement>('.world-style-lifecycle')?.dataset['state'];

  it('is staged again after a reload, and applies as the proposal it was', async () => {
    const { mounted, deleted, outcomes, applied } = await harness({
      open: [openPreview({ id: 'a', reference: 'companion-utterance:0f2c' })],
    });
    await settle();

    expect(deleted).toEqual([]);
    expect(outcomes).toEqual([]);
    expect(reviewShown(mounted)).toBe(true);
    expect(lifecycle()).toBe('ready');
    expect(mounted.options.preferences().worldStyleParameters['horizon-softness']).toBe(0.8);

    mounted.options.root.querySelector<HTMLButtonElement>('.world-style-apply')!.click();
    await settle();
    expect(applied).toEqual(['/api/world/styles/previews/preview-a/apply']);
    expect(outcomes.at(-1)).toMatchObject({
      originReference: 'companion-utterance:0f2c', kind: 'accepted', earlier: true,
    });
  });

  it('takes up the newest on the current version and closes nothing', async () => {
    const { mounted, deleted, outcomes, open } = await harness({
      open: [
        openPreview({ id: 'new', softness: 0.8 }),
        openPreview({ id: 'panel', origin: 'settings', softness: 0.3 }),
        openPreview({ id: 'old', softness: 0.6 }),
      ],
    });
    await settle();

    expect(deleted).toEqual([]);
    expect(outcomes).toEqual([]);
    expect(open).toHaveLength(3);
    expect(reviewShown(mounted)).toBe(true);
    expect(mounted.options.preferences().worldStyleParameters['horizon-softness']).toBe(0.8);
  });

  it('shows one made against an earlier version as stale, and never applies it', async () => {
    // The world is at v0 and the proposal was drafted against an earlier version: v0 is a later
    // change its whole old design would undo.
    const { mounted, deleted, applied, bodies, outcomes } = await harness({
      open: [openPreview({ id: 'stale', base: 'v-earlier' })],
    });
    await settle();

    expect(deleted).toEqual([]);
    expect(reviewShown(mounted)).toBe(true);
    expect(lifecycle()).toBe('stale');
    // Not the promise of a fresh preview: one found on opening is never re-made.
    expect(document.querySelector('.world-style-lifecycle')?.textContent)
      .toContain('earlier version of your world');

    mounted.options.root.querySelector<HTMLButtonElement>('.world-style-apply')!.click();
    await settle();
    expect(applied).toEqual([]);
    expect(bodies).toEqual([]);
    expect(lifecycle()).toBe('failed');
    expect(outcomes).toEqual([{
      originReference: 'companion-utterance:stale',
      kind: 'refused',
      detail: expect.stringContaining('earlier version of your world'),
      earlier: true,
    }]);
  });

  it('never applies one the authority finds stale, and makes nothing again', async () => {
    const { mounted, deleted, applied, bodies, outcomes } = await harness({
      applyStale: true,
      open: [openPreview({ id: 'looks-current' })],
    });
    await settle();

    mounted.options.root.querySelector<HTMLButtonElement>('.world-style-apply')!.click();
    await settle();

    expect(applied).toEqual(['/api/world/styles/previews/preview-looks-current/apply']);
    // Nothing is made again from the old design, and nothing is left to close: the authority
    // closed the preview in the transaction that refused it.
    expect(bodies).toEqual([]);
    expect(deleted).toEqual([]);
    expect(outcomes.at(-1)).toMatchObject({
      originReference: 'companion-utterance:looks-current', kind: 'refused', earlier: true,
    });
    expect(lifecycle()).toBe('failed');
  });

  it('leaves open one it cannot show, and says so in words the Companion keeps', async () => {
    const { mounted, deleted, outcomes, open } = await harness({
      open: [openPreview({ id: 'other', profile: { profileId: 'survey-relief', profileVersion: 1 } })],
    });
    await settle();

    expect(deleted).toEqual([]);
    expect(open).toHaveLength(1);
    expect(reviewShown(mounted)).toBe(false);
    expect(outcomes).toEqual([{
      originReference: 'companion-utterance:other',
      kind: 'still_open',
      detail: expect.stringContaining('left as it was'),
      earlier: true,
    }]);
    // The world opened and works: a proposal made now stages as usual.
    worldStyleProposalInbox.submit(COMPANION);
    await settle();
    expect(reviewShown(mounted)).toBe(true);
  });

  it('takes up no settings preview another page left open, and leaves it open', async () => {
    const { mounted, deleted, outcomes } = await harness({
      open: [openPreview({ id: 'panel', origin: 'settings' })],
    });
    await settle();

    expect(deleted).toEqual([]);
    expect(outcomes).toEqual([]);
    expect(reviewShown(mounted)).toBe(false);
  });

  it('reads the open previews of the world the page opens, after a switch as on a reload', async () => {
    const { gets, mounted } = await harness({
      worldId: 'world:personal:second',
      open: [openPreview({ id: 'b' })],
    });
    await settle();

    expect(gets).toContain(
      `/api/world/styles/previews?world_id=${encodeURIComponent('world:personal:second')}`,
    );
    expect(reviewShown(mounted)).toBe(true);
  });

  it('still opens the world when the read-back fails, and takes nothing up', async () => {
    const { mounted, deleted } = await harness({ openStatus: 409 });
    await settle();

    expect(deleted).toEqual([]);
    expect(reviewShown(mounted)).toBe(false);
    // The world opened: a proposal made now stages as usual.
    worldStyleProposalInbox.submit(COMPANION);
    await settle();
    expect(reviewShown(mounted)).toBe(true);
  });

  it('skips a row it cannot parse, and one the server could not read, and takes up the next', async () => {
    const broken = { preview: { preview_id: 'preview-broken' }, proposal: { provenance: 'nonsense' } };
    const { mounted, deleted } = await harness({
      unreadable: 2,
      open: [broken, openPreview({ id: 'good', softness: 0.8 })],
    });
    await settle();

    expect(deleted).toEqual([]);
    expect(reviewShown(mounted)).toBe(true);
    expect(mounted.options.preferences().worldStyleParameters['horizon-softness']).toBe(0.8);
  });

  it('leaves a proposal another tab staged open for it, when a second tab opens the world', async () => {
    const first = await harness();
    worldStyleProposalInbox.submit(COMPANION);
    await settle();
    expect(first.open).toHaveLength(1);

    // A second tab on the same world, with its own client and panel, reading the same authority.
    const second = new WorldStyleClient({
      worldId: TEST_WORLD,
      baseUrl: 'https://exulanica.test/api',
      token: 'secret',
      fetch: vi.fn(async (input: string | URL | Request, init: RequestInit = {}) => {
        const url = new URL(String(input));
        if (url.pathname.endsWith('/world/styles/catalog')) return json(catalog());
        if (url.pathname.endsWith('/world/styles/current')) {
          return json({ current_topology_digest: 'topology-a', current: version('v0', 0) });
        }
        if (url.pathname.endsWith('/world/styles/versions')) return json([version('v0', 0)]);
        if (url.pathname.endsWith('/world/styles/previews') && (init.method ?? 'GET') === 'GET') {
          return json({ previews: [...first.open].reverse(), unreadable: 0 });
        }
        throw new Error(`the second tab sent ${init.method ?? 'GET'} ${url.pathname}`);
      }) as unknown as typeof globalThis.fetch,
    });
    await second.connect();

    expect(second.activePreview()?.request.originReference).toBe('companion-utterance:0f2c');
    expect(first.deleted).toEqual([]);
    expect(first.open).toHaveLength(1);
    // The first tab can still apply what it staged.
    first.mounted.options.root.querySelector<HTMLButtonElement>('.world-style-apply')!.click();
    await settle();
    expect(first.applied).toHaveLength(1);
  });
});

describe('a staged proposal the world moved past, or that waited too long', () => {
  beforeEach(() => {
    while (cleanups.length > 0) cleanups.pop()?.();
    document.body.replaceChildren();
  });

  const lifecycle = (): string | undefined =>
    document.querySelector<HTMLElement>('.world-style-lifecycle')?.dataset['state'];
  const lifecycleText = (): string =>
    document.querySelector('.world-style-lifecycle')?.textContent ?? '';
  const reviewShown = (mounted: Harness['mounted']): boolean =>
    !mounted.options.root.querySelector<HTMLElement>('.world-style-proposal-review')!.hidden;
  const applyButton = (mounted: Harness['mounted']): HTMLButtonElement =>
    mounted.options.root.querySelector<HTMLButtonElement>('.world-style-apply')!;
  /** The saved design this page opened on, which is also the panel's applied design. */
  const SAVED = DEFAULT_PREFERENCES.worldStyleParameters;
  /** Another tab applies its own change: vitality moved, everything else as it was. */
  const elsewhere = () => version('v1', 1, 0.46, {
    global_style: {
      profile_id: PROFILE.profileId,
      profile_version: PROFILE.profileVersion,
      parameters: { ...PARAMETERS, vitality: 0.3 },
    },
  });
  /** Move one control by hand, as a person would, and read the settings preview it posts. */
  const nudge = async (
    h: Harness,
    label: string,
    value: string,
  ): Promise<Record<string, unknown>> => {
    const settings = (): number => h.bodies.filter((body) => body['origin'] === 'settings').length;
    const before = settings();
    const input = h.mounted.options.root.querySelector<HTMLInputElement>(`[aria-label="${label}"]`)!;
    input.value = value;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    await vi.waitFor(() => expect(settings()).toBe(before + 1), { timeout: 2000 });
    await settle();
    return (h.bodies.at(-1)!['profile'] as { parameters: Record<string, unknown> }).parameters;
  };

  const HISTORY = 'select[aria-label="World design history"]';
  /** The versions Version history lists, as their ids. */
  const historyOptions = (h: Harness): string[] =>
    [...h.mounted.options.root.querySelectorAll<HTMLOptionElement>(`${HISTORY} option`)]
      .map((option) => option.value);
  /** What the refusal says to do: choose the saved version in Version history and restore it. */
  const restoreSaved = (h: Harness, saved: string): void => {
    const history = h.mounted.options.root.querySelector<HTMLSelectElement>(HISTORY)!;
    history.value = saved;
    history.dispatchEvent(new Event('change', { bubbles: true }));
    const restore = [...h.mounted.options.root.querySelectorAll('button')]
      .find((button) => button.textContent === 'Restore selected version')!;
    expect(restore.disabled).toBe(false);
    restore.click();
  };
  /** Move one control and wait until the authority has answered its Settings preview. */
  const changeGoesThrough = async (h: Harness): Promise<void> => {
    const vitality = h.mounted.options.root.querySelector<HTMLInputElement>(
      '[aria-label="Color vitality"]',
    )!;
    const before = h.bodies.filter((body) => body['origin'] === 'settings').length;
    vitality.value = vitality.value === '0.3' ? '0.4' : '0.3';
    vitality.dispatchEvent(new Event('input', { bubbles: true }));
    await vi.waitFor(() => {
      expect(h.bodies.filter((body) => body['origin'] === 'settings').length).toBe(before + 1);
    }, { timeout: 2000 });
    await settle();
    expect(lifecycle()).toBe('ready');
  };

  it('refuses one staged on this page once another writer changed the world, and makes nothing again', async () => {
    const h = await harness();
    worldStyleProposalInbox.submit(COMPANION);
    await settle();
    h.setCurrent(elsewhere());

    applyButton(h.mounted).click();
    await settle();

    expect(h.applied).toHaveLength(1);
    // Not made again against the newer version, and nothing left to discard: the authority
    // closed it in the transaction that refused it.
    expect(h.bodies).toHaveLength(1);
    expect(h.deleted).toEqual([]);
    expect(lifecycle()).toBe('failed');
    expect(lifecycleText()).toContain('earlier version of your world');
    // Apply found the live appearance moved from the one this page shows: every change is held
    // back until the saved version is restored, which the words say, and not "ask again".
    expect(lifecycleText()).toContain(RESTORE_BEFORE_CHANGING);
    expect(lifecycleText()).not.toContain('Ask again');
    expect(h.outcomes.map((outcome) => outcome.kind)).toEqual(['previewed', 'refused']);
    // Version history lists the writer's version beside the saved one: what a restore replaces.
    await vi.waitFor(() => expect(historyOptions(h)).toEqual(['v0', 'v1']), { timeout: 2000 });
    expect(lifecycleText()).toContain(RESTORE_BEFORE_CHANGING);
    expect(h.outcomes.at(-1)?.detail).toContain(RESTORE_BEFORE_CHANGING);
    expect(h.client.activePreview()).toBeNull();
    expect(h.client.requiresReconciliation()).toBe(true);
    expect(reviewShown(h.mounted)).toBe(false);
    // The panel stays on the version it shows: none of the proposal's values, and not the other
    // writer's change, which this page cannot build on.
    expect(h.mounted.options.preferences().worldStyleParameters).toEqual(SAVED);
    expect(applyButton(h.mounted).disabled).toBe(true);
  });

  it('then refuses a moved control and a new proposal until the saved version is restored, as it says', async () => {
    const h = await harness();
    worldStyleProposalInbox.submit(COMPANION);
    await settle();
    h.setCurrent(elsewhere());
    applyButton(h.mounted).click();
    await settle();
    expect(h.bodies).toHaveLength(1);

    const vitality = h.mounted.options.root.querySelector<HTMLInputElement>(
      '[aria-label="Color vitality"]',
    )!;
    vitality.value = '0.3';
    vitality.dispatchEvent(new Event('input', { bubbles: true }));
    await vi.waitFor(() => expect(lifecycleText()).toContain('Restore this saved appearance'), {
      timeout: 2000,
    });
    await settle();
    expect(h.bodies).toHaveLength(1);

    worldStyleProposalInbox.submit(THIRD);
    await settle();
    expect(h.bodies).toHaveLength(1);
    expect(h.outcomes.at(-1)).toMatchObject({ originReference: THIRD.originReference, kind: 'refused' });
    expect(h.outcomes.at(-1)?.detail).toContain('Restore this saved appearance');

    // What the words said, after a writer that left the saved world alone: restore the saved
    // version from Version history, which replaces the change, and the next change goes through
    // with no reload.
    const refusal = h.outcomes.find((outcome) => outcome.kind === 'refused')?.detail ?? '';
    expect(refusal).toMatch(/restore your saved version in Version history/);
    await vi.waitFor(() => expect(historyOptions(h)).toEqual(['v0', 'v1']), { timeout: 2000 });
    restoreSaved(h, 'v0');
    await vi.waitFor(() => expect(lifecycle()).toBe('saved'), { timeout: 2000 });
    expect(h.restored).toMatchObject([{ targetVersionId: 'v0', baseStyleVersionId: 'v1' }]);
    expect(h.client.requiresReconciliation()).toBe(false);
    await changeGoesThrough(h);
  });

  it('after a preview found the move, the restore it names works with no reload', async () => {
    const h = await harness();
    worldStyleProposalInbox.submit(COMPANION);
    await settle();
    h.setCurrent(elsewhere());
    worldStyleProposalInbox.submit(SECOND);
    await settle();
    expect(h.outcomes.at(-1)).toMatchObject({ originReference: SECOND.originReference, kind: 'refused' });
    expect(h.outcomes.at(-1)?.detail).toContain(RESTORE_BEFORE_CHANGING);
    expect(lifecycleText()).toMatch(/restore your saved version in Version history/);
    await vi.waitFor(() => expect(historyOptions(h)).toEqual(['v0', 'v1']), { timeout: 2000 });

    restoreSaved(h, 'v0');
    await vi.waitFor(() => expect(lifecycle()).toBe('saved'), { timeout: 2000 });

    expect(h.restored).toMatchObject([{ targetVersionId: 'v0', baseStyleVersionId: 'v1' }]);
    await changeGoesThrough(h);
  });

  it('after another page advanced the saved world, the restore asks for a reload, after which a change goes through', async () => {
    const h = await harness({ restoreEntryMoved: true });
    worldStyleProposalInbox.submit(COMPANION);
    await settle();
    h.setCurrent(elsewhere());
    worldStyleProposalInbox.submit(SECOND);
    await settle();
    expect(h.outcomes.at(-1)?.detail).toContain(RESTORE_BEFORE_CHANGING);
    expect(lifecycleText()).toMatch(
      /restore your saved version in Version history, .* and reload if it asks you to\./,
    );
    await vi.waitFor(() => expect(historyOptions(h)).toEqual(['v0', 'v1']), { timeout: 2000 });

    restoreSaved(h, 'v0');
    await vi.waitFor(() => expect(lifecycle()).toBe('failed'), { timeout: 2000 });

    // "... and reload if it asks you to": it does.
    expect(lifecycleText()).toContain('Reload before trying again');
    expect(h.restored).toHaveLength(1);
    // The reloaded page opens the saved world as another page left it, live, and a change goes
    // through.
    const reloaded = await harness({ start: elsewhere() });
    expect(reloaded.client.requiresReconciliation()).toBe(false);
    await changeGoesThrough(reloaded);
  });

  it('keeps the words of a refusal that arrived while Customize was hidden until it is shown', async () => {
    const h = await harness();
    // The person opens the Companion, so the shell hides Customize.
    h.mounted.options.setVisible(true);
    h.mounted.options.setVisible(false);
    await settle();
    h.setCurrent(elsewhere());
    worldStyleProposalInbox.submit(SECOND);
    await settle();
    expect(lifecycleText()).toContain(RESTORE_BEFORE_CHANGING);

    // The Companion closes: the shell reports Customize hidden again, twice, as reflectShell does,
    // and then the person opens Customize.
    h.mounted.options.setVisible(false);
    h.mounted.options.setVisible(false);
    await settle();
    h.mounted.options.setVisible(true);

    expect(lifecycle()).toBe('failed');
    expect(lifecycleText()).toContain(RESTORE_BEFORE_CHANGING);
  });

  it('takes a refused proposal off the panel even when the world cannot be read after it', async () => {
    // The second read of the current version is the one after the refusal; it fails.
    const h = await harness({ currentStatus: (read) => (read === 2 ? 500 : undefined) });
    worldStyleProposalInbox.submit(COMPANION);
    await settle();
    h.setCurrent(elsewhere());

    applyButton(h.mounted).click();
    await settle();

    expect(h.applied).toHaveLength(1);
    expect(lifecycle()).toBe('failed');
    expect(h.outcomes.map((outcome) => outcome.kind)).toEqual(['previewed', 'refused']);
    expect(h.client.activePreview()).toBeNull();
    expect(reviewShown(h.mounted)).toBe(false);
    expect(h.mounted.options.preferences().worldStyleParameters).toEqual(SAVED);

    // A moved control proposes the person's change on the design they see, never the proposal's
    // values, whatever becomes of that Settings draft afterwards.
    const vitality = h.mounted.options.root.querySelector<HTMLInputElement>(
      '[aria-label="Color vitality"]',
    )!;
    vitality.value = '0.3';
    vitality.dispatchEvent(new Event('input', { bubbles: true }));
    await vi.waitFor(() => {
      expect(h.bodies.some((body) => body['origin'] === 'settings')).toBe(true);
    }, { timeout: 2000 });
    await settle();
    const settings = h.bodies.filter((body) => body['origin'] === 'settings');
    for (const body of settings) {
      const parameters = (body['profile'] as { parameters: Record<string, unknown> }).parameters;
      expect(parameters).toEqual({ ...SAVED, vitality: 0.3 });
    }
  });

  it('refuses a proposal whose preview meets a newer version, and then the one staged before it', async () => {
    const h = await harness();
    worldStyleProposalInbox.submit(COMPANION);
    await settle();
    h.setCurrent(elsewhere());

    worldStyleProposalInbox.submit(SECOND);
    await settle();

    // One POST each: the second met the newer version and was not made again on it.
    expect(h.bodies).toHaveLength(2);
    expect(h.deleted).toEqual([]);
    expect(h.outcomes.map((o) => [o.originReference, o.kind])).toEqual([
      ['companion-utterance:0f2c', 'previewed'],
      ['companion-utterance:77aa', 'refused'],
    ]);
    expect(h.outcomes.at(-1)?.detail).toContain('changed elsewhere');
    expect(h.outcomes.at(-1)?.detail).toContain(RESTORE_BEFORE_CHANGING);
    expect(lifecycle()).toBe('failed');

    // Asking again before a reload is refused before any request.
    worldStyleProposalInbox.submit(THIRD);
    await settle();
    expect(h.bodies).toHaveLength(2);
    expect(h.outcomes.at(-1)).toMatchObject({ originReference: THIRD.originReference, kind: 'refused' });
    expect(h.outcomes.at(-1)?.detail).toContain('Restore this saved appearance');

    // The first is still staged, and this page now knows it was made for an earlier version.
    applyButton(h.mounted).click();
    await settle();
    expect(h.applied).toEqual([]);
    expect(h.outcomes.at(-1)).toMatchObject({
      originReference: 'companion-utterance:0f2c', kind: 'refused',
    });
    // Known from the refused preview's read, which cannot tell what moved the world.
    expect(h.outcomes.at(-1)?.detail).toContain(RESTORE_BEFORE_CHANGING);
    expect(h.mounted.options.preferences().worldStyleParameters).toEqual(SAVED);
  });

  it('after refusing one found on opening, a moved control proposes only its own change', async () => {
    const h = await harness({ open: [openPreview({ id: 'stale', base: 'v-earlier', softness: 0.8 })] });
    await settle();
    expect(h.mounted.options.preferences().worldStyleParameters['horizon-softness']).toBe(0.8);

    applyButton(h.mounted).click();
    await settle();
    expect(h.applied).toEqual([]);
    expect(lifecycle()).toBe('failed');
    // The controls show the applied design again, none of the refused values.
    expect(h.mounted.options.preferences().worldStyleParameters).toEqual(SAVED);
    expect(reviewShown(h.mounted)).toBe(false);

    const posted = await nudge(h, 'Color vitality', '0.3');
    expect(posted).toEqual({ ...SAVED, vitality: 0.3 });
  });

  it('refuses one that waited too long in words, offers nothing again, and a moved control proposes only its own change', async () => {
    const h = await harness({ applyExpired: true });
    worldStyleProposalInbox.submit(COMPANION);
    await settle();

    applyButton(h.mounted).click();
    await settle();

    expect(h.applied).toHaveLength(1);
    expect(h.bodies).toHaveLength(1);
    expect(h.deleted).toEqual([]);
    expect(lifecycle()).toBe('failed');
    expect(lifecycleText()).toContain('waited too long');
    expect(h.outcomes.map((outcome) => outcome.kind)).toEqual(['previewed', 'refused']);
    expect(h.outcomes.at(-1)?.detail).toContain('waited too long');
    expect(h.client.activePreview()).toBeNull();
    expect(reviewShown(h.mounted)).toBe(false);
    expect(h.mounted.options.preferences().worldStyleParameters).toEqual(SAVED);
    expect(applyButton(h.mounted).disabled).toBe(true);

    const posted = await nudge(h, 'Color vitality', '0.3');
    expect(posted).toEqual({ ...SAVED, vitality: 0.3 });
  });

  it('says to restore when one that waited too long is refused after the world moved', async () => {
    const h = await harness({ applyExpired: true });
    worldStyleProposalInbox.submit(COMPANION);
    await settle();
    h.setCurrent(elsewhere());

    applyButton(h.mounted).click();
    await settle();

    expect(lifecycle()).toBe('failed');
    expect(lifecycleText()).toContain('waited too long');
    expect(lifecycleText()).toContain(RESTORE_BEFORE_CHANGING);
    expect(h.outcomes.at(-1)?.detail).toContain(RESTORE_BEFORE_CHANGING);
    expect(h.mounted.options.preferences().worldStyleParameters).toEqual(SAVED);
    await vi.waitFor(() => expect(historyOptions(h)).toEqual(['v0', 'v1']), { timeout: 2000 });
  });

  it('says a settings preview that waited too long was not saved, and keeps the person\'s draft', async () => {
    const h = await harness({ applyExpired: true });
    const posted = await nudge(h, 'Color vitality', '0.3');
    expect(posted['vitality']).toBe(0.3);

    applyButton(h.mounted).click();
    await settle();

    expect(lifecycle()).toBe('failed');
    expect(lifecycleText()).toContain('waited too long');
    // A settings draft is the person's own: it stays, and nobody is told about a proposal.
    expect(h.mounted.options.preferences().worldStyleParameters['vitality']).toBe(0.3);
    expect(h.outcomes).toEqual([]);
    expect(applyButton(h.mounted).disabled).toBe(false);
  });

  it('says to restore when a settings preview that waited too long meets a moved world, and lists what moved it', async () => {
    const h = await harness({ applyExpired: true });
    await nudge(h, 'Color vitality', '0.3');
    h.setCurrent(elsewhere());

    applyButton(h.mounted).click();
    await settle();

    expect(lifecycle()).toBe('failed');
    expect(lifecycleText()).toContain('waited too long');
    expect(lifecycleText()).toContain(RESTORE_BEFORE_CHANGING);
    expect(lifecycleText()).not.toContain('Apply again');
    expect(h.mounted.options.preferences().worldStyleParameters['vitality']).toBe(0.3);
    await vi.waitFor(() => expect(historyOptions(h)).toEqual(['v0', 'v1']), { timeout: 2000 });
  });
});

describe('a replaced preview whose discard fails', () => {
  beforeEach(() => {
    while (cleanups.length > 0) cleanups.pop()?.();
    document.body.replaceChildren();
  });

  it('keeps the new proposal staged and says the old one is still open', async () => {
    const { mounted, outcomes, deleted } = await harness({ deleteStatus: 500 });
    worldStyleProposalInbox.submit(COMPANION);
    await settle();
    worldStyleProposalInbox.submit(SECOND);
    await settle();

    expect(deleted).toHaveLength(1);
    expect(outcomes.map((o) => [o.originReference, o.kind])).toEqual([
      ['companion-utterance:0f2c', 'previewed'],
      ['companion-utterance:0f2c', 'still_open'],
      ['companion-utterance:77aa', 'previewed'],
    ]);
    expect(outcomes[1]?.detail).toContain('still open');
    expect(mounted.options.preferences().worldStyleParameters['vitality']).toBe(0.5);
    expect(document.querySelector<HTMLElement>('.world-style-lifecycle')?.dataset['state'])
      .toBe('ready');
  });
});

describe('a person who moves a staged proposal\'s control', () => {
  beforeEach(() => {
    while (cleanups.length > 0) cleanups.pop()?.();
    document.body.replaceChildren();
  });

  it('may apply their own values as a Settings change, even after moving it back', async () => {
    const { mounted, bodies, applied } = await harness();
    worldStyleProposalInbox.submit(COMPANION);
    await settle();
    const softness = mounted.options.root.querySelector<HTMLInputElement>(
      '[aria-label="Horizon softness"]',
    )!;
    softness.value = '0.6';
    softness.dispatchEvent(new Event('input', { bubbles: true }));
    await vi.waitFor(() => {
      expect(bodies.some((body) => body['origin'] === 'settings')).toBe(true);
    }, { timeout: 2000 });
    await settle();
    softness.value = '0.8';
    softness.dispatchEvent(new Event('input', { bubbles: true }));
    await vi.waitFor(() => {
      expect(bodies.filter((body) => body['origin'] === 'settings')).toHaveLength(2);
    }, { timeout: 2000 });
    await settle();

    mounted.options.root.querySelector<HTMLButtonElement>('.world-style-apply')!.click();
    await settle();

    expect(applied).toHaveLength(1);
    expect(document.querySelector<HTMLElement>('.world-style-lifecycle')?.dataset['state'])
      .toBe('saved');
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
    expect(say('proposal.staged')).toContain('Customize');
  });

  it('never says a refused value was moved to the nearest one it could have been', () => {
    expect(say('proposal.refused.out_of_range')).toContain('refused');
    expect(say('proposal.refused.out_of_range')).toContain('rather than moved');
  });
});
