/** Durable, reviewed interaction settings shared by Settings and Companion.
 *
 * Device preferences remain the immediate rendering state. This client sends only the controls
 * the person just changed through the server's preview/apply lifecycle; it never treats an old
 * local preference bundle as permission to rewrite a new account or device silently.
 */

import { Transport, type TransportOptions } from '@exulanica/graph-client';
import type { AtlasPreferences } from './preferences.js';
import { worldPath } from './world-scope.js';

export type InteractionValue = boolean | number | string;

interface InteractionVersionWire {
  readonly version_id: string;
  readonly parameters: Readonly<Record<string, InteractionValue>>;
}

export interface InteractionPolicyState {
  readonly current: InteractionVersionWire | null;
  readonly parameters: Readonly<Record<string, InteractionValue>>;
  readonly base_structure_snapshot_id: string | null;
  readonly base_topology_sha256: string | null;
}

interface InteractionPreviewWire {
  readonly preview_id: string;
}

export interface CompanionPolicyProposal {
  readonly capabilityPatch: Readonly<Record<string, InteractionValue>>;
  readonly explanation: string;
  readonly referenceIds: readonly string[];
  readonly modelId: string;
  readonly promptVersion: string;
  readonly originReference: string;
  readonly proposalInput: Readonly<Record<string, unknown>>;
  readonly refinesProposalId?: string;
}

/** Opaque review handle rendered before a Companion-authored setting can be applied. */
export interface InteractionPolicyReview {
  readonly previewId: string;
  readonly basePolicyVersionId: string | null;
  readonly baseStructureSnapshotId: string | null;
  readonly baseTopologySha256: string | null;
}

type IdFactory = () => string;

const settingCapabilities = (
  preferences: AtlasPreferences,
  systemReducedMotion: boolean,
): Readonly<Record<keyof AtlasPreferences, readonly [string, InteractionValue] | undefined>> => ({
  version: undefined,
  regionMinimap: undefined,
  appearance: undefined,
  contrast: undefined,
  transparency: undefined,
  worldArtProfile: undefined,
  worldArtProfileVersion: undefined,
  worldStyleParameters: undefined,
  fieldOfView: ['comfort.field-of-view-degrees', preferences.fieldOfView],
  mouseSensitivity: [
    'comfort.look-sensitivity-milli',
    Math.round(preferences.mouseSensitivity * 1000),
  ],
  vignette: ['comfort.vignette', preferences.vignette],
  cameraBob: ['comfort.camera-bob', preferences.cameraBob],
  turnMode: ['navigation.turn-mode', preferences.turnMode],
  transition: [
    'navigation.transition-style',
    preferences.transition === 'system'
      ? (systemReducedMotion ? 'fade' : 'motion')
      : preferences.transition,
  ],
  companionInitiative: ['initiative.mode', preferences.companionInitiative],
  companionBody: undefined,
  companionColor: undefined,
  companionFace: undefined,
  companionSide: undefined,
});

/** Apply a durable server policy without disturbing device-only presentation choices. */
export function preferencesFromInteractionPolicy(
  local: AtlasPreferences,
  parameters: Readonly<Record<string, InteractionValue>>,
): AtlasPreferences {
  const fieldOfView = parameters['comfort.field-of-view-degrees'];
  const sensitivity = parameters['comfort.look-sensitivity-milli'];
  const vignette = parameters['comfort.vignette'];
  const cameraBob = parameters['comfort.camera-bob'];
  const turnMode = parameters['navigation.turn-mode'];
  const transition = parameters['navigation.transition-style'];
  const initiative = parameters['initiative.mode'];
  return {
    ...local,
    ...(typeof fieldOfView === 'number' ? { fieldOfView } : {}),
    ...(typeof sensitivity === 'number' ? { mouseSensitivity: sensitivity / 1000 } : {}),
    ...(vignette === 'off' || vignette === 'subtle' || vignette === 'strong' ? { vignette } : {}),
    ...(typeof cameraBob === 'boolean' ? { cameraBob } : {}),
    ...(turnMode === 'smooth' || turnMode === 'snap' ? { turnMode } : {}),
    ...(transition === 'motion' || transition === 'fade' ? { transition } : {}),
    ...(initiative === 'normal' || initiative === 'minimal' || initiative === 'off'
      ? { companionInitiative: initiative }
      : {}),
  };
}

export class InteractionPolicyClient {
  readonly #transport: Transport;
  readonly #ids: IdFactory;
  readonly #worldId: string;
  #sequence: Promise<void> = Promise.resolve();

  /** `worldId` is the world whose interaction policy this client reads and changes. */
  constructor(options: TransportOptions & { readonly ids?: IdFactory; readonly worldId: string }) {
    this.#transport = new Transport(options);
    this.#ids = options.ids ?? (() => globalThis.crypto.randomUUID());
    this.#worldId = options.worldId;
  }

  current(): Promise<InteractionPolicyState> {
    return this.#transport.getJson(worldPath('/world/interactions/current', this.#worldId));
  }

