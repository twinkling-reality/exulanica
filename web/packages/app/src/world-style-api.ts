/**
 * Authenticated adapter for the backend-owned world-style lifecycle.
 *
 * The server intentionally exposes a camel-case catalog and snake-case persisted records. This
 * file is the only translation layer. It validates the inert catalog against the reviewed local
 * recipe registry before any profile is rendered, completes and validates parameters locally,
 * and keeps preview handles transient.
 *
 * Server and browser agree when their PAYLOADS agree. Both are built from the one backend registry
 * document, which this Atlas carries as exact bytes, so the catalog and every recipe binding the
 * server sends are compared with what that document produces. The handshake used to compare a
 * pinned commit hash instead, which said nothing about whether the two sides still said the same
 * thing.
 */

import type { WorldStyleParameterDefinition, WorldStyleParameterValue } from '@exulanica/atlas-core';
import { ApiError, Transport, type TransportOptions } from '@exulanica/graph-client';
import {
  WORLD_STYLE_RECIPES,
  WORLD_STYLE_REGISTRY_DOCUMENT,
  worldStyleControlFromDocument,
  worldStyleRecipe,
  type WorldStyleRegistryDocument,
} from '@exulanica/presentation';
import { worldPath } from './world-scope.js';

export type WorldStyleOrigin = 'user' | 'settings' | 'companion';
export type WorldStyleScope =
  | { readonly kind: 'global' }
  | { readonly kind: 'region'; readonly islandId: string };

export interface WorldStyleReferenceRecord {
  readonly profileId: string;
  readonly profileVersion: number;
  readonly parameters: Readonly<Record<string, WorldStyleParameterValue>>;
}

export interface WorldStyleRegionRecord extends WorldStyleReferenceRecord {
  readonly islandId: string;
}

export interface WorldStyleProvenance {
  readonly origin: WorldStyleOrigin;
  readonly actor: string;
  readonly originReference: string | null;
}

export interface WorldStyleRecipeBinding {
  readonly schemaVersion: 1;
  readonly frontendCommit: string;
  readonly availability: 'product' | 'developer';
  readonly origin: 'authored' | 'generated';
  readonly profileId: string;
  readonly profileVersion: number;
  readonly modules: readonly string[];
  readonly capabilityMapping: Readonly<Record<string, string>>;
}

export interface WorldStyleVersionRecord {
  readonly versionId: string;
  readonly revision: number;
  readonly parentVersionId: string | null;
  readonly topologyDigest: string;
  readonly globalStyle: WorldStyleReferenceRecord;
  readonly regionStyles: readonly WorldStyleRegionRecord[];
  readonly appliedFromProposalId: string | null;
  readonly rollbackTargetVersionId: string | null;
  readonly provenance: WorldStyleProvenance | null;
  readonly createdAt: string;
  readonly warnings: readonly string[];
  readonly recipeBinding: WorldStyleRecipeBinding;
  readonly capabilityMapping: Readonly<Record<string, string>>;
  readonly referenceIds: readonly string[];
  readonly modelId: string | null;
  readonly promptVersion: string | null;
  readonly refinesProposalId: string | null;
}

export interface WorldStyleState {
  readonly currentTopologyDigest: string;
  readonly current: WorldStyleVersionRecord;
}

export interface WorldStylePreviewRecord {
  readonly previewId: string;
  readonly proposalId: string;
  readonly candidate: WorldStyleVersionRecord;
  readonly createdAt: string;
}

export interface WorldStyleProposalRecord {
  readonly proposalId: string;
  readonly provenance: WorldStyleProvenance;
  readonly scope: WorldStyleScope;
  readonly baseStyleVersionId: string;
  readonly baseTopologyDigest: string;
  readonly profile: WorldStyleReferenceRecord;
  readonly referenceIds: readonly string[];
  readonly modelId: string | null;
  readonly promptVersion: string | null;
  readonly refinesProposalId: string | null;
  readonly recipeBinding: WorldStyleRecipeBinding;
  readonly capabilityMapping: Readonly<Record<string, string>>;
  readonly status: string;
  readonly validationIssues: readonly string[];
  readonly createdAt: string;
  readonly updatedAt: string;
}

