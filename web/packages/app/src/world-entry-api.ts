/** Exact, durable workspace entries into personal authored worlds. */

import { Transport, type TransportOptions } from '@exulanica/graph-client';

export interface SavedWorldEntry {
  readonly entryId: string;
  readonly worldId: string;
  readonly title: string;
  readonly sourceKind: 'personal' | 'authored';
  readonly sourceSnapshotId: string;
  readonly sourceSnapshotSha256: string;
  readonly authoredScene: AuthoredStarterScene | null;
  readonly authoredVersionId: string;
  readonly authoredStateSha256: string;
  readonly authoredEditSeq: number;
  readonly currentAuthoredStateSha256: string;
  readonly currentAuthoredEditSeq: number;
  readonly styleVersionId: string;
  readonly revision: number;
  readonly availability: 'available' | 'unavailable';
  readonly unavailableReason: 'source_deleted' | string | null;
  readonly sourceAttachments: readonly SavedWorldSourceAttachment[];
  /**
   * Photographs removed from this world, each once, with the detach that removed it. Parsed
   * entries always carry the list; it is optional so entries built elsewhere need not name it.
   */
  readonly previousSourceAttachments?: readonly SavedWorldPreviousSourceAttachment[];
  readonly createdAt: string;
  readonly updatedAt: string;
}

/** An entry-scoped reference photograph. It is lineage, not scene topology or reconstruction. */
export interface SavedWorldSourceAttachment {
  readonly attachmentId: string;
  readonly operationId: string;
  readonly captureId: string;
  readonly evidenceSpanId: string;
  readonly sourceSha256: string;
  readonly authorizationId: string;
  readonly screeningId: string;
  readonly role: 'reference';
  readonly attachedEntryRevision: number;
  readonly attachedBy: string;
  readonly attachedAt: string;
  readonly availability: 'available' | 'unavailable';
  readonly unavailableReason:
    | 'source_unavailable'
    | 'authorization_expired'
    | 'screening_expired'
    | 'viewer_unavailable'
    | null;
  /** Digest of the currently authorized viewer representation, never the original source digest. */
  readonly viewerSha256: string | null;
  readonly evidencePath: string | null;
}

/**
 * A photograph this world used and no longer uses. Its rows and media remain; the world may use
 * it again only through a rebind after a new human review. `availability` says whether the
 * original photograph is still a live source in the library.
 */
export interface SavedWorldPreviousSourceAttachment {
  readonly attachmentId: string;
  readonly operationId: string;
  readonly captureId: string;
  readonly evidenceSpanId: string;
  readonly sourceSha256: string;
  readonly authorizationId: string;
  readonly screeningId: string;
  readonly attachedEntryRevision: number;
  readonly attachedAt: string;
  readonly detachOperationId: string;
  readonly detachedEntryRevision: number;
  readonly detachedAt: string;
  readonly availability: 'available' | 'unavailable';
  readonly unavailableReason: 'source_unavailable' | null;
}

/** The entry cursor a membership event was prepared against, retained for exact retry. */
interface MembershipCursor {
  readonly entryId: string;
  readonly operationId: string;
  readonly baseRevision: number;
  readonly authoredVersionId: string;
  readonly authoredStateSha256: string;
  readonly authoredEditSeq: number;
  readonly styleVersionId: string;
}

/** Remove references from this world. The photographs stay in the library. */
export interface SourceDetachRequest extends MembershipCursor {
  readonly kind: 'detach';
  readonly attachmentIds: readonly string[];
}

/** Add removed photographs back; the server pins their new human review. */
export interface SourceRebindRequest extends MembershipCursor {
  readonly kind: 'rebind';
  readonly sources: readonly {
    readonly captureId: string;
    readonly evidenceSpanId: string;
  }[];
}

/** The complete entry cursor and selected references retained for exact retry. */
export interface SourceAttachmentRequest {
  readonly entryId: string;
  readonly operationId: string;
  readonly baseRevision: number;
  readonly authoredVersionId: string;
  readonly authoredStateSha256: string;
  readonly authoredEditSeq: number;
  readonly styleVersionId: string;
  readonly sources: readonly {
    readonly captureId: string;
    readonly evidenceSpanId: string;
  }[];
}