  /** Queue settings writes so a fast pair of choices cannot share a stale base. */
  syncSettings(
    before: AtlasPreferences,
    after: AtlasPreferences,
    systemReducedMotion: boolean,
  ): Promise<void> {
    const prior = settingCapabilities(before, systemReducedMotion);
    const next = settingCapabilities(after, systemReducedMotion);
    const capabilityPatch: Record<string, InteractionValue> = {};
    const controls: string[] = [];
    for (const key of Object.keys(next) as (keyof AtlasPreferences)[]) {
      const from = prior[key];
      const to = next[key];
      if (to === undefined || (from !== undefined && Object.is(from[1], to[1]))) continue;
      capabilityPatch[to[0]] = to[1];
      controls.push(key);
    }
    if (controls.length === 0) return this.#sequence;
    const operation = this.#sequence.then(async () => {
      await this.#proposeAndApply({
        origin: 'settings',
        originReference: 'options-panel',
        capabilityPatch,
        proposalInput: { control_ids: controls },
        explanation: `Apply the reviewed Settings choice: ${controls.join(', ')}.`,
        referenceIds: [],
        modelId: null,
        promptVersion: null,
        refinesProposalId: null,
      });
    });
    this.#sequence = operation.catch(() => undefined);
    return operation;
  }

  /** Companion suggestions stop at preview; a confirmation surface must apply the handle. */
  proposeCompanion(proposal: CompanionPolicyProposal): Promise<InteractionPolicyReview | null> {
    const operation = this.#sequence.then(() =>
      this.#createPreview({
        origin: 'companion',
        originReference: proposal.originReference,
        capabilityPatch: proposal.capabilityPatch,
        proposalInput: proposal.proposalInput,
        explanation: proposal.explanation,
        referenceIds: [...proposal.referenceIds],
        modelId: proposal.modelId,
        promptVersion: proposal.promptVersion,
        refinesProposalId: proposal.refinesProposalId ?? null,
      }),
    );
    this.#sequence = operation.then(() => undefined).catch(() => undefined);
    return operation;
  }

  /** The confirmation surface, and no proposal generator, calls this. */
  applyCompanionReview(review: InteractionPolicyReview): Promise<void> {
    const operation = this.#sequence.then(() => this.#applyPreview(review));
    this.#sequence = operation.catch(() => undefined);
    return operation;
  }

  async #proposeAndApply(input: {
    readonly origin: 'settings' | 'companion';
    readonly originReference: string;
    readonly capabilityPatch: Readonly<Record<string, InteractionValue>>;
    readonly proposalInput: Readonly<Record<string, unknown>>;
    readonly explanation: string;
    readonly referenceIds: readonly string[];
    readonly modelId: string | null;
    readonly promptVersion: string | null;
    readonly refinesProposalId: string | null;
  }): Promise<void> {
    const review = await this.#createPreview(input);
    if (review !== null) await this.#applyPreview(review);
  }

  async #createPreview(input: {
    readonly origin: 'settings' | 'companion';
    readonly originReference: string;
    readonly capabilityPatch: Readonly<Record<string, InteractionValue>>;
    readonly proposalInput: Readonly<Record<string, unknown>>;
    readonly explanation: string;
    readonly referenceIds: readonly string[];
    readonly modelId: string | null;
    readonly promptVersion: string | null;
    readonly refinesProposalId: string | null;
  }): Promise<InteractionPolicyReview | null> {
    const state = await this.current();
    const patch = Object.fromEntries(
      Object.entries(input.capabilityPatch).filter(
        ([key, value]) => !Object.is(state.parameters[key], value),
      ),
    );
    if (Object.keys(patch).length === 0) return null;
    const proposalId = this.#ids();
    const preview = await this.#transport.postJson<InteractionPreviewWire>(
      worldPath('/world/interactions/previews', this.#worldId),
      {
        proposal_id: proposalId,
        origin: input.origin,
        origin_reference: input.originReference,
        base_policy_version_id: state.current?.version_id ?? null,
        base_structure_snapshot_id: state.base_structure_snapshot_id,
        base_topology_sha256: state.base_topology_sha256,
        capability_patch: patch,
        proposal_input: input.proposalInput,
        explanation: input.explanation,
        reference_ids: input.referenceIds,
        model_id: input.modelId,
        prompt_version: input.promptVersion,
        refines_proposal_id: input.refinesProposalId,
      },
    );
    return {
      previewId: preview.preview_id,
      basePolicyVersionId: state.current?.version_id ?? null,
      baseStructureSnapshotId: state.base_structure_snapshot_id,
      baseTopologySha256: state.base_topology_sha256,
    };
  }

  async #applyPreview(review: InteractionPolicyReview): Promise<void> {
    await this.#transport.postJson(
      worldPath(
        `/world/interactions/previews/${encodeURIComponent(review.previewId)}/apply`,
        this.#worldId,
      ),
      {
        base_policy_version_id: review.basePolicyVersionId,
        base_structure_snapshot_id: review.baseStructureSnapshotId,
        base_topology_sha256: review.baseTopologySha256,
      },
    );
  }
}