export interface UpstreamWorldStyleProposal {
  readonly origin: 'user' | 'companion';
  readonly originReference?: string;
  readonly scope?: WorldStyleScope;
  readonly profile: {
    readonly profileId: string;
    readonly profileVersion: number;
    readonly parameters?: Readonly<Record<string, unknown>>;
  };
  readonly referenceIds?: readonly string[];
  readonly modelId?: string;
  readonly promptVersion?: string;
  readonly refinesProposalId?: string;
}

interface PreviewRequest {
  readonly origin: WorldStyleOrigin;
  readonly originReference: string | null;
  readonly scope: WorldStyleScope;
  readonly profile: WorldStyleReferenceRecord;
  readonly referenceIds: readonly string[];
  readonly modelId: string | null;
  readonly promptVersion: string | null;
  readonly refinesProposalId: string | null;
}

export interface ActiveWorldStylePreview {
  readonly preview: WorldStylePreviewRecord;
  readonly request: PreviewRequest;
  readonly baseStyleVersionId: string;
  readonly baseTopologyDigest: string;
  readonly recoveredFromStale: boolean;
}

export interface WorldStyleConnection {
  readonly state: WorldStyleState;
  readonly versions: readonly WorldStyleVersionRecord[];
}

export interface SavedStyleEntryBinding {
  readonly entryId: string;
  readonly revision: number;
  readonly authoredStateSha256: string;
  readonly authoredEditSeq: number;
  readonly styleVersionId: string;
}

export type WorldStyleApplyResult =
  | { readonly kind: 'applied'; readonly version: WorldStyleVersionRecord }
  | { readonly kind: 'stale-recovered'; readonly preview: ActiveWorldStylePreview };

export type WorldStyleRollbackResult =
  | { readonly kind: 'applied'; readonly version: WorldStyleVersionRecord }
  | { readonly kind: 'stale'; readonly state: WorldStyleState };

export class WorldStyleContractError extends Error {
  constructor(readonly code: string, message: string) {
    super(message);
    this.name = 'WorldStyleContractError';
  }
}

type IdFactory = () => string;

function savedEntryBody(
  entry: SavedStyleEntryBinding | undefined,
): Readonly<Record<string, unknown>> {
  if (entry === undefined) return Object.freeze({});
  return Object.freeze({
    saved_entry: {
      entry_id: entry.entryId,
      base_revision: entry.revision,
      authored_state_sha256: entry.authoredStateSha256,
      authored_edit_seq: entry.authoredEditSeq,
      style_version_id: entry.styleVersionId,
    },
  });
}

export class WorldStyleClient {
  readonly #transport: Transport;
  readonly #ids: IdFactory;
  readonly #worldId: string;
  readonly #savedEntry: (() => SavedStyleEntryBinding) | undefined;
  readonly #onSavedEntryAdvanced:
    | ((version: WorldStyleVersionRecord, base: SavedStyleEntryBinding) => void)
    | undefined;
  #state: WorldStyleState | null = null;
  #versions: readonly WorldStyleVersionRecord[] = Object.freeze([]);
  #active: ActiveWorldStylePreview | null = null;
  #previewQueue: Promise<void> = Promise.resolve();
  #displayedVersionId: string | null = null;
  #requiresReconciliation = false;

  constructor(options: TransportOptions & {
    readonly ids?: IdFactory;
    /** The world whose appearance this client reads and changes. */
    readonly worldId: string;
    readonly savedEntry?: () => SavedStyleEntryBinding;
    readonly onSavedEntryAdvanced?: (
      version: WorldStyleVersionRecord,
      base: SavedStyleEntryBinding,
    ) => void;
  }) {
    this.#transport = new Transport(options);
    this.#ids = options.ids ?? (() => globalThis.crypto.randomUUID());
    this.#worldId = options.worldId;
    this.#savedEntry = options.savedEntry;
    this.#onSavedEntryAdvanced = options.onSavedEntryAdvanced;
  }

  state(): WorldStyleState | null {
    return this.#state;
  }

  versions(): readonly WorldStyleVersionRecord[] {
    return this.#versions;
  }

  activePreview(): ActiveWorldStylePreview | null {
    return this.#active;
  }