/** The bounded, source-independent region pinned by an authored starter entry. */
export interface AuthoredStarterScene {
  readonly schemaVersion: 1;
  readonly kind: 'authored-starter';
  readonly region: {
    readonly regionId: 'region:starter';
    readonly origin: 'authored';
    readonly module: {
      readonly key: 'region.authored-ground';
      readonly version: 1;
    };
    readonly ground: {
      readonly kind: 'flat';
      readonly halfWidthMm: number;
      readonly halfDepthMm: number;
      readonly elevationMm: number;
    };
    readonly spawn: {
      readonly xMm: number;
      readonly yMm: number;
      readonly zMm: number;
      readonly yawMicroradians: number;
    };
  };
}

export interface SavedWorldCandidate {
  readonly worldId: string;
  readonly authoredVersionId: string;
  readonly title: string;
  readonly sourceInvalidated: boolean;
  readonly styles: readonly { readonly versionId: string; readonly revision: number }[];
}

/** One saved world can resume directly. Multiple or unavailable entries require a visible choice. */
export function automaticWorldEntry(
  entries: readonly SavedWorldEntry[],
): SavedWorldEntry | null {
  return entries.length === 1 && entries[0]?.availability === 'available' ? entries[0] : null;
}

/**
 * Accept an entry refresh that changes only entry metadata or reference availability.
 * Rendering cursors require a full world reopen and may never be adopted under the live canvas.
 */
export function requireMetadataOnlyEntryUpdate(
  active: SavedWorldEntry,
  updated: SavedWorldEntry,
): SavedWorldEntry {
  if (active.entryId !== updated.entryId) {
    throw new Error('The saved world entry is no longer active.');
  }
  if (updated.revision < active.revision) {
    throw new Error('An older saved world response cannot replace the active entry.');
  }
  const sameWorldCursor =
    active.worldId === updated.worldId &&
    active.sourceKind === updated.sourceKind &&
    active.sourceSnapshotId === updated.sourceSnapshotId &&
    active.sourceSnapshotSha256 === updated.sourceSnapshotSha256 &&
    active.authoredVersionId === updated.authoredVersionId &&
    active.authoredStateSha256 === updated.authoredStateSha256 &&
    active.authoredEditSeq === updated.authoredEditSeq &&
    active.currentAuthoredStateSha256 === updated.currentAuthoredStateSha256 &&
    active.currentAuthoredEditSeq === updated.currentAuthoredEditSeq &&
    active.styleVersionId === updated.styleVersionId &&
    active.availability === updated.availability &&
    active.unavailableReason === updated.unavailableReason &&
    JSON.stringify(active.authoredScene) === JSON.stringify(updated.authoredScene);
  if (!sameWorldCursor) {
    throw new Error(
      'This saved world changed beyond its reference metadata. Reload the world before editing it.',
    );
  }
  return updated;
}

export class WorldEntryClient {
  readonly #transport: Transport;

  constructor(options: TransportOptions) {
    this.#transport = new Transport(options);
  }

  async entries(): Promise<readonly SavedWorldEntry[]> {
    const body = await this.#transport.getJson<unknown>('/world-entries');
    if (!Array.isArray(body)) throw new TypeError('The server returned an invalid world entry list.');
    return Object.freeze(body.map(parseEntry));
  }

