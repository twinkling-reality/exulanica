/**
 * Composition preview and apply, from the client's side.
 *
 * Speaks `POST /world/versions/{version_id}/compositions/preview` and `.../compositions/apply`,
 * both with `?world_id=`. The request names references and intent only: which source, where it
 * goes, and the version state the caller last read. Readiness, rights, byte availability and the
 * version the server compared against are all answered by the server; nothing here can assert
 * them, and nothing here sends a field that could.
 *
 * Apply for a versioned world goes through `WorldObjectsClient.compositionApply`, so it shares the
 * serialized write queue, the stale-base re-read and the saved-entry cursor advance every other
 * authored edit uses. This module owns the composition vocabulary (request, preview document,
 * stable blocked codes); that client owns the transport and the version.
 */

import { Transport, type TransportOptions } from '@exulanica/graph-client';
import {
  assertTransform,
  parseVersion,
  type AlternateVersion,
  type ObjectBehaviour,
  type ObjectRole,
  type ObjectWriteResult,
  type TransformInput,
  type WorldObjectsClient,
} from './world-objects-api.js';
import type {
  SavedWorldEntry,
  SavedWorldSourceAttachment,
} from './world-entry-api.js';

// -- the request ---------------------------------------------------------------------------------

export type CompositionSourceKind = 'reviewed_asset' | 'environment_admission' | 'source_attachment';

export type EnvironmentSelectionInput =
  | { readonly kind: 'whole_asset' }
  | { readonly kind: 'feature'; readonly featureId: string; readonly renderBatchId: number };

export interface SourceAnchorInput {
  readonly frameName: string;
  readonly coordinateScale: number;
  readonly coordinates: readonly number[];
}

/** What to add, by reference. The server resolves every digest, right and byte behind it. */
export type CompositionSource =
  | { readonly kind: 'reviewed_asset'; readonly assetKey: string }
  | {
    readonly kind: 'environment_admission';
    readonly admissionId: string;
    readonly renderAssetId: string;
    /** Required for a feature selection and null for a whole asset. */
    readonly publicationId: string | null;
    readonly selection: EnvironmentSelectionInput;
  }
  | { readonly kind: 'source_attachment'; readonly entryId: string; readonly attachmentId: string };

/** Where it goes. The same pose is previewed and applied. */
export interface CompositionPlacement {
  readonly subjectId: string;
  readonly regionId: string;
  readonly transform: TransformInput;
  readonly originRole: ObjectRole;
  /** Reviewed assets only. */
  readonly behaviour?: ObjectBehaviour | null;
  /** Environment admissions only, where it is required. */
  readonly sourceAnchor?: SourceAnchorInput;
}

export interface CompositionRequest {
  readonly source: CompositionSource;
  readonly placement: CompositionPlacement | null;
}

export interface CompositionApplyRequest extends CompositionRequest {
  readonly placement: CompositionPlacement;
}

export class CompositionRequestError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'CompositionRequestError';
  }
}

function wireSource(source: CompositionSource): Record<string, unknown> {
  switch (source.kind) {
    case 'reviewed_asset':
      return { kind: source.kind, asset_key: source.assetKey };
    case 'environment_admission':
      return {
        kind: source.kind,
        admission_id: source.admissionId,
        render_asset_id: source.renderAssetId,
        publication_id: source.publicationId,
        selection: source.selection.kind === 'whole_asset'
          ? { kind: 'whole_asset' }
          : {
            kind: 'feature',
            feature_id: source.selection.featureId,
            render_batch_id: source.selection.renderBatchId,
          },
      };
    case 'source_attachment':
      return { kind: source.kind, entry_id: source.entryId, attachment_id: source.attachmentId };
  }
}

