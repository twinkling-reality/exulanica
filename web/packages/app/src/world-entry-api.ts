/** Exact, durable workspace entries into personal authored worlds, and the worlds they name. */

import { Transport, type TransportOptions } from '@exulanica/graph-client';
import { worldPath } from './world-scope.js';

/**
 * The kind the server gives a world composed from the workspace's own photographs and other
 * personal sources. The server's registry states the kinds (`exulanica/world/worlds.py`);
 * `world-entry-api.test.ts` holds this spelling to the count policy the server reads.
 */
export const PERSONAL_SOURCE_WORLD_KIND = 'personal-source';

/** How many worlds of each kind one workspace may hold; null where the policy sets no limit. */
export interface WorldCountPolicy {
  readonly policyId: string;
  readonly version: number;
  readonly sha256: string;
  readonly limits: Readonly<Record<string, number | null>>;
}

/** One world the workspace holds, as `GET /worlds` lists it. */
export interface WorkspaceWorld {
  readonly worldId: string;
  readonly kind: string;
  readonly createdAt: string;
}

/** Every world the workspace holds, oldest first, with the policy that bounds how many. */
export interface WorkspaceWorlds {
  readonly policy: WorldCountPolicy;
  readonly worlds: readonly WorkspaceWorld[];
}

/** There is no single personal-source world to act on: none exists, or several do. */
export class PersonalSourceWorldUnresolved extends Error {
  constructor(
    readonly code: 'no_personal_source_world' | 'several_personal_source_worlds',
    readonly worldIds: readonly string[],
  ) {
    super(code === 'no_personal_source_world'
      ? 'This workspace has no world built from its own photographs yet.'
      : 'This workspace has more than one world built from its own photographs; choose one.');
    this.name = 'PersonalSourceWorldUnresolved';
  }
}

/**
 * The workspace's one personal-source world, read from the server's list rather than assumed.
 *
 * With the count policy at one there is at most one, and this is it. A list holding several is
 * refused rather than resolved by position or recency: which of them is meant is the person's
 * choice, and a caller that has it passes the world id itself.
 */
export function personalSourceWorld(worlds: WorkspaceWorlds): string {
  const personal = worlds.worlds.filter((world) => world.kind === PERSONAL_SOURCE_WORLD_KIND);
  if (personal.length === 1) return personal[0]!.worldId;
  throw new PersonalSourceWorldUnresolved(
    personal.length === 0 ? 'no_personal_source_world' : 'several_personal_source_worlds',
    personal.map((world) => world.worldId),
  );
}

/** What composing the workspace's reviewed photographs into a world would do now. */
export type PersonalWorldAction = 'create_world' | 'update_world' | 'save_entry';

/**
 * The server's answer to "can a world be made from my reviewed photographs now?"
 *
 * Every decision in it is the server's (`GET /worlds/personal-source`): which photographs count,
 * how they group into places, and each refusal with the words it is shown in. The browser reads
 * it and never works any of it out again.
 */
export interface PersonalWorldState {
  readonly action: PersonalWorldAction | null;
  readonly refusal: { readonly code: string; readonly detail: string } | null;
  readonly worldId: string | null;
  readonly savedEntryId: string | null;
  readonly photographs: {
    readonly reviewed: number;
    readonly composed: number;
    readonly outsideSceneGroups: number;
  };
  readonly regions: number;
  /** The digest the write takes back, so it composes exactly what this read showed. */
  readonly topologyDigest: string | null;
  readonly currentTopologyDigest: string | null;
}

/** What `POST /worlds/personal-source` composed, and the world every later request names. */
export interface ComposedPersonalWorld {
  readonly action: PersonalWorldAction;
  readonly worldId: string;
  readonly topologyDigest: string;
  readonly styleVersionId: string;
  readonly savedEntryId: string | null;
}

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

/**
 * The ground an authored region states.
 *
 * `flat` is a ground whose horizontal extent is a real property of the place: the perimeter is
 * where the described surface actually stops. `endless` states that there is no such perimeter and
 * therefore carries none. How far a person can walk across an endless ground is a limit of this
 * renderer, not of the world, and it is stated by the binding that has it rather than by a stored
 * descriptor that every world created today would keep.
 */
export type AuthoredGround =
  | {
      readonly kind: 'flat';
      readonly halfWidthMm: number;
      readonly halfDepthMm: number;
      readonly elevationMm: number;
    }
  | {
      readonly kind: 'endless';
      readonly elevationMm: number;
    };