  async connect(selectedVersionId?: string): Promise<WorldStyleConnection> {
    const [catalog, state, versions] = await Promise.all([
      // The reviewed catalog is the same for every world, so this read names none.
      this.#transport.getJson<unknown>('/world/styles/catalog'),
      this.#transport.getJson<unknown>(this.#path('/world/styles/current')),
      this.#transport.getJson<unknown>(this.#path('/world/styles/versions')),
    ]);
    validateCatalog(catalog);
    this.#state = parseState(state);
    this.#versions = parseVersions(versions);
    const selected = selectedVersionId === undefined
      ? this.#state.current
      : this.#versions.find((version) => version.versionId === selectedVersionId);
    if (selected === undefined) {
      throw new WorldStyleContractError(
        'unknown_reference', `Saved style version ${selectedVersionId} is unavailable.`,
      );
    }
    this.#displayedVersionId = selected.versionId;
    this.#requiresReconciliation = selected.versionId !== this.#state.current.versionId;
    return Object.freeze({
      state: Object.freeze({
        currentTopologyDigest: selected.topologyDigest,
        current: selected,
      }),
      versions: this.#versions,
    });
  }

  async refresh(): Promise<WorldStyleState> {
    const state = parseState(
      await this.#transport.getJson<unknown>(this.#path('/world/styles/current')),
    );
    this.#state = state;
    this.#requiresReconciliation = this.#displayedVersionId !== null
      && this.#displayedVersionId !== state.current.versionId;
    return state;
  }