  async entry(entryId: string): Promise<SavedWorldEntry> {
    return parseEntry(await this.#transport.getJson<unknown>(
      `/world-entries/${encodeURIComponent(entryId)}`,
    ));
  }

  /** Create or exact-idempotently reopen this workspace's source-independent starter. */
  async ensureStarter(title: string): Promise<SavedWorldEntry> {
    return parseEntry(await this.#transport.postJson<unknown>('/world-entries/starter', { title }));
  }

  async candidates(): Promise<readonly SavedWorldCandidate[]> {
    const body = await this.#transport.getJson<unknown>('/world-entries/candidates');
    if (!Array.isArray(body)) {
      throw new TypeError('The server returned an invalid saved world candidate list.');
    }
    return Object.freeze(body.map((value) => {
      const row = record(value, 'saved world candidate');
      const styles = row['styles'];
      if (!Array.isArray(styles)) throw new TypeError('Invalid saved world style choices.');
      return Object.freeze({
        worldId: text(row['world_id'], 'world ID'),
        authoredVersionId: text(row['authored_version_id'], 'authored version ID'),
        title: text(row['title'], 'world title'),
        sourceInvalidated: row['source_invalidated'] === true,
        styles: Object.freeze(styles.map((value) => {
          const style = record(value, 'saved world style choice');
          return Object.freeze({
            versionId: text(style['version_id'], 'style version ID'),
            revision: integer(style['revision'], 'style revision'),
          });
        })),
      });
    }));
  }

  async create(input: {
    readonly worldId: string;
    readonly title: string;
    readonly authoredVersionId: string;
    readonly styleVersionId: string;
  }): Promise<SavedWorldEntry> {
    return parseEntry(await this.#transport.postJson<unknown>('/world-entries', {
      world_id: input.worldId,
      title: input.title,
      source_kind: 'personal',
      authored_version_id: input.authoredVersionId,
      style_version_id: input.styleVersionId,
    }));
  }

  /** Explicitly open the first authored version from the current personal-source topology. */
  async createFromPersonalSources(
    title: string,
    worldId = 'atlas:default',
  ): Promise<SavedWorldEntry> {
    const query = `?world_id=${encodeURIComponent(worldId)}`;
    const state = record(
      await this.#transport.getJson<unknown>(`/world/styles/current${query}`),
      'world style state',
    );
    const style = record(state['current'], 'current world style');
    const topologyDigest = text(state['current_topology_digest'], 'topology digest');
    const authored = record(await this.#transport.postJson<unknown>(
      `/world/versions/bootstrap${query}`,
      { base_topology_digest: topologyDigest, title },
    ), 'bootstrapped authored world');
    return this.create({
      worldId,
      title,
      authoredVersionId: text(authored['version_id'], 'authored version ID'),
      styleVersionId: text(style['version_id'], 'style version ID'),
    });
  }

  async saveVersion(
    base: SavedWorldEntry,
    input: {
      readonly authoredVersionId: string;
      readonly authoredStateSha256: string;
      readonly authoredEditSeq: number;
      readonly styleVersionId: string;
    },
  ): Promise<SavedWorldEntry> {
    return parseEntry(await this.#transport.putJson<unknown>(
      `/world-entries/${encodeURIComponent(base.entryId)}`,
      {
        base_revision: base.revision,
        authored_version_id: input.authoredVersionId,
        expected_authored_state_sha256: input.authoredStateSha256,
        expected_authored_edit_seq: input.authoredEditSeq,
        style_version_id: input.styleVersionId,
      },
    ));
  }

  /** Rename without moving any authored, source, or appearance cursor. */
  async rename(base: SavedWorldEntry, title: string): Promise<SavedWorldEntry> {
    return parseEntry(await this.#transport.putJson<unknown>(
      `/world-entries/${encodeURIComponent(base.entryId)}`,
      {
        base_revision: base.revision,
        authored_version_id: base.authoredVersionId,
        expected_authored_state_sha256: base.authoredStateSha256,
        expected_authored_edit_seq: base.authoredEditSeq,
        style_version_id: base.styleVersionId,
        title,
      },
    ));
  }

  /** Attach reviewed photographs as references without moving any world or appearance cursor. */
  async attachSources(request: SourceAttachmentRequest): Promise<SavedWorldEntry> {
    if (request.sources.length < 1 || request.sources.length > 200) {
      throw new TypeError('Select between 1 and 200 reviewed photographs to attach.');
    }
    const unique = new Set(request.sources.map((source) =>
      `${source.captureId}:${source.evidenceSpanId}`));
    if (unique.size !== request.sources.length) {
      throw new TypeError('Each reviewed photograph can be attached only once per request.');
    }
    return parseEntry(await this.#transport.postJson<unknown>(
      `/world-entries/${encodeURIComponent(request.entryId)}/source-attachments`,
      {
        operation_id: request.operationId,
        base_revision: request.baseRevision,
        authored_version_id: request.authoredVersionId,
        authored_state_sha256: request.authoredStateSha256,
        authored_edit_seq: request.authoredEditSeq,
        style_version_id: request.styleVersionId,
        sources: request.sources.map((source) => ({
          capture_id: source.captureId,
          evidence_span_id: source.evidenceSpanId,
        })),
      },
    ));
  }

  /** Remove references from this world's current collection. No row or media is deleted. */
  async detachSources(request: SourceDetachRequest): Promise<SavedWorldEntry> {
    if (request.attachmentIds.length < 1 || request.attachmentIds.length > 200) {
      throw new TypeError('Remove between 1 and 200 reference photographs.');
    }
    if (new Set(request.attachmentIds).size !== request.attachmentIds.length) {
      throw new TypeError('Each reference photograph can be removed only once per request.');
    }
    return parseEntry(await this.#transport.postJson<unknown>(
      `/world-entries/${encodeURIComponent(request.entryId)}/source-detachments`,
      {
        ...cursorBody(request),
        selections: request.attachmentIds.map((attachmentId) => ({
          attachment_id: attachmentId,
        })),
      },
    ));
  }

  /** Add removed photographs back after a new human review. Never used without that review. */
  async rebindSources(request: SourceRebindRequest): Promise<SavedWorldEntry> {
    if (request.sources.length < 1 || request.sources.length > 200) {
      throw new TypeError('Add back between 1 and 200 reference photographs.');
    }
    if (new Set(request.sources.map((source) => source.captureId)).size !==
        request.sources.length) {
      throw new TypeError('Each photograph can be added back only once per request.');
    }
    return parseEntry(await this.#transport.postJson<unknown>(
      `/world-entries/${encodeURIComponent(request.entryId)}/source-rebinds`,
      {
        ...cursorBody(request),
        sources: request.sources.map((source) => ({
          capture_id: source.captureId,
          evidence_span_id: source.evidenceSpanId,
        })),
      },
    ));
  }

  /** Adopt only the exact current branch state returned with this entry read. */
  adoptLatestAuthored(base: SavedWorldEntry): Promise<SavedWorldEntry> {
    return this.saveVersion(base, {
      authoredVersionId: base.authoredVersionId,
      authoredStateSha256: base.currentAuthoredStateSha256,
      authoredEditSeq: base.currentAuthoredEditSeq,
      styleVersionId: base.styleVersionId,
    });
  }
}