function wirePlacement(
  kind: CompositionSourceKind,
  placement: CompositionPlacement,
): Record<string, unknown> {
  assertTransform(placement.transform);
  const behaviour = placement.behaviour ?? null;
  // The server refuses a behaviour on any other kind and an anchor on any other kind, so a
  // request that carries one is a fault here rather than something to send and have ignored.
  if (behaviour !== null && kind !== 'reviewed_asset') {
    throw new CompositionRequestError('Only a reviewed asset can carry a behaviour.');
  }
  if ((placement.sourceAnchor !== undefined) !== (kind === 'environment_admission')) {
    throw new CompositionRequestError('A source anchor belongs to an environment placement only.');
  }
  const body: Record<string, unknown> = {
    subject_id: placement.subjectId,
    region_id: placement.regionId,
    transform: {
      x_mm: placement.transform.xMm,
      y_mm: placement.transform.yMm,
      z_mm: placement.transform.zMm,
      yaw_microradians: placement.transform.yawMicroradians,
      scale_milli: placement.transform.scaleMilli,
    },
    origin_role: placement.originRole,
  };
  if (kind === 'reviewed_asset') {
    body['behaviour'] = behaviour === null ? null : {
      behaviour_key: behaviour.behaviourKey,
      behaviour_version: behaviour.behaviourVersion,
      parameters: { ...behaviour.parameters },
    };
  }
  if (placement.sourceAnchor !== undefined) {
    body['source_anchor'] = {
      frame_name: placement.sourceAnchor.frameName,
      coordinate_scale: placement.sourceAnchor.coordinateScale,
      coordinates: [...placement.sourceAnchor.coordinates],
    };
  }
  return body;
}

/**
 * The request body without its base: `source` and `placement` in wire names.
 *
 * The base and, for apply, the saved-entry binding are added by the client that holds the version
 * they belong to, so they cannot disagree with it.
 */
export function compositionRequestBody(request: CompositionRequest): Record<string, unknown> {
  return {
    source: wireSource(request.source),
    placement: request.placement === null
      ? null
      : wirePlacement(request.source.kind, request.placement),
  };
}

// -- the preview document ------------------------------------------------------------------------

/**
 * The stable refusal codes the server reports, in the order the contract lists them.
 *
 * A code outside this list is still carried on the document as it arrived; it is shown with a
 * generic sentence rather than dropped or guessed at.
 */
export const COMPOSITION_BLOCKED_REASONS = Object.freeze([
  'source_invalidated',
  'stale_base',
  'unknown_asset',
  'asset_bytes_unavailable',
  'environment_binding_unknown',
  'environment_withdrawn',
  'compose_not_permitted',
  'environment_bytes_unavailable',
  'environment_binding_drift',
  'unknown_attachment',
  'expired_source_not_composable',
  'attachment_is_not_composition',
  'placement_required',
  'invalid_placement',
  'subject_already_present',
] as const);

export type CompositionBlockedReason = typeof COMPOSITION_BLOCKED_REASONS[number];

export function isCompositionBlockedReason(value: unknown): value is CompositionBlockedReason {
  return typeof value === 'string'
    && (COMPOSITION_BLOCKED_REASONS as readonly string[]).includes(value);
}

export type CompositionChangeKind = 'add_object' | 'add_environment' | 'none';

/** Whether the bytes the placement would draw are stored; null when the source did not resolve. */
export type CompositionBytes = 'available' | 'unavailable' | 'not_applicable' | null;

export interface CompositionPreview {
  readonly availability: 'ready' | 'blocked';
  /** Null exactly when ready. An unrecognised code is kept as it arrived. */
  readonly blockedReason: string | null;
  /** The server's own sentence for logs and details. Never branched on. */
  readonly blockedDetail: string | null;
  readonly source: {
    readonly kind: CompositionSourceKind;
    readonly contentSha256: string | null;
    readonly bytes: CompositionBytes;
    /** The identifiers the server resolved, by wire name (for example `asset_key`). */
    readonly identifiers: Readonly<Record<string, string | null>>;
  };
  /** The version as stored when the server answered, never an echo of the request. */
  readonly version: {
    readonly authoredVersionId: string;
    readonly worldId: string;
    readonly stateSha256: string;
    readonly editSeq: number;
    readonly sourceSnapshotId: string;
    readonly styleVersionId: string | null;
  };
  readonly wouldChange: {
    readonly kind: CompositionChangeKind;
    readonly subjectId: string | null;
    /** The canonical document apply would store; present only when ready. */
    readonly document: Readonly<Record<string, unknown>> | null;
    readonly preserves: readonly string[];
  };
}

