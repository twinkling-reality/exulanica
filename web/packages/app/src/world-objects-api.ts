/**
 * Alternate world versions and the objects a person authored into them, from the client's side.
 *
 * This speaks [docs/world-objects-contract.md](../../../../docs/world-objects-contract.md), which
 * is implemented: migration `0042_authored_world_objects.sql`, `exulanica/world/objects.py`, and
 * the `/world/versions` and `/world/assets` routes. An earlier draft of this module was written
 * against a guessed contract before that landed; every shape below now comes from the published
 * one, and `packages/graph-client/test/fixtures/world-objects.json` is a real `GET
 * /world/versions/{id}` body the tests parse.
 *
 * Four properties are worth naming, because each is a decision the contract made and this file
 * obeys rather than reinterprets.
 *
 * **snake_case only, in both directions.** The contract says so in section 6 and gives the reason:
 * the `/world/styles` routes accept camelCase aliases because they adapt an existing client
 * recipe, and "inventing a second casing for a contract nobody has generated against yet would be
 * inventing the problem the aliases above exist to solve". So requests are sent snake_case, and
 * this module remains the only place wire names become TypeScript names.
 *
 * **The base token is content-derived, not a counter.** Every mutation carries the version id and
 * the `state_sha256` the caller read. A mismatch is `stale_object_base` and changes nothing. There
 * is no proposal id here, unlike the appearance authority: the caller chooses `object_id`, and
 * re-adding an id that exists is `invalid_object_state` rather than a silent second object.
 *
 * **Every mutation returns the whole version.** `AlternateVersionView` is the response of add,
 * move, remove and undo alike, so a write is also the re-read. This module replaces its held
 * version with the response rather than issuing a second request, which is what makes a write and
 * the state it produced impossible to disagree.
 *
 * **A removal is stored, not executed.** The object row survives with `removed: true` so its id
 * stays stable and undo restores it. Nothing here filters removed objects out: a surface that
 * needs only the visible ones asks for those, and one that wants to say what was taken away can.
 *
 * **No remote asset URL is accepted.** An asset is identified by content digest and its bytes are
 * read from `/world/assets/{asset_key}/bytes`. There is no href on the wire at all, which is the
 * strongest form of the rule `world-style-backend.md` states for recipes.
 */

import { ApiError, Transport, type TransportOptions } from '@exulanica/graph-client';

// -- the read model ------------------------------------------------------------------------------

/** `origin.role`, chosen by the person and never inferred. */
export type ObjectRole = 'fictional' | 'personal';

export const OBJECT_ROLES: readonly ObjectRole[] = Object.freeze(['fictional', 'personal']);

/**
 * The words a surface shows for a role.
 *
 * product-direction.md is explicit that uploading something establishes no personal association by
 * itself and that the first slice ASKS rather than classifies, so both options have to read as
 * choices a person makes about their own material rather than as classifications of it.
 */
export const OBJECT_ROLE_LABELS: Readonly<Record<ObjectRole, string>> = Object.freeze({
  fictional: 'Invented for this world',
  personal: 'Connected to something I experienced',
});

/** The three-state honesty the contract borrows from `GET /world/source-media`. */
export type AssetAvailability = 'available' | 'unavailable_asset' | string;

export interface ReviewedAsset {
  readonly assetKey: string;
  readonly title: string;
  readonly summary: string;
  readonly mediaType: string;
  readonly contentSha256: string;
  readonly byteSize: number;
  readonly licenceId: string;
  readonly licenceSha256: string;
  /** `available`, or a recorded reason it is not. Never a substitute. */
  readonly availability: AssetAvailability;
}

export interface ObjectTransform {
  readonly coordinateSpace: string;
  readonly coordinateUnit: string;
  readonly xMm: number;
  readonly yMm: number;
  readonly zMm: number;
  readonly yawMicroradians: number;
  readonly scaleMilli: number;
}

export interface ObjectBehaviour {
  readonly behaviourKey: string;
  readonly behaviourVersion: number;
  readonly parameters: Readonly<Record<string, unknown>>;
}