  async refreshVersions(): Promise<readonly WorldStyleVersionRecord[]> {
    this.#versions = parseVersions(
      await this.#transport.getJson<unknown>(this.#path('/world/styles/versions')),
    );
    return this.#versions;
  }

  previewSettings(reference: {
    readonly profileId: string;
    readonly profileVersion: number;
    readonly parameters?: Readonly<Record<string, unknown>>;
  }): Promise<ActiveWorldStylePreview> {
    return this.#enqueuePreview(() => this.#replacePreview({
      origin: 'settings',
      originReference: 'appearance-panel',
      scope: Object.freeze({ kind: 'global' }),
      profile: validateLocalReference(reference),
      referenceIds: Object.freeze([]),
      modelId: null,
      promptVersion: null,
      refinesProposalId: null,
    }));
  }

  previewUpstream(proposal: UpstreamWorldStyleProposal): Promise<ActiveWorldStylePreview> {
    if (proposal.origin === 'companion') {
      if (
        proposal.originReference === undefined || proposal.originReference.trim().length === 0 ||
        proposal.modelId === undefined || proposal.modelId.trim().length === 0 ||
        proposal.promptVersion === undefined || proposal.promptVersion.trim().length === 0 ||
        proposal.referenceIds === undefined || proposal.referenceIds.length === 0
      ) {
        throw new WorldStyleContractError(
          'incomplete_companion_provenance',
          'Companion style proposals require an origin reference, model, prompt version, and at least one reference ID.',
        );
      }
    }
    return this.#enqueuePreview(() => this.#replacePreview({
      origin: proposal.origin,
      originReference: proposal.originReference ?? null,
      scope: proposal.scope ?? Object.freeze({ kind: 'global' }),
      profile: validateLocalReference(proposal.profile),
      referenceIds: freezeStrings(proposal.referenceIds ?? []),
      modelId: proposal.modelId ?? null,
      promptVersion: proposal.promptVersion ?? null,
      refinesProposalId: proposal.refinesProposalId ?? null,
    }));
  }

  async inspectProposal(proposalId: string): Promise<WorldStyleProposalRecord> {
    return parseProposal(await this.#transport.getJson<unknown>(
      this.#path(`/world/styles/proposals/${encodeURIComponent(proposalId)}`),
    ));
  }

  discardActive(): Promise<void> {
    return this.#previewQueue.then(() => this.#discardActiveNow());
  }

  async #discardActiveNow(): Promise<void> {
    const active = this.#active;
    this.#active = null;
    if (active === null) return;
    try {
      await this.#transport.delete(
        this.#path(`/world/styles/previews/${encodeURIComponent(active.preview.previewId)}`),
      );
    } catch (error) {
      if (!(error instanceof ApiError) || error.code !== 'invalid_preview_state') throw error;
    }
  }

  async applyActive(): Promise<WorldStyleApplyResult> {
    await this.#previewQueue;
    const active = this.#active;
    if (active === null) {
      throw new WorldStyleContractError('missing_preview', 'There is no reviewed world preview to apply.');
    }
    const savedEntry = this.#savedEntry?.();
    try {
      const version = parseVersion(await this.#transport.postJson<unknown>(
        this.#path(`/world/styles/previews/${encodeURIComponent(active.preview.previewId)}/apply`),
        {
          baseStyleVersionId: active.baseStyleVersionId,
          baseTopologyDigest: active.baseTopologyDigest,
          ...savedEntryBody(savedEntry),
        },
      ));
      this.#active = null;
      this.#state = Object.freeze({
        currentTopologyDigest: active.baseTopologyDigest,
        current: version,
      });
      this.#versions = appendVersion(this.#versions, version);
      this.#displayedVersionId = version.versionId;
      this.#requiresReconciliation = false;
      if (savedEntry !== undefined) this.#onSavedEntryAdvanced?.(version, savedEntry);
      return Object.freeze({ kind: 'applied', version });
    } catch (error) {
      if (error instanceof ApiError && error.code === 'stale_saved_world_entry') {
        throw new WorldStyleContractError(
          'saved_entry_conflict',
          'This saved world changed elsewhere. The appearance was not saved. Reload before trying again.',
        );
      }
      if (!(error instanceof ApiError) || error.code !== 'stale_style_version') throw error;
      await this.refresh();
      const recovered = await this.#createPreview({
        ...active.request,
        refinesProposalId: active.preview.proposalId,
      }, true);
      this.#active = recovered;
      return Object.freeze({ kind: 'stale-recovered', preview: recovered });
    }
  }

  async rollback(targetVersionId: string): Promise<WorldStyleRollbackResult> {
    const state = this.#requireState();
    const savedEntry = this.#savedEntry?.();
    try {
      const version = parseVersion(await this.#transport.postJson<unknown>(
        this.#path('/world/styles/rollback'),
        {
          targetVersionId,
          baseStyleVersionId: state.current.versionId,
          baseTopologyDigest: state.currentTopologyDigest,
          origin: 'settings',
          originReference: 'appearance-history',
          ...savedEntryBody(savedEntry),
        },
      ));
      this.#state = Object.freeze({
        currentTopologyDigest: state.currentTopologyDigest,
        current: version,
      });
      this.#versions = appendVersion(this.#versions, version);
      this.#displayedVersionId = version.versionId;
      this.#requiresReconciliation = false;
      if (savedEntry !== undefined) this.#onSavedEntryAdvanced?.(version, savedEntry);
      return Object.freeze({ kind: 'applied', version });
    } catch (error) {
      if (error instanceof ApiError && error.code === 'stale_saved_world_entry') {
        throw new WorldStyleContractError(
          'saved_entry_conflict',
          'This saved world changed elsewhere. The restored appearance was not saved. Reload before trying again.',
        );
      }
      if (!(error instanceof ApiError) || error.code !== 'stale_style_version') throw error;
      return Object.freeze({ kind: 'stale', state: await this.refresh() });
    }
  }

  async #replacePreview(request: PreviewRequest): Promise<ActiveWorldStylePreview> {
    if (this.#requiresReconciliation) {
      throw new WorldStyleContractError(
        'saved_style_reconciliation_required',
        'Restore this saved appearance before changing it, because another appearance is active.',
      );
    }
    await this.#discardActiveNow();
    try {
      const active = await this.#createPreview(request, false);
      this.#active = active;
      return active;
    } catch (error) {
      if (!(error instanceof ApiError) || error.code !== 'stale_style_version') throw error;
      const rejectedProposalId = this.#lastProposalId;
      await this.refresh();
      const recovered = await this.#createPreview({
        ...request,
        refinesProposalId: rejectedProposalId,
      }, true);
      this.#active = recovered;
      return recovered;
    }
  }

  #lastProposalId: string | null = null;

  #enqueuePreview<T>(operation: () => Promise<T>): Promise<T> {
    const queued = this.#previewQueue.then(operation);
    this.#previewQueue = queued.then(() => undefined, () => undefined);
    return queued;
  }

  async #createPreview(
    request: PreviewRequest,
    recoveredFromStale: boolean,
  ): Promise<ActiveWorldStylePreview> {
    const state = this.#requireState();
    const proposalId = this.#ids();
    this.#lastProposalId = proposalId;
    const scope = request.scope.kind === 'global'
      ? { kind: 'global' as const }
      : { kind: 'region' as const, islandId: request.scope.islandId };
    const preview = parsePreview(await this.#transport.postJson<unknown>(
      this.#path('/world/styles/previews'),
      {
        proposalId,
        origin: request.origin,
        originReference: request.originReference,
        scope,
        baseStyleVersionId: state.current.versionId,
        baseTopologyDigest: state.currentTopologyDigest,
        profile: request.profile,
        referenceIds: request.referenceIds,
        modelId: request.modelId,
        promptVersion: request.promptVersion,
        refinesProposalId: request.refinesProposalId,
      },
    ));
    return Object.freeze({
      preview,
      request,
      baseStyleVersionId: state.current.versionId,
      baseTopologyDigest: state.currentTopologyDigest,
      recoveredFromStale,
    });
  }

  #requireState(): WorldStyleState {
    if (this.#state === null) {
      throw new WorldStyleContractError('not_connected', 'World style authority is not connected.');
    }
    return this.#state;
  }

  #path(path: string): string {
    return worldPath(path, this.#worldId);
  }
}