export class CompositionContractError extends Error {
  constructor(label: string) {
    super(`The server returned an invalid composition ${label}.`);
    this.name = 'CompositionContractError';
  }
}

function record(value: unknown, label: string): Readonly<Record<string, unknown>> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new CompositionContractError(label);
  }
  return value as Readonly<Record<string, unknown>>;
}

function text(value: unknown, label: string): string {
  if (typeof value !== 'string' || value.length === 0) throw new CompositionContractError(label);
  return value;
}

function textOrNull(value: unknown, label: string): string | null {
  if (value === null || value === undefined) return null;
  return text(value, label);
}

function digestOrNull(value: unknown, label: string): string | null {
  const parsed = textOrNull(value, label);
  if (parsed !== null && !/^[0-9a-f]{64}$/.test(parsed)) throw new CompositionContractError(label);
  return parsed;
}

function oneOf<T extends string>(value: unknown, allowed: readonly T[], label: string): T {
  if (typeof value !== 'string' || !(allowed as readonly string[]).includes(value)) {
    throw new CompositionContractError(label);
  }
  return value as T;
}

const SOURCE_KINDS = ['reviewed_asset', 'environment_admission', 'source_attachment'] as const;
const CHANGE_KINDS = ['add_object', 'add_environment', 'none'] as const;
const BYTES_STATES = ['available', 'unavailable', 'not_applicable'] as const;

/** Parse the preview document. Availability and blocked_reason are the server's, and only its. */
export function parseCompositionPreview(value: unknown): CompositionPreview {
  const row = record(value, 'preview');
  const availability = oneOf(row['availability'], ['ready', 'blocked'] as const, 'availability');
  const blockedReason = textOrNull(row['blocked_reason'], 'blocked reason');
  if ((availability === 'ready') !== (blockedReason === null)) {
    throw new CompositionContractError('blocked reason');
  }
  const source = record(row['source'], 'source');
  const kind = oneOf(source['kind'], SOURCE_KINDS, 'source kind');
  const bytes = source['bytes'] === null || source['bytes'] === undefined
    ? null
    : oneOf(source['bytes'], BYTES_STATES, 'source bytes');
  const identifiers: Record<string, string | null> = {};
  for (const [key, held] of Object.entries(source)) {
    if (key === 'kind' || key === 'content_sha256' || key === 'bytes') continue;
    if (typeof held === 'string' || held === null) identifiers[key] = held;
  }
  const version = record(row['version'], 'version');
  const editSeq = version['edit_seq'];
  if (!Number.isSafeInteger(editSeq) || (editSeq as number) < 0) {
    throw new CompositionContractError('edit sequence');
  }
  const stateSha256 = digestOrNull(version['state_sha256'], 'state digest');
  if (stateSha256 === null) throw new CompositionContractError('state digest');
  const change = record(row['would_change'], 'would_change');
  const preserves = change['preserves'];
  if (!Array.isArray(preserves) || !preserves.every((item) => typeof item === 'string')) {
    throw new CompositionContractError('preserves');
  }
  const documentValue = change['document'];
  return Object.freeze({
    availability,
    blockedReason,
    blockedDetail: typeof row['blocked_detail'] === 'string' ? row['blocked_detail'] : null,
    source: Object.freeze({
      kind,
      contentSha256: digestOrNull(source['content_sha256'], 'source digest'),
      bytes,
      identifiers: Object.freeze(identifiers),
    }),
    version: Object.freeze({
      authoredVersionId: text(version['authored_version_id'], 'authored version id'),
      worldId: text(version['world_id'], 'world id'),
      stateSha256,
      editSeq: editSeq as number,
      sourceSnapshotId: text(version['source_snapshot_id'], 'source snapshot id'),
      styleVersionId: textOrNull(version['style_version_id'], 'style version id'),
    }),
    wouldChange: Object.freeze({
      kind: oneOf(change['kind'], CHANGE_KINDS, 'change kind'),
      subjectId: textOrNull(change['subject_id'], 'subject id'),
      document: documentValue === null || documentValue === undefined
        ? null
        : Object.freeze({ ...record(documentValue, 'change document') }),
      preserves: Object.freeze([...preserves as string[]]),
    }),
  });
}