export interface AuthoredObject {
  readonly objectId: string;
  /** The whole registry row, embedded, so a renderer knows what it may draw without a second call. */
  readonly asset: ReviewedAsset;
  readonly regionId: string;
  readonly transform: ObjectTransform;
  readonly origin: { readonly kind: string; readonly role: ObjectRole };
  readonly behaviour: ObjectBehaviour | null;
  /** True while a removal is in force. The row survives so undo can restore this id. */
  readonly removed: boolean;
}

export interface ElementOverride {
  readonly elementId: string;
  readonly suppressed: boolean;
  readonly transform: ObjectTransform | null;
}

export interface VersionEdit {
  readonly editId: string;
  readonly editSeq: number;
  readonly kind: string;
  readonly objectId: string | null;
  readonly elementId: string | null;
  readonly undoneEditId: string | null;
  readonly baseStateSha256: string;
  readonly resultStateSha256: string;
  readonly actor: string;
  readonly recordedAt: string;
}

export interface AlternateVersion {
  readonly schemaVersion: number;
  readonly versionId: string;
  readonly worldId: string;
  readonly sourceSnapshotId: string;
  readonly parentVersionId: string | null;
  readonly title: string;
  readonly origin: string;
  readonly styleVersionId: string | null;
  /** The base token for the next edit. */
  readonly stateSha256: string;
  readonly editSeq: number;
  /** True when the source snapshot was deleted. Further edits are refused. */
  readonly sourceInvalidated: boolean;
  readonly createdBy: string;
  readonly createdAt: string;
  readonly objects: readonly AuthoredObject[];
  readonly elementOverrides: readonly ElementOverride[];
  readonly edits: readonly VersionEdit[];
}

export class WorldObjectsContractError extends Error {
  constructor(readonly code: string, message: string) {
    super(message);
    this.name = 'WorldObjectsContractError';
  }
}

export type ObjectWriteResult =
  | { readonly kind: 'recorded'; readonly version: AlternateVersion }
  /** The base this edit was made against has moved. The current state is here; ask again. */
  | { readonly kind: 'stale'; readonly current: AlternateVersion };

export interface ObjectPlacementRequest {
  readonly objectId: string;
  readonly assetSha256: string;
  readonly regionId: string;
  readonly transform: TransformInput;
  readonly originRole: ObjectRole;
  readonly behaviour: ObjectBehaviour | null;
}

/** What a caller supplies for a transform. The wire's own units, and integers throughout. */
export interface TransformInput {
  readonly xMm: number;
  readonly yMm: number;
  readonly zMm: number;
  readonly yawMicroradians: number;
  readonly scaleMilli: number;
}

/**
 * The declared bounds, copied from `exulanica/world/objects.py`.
 *
 * A request outside them is `invalid_object_data`, so they are checked here first: a round trip to
 * learn that a yaw of minus one is not a yaw is a round trip a client can spend on nothing.
 */
export const MAX_YAW_MICRORADIANS = 6_283_185;
export const MAX_SCALE_MILLI = 1_000_000;
export const MAX_TRANSLATION_MM = 1_000_000_000;

export function assertTransform(value: TransformInput): void {
  for (const [name, held] of [
    ['x_mm', value.xMm], ['y_mm', value.yMm], ['z_mm', value.zMm],
  ] as const) {
    if (!Number.isSafeInteger(held) || Math.abs(held) > MAX_TRANSLATION_MM) {
      throw new WorldObjectsContractError('invalid_object_data', `transform.${name} is out of range.`);
    }
  }
  if (!Number.isSafeInteger(value.yawMicroradians)
    || value.yawMicroradians < 0 || value.yawMicroradians > MAX_YAW_MICRORADIANS) {
    throw new WorldObjectsContractError(
      'invalid_object_data',
      `transform.yaw_microradians must be between 0 and ${MAX_YAW_MICRORADIANS}.`,
    );
  }
  if (!Number.isSafeInteger(value.scaleMilli)
    || value.scaleMilli < 1 || value.scaleMilli > MAX_SCALE_MILLI) {
    throw new WorldObjectsContractError(
      'invalid_object_data',
      `transform.scale_milli must be between 1 and ${MAX_SCALE_MILLI}.`,
    );
  }
}