export function validateLocalReference(reference: {
  readonly profileId: string;
  readonly profileVersion: number;
  readonly parameters?: Readonly<Record<string, unknown>>;
}): WorldStyleReferenceRecord {
  const recipe = worldStyleRecipe(reference.profileId, reference.profileVersion);
  if (recipe === null) {
    throw new WorldStyleContractError(
      'unknown_profile_version',
      `Unknown reviewed world profile ${reference.profileId}@${reference.profileVersion}.`,
    );
  }
  const supplied = reference.parameters ?? {};
  const definitions = new Map(recipe.controls.map((control) => [control.key, control] as const));
  for (const key of Object.keys(supplied)) {
    if (!definitions.has(key)) {
      throw new WorldStyleContractError(
        'unknown_parameter',
        `Unknown parameter ${key} for ${reference.profileId}@${reference.profileVersion}.`,
      );
    }
  }
  const parameters: Record<string, WorldStyleParameterValue> = {};
  for (const control of recipe.controls) {
    const value = supplied[control.key] ?? control.defaultValue;
    if (!validControlValue(control, value)) {
      throw new WorldStyleContractError(
        'invalid_parameter',
        `Invalid value for ${control.key} on ${reference.profileId}@${reference.profileVersion}.`,
      );
    }
    parameters[control.key] = value;
  }
  return Object.freeze({
    profileId: reference.profileId,
    profileVersion: reference.profileVersion,
    parameters: Object.freeze(parameters),
  });
}

function validControlValue(control: WorldStyleParameterDefinition, value: unknown): value is WorldStyleParameterValue {
  return control.kind === 'range'
    ? typeof value === 'number' && Number.isFinite(value) && value >= control.min && value <= control.max
    : control.kind === 'choice'
      ? typeof value === 'string' && control.options.some((option) => option.value === value)
      : control.kind === 'color'
        ? typeof value === 'string' && /^#[0-9a-f]{6}$/i.test(value)
        : typeof value === 'boolean';
}

type RegistryProfile = WorldStyleRegistryDocument['profiles'][number];

function registryProfile(profileId: string, profileVersion: number): RegistryProfile | null {
  return WORLD_STYLE_REGISTRY_DOCUMENT.profiles.find((profile) =>
    profile.profile_id === profileId && profile.profile_version === profileVersion) ?? null;
}

/** The binding the backend registry serves for one profile, built as `registry.py` builds it. */
function expectedBinding(profile: RegistryProfile): WorldStyleRecipeBinding {
  return {
    schemaVersion: 1,
    frontendCommit: WORLD_STYLE_REGISTRY_DOCUMENT.frontend_contract.commit,
    availability: profile.recipe.availability as WorldStyleRecipeBinding['availability'],
    origin: profile.recipe.origin as WorldStyleRecipeBinding['origin'],
    profileId: profile.profile_id,
    profileVersion: profile.profile_version,
    modules: profile.recipe.modules,
    capabilityMapping: Object.fromEntries(
      profile.controls.map((control) => [control.key, control.capability]),
    ),
  };
}