function cursorBody(request: MembershipCursor): Record<string, unknown> {
  return {
    operation_id: request.operationId,
    base_revision: request.baseRevision,
    authored_version_id: request.authoredVersionId,
    authored_state_sha256: request.authoredStateSha256,
    authored_edit_seq: request.authoredEditSeq,
    style_version_id: request.styleVersionId,
  };
}

function parseEntry(value: unknown): SavedWorldEntry {
  const row = record(value, 'saved world entry');
  const sourceKind = row['source_kind'];
  const availability = row['availability'];
  if (sourceKind !== 'personal' && sourceKind !== 'authored') {
    throw new TypeError('The server returned an unknown world source kind.');
  }
  if (availability !== 'available' && availability !== 'unavailable') {
    throw new TypeError('The server returned an unknown world availability.');
  }
  const authoredScene = parseAuthoredScene(row['authored_scene']);
  const sourceAttachments = row['source_attachments'];
  if (!Array.isArray(sourceAttachments)) {
    throw new TypeError('The server returned invalid saved world source attachments.');
  }
  // A server before removed references existed sends no list; it has removed nothing.
  const previousAttachments = row['previous_source_attachments'] ?? [];
  if (!Array.isArray(previousAttachments)) {
    throw new TypeError('The server returned invalid removed saved world references.');
  }
  if (sourceKind === 'authored' && authoredScene === null) {
    throw new TypeError('An authored world entry did not include its pinned authored scene.');
  }
  if (sourceKind === 'personal' && authoredScene !== null) {
    throw new TypeError('A personal world entry cannot claim an authored starter scene.');
  }
  return Object.freeze({
    entryId: text(row['entry_id'], 'entry ID'),
    worldId: text(row['world_id'], 'world ID'),
    title: text(row['title'], 'world title'),
    sourceKind,
    sourceSnapshotId: text(row['source_snapshot_id'], 'source snapshot ID'),
    sourceSnapshotSha256: sha256(row['source_snapshot_sha256'], 'source snapshot digest'),
    authoredScene,
    authoredVersionId: text(row['authored_version_id'], 'authored version ID'),
    authoredStateSha256: sha256(row['authored_state_sha256'], 'authored state digest'),
    authoredEditSeq: integer(row['authored_edit_seq'], 'authored edit sequence'),
    currentAuthoredStateSha256: sha256(
      row['current_authored_state_sha256'], 'current authored state digest',
    ),
    currentAuthoredEditSeq: integer(
      row['current_authored_edit_seq'], 'current authored edit sequence',
    ),
    styleVersionId: text(row['style_version_id'], 'style version ID'),
    revision: integer(row['revision'], 'entry revision'),
    availability,
    unavailableReason: optionalText(row['unavailable_reason'], 'unavailable reason'),
    sourceAttachments: Object.freeze(sourceAttachments.map(parseSourceAttachment)),
    previousSourceAttachments: Object.freeze(previousAttachments.map(parsePreviousAttachment)),
    createdAt: text(row['created_at'], 'created time'),
    updatedAt: text(row['updated_at'], 'updated time'),
  });
}