const wireTransform = (value: TransformInput): Readonly<Record<string, number>> => Object.freeze({
  x_mm: value.xMm,
  y_mm: value.yMm,
  z_mm: value.zMm,
  yaw_microradians: value.yawMicroradians,
  scale_milli: value.scaleMilli,
});

// -- the client ----------------------------------------------------------------------------------

export class WorldObjectsClient {
  readonly #transport: Transport;
  #assets: readonly ReviewedAsset[] = Object.freeze([]);
  #version: AlternateVersion | null = null;
  /**
   * Mutations are serialized, for the same reason `world-style-api.ts` serializes previews. Two
   * writes in flight against one `state_sha256` would have the second refused as stale by a
   * version the person never saw, and the recovery would be a question about a state that no
   * longer existed by the time they read it.
   */
  #queue: Promise<void> = Promise.resolve();

  constructor(options: TransportOptions) {
    this.#transport = new Transport(options);
  }

  assets(): readonly ReviewedAsset[] {
    return this.#assets;
  }

  version(): AlternateVersion | null {
    return this.#version;
  }

  /** Every alternate version in this workspace, newest first. */
  async versions(): Promise<readonly AlternateVersion[]> {
    const body = await this.#transport.getJson<unknown>('/world/versions');
    return Object.freeze(array(body, 'alternate version list').map(parseVersion));
  }

  async reviewedAssets(): Promise<readonly ReviewedAsset[]> {
    const body = await this.#transport.getJson<unknown>('/world/assets');
    this.#assets = Object.freeze(array(body, 'reviewed asset list').map(parseAsset));
    return this.#assets;
  }