/** The whole catalog the backend registry serves, built as `StyleRegistry.catalog()` builds it. */
function expectedCatalog(): unknown {
  const document = WORLD_STYLE_REGISTRY_DOCUMENT;
  const fallback = registryProfile(
    document.default_profile.profile_id,
    document.default_profile.profile_version,
  );
  return {
    schemaVersion: 1,
    contractSource: { frontendCommit: document.frontend_contract.commit },
    defaultProfile: {
      profileId: document.default_profile.profile_id,
      profileVersion: document.default_profile.profile_version,
      parameters: Object.fromEntries(
        (fallback?.controls ?? []).map((control) => [control.key, control.default_value]),
      ),
    },
    profiles: document.profiles.map((profile) => ({
      profileId: profile.profile_id,
      profileVersion: profile.profile_version,
      displayName: profile.display_name,
      description: profile.description,
      compatibilityKey: profile.compatibility_key,
      status: profile.status,
      recipeBinding: expectedBinding(profile),
      controls: profile.controls.map(worldStyleControlFromDocument),
    })),
  };
}

function validateCatalog(value: unknown): void {
  const catalog = record(value, 'world style catalog');
  if (catalog['schemaVersion'] !== 1) {
    throw new WorldStyleContractError('unknown_catalog_version', 'The server returned an unsupported world style catalog.');
  }
  const profiles = array(catalog['profiles'], 'world style catalog profiles');
  const seen = new Set<string>();
  for (const candidate of profiles) {
    const profile = record(candidate, 'world style catalog profile');
    const profileId = text(profile['profileId'], 'profile ID');
    const profileVersion = positiveInteger(profile['profileVersion'], 'profile version');
    const key = `${profileId}@${profileVersion}`;
    if (seen.has(key)) throw new WorldStyleContractError('duplicate_profile', `Duplicate server profile ${key}.`);
    seen.add(key);
    const recipe = worldStyleRecipe(profileId, profileVersion);
    if (recipe === null) {
      throw new WorldStyleContractError('unknown_profile_version', `The server advertised unknown profile ${key}.`);
    }
    const binding = parseBinding(profile['recipeBinding']);
    validateBinding(binding, profileId, profileVersion);
    if (!sameValue(profile['controls'], recipe.controls)) {
      throw new WorldStyleContractError('control_manifest_mismatch', `Control manifest mismatch for ${key}.`);
    }
  }
  for (const recipe of WORLD_STYLE_RECIPES) {
    const key = `${recipe.profile.profileId}@${recipe.profile.profileVersion}`;
    if (!seen.has(key)) {
      throw new WorldStyleContractError('missing_server_profile', `The server is missing reviewed profile ${key}.`);
    }
  }
  // The specific checks above name what broke. This one is the contract: every byte of meaning in
  // the served catalog, names, descriptions, statuses and defaults included, must be what the
  // shared registry document says.
  if (!sameValue(catalog, expectedCatalog())) {
    throw new WorldStyleContractError(
      'catalog_contract_mismatch',
      'The server and this Atlas do not share the same reviewed world recipe contract.',
    );
  }
}

function parseState(value: unknown): WorldStyleState {
  const state = record(value, 'world style state');
  return Object.freeze({
    currentTopologyDigest: text(state['current_topology_digest'], 'current topology digest'),
    current: parseVersion(state['current'], true),
  });
}

function parseVersions(value: unknown): readonly WorldStyleVersionRecord[] {
  return Object.freeze(array(value, 'world style versions').map(version => parseVersion(version, true)));
}