function parseSourceAttachment(value: unknown): SavedWorldSourceAttachment {
  const row = record(value, 'saved world source attachment');
  const role = row['role'];
  const availability = row['availability'];
  const unavailableReason = optionalText(
    row['unavailable_reason'], 'source attachment unavailable reason',
  );
  const reasons = new Set([
    'source_unavailable', 'authorization_expired', 'screening_expired', 'viewer_unavailable',
  ]);
  if (role !== 'reference') throw new TypeError('The server returned an unknown attachment role.');
  if (availability !== 'available' && availability !== 'unavailable') {
    throw new TypeError('The server returned an unknown source attachment availability.');
  }
  if (
    (unavailableReason !== null && !reasons.has(unavailableReason)) ||
    (availability === 'available' && unavailableReason !== null) ||
    (availability === 'unavailable' && unavailableReason === null)
  ) {
    throw new TypeError('The server returned an invalid source attachment availability reason.');
  }
  const viewerSha256 = optionalSha256(row['viewer_sha256'], 'viewer digest');
  const evidencePath = optionalText(row['evidence_path'], 'attachment evidence path');
  if (
    (availability === 'available' && (viewerSha256 === null || evidencePath === null)) ||
    (availability === 'unavailable' && (viewerSha256 !== null || evidencePath !== null))
  ) {
    throw new TypeError('The source attachment viewer fields disagree with its availability.');
  }
  return Object.freeze({
    attachmentId: text(row['attachment_id'], 'attachment ID'),
    operationId: text(row['operation_id'], 'attachment operation ID'),
    captureId: text(row['capture_id'], 'attachment capture ID'),
    evidenceSpanId: text(row['evidence_span_id'], 'attachment evidence span ID'),
    sourceSha256: sha256(row['source_sha256'], 'original source digest'),
    authorizationId: text(row['authorization_id'], 'attachment authorization ID'),
    screeningId: text(row['screening_id'], 'attachment screening ID'),
    role,
    attachedEntryRevision: integer(row['attached_entry_revision'], 'attached entry revision'),
    attachedBy: text(row['attached_by'], 'attachment actor'),
    attachedAt: text(row['attached_at'], 'attachment time'),
    availability,
    unavailableReason: unavailableReason as SavedWorldSourceAttachment['unavailableReason'],
    viewerSha256,
    evidencePath,
  });
}