  async readVersion(versionId: string): Promise<AlternateVersion> {
    this.#version = parseVersion(
      await this.#transport.getJson<unknown>(`/world/versions/${encodeURIComponent(versionId)}`),
    );
    return this.#version;
  }

  /**
   * Read the reviewed registry and one version together, or the newest version when none is named.
   *
   * There is no version picker in this build. Opening the newest is a presentation decision and it
   * is made here rather than pretending the contract has a current pointer: it deliberately does
   * not, because "two alternate versions of one place could not coexist at all" is exactly the
   * limitation this plane exists to remove.
   */
  async connect(versionId?: string): Promise<{
    readonly assets: readonly ReviewedAsset[];
    readonly version: AlternateVersion | null;
  }> {
    const [assets, version] = await Promise.all([
      this.reviewedAssets(),
      versionId === undefined
        ? this.versions().then((all) => all[0] ?? null)
        : this.readVersion(versionId),
    ]);
    this.#version = version;
    return Object.freeze({ assets, version });
  }

  async createVersion(input: {
    readonly title: string;
    readonly sourceSnapshotId?: string;
    readonly parentVersionId?: string;
    readonly styleVersionId?: string;
  }): Promise<AlternateVersion> {
    const body: Record<string, unknown> = { title: input.title };
    if (input.sourceSnapshotId !== undefined) body['source_snapshot_id'] = input.sourceSnapshotId;
    if (input.parentVersionId !== undefined) body['parent_version_id'] = input.parentVersionId;
    if (input.styleVersionId !== undefined) body['style_version_id'] = input.styleVersionId;
    this.#version = parseVersion(await this.#transport.postJson<unknown>('/world/versions', body));
    return this.#version;
  }

  async place(base: AlternateVersion, request: ObjectPlacementRequest): Promise<ObjectWriteResult> {
    assertTransform(request.transform);
    return this.#write(base, `${objectsPath(base.versionId)}`, {
      object_id: request.objectId,
      asset_sha256: request.assetSha256,
      region_id: request.regionId,
      transform: wireTransform(request.transform),
      origin_role: request.originRole,
      behaviour: request.behaviour === null ? null : {
        behaviour_key: request.behaviour.behaviourKey,
        behaviour_version: request.behaviour.behaviourVersion,
        parameters: { ...request.behaviour.parameters },
      },
    });
  }

  async move(
    base: AlternateVersion,
    objectId: string,
    transform: TransformInput,
  ): Promise<ObjectWriteResult> {
    assertTransform(transform);
    return this.#write(base, `${objectPath(base.versionId, objectId)}/move`, {
      transform: wireTransform(transform),
    });
  }

  remove(base: AlternateVersion, objectId: string): Promise<ObjectWriteResult> {
    return this.#write(base, `${objectPath(base.versionId, objectId)}/remove`, {});
  }

  /** Reverse the newest edit no undo already names. Refused with `invalid_object_state` when none. */
  undo(base: AlternateVersion): Promise<ObjectWriteResult> {
    return this.#write(base, `${objectsPath(base.versionId)}/undo`, {});
  }

  /**
   * Reviewed bytes, and the digest they must hash to.
   *
   * Returned together because they are useless apart: the digest comes from the registry row and
   * the bytes from the byte route, and checking one against the other is the whole point.
   * Verification itself belongs to the renderer, which is the only layer that decodes.
   */
  async assetBytes(asset: ReviewedAsset, signal?: AbortSignal): Promise<ArrayBuffer> {
    void signal;
    const response = await this.#transport.getBytes(assetBytesPath(asset.assetKey));
    return response.arrayBuffer();
  }

  /** The licence text those bytes are published under. */
  async assetLicence(asset: ReviewedAsset): Promise<string> {
    const response = await this.#transport.getBytes(`${assetPath(asset.assetKey)}/licence`);
    return response.text();
  }

  /**
   * One mutation, carrying the base it was made against, serialized behind the last one.
   *
   * `stale_object_base` is caught BY CODE and turned into a result the surface can act on, with
   * the current state attached so the person is asked again about what is actually there. Every
   * other failure is rethrown as it arrived: a client that swallowed `unavailable_asset` or
   * `invalidated_source_version` would be deciding on someone's behalf that a refusal did not
   * matter.
   */
  #write(
    base: AlternateVersion,
    path: string,
    body: Readonly<Record<string, unknown>>,
  ): Promise<ObjectWriteResult> {
    const run = async (): Promise<ObjectWriteResult> => {
      try {
        const version = parseVersion(await this.#transport.postJson<unknown>(path, {
          ...body,
          base_state_sha256: base.stateSha256,
        }));
        this.#version = version;
        return Object.freeze({ kind: 'recorded' as const, version });
      } catch (error) {
        if (error instanceof ApiError && error.code === 'stale_object_base') {
          const current = await this.readVersion(base.versionId);
          return Object.freeze({ kind: 'stale' as const, current });
        }
        throw error;
      }
    };
    const result = this.#queue.then(run, run);
    this.#queue = result.then(() => undefined, () => undefined);
    return result;
  }
}

// -- paths ---------------------------------------------------------------------------------------

const objectsPath = (versionId: string): string =>
  `/world/versions/${encodeURIComponent(versionId)}/objects`;

const objectPath = (versionId: string, objectId: string): string =>
  `${objectsPath(versionId)}/${encodeURIComponent(objectId)}`;

const assetPath = (assetKey: string): string => `/world/assets/${encodeURIComponent(assetKey)}`;

export const assetBytesPath = (assetKey: string): string => `${assetPath(assetKey)}/bytes`;

// -- parsers -------------------------------------------------------------------------------------

const invalid = (label: string): WorldObjectsContractError =>
  new WorldObjectsContractError('invalid_response', `The server returned an invalid ${label}.`);

function record(value: unknown, label: string): Readonly<Record<string, unknown>> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) throw invalid(label);
  return value as Readonly<Record<string, unknown>>;
}

function array(value: unknown, label: string): readonly unknown[] {
  if (!Array.isArray(value)) throw invalid(label);
  return value;
}

function text(value: unknown, label: string): string {
  if (typeof value !== 'string' || value.length === 0) throw invalid(label);
  return value;
}

function optionalText(value: unknown, label: string): string | null {
  if (value === null || value === undefined) return null;
  return text(value, label);
}