function parseVersion(value: unknown, historical = false): WorldStyleVersionRecord {
  const version = record(value, 'world style version');
  const globalStyle = parseReference(version['global_style']);
  const recipeBinding = parseBinding(version['recipe_binding']);
  validateBinding(recipeBinding, globalStyle.profileId, globalStyle.profileVersion, historical);
  const capabilityMapping = stringRecord(version['capability_mapping'], 'capability mapping');
  if (!sameValue(capabilityMapping, recipeBinding.capabilityMapping)) {
    throw new WorldStyleContractError('capability_mapping_mismatch', 'Persisted capability mapping does not match its recipe binding.');
  }
  return Object.freeze({
    versionId: text(version['version_id'], 'version ID'),
    revision: nonNegativeInteger(version['revision'], 'revision'),
    parentVersionId: nullableText(version['parent_version_id'], 'parent version ID'),
    topologyDigest: text(version['topology_digest'], 'topology digest'),
    globalStyle,
    regionStyles: Object.freeze(array(version['region_styles'], 'regional styles').map(parseRegion)),
    appliedFromProposalId: nullableText(version['applied_from_proposal_id'], 'applied proposal ID'),
    rollbackTargetVersionId: nullableText(version['rollback_target_version_id'], 'rollback target version ID'),
    provenance: version['provenance'] === null ? null : parseProvenance(version['provenance']),
    createdAt: text(version['created_at'], 'version creation time'),
    warnings: freezeStrings(array(version['warnings'], 'version warnings')),
    recipeBinding,
    capabilityMapping,
    referenceIds: freezeStrings(array(version['reference_ids'], 'version reference IDs')),
    modelId: nullableText(version['model_id'], 'model ID'),
    promptVersion: nullableText(version['prompt_version'], 'prompt version'),
    refinesProposalId: nullableText(version['refines_proposal_id'], 'refined proposal ID'),
  });
}

function parsePreview(value: unknown): WorldStylePreviewRecord {
  const preview = record(value, 'world style preview');
  return Object.freeze({
    previewId: text(preview['preview_id'], 'preview ID'),
    proposalId: text(preview['proposal_id'], 'proposal ID'),
    candidate: parseVersion(preview['candidate']),
    createdAt: text(preview['created_at'], 'preview creation time'),
  });
}

function parseProposal(value: unknown): WorldStyleProposalRecord {
  const proposal = record(value, 'world style proposal');
  const scopeWire = record(proposal['scope'], 'proposal scope');
  const kind = scopeWire['kind'];
  const scope: WorldStyleScope = kind === 'global'
    ? Object.freeze({ kind: 'global' })
    : kind === 'region'
      ? Object.freeze({ kind: 'region', islandId: text(scopeWire['region_id'], 'proposal region ID') })
      : (() => { throw new WorldStyleContractError('invalid_scope', 'Unknown world style proposal scope.'); })();
  const profile = parseReference(proposal['profile']);
  const binding = parseBinding(proposal['recipe_binding']);
  validateBinding(binding, profile.profileId, profile.profileVersion);
  return Object.freeze({
    proposalId: text(proposal['proposal_id'], 'proposal ID'),
    provenance: parseProvenance(proposal['provenance']),
    scope,
    baseStyleVersionId: text(proposal['base_style_version_id'], 'base style version ID'),
    baseTopologyDigest: text(proposal['base_topology_digest'], 'base topology digest'),
    profile,
    referenceIds: freezeStrings(array(proposal['reference_ids'], 'proposal reference IDs')),
    modelId: nullableText(proposal['model_id'], 'model ID'),
    promptVersion: nullableText(proposal['prompt_version'], 'prompt version'),
    refinesProposalId: nullableText(proposal['refines_proposal_id'], 'refined proposal ID'),
    recipeBinding: binding,
    capabilityMapping: stringRecord(proposal['capability_mapping'], 'proposal capability mapping'),
    status: text(proposal['status'], 'proposal status'),
    validationIssues: freezeStrings(array(proposal['validation_issues'], 'proposal validation issues')),
    createdAt: text(proposal['created_at'], 'proposal creation time'),
    updatedAt: text(proposal['updated_at'], 'proposal update time'),
  });
}

function parseReference(value: unknown): WorldStyleReferenceRecord {
  const reference = record(value, 'world style reference');
  return validateLocalReference({
    profileId: text(reference['profile_id'], 'profile ID'),
    profileVersion: positiveInteger(reference['profile_version'], 'profile version'),
    parameters: record(reference['parameters'], 'style parameters'),
  });
}

function parseRegion(value: unknown): WorldStyleRegionRecord {
  const region = record(value, 'regional world style');
  const reference = parseReference(region);
  return Object.freeze({
    islandId: text(region['region_id'], 'region ID'),
    ...reference,
  });
}

function parseProvenance(value: unknown): WorldStyleProvenance {
  const provenance = record(value, 'world style provenance');
  const origin = provenance['origin'];
  if (origin !== 'user' && origin !== 'settings' && origin !== 'companion') {
    throw new WorldStyleContractError('invalid_origin', 'Unknown world style proposal origin.');
  }
  return Object.freeze({
    origin,
    actor: text(provenance['actor'], 'proposal actor'),
    originReference: nullableText(provenance['origin_reference'], 'origin reference'),
  });
}