// -- through a versioned world ---------------------------------------------------------------------

export type CompositionTransport = Pick<WorldObjectsClient, 'compositionPreview' | 'compositionApply'>;

/** Ask the server whether this addition is ready against the version the caller read. */
export async function previewComposition(
  client: CompositionTransport,
  base: AlternateVersion,
  request: CompositionRequest,
): Promise<CompositionPreview> {
  return parseCompositionPreview(
    await client.compositionPreview(base, compositionRequestBody(request)),
  );
}

/** Apply the same request. The server resolves it again and writes it, or refuses by code. */
export function applyComposition(
  client: CompositionTransport,
  base: AlternateVersion,
  request: CompositionApplyRequest,
): Promise<ObjectWriteResult> {
  return client.compositionApply(base, compositionRequestBody(request));
}

// -- addressed by explicit ids ---------------------------------------------------------------------

/** A request for a caller that holds ids rather than a version it read. */
export interface AddressedCompositionRequest extends CompositionRequest {
  readonly worldId: string;
  readonly baseStateSha256: string;
}

export interface AddressedCompositionApplyRequest extends AddressedCompositionRequest {
  readonly placement: CompositionPlacement;
  readonly savedEntry?: {
    readonly entryId: string;
    readonly baseRevision: number;
    readonly authoredStateSha256: string;
    readonly authoredEditSeq: number;
  };
}

/** The same two routes, addressed by version id and world id. */
export class CompositionPreviewClient {
  readonly #transport: Transport;

  constructor(options: TransportOptions) {
    this.#transport = new Transport(options);
  }

  async preview(
    versionId: string,
    request: AddressedCompositionRequest,
  ): Promise<CompositionPreview> {
    return parseCompositionPreview(await this.#transport.postJson<unknown>(
      compositionPath(versionId, 'preview', request.worldId),
      { base_state_sha256: request.baseStateSha256, ...compositionRequestBody(request) },
    ));
  }

  async apply(
    versionId: string,
    request: AddressedCompositionApplyRequest,
  ): Promise<AlternateVersion> {
    const body: Record<string, unknown> = {
      base_state_sha256: request.baseStateSha256,
      ...compositionRequestBody(request),
    };
    if (request.savedEntry !== undefined) {
      body['saved_entry'] = {
        entry_id: request.savedEntry.entryId,
        base_revision: request.savedEntry.baseRevision,
        authored_state_sha256: request.savedEntry.authoredStateSha256,
        authored_edit_seq: request.savedEntry.authoredEditSeq,
      };
    }
    return parseVersion(await this.#transport.postJson<unknown>(
      compositionPath(versionId, 'apply', request.worldId),
      body,
    ));
  }
}

export function compositionPath(
  versionId: string,
  route: 'preview' | 'apply',
  worldId: string,
): string {
  return `/world/versions/${encodeURIComponent(versionId)}/compositions/${route}`
    + `?world_id=${encodeURIComponent(worldId)}`;
}

/**
 * A preview request for one saved-world reference photograph.
 *
 * It names the entry and the attachment and nothing else. The server resolves the attachment and
 * answers blocked: a reference stays a reference and never becomes placed geometry.
 */
export function sourceAttachmentCompositionRequest(
  entry: SavedWorldEntry,
  attachment: SavedWorldSourceAttachment,
): { readonly versionId: string; readonly request: AddressedCompositionRequest } {
  return Object.freeze({
    versionId: entry.authoredVersionId,
    request: Object.freeze({
      worldId: entry.worldId,
      baseStateSha256: entry.authoredStateSha256,
      source: Object.freeze({
        kind: 'source_attachment' as const,
        entryId: entry.entryId,
        attachmentId: attachment.attachmentId,
      }),
      placement: null,
    }),
  });
}