/** Summary and title may be empty; a blank reviewed summary is a thin row, not a broken one. */
function anyText(value: unknown, label: string): string {
  if (typeof value !== 'string') throw invalid(label);
  return value;
}

function integer(value: unknown, label: string): number {
  if (!Number.isSafeInteger(value)) throw invalid(label);
  return value as number;
}

function flag(value: unknown, label: string): boolean {
  if (typeof value !== 'boolean') throw invalid(label);
  return value;
}

function digest(value: unknown, label: string): string {
  const parsed = text(value, label);
  if (!/^[0-9a-f]{64}$/.test(parsed)) throw invalid(label);
  return parsed;
}

export function parseAsset(value: unknown): ReviewedAsset {
  const row = record(value, 'reviewed asset');
  return Object.freeze({
    assetKey: text(row['asset_key'], 'reviewed asset key'),
    title: anyText(row['title'], 'reviewed asset title'),
    summary: anyText(row['summary'], 'reviewed asset summary'),
    mediaType: text(row['media_type'], 'reviewed asset media type'),
    contentSha256: digest(row['content_sha256'], 'reviewed asset content hash'),
    byteSize: integer(row['byte_size'], 'reviewed asset byte size'),
    licenceId: text(row['licence_id'], 'reviewed asset licence id'),
    licenceSha256: digest(row['licence_sha256'], 'reviewed asset licence hash'),
    availability: text(row['availability'], 'reviewed asset availability'),
  });
}

export function parseTransform(value: unknown): ObjectTransform {
  const row = record(value, 'object transform');
  return Object.freeze({
    // Carried on the wire so "a reader never has to know them from context". Read rather than
    // assumed, and refused when they are not the ones this build converts.
    coordinateSpace: text(row['coordinate_space'], 'transform coordinate space'),
    coordinateUnit: text(row['coordinate_unit'], 'transform coordinate unit'),
    xMm: integer(row['x_mm'], 'transform x_mm'),
    yMm: integer(row['y_mm'], 'transform y_mm'),
    zMm: integer(row['z_mm'], 'transform z_mm'),
    yawMicroradians: integer(row['yaw_microradians'], 'transform yaw'),
    scaleMilli: integer(row['scale_milli'], 'transform scale'),
  });
}

function parseBehaviour(value: unknown): ObjectBehaviour | null {
  if (value === null || value === undefined) return null;
  const row = record(value, 'object behaviour');
  return Object.freeze({
    behaviourKey: text(row['behaviour_key'], 'object behaviour key'),
    behaviourVersion: integer(row['behaviour_version'], 'object behaviour version'),
    // Parameters stay UNPARSED here on purpose. Which parameters exist and what they may be is the
    // behaviour registry's to say, not the transport's; validating them twice in two vocabularies
    // is how the two drift apart.
    parameters: Object.freeze({ ...record(row['parameters'], 'object behaviour parameters') }),
  });
}

export function parseObject(value: unknown): AuthoredObject {
  const row = record(value, 'authored object');
  const origin = record(row['origin'], 'authored object origin');
  const role = text(origin['role'], 'authored object role');
  if (!OBJECT_ROLES.includes(role as ObjectRole)) throw invalid('authored object role');
  return Object.freeze({
    objectId: text(row['object_id'], 'authored object id'),
    asset: parseAsset(row['asset']),
    regionId: text(row['region_id'], 'authored object region'),
    transform: parseTransform(row['transform']),
    origin: Object.freeze({
      kind: text(origin['kind'], 'authored object origin kind'),
      role: role as ObjectRole,
    }),
    behaviour: parseBehaviour(row['behaviour']),
    removed: flag(row['removed'], 'authored object removal'),
  });
}

function parseOverride(value: unknown): ElementOverride {
  const row = record(value, 'element override');
  const transform = row['transform'];
  return Object.freeze({
    elementId: text(row['element_id'], 'element override id'),
    suppressed: flag(row['suppressed'], 'element override suppression'),
    transform: transform === null || transform === undefined ? null : parseTransform(transform),
  });
}