function parseBinding(value: unknown): WorldStyleRecipeBinding {
  const binding = record(value, 'world style recipe binding');
  const availability = binding['availability'];
  const origin = binding['origin'];
  if (binding['schemaVersion'] !== 1) {
    throw new WorldStyleContractError('unknown_recipe_version', 'Unknown world style recipe version.');
  }
  if (availability !== 'product' && availability !== 'developer') {
    throw new WorldStyleContractError('invalid_availability', 'Unknown world style availability.');
  }
  if (origin !== 'authored' && origin !== 'generated') {
    throw new WorldStyleContractError('invalid_recipe_origin', 'Unknown world style recipe origin.');
  }
  return Object.freeze({
    schemaVersion: 1,
    frontendCommit: text(binding['frontendCommit'], 'frontend contract commit'),
    availability,
    origin,
    profileId: text(binding['profileId'], 'binding profile ID'),
    profileVersion: positiveInteger(binding['profileVersion'], 'binding profile version'),
    modules: freezeStrings(array(binding['modules'], 'binding modules')),
    capabilityMapping: stringRecord(binding['capabilityMapping'], 'binding capability mapping'),
  });
}

function validateBinding(
  binding: WorldStyleRecipeBinding,
  profileId: string,
  profileVersion: number,
  historical = false,
): void {
  const recipe = worldStyleRecipe(profileId, profileVersion);
  const profile = registryProfile(profileId, profileVersion);
  const expected = profile === null ? null : expectedBinding(profile);
  const executableBinding = recipe !== null && expected !== null && (
    sameValue(binding, expected) ||
    (historical && (recipe.readCompatibleBindings ?? []).some(compatible => sameValue(binding, {
      ...expected,
      modules: compatible.modules,
      capabilityMapping: compatible.capabilityMapping,
    })))
  );
  if (!executableBinding) {
    throw new WorldStyleContractError(
      'recipe_binding_mismatch',
      `The server recipe binding for ${profileId}@${profileVersion} is not executable by this Atlas.`,
    );
  }
}

function appendVersion(
  versions: readonly WorldStyleVersionRecord[],
  next: WorldStyleVersionRecord,
): readonly WorldStyleVersionRecord[] {
  return Object.freeze(
    [...versions.filter((version) => version.versionId !== next.versionId), next]
      .sort((left, right) => left.revision - right.revision),
  );
}

function record(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new WorldStyleContractError('invalid_response', `The server returned an invalid ${label}.`);
  }
  return value as Record<string, unknown>;
}

function array(value: unknown, label: string): readonly unknown[] {
  if (!Array.isArray(value)) {
    throw new WorldStyleContractError('invalid_response', `The server returned invalid ${label}.`);
  }
  return value;
}

function text(value: unknown, label: string): string {
  if (typeof value !== 'string' || value.length === 0) {
    throw new WorldStyleContractError('invalid_response', `The server returned an invalid ${label}.`);
  }
  return value;
}

function nullableText(value: unknown, label: string): string | null {
  return value === null ? null : text(value, label);
}

function positiveInteger(value: unknown, label: string): number {
  if (!Number.isSafeInteger(value) || (value as number) < 1) {
    throw new WorldStyleContractError('invalid_response', `The server returned an invalid ${label}.`);
  }
  return value as number;
}

function nonNegativeInteger(value: unknown, label: string): number {
  if (!Number.isSafeInteger(value) || (value as number) < 0) {
    throw new WorldStyleContractError('invalid_response', `The server returned an invalid ${label}.`);
  }
  return value as number;
}

function freezeStrings(values: readonly unknown[]): readonly string[] {
  return Object.freeze(values.map((value) => text(value, 'string list entry')));
}

function stringRecord(value: unknown, label: string): Readonly<Record<string, string>> {
  const source = record(value, label);
  return Object.freeze(Object.fromEntries(
    Object.entries(source).map(([key, item]) => [key, text(item, `${label} value`)]),
  ));
}

function sameValue(left: unknown, right: unknown): boolean {
  return JSON.stringify(canonical(left)) === JSON.stringify(canonical(right));
}

function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical);
  if (typeof value !== 'object' || value === null) return value;
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, item]) => [key, canonical(item)]),
  );
}
