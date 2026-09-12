/**
 * Authenticated adapter for the backend-owned world-style lifecycle.
 *
 * The server intentionally exposes a camel-case catalog and snake-case persisted records. This
 * file is the only translation layer. It validates the inert catalog against the reviewed local
 * recipe registry before any profile is rendered, completes and validates parameters locally,
 * and keeps preview handles transient.
 */

import type { WorldStyleParameterDefinition, WorldStyleParameterValue } from '@exulanica/atlas-core';
import { ApiError, Transport, type TransportOptions } from '@exulanica/graph-client';
import {
  WORLD_STYLE_CONTRACT_COMMIT,
  WORLD_STYLE_RECIPES,
  worldStyleRecipe,
} from '@exulanica/presentation';

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

export class WorldStyleClient {
  readonly #transport: Transport;
  readonly #ids: IdFactory;
  #state: WorldStyleState | null = null;
  #versions: readonly WorldStyleVersionRecord[] = Object.freeze([]);
  #active: ActiveWorldStylePreview | null = null;
  #previewQueue: Promise<void> = Promise.resolve();

  constructor(options: TransportOptions & { readonly ids?: IdFactory }) {
    this.#transport = new Transport(options);
    this.#ids = options.ids ?? (() => globalThis.crypto.randomUUID());
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

  async connect(): Promise<WorldStyleConnection> {
    const [catalog, state, versions] = await Promise.all([
      this.#transport.getJson<unknown>('/world/styles/catalog'),
      this.#transport.getJson<unknown>('/world/styles/current'),
      this.#transport.getJson<unknown>('/world/styles/versions'),
    ]);
    validateCatalog(catalog);
    this.#state = parseState(state);
    this.#versions = parseVersions(versions);
    return Object.freeze({ state: this.#state, versions: this.#versions });
  }

  async refresh(): Promise<WorldStyleState> {
    const state = parseState(await this.#transport.getJson<unknown>('/world/styles/current'));
    this.#state = state;
    return state;
  }

  async refreshVersions(): Promise<readonly WorldStyleVersionRecord[]> {
    this.#versions = parseVersions(
      await this.#transport.getJson<unknown>('/world/styles/versions'),
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
      `/world/styles/proposals/${encodeURIComponent(proposalId)}`,
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
        `/world/styles/previews/${encodeURIComponent(active.preview.previewId)}`,
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
    try {
      const version = parseVersion(await this.#transport.postJson<unknown>(
        `/world/styles/previews/${encodeURIComponent(active.preview.previewId)}/apply`,
        {
          baseStyleVersionId: active.baseStyleVersionId,
          baseTopologyDigest: active.baseTopologyDigest,
        },
      ));
      this.#active = null;
      this.#state = Object.freeze({
        currentTopologyDigest: active.baseTopologyDigest,
        current: version,
      });
      this.#versions = appendVersion(this.#versions, version);
      return Object.freeze({ kind: 'applied', version });
    } catch (error) {
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
    try {
      const version = parseVersion(await this.#transport.postJson<unknown>(
        '/world/styles/rollback',
        {
          targetVersionId,
          baseStyleVersionId: state.current.versionId,
          baseTopologyDigest: state.currentTopologyDigest,
          origin: 'settings',
          originReference: 'appearance-history',
        },
      ));
      this.#state = Object.freeze({
        currentTopologyDigest: state.currentTopologyDigest,
        current: version,
      });
      this.#versions = appendVersion(this.#versions, version);
      return Object.freeze({ kind: 'applied', version });
    } catch (error) {
      if (!(error instanceof ApiError) || error.code !== 'stale_style_version') throw error;
      return Object.freeze({ kind: 'stale', state: await this.refresh() });
    }
  }

  async #replacePreview(request: PreviewRequest): Promise<ActiveWorldStylePreview> {
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
      '/world/styles/previews',
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

function validateCatalog(value: unknown): void {
  const catalog = record(value, 'world style catalog');
  if (catalog['schemaVersion'] !== 1) {
    throw new WorldStyleContractError('unknown_catalog_version', 'The server returned an unsupported world style catalog.');
  }
  const source = record(catalog['contractSource'], 'world style catalog source');
  if (source['frontendCommit'] !== WORLD_STYLE_CONTRACT_COMMIT) {
    throw new WorldStyleContractError(
      'catalog_contract_mismatch',
      'The server and this Atlas do not share the same reviewed world recipe contract.',
    );
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
  const executableBinding = recipe !== null && (
    (sameValue(binding.modules, recipe.modules) && sameValue(binding.capabilityMapping,
      Object.fromEntries(recipe.controls.map(control => [control.key, control.capability])))) ||
    (historical && (recipe.readCompatibleBindings ?? []).some(compatible =>
      sameValue(binding.modules, compatible.modules) &&
      sameValue(binding.capabilityMapping, compatible.capabilityMapping)))
  );
  if (
    recipe === null ||
    binding.frontendCommit !== WORLD_STYLE_CONTRACT_COMMIT ||
    binding.profileId !== profileId ||
    binding.profileVersion !== profileVersion ||
    binding.availability !== recipe.availability ||
    binding.origin !== recipe.origin ||
    !executableBinding
  ) {
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