/** The source-independent region pinned by an authored starter entry. */
export interface AuthoredStarterScene {
  readonly schemaVersion: 1;
  readonly kind: 'authored-starter';
  readonly region: {
    readonly regionId: 'region:starter';
    readonly origin: 'authored';
    readonly module: {
      readonly key: 'region.authored-ground';
      readonly version: 1 | 2;
    };
    readonly ground: AuthoredGround;
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

  /** Every world this workspace holds, and how many of each kind it may hold. */
  async worlds(): Promise<WorkspaceWorlds> {
    return parseWorlds(await this.#transport.getJson<unknown>('/worlds'));
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

  /**
   * Explicitly open the first authored version from a personal-source world's current topology.
   *
   * `worldId` names the world; without it, the workspace's one personal-source world is read from
   * `GET /worlds`, and a workspace with none or with several is refused by name.
   */
  async createFromPersonalSources(title: string, worldId?: string): Promise<SavedWorldEntry> {
    const world = worldId ?? personalSourceWorld(await this.worlds());
    const state = record(
      await this.#transport.getJson<unknown>(worldPath('/world/styles/current', world)),
      'world style state',
    );
    const style = record(state['current'], 'current world style');
    const topologyDigest = text(state['current_topology_digest'], 'topology digest');
    const authored = record(await this.#transport.postJson<unknown>(
      worldPath('/world/versions/bootstrap', world),
      { base_topology_digest: topologyDigest, title },
    ), 'bootstrapped authored world');
    return this.create({
      worldId: world,
      title,
      authoredVersionId: text(authored['version_id'], 'authored version ID'),
      styleVersionId: text(style['version_id'], 'style version ID'),
    });
  }

  /** Whether a world can be made or brought up to date from the reviewed photographs now. */
  async personalWorld(): Promise<PersonalWorldState> {
    return parsePersonalWorld(await this.#transport.getJson<unknown>('/worlds/personal-source'));
  }

  /**
   * Compose exactly the photographs `state` showed, then save or reopen the world they make.
   *
   * The composition is refused by the server if the photographs changed since `state` was read.
   * When a saved world already names the personal-source world, that entry is read and returned
   * rather than a second one created; otherwise the new world is opened through the protected
   * bootstrap and saved under `title`. A state the server refused is not sent.
   */
  async makeFromPersonalSources(
    state: PersonalWorldState,
    title: string,
  ): Promise<SavedWorldEntry> {
    if (state.action === null || state.topologyDigest === null) {
      throw new Error(state.refusal?.detail ?? 'A world cannot be made from your photographs now.');
    }
    const composed = parseComposedPersonalWorld(await this.#transport.postJson<unknown>(
      '/worlds/personal-source',
      { topology_digest: state.topologyDigest },
    ));
    return composed.savedEntryId !== null
      ? this.entry(composed.savedEntryId)
      : this.createFromPersonalSources(title, composed.worldId);
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

function parseWorlds(value: unknown): WorkspaceWorlds {
  const body = record(value, 'world list');
  const policy = record(body['policy'], 'world count policy');
  const limits = record(policy['limits'], 'world count limits');
  const worlds = body['worlds'];
  if (!Array.isArray(worlds)) throw new TypeError('The server returned an invalid world list.');
  return Object.freeze({
    policy: Object.freeze({
      policyId: text(policy['policy_id'], 'policy ID'),
      version: positiveInteger(policy['version'], 'policy version'),
      sha256: sha256(policy['sha256'], 'policy digest'),
      limits: Object.freeze(Object.fromEntries(Object.entries(limits).map(([kind, limit]) => [
        kind, limit === null ? null : positiveInteger(limit, `${kind} limit`),
      ]))),
    }),
    worlds: Object.freeze(worlds.map((item) => {
      const world = record(item, 'world');
      return Object.freeze({
        worldId: text(world['world_id'], 'world ID'),
        kind: text(world['kind'], 'world kind'),
        createdAt: text(world['created_at'], 'world creation time'),
      });
    })),
  });
}

const PERSONAL_WORLD_ACTIONS: ReadonlySet<string> = new Set<PersonalWorldAction>([
  'create_world', 'update_world', 'save_entry',
]);

function personalWorldAction(value: unknown): PersonalWorldAction {
  if (typeof value !== 'string' || !PERSONAL_WORLD_ACTIONS.has(value)) {
    throw new TypeError('The server returned an unknown personal world action.');
  }
  return value as PersonalWorldAction;
}

function parsePersonalWorld(value: unknown): PersonalWorldState {
  const body = record(value, 'personal world state');
  const photographs = record(body['photographs'], 'personal world photographs');
  const action = body['action'] === null ? null : personalWorldAction(body['action']);
  const refusal = body['refusal'] === null ? null : record(body['refusal'], 'refusal');
  // Exactly one of the two: an action the server allows, or its refusal with its words.
  if ((action === null) === (refusal === null)) {
    throw new TypeError('The server returned a personal world state with no single answer.');
  }
  return Object.freeze({
    action,
    refusal: refusal === null ? null : Object.freeze({
      code: text(refusal['code'], 'refusal code'),
      detail: text(refusal['detail'], 'refusal detail'),
    }),
    worldId: optionalText(body['world_id'], 'world ID'),
    savedEntryId: optionalText(body['saved_entry_id'], 'saved entry ID'),
    photographs: Object.freeze({
      reviewed: integer(photographs['reviewed'], 'reviewed photograph count'),
      composed: integer(photographs['composed'], 'composed photograph count'),
      outsideSceneGroups: integer(
        photographs['outside_scene_groups'], 'ungrouped photograph count',
      ),
    }),
    regions: integer(body['regions'], 'region count'),
    topologyDigest: optionalText(body['topology_digest'], 'topology digest'),
    currentTopologyDigest: optionalText(
      body['current_topology_digest'], 'current topology digest',
    ),
  });
}

function parseComposedPersonalWorld(value: unknown): ComposedPersonalWorld {
  const body = record(value, 'composed personal world');
  return Object.freeze({
    action: personalWorldAction(body['action']),
    worldId: text(body['world_id'], 'world ID'),
    topologyDigest: text(body['topology_digest'], 'topology digest'),
    styleVersionId: text(body['style_version_id'], 'style version ID'),
    savedEntryId: optionalText(body['saved_entry_id'], 'saved entry ID'),
  });
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

/**
 * The ground module version and the ground kind are one fact, so neither is read alone.
 *
 * Version 1 is a 24 metre rectangle and version 2 states no extent at all. A descriptor that named
 * one version and the other's ground would be a server this browser cannot read, and reading the
 * kind without the version would let a future version's meaning be inferred from a word.
 */
const AUTHORED_GROUND_KIND_BY_MODULE_VERSION = new Map<number, 'flat' | 'endless'>([
  [1, 'flat'],
  [2, 'endless'],
]);

function parseAuthoredScene(value: unknown): AuthoredStarterScene | null {
  if (value === null) return null;
  const scene = record(value, 'authored scene');
  if (scene['schema_version'] !== 1 || scene['kind'] !== 'authored-starter') {
    throw new TypeError('The server returned an unsupported authored scene.');
  }
  const region = record(scene['region'], 'authored region');
  const module = record(region['module'], 'authored region module');
  const groundRow = record(region['ground'], 'authored region ground');
  const spawn = record(region['spawn'], 'authored region spawn');
  const moduleVersion = module['version'];
  const expectedKind = typeof moduleVersion === 'number'
    ? AUTHORED_GROUND_KIND_BY_MODULE_VERSION.get(moduleVersion)
    : undefined;
  if (
    region['region_id'] !== 'region:starter' || region['origin'] !== 'authored' ||
    module['key'] !== 'region.authored-ground' || expectedKind === undefined ||
    groundRow['kind'] !== expectedKind
  ) {
    throw new TypeError('The server returned an unsupported authored starter region.');
  }
  const xMm = integer(spawn['x_mm'], 'authored spawn x');
  const yMm = integer(spawn['y_mm'], 'authored spawn y');
  const zMm = integer(spawn['z_mm'], 'authored spawn z');
  const yawMicroradians = integer(spawn['yaw_microradians'], 'authored spawn yaw');
  const ground = parseAuthoredGround(groundRow, expectedKind);
  /*
   * The spawn has to be a place on the ground the same descriptor states.
   *
   * On a bounded ground that is the rectangle. On an endless ground there is no rectangle to be
   * outside of, so the refusal moves to the only thing that can still be wrong about the pair: an
   * endless ground that carries an extent is a descriptor two halves of the server disagree about,
   * and `parseAuthoredGround` refuses it. Dropping the check entirely would leave a line that can
   * no longer answer anything.
   */
  if (
    ground.kind === 'flat' &&
    (Math.abs(xMm) > ground.halfWidthMm || Math.abs(zMm) > ground.halfDepthMm)
  ) {
    throw new TypeError('The authored starter spawn is outside its ground.');
  }
  return Object.freeze({
    schemaVersion: 1,
    kind: 'authored-starter',
    region: Object.freeze({
      regionId: 'region:starter',
      origin: 'authored',
      module: Object.freeze({
        key: 'region.authored-ground',
        version: moduleVersion as 1 | 2,
      }),
      ground,
      spawn: Object.freeze({ xMm, yMm, zMm, yawMicroradians }),
    }),
  });
}

function parseAuthoredGround(
  ground: Record<string, unknown>,
  kind: 'flat' | 'endless',
): AuthoredGround {
  const elevationMm = integer(ground['elevation_mm'], 'authored ground elevation');
  if (kind === 'endless') {
    if ('half_width_mm' in ground || 'half_depth_mm' in ground) {
      throw new TypeError('An endless authored ground cannot declare a horizontal extent.');
    }
    return Object.freeze({ kind: 'endless', elevationMm });
  }
  return Object.freeze({
    kind: 'flat',
    halfWidthMm: positiveInteger(ground['half_width_mm'], 'authored ground half width'),
    halfDepthMm: positiveInteger(ground['half_depth_mm'], 'authored ground half depth'),
    elevationMm,
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
