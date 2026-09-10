// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  WORLD_STYLE_CONTRACT_COMMIT,
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
import {
  WorldStyleProposalOutcomes,
  worldStyleProposalInbox,
  worldStyleProposalOutcomes,
} from '../src/world-style-proposals.js';

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

const binding = () => {
  const recipe = worldStyleRecipe(PROFILE.profileId, PROFILE.profileVersion)!;
  return {
    schemaVersion: 1,
    frontendCommit: WORLD_STYLE_CONTRACT_COMMIT,
    availability: recipe.availability,
    origin: recipe.origin,
    profileId: PROFILE.profileId,
    profileVersion: PROFILE.profileVersion,
    modules: [...recipe.modules],
    capabilityMapping: Object.fromEntries(
      recipe.controls.map((control) => [control.key, control.capability]),
    ),
  };
};

const catalog = () => ({
  schemaVersion: 1,
  contractSource: { frontendCommit: WORLD_STYLE_CONTRACT_COMMIT },
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

  it('says the most general true thing about a refusal this build has no words for', async () => {
    const fetch = vi.fn(async () =>
      json(wireProposal({ proposal: null, refusal: { code: 'invented_later', detail: 'x' } })),
    ) as unknown as typeof globalThis.fetch;
    const client = new CompanionProposalClient({
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
}

async function harness(over: { previewStatus?: number; previewBody?: unknown } = {}): Promise<Harness> {
  const bodies: Record<string, unknown>[] = [];
  const applied: string[] = [];
  const deleted: string[] = [];
  const fetch = vi.fn(async (input: string | URL | Request, init: RequestInit = {}) => {
    const url = new URL(String(input));
    if (url.pathname.endsWith('/world/styles/catalog')) return json(catalog());
    if (url.pathname.endsWith('/world/styles/current')) {
      return json({ current_topology_digest: 'topology-a', current: version('v0', 0) });
    }
    if (url.pathname.endsWith('/world/styles/versions')) return json([version('v0', 0)]);
    if (url.pathname.endsWith('/world/styles/previews') && init.method === 'POST') {
      const body = JSON.parse(String(init.body)) as Record<string, unknown>;
      bodies.push(body);
      if (over.previewStatus !== undefined) {
        return json(over.previewBody ?? { code: 'invalid_style_data', detail: 'no' }, over.previewStatus);
      }
      return json(
        {
          preview_id: 'preview-1',
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
      return json(version('v1', 1, 0.8));
    }
    if (url.pathname.includes('/world/styles/previews/') && init.method === 'DELETE') {
      deleted.push(url.pathname);
      return new Response(null, { status: 204 });
    }
    throw new Error(`unhandled ${init.method ?? 'GET'} ${url.pathname}`);
  }) as unknown as typeof globalThis.fetch;

  const client = new WorldStyleClient({
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
  return { bodies, applied, deleted, mounted, outcomes, stop };
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
 * `submit` fires its listeners with `void listener(proposal)` and does not await them, and the
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

    expect(worldStyleProposalInbox.submit(COMPANION)).toBe(true);
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