function parsePreviousAttachment(value: unknown): SavedWorldPreviousSourceAttachment {
  const row = record(value, 'removed saved world reference');
  const availability = row['availability'];
  const unavailableReason = row['unavailable_reason'];
  if (
    !(availability === 'available' && unavailableReason === null) &&
    !(availability === 'unavailable' && unavailableReason === 'source_unavailable')
  ) {
    throw new TypeError('The server returned an invalid removed reference availability.');
  }
  return Object.freeze({
    attachmentId: text(row['attachment_id'], 'removed reference attachment ID'),
    operationId: text(row['operation_id'], 'removed reference operation ID'),
    captureId: text(row['capture_id'], 'removed reference capture ID'),
    evidenceSpanId: text(row['evidence_span_id'], 'removed reference evidence span ID'),
    sourceSha256: sha256(row['source_sha256'], 'removed reference source digest'),
    authorizationId: text(row['authorization_id'], 'removed reference authorization ID'),
    screeningId: text(row['screening_id'], 'removed reference screening ID'),
    attachedEntryRevision: integer(row['attached_entry_revision'], 'attached entry revision'),
    attachedAt: text(row['attached_at'], 'attachment time'),
    detachOperationId: text(row['detach_operation_id'], 'removal operation ID'),
    detachedEntryRevision: integer(row['detached_entry_revision'], 'removal entry revision'),
    detachedAt: text(row['detached_at'], 'removal time'),
    availability,
    unavailableReason,
  });
}

function parseAuthoredScene(value: unknown): AuthoredStarterScene | null {
  if (value === null) return null;
  const scene = record(value, 'authored scene');
  if (scene['schema_version'] !== 1 || scene['kind'] !== 'authored-starter') {
    throw new TypeError('The server returned an unsupported authored scene.');
  }
  const region = record(scene['region'], 'authored region');
  const module = record(region['module'], 'authored region module');
  const ground = record(region['ground'], 'authored region ground');
  const spawn = record(region['spawn'], 'authored region spawn');
  if (
    region['region_id'] !== 'region:starter' || region['origin'] !== 'authored' ||
    module['key'] !== 'region.authored-ground' || module['version'] !== 1 ||
    ground['kind'] !== 'flat'
  ) {
    throw new TypeError('The server returned an unsupported authored starter region.');
  }
  const halfWidthMm = positiveInteger(ground['half_width_mm'], 'authored ground half width');
  const halfDepthMm = positiveInteger(ground['half_depth_mm'], 'authored ground half depth');
  const elevationMm = integer(ground['elevation_mm'], 'authored ground elevation');
  const xMm = integer(spawn['x_mm'], 'authored spawn x');
  const yMm = integer(spawn['y_mm'], 'authored spawn y');
  const zMm = integer(spawn['z_mm'], 'authored spawn z');
  const yawMicroradians = integer(spawn['yaw_microradians'], 'authored spawn yaw');
  if (Math.abs(xMm) > halfWidthMm || Math.abs(zMm) > halfDepthMm) {
    throw new TypeError('The authored starter spawn is outside its ground.');
  }
  return Object.freeze({
    schemaVersion: 1,
    kind: 'authored-starter',
    region: Object.freeze({
      regionId: 'region:starter',
      origin: 'authored',
      module: Object.freeze({ key: 'region.authored-ground', version: 1 }),
      ground: Object.freeze({ kind: 'flat', halfWidthMm, halfDepthMm, elevationMm }),
      spawn: Object.freeze({ xMm, yMm, zMm, yawMicroradians }),
    }),
  });
}

function record(value: unknown, name: string): Record<string, unknown> {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new TypeError(`The server returned an invalid ${name}.`);
  }
  return value as Record<string, unknown>;
}

function text(value: unknown, name: string): string {
  if (typeof value !== 'string' || value.length === 0) throw new TypeError(`Invalid ${name}.`);
  return value;
}

function optionalText(value: unknown, name: string): string | null {
  return value === null ? null : text(value, name);
}

function integer(value: unknown, name: string): number {
  if (!Number.isSafeInteger(value)) throw new TypeError(`Invalid ${name}.`);
  return value as number;
}

function positiveInteger(value: unknown, name: string): number {
  const parsed = integer(value, name);
  if (parsed <= 0) throw new TypeError(`Invalid ${name}.`);
  return parsed;
}

function sha256(value: unknown, name: string): string {
  const parsed = text(value, name);
  if (!/^[0-9a-f]{64}$/.test(parsed)) throw new TypeError(`Invalid ${name}.`);
  return parsed;
}

function optionalSha256(value: unknown, name: string): string | null {
  return value === null ? null : sha256(value, name);
}