function parseEdit(value: unknown): VersionEdit {
  const row = record(value, 'version edit');
  return Object.freeze({
    editId: text(row['edit_id'], 'version edit id'),
    editSeq: integer(row['edit_seq'], 'version edit sequence'),
    kind: text(row['kind'], 'version edit kind'),
    objectId: optionalText(row['object_id'], 'version edit object'),
    elementId: optionalText(row['element_id'], 'version edit element'),
    undoneEditId: optionalText(row['undone_edit_id'], 'version edit undone id'),
    baseStateSha256: digest(row['base_state_sha256'], 'version edit base hash'),
    resultStateSha256: digest(row['result_state_sha256'], 'version edit result hash'),
    actor: text(row['actor'], 'version edit actor'),
    recordedAt: text(row['recorded_at'], 'version edit timestamp'),
  });
}

export function parseVersion(value: unknown): AlternateVersion {
  const row = record(value, 'alternate world version');
  const objects = array(row['objects'], 'authored object list').map(parseObject);
  if (new Set(objects.map((object) => object.objectId)).size !== objects.length) {
    throw invalid('authored object list');
  }
  return Object.freeze({
    schemaVersion: integer(row['schema_version'], 'version schema version'),
    versionId: text(row['version_id'], 'version id'),
    worldId: text(row['world_id'], 'world id'),
    sourceSnapshotId: text(row['source_snapshot_id'], 'source snapshot id'),
    parentVersionId: optionalText(row['parent_version_id'], 'parent version id'),
    title: anyText(row['title'], 'version title'),
    origin: text(row['origin'], 'version origin'),
    styleVersionId: optionalText(row['style_version_id'], 'style version id'),
    stateSha256: digest(row['state_sha256'], 'version state hash'),
    editSeq: integer(row['edit_seq'], 'version edit sequence'),
    sourceInvalidated: flag(row['source_invalidated'], 'version source invalidation'),
    createdBy: text(row['created_by'], 'version author'),
    createdAt: text(row['created_at'], 'version timestamp'),
    objects: Object.freeze(objects),
    elementOverrides: Object.freeze(
      array(row['element_overrides'], 'element override list').map(parseOverride),
    ),
    edits: Object.freeze(array(row['edits'], 'version edit list').map(parseEdit)),
  });
}

/** What a refusal from this authority means, in the words a surface can show. */
export function objectWriteFailure(error: unknown): string {
  if (error instanceof WorldObjectsContractError) return error.message;
  if (!(error instanceof ApiError)) {
    return error instanceof Error ? error.message : 'the write was refused';
  }
  if (error.isUnauthenticated) return 'This session is not authorized to change this world.';
  const detail = error.message.replace(`${error.code}: `, '');
  // A body-shape refusal comes from Pydantic rather than from the domain, so it carries
  // `{detail: [...]}` with no `code` at all. `toApiError` deliberately does not trust a failed
  // response to be JSON and degrades to `http_422` plus the status text, which reaches a person
  // as "Unprocessable Entity" and tells them nothing. This is the failure a wrong id, an
  // out-of-range transform or a stray field produces, which makes it the most likely one to be
  // seen, so it is named here rather than left as the only refusal in this table with no words.
  if (error.code === `http_${error.status}` && error.status === 422) {
    return 'The authority refused the shape of this edit. That is a fault in this build rather '
      + 'than something you did.';
  }
  switch (error.code) {
    case 'unknown_reference':
      return 'That version, object or asset is not in this workspace.';
    case 'stale_object_base':
      return 'This world changed while you were deciding, so nothing was written.';
    case 'invalid_object_state':
      return `That edit does not apply to this world as it stands: ${detail}`;
    case 'invalid_object_data':
      return `The authority refused this edit: ${detail}`;
    case 'invalidated_source_version':
      return 'The place this version was built on was deleted, so it can no longer be changed. '
        + 'What you already made is kept.';
    case 'unavailable_asset':
      return 'The reviewed bytes for that asset are not in storage, so it cannot be drawn.';
    default:
      return `${error.code}: ${detail}`;
  }
}
