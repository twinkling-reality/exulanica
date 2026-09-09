/**
 * The authored-object authority, from the client's side.
 *
 * This module speaks [docs/world-objects-contract.md](../../../../docs/world-objects-contract.md),
 * which is PROVISIONAL: no `/world-objects` route exists on the server yet. That is stated here
 * rather than only in the document because it changes how this file must be read. Every parser
 * below is a guess at a shape somebody else will fix, so the parsers are strict on purpose: when
 * the real routes land, a disagreement should arrive as `invalid_response` with the field named,
 * not as an object drawn at the wrong place.
 *
 * The shape follows `world-style-api.ts`, which is the closest thing in the package to what this
 * is, and follows it deliberately rather than incidentally:
 *
 * **This is the only place snake_case becomes camelCase.** Wire keys are read as string literals
 * and renamed field by field in a parser. Nothing downstream sees a wire key, and nothing here
 * types a response as its domain type before it has been checked.
 *
 * **Failures keep their code, never their status.** A server problem stays an `ApiError` and is
 * branched on by `error.code`. This module's own error class is for a response that did not make
 * sense, which is a different fact from a request the server refused.
 *
 * **The client mints the proposal id.** Every mutation carries one, and a replay of the same id
 * is answered by the server with `alreadyRecorded: true` rather than with a second object. That
 * is what makes a retried write safe, and it is why the id is generated here rather than by the
 * route.
 *
 * **A stale write is returned, not thrown.** Two edits to the same world version is an expected
 * outcome of two people, or one person in two tabs, and it is answered with a discriminated
 * union so the surface can re-read and ask again. There is no last-writer-wins here and no
 * automatic merge; the person is asked a second time because the thing they based their edit on
 * moved.
 *
 * **No remote asset URL is accepted.** An asset reference must be a workspace-local path with
 * declared workspace-bearer authorization and a digest, exactly like a reconstruction artifact.
 * A registry entry that names an external origin is refused at parse time, before anything can
 * try to fetch it.
 */

import { ApiError, Transport, type TransportOptions } from '@exulanica/graph-client';

// -- the read model ------------------------------------------------------------------------------

export type ObjectOrigin = 'fictional-source' | 'appearance-reference' | 'personal-association';

export const OBJECT_ORIGINS: readonly ObjectOrigin[] = Object.freeze([
  'fictional-source',
  'appearance-reference',
  'personal-association',
]);

/** The words the surface shows for a role, kept beside the vocabulary they belong to. */
export const OBJECT_ORIGIN_LABELS: Readonly<Record<ObjectOrigin, string>> = Object.freeze({
  'fictional-source': 'Invented for this world',
  'appearance-reference': 'A reference for how something looks',
  'personal-association': 'Connected to something I experienced',
});

export interface ObjectAssetBytesReference {
  readonly href: string;
  readonly contentSha256: string;
  readonly byteSize: number;
}

export interface ReviewedObjectAsset {
  readonly assetId: string;
  readonly label: string;
  readonly container: string;
  /** Null exactly when the bytes are unavailable. Show that; do not substitute a shape. */
  readonly reference: ObjectAssetBytesReference | null;
  readonly origin: ObjectOrigin;
  readonly footprint: { readonly radius: number; readonly height: number };
  readonly supportedBehaviours: readonly string[];
}

export interface ObjectAssetRegistry {
  readonly registryVersion: number;
  readonly assets: readonly ReviewedObjectAsset[];
}

export interface AuthoredObjectBehaviourRecord {
  readonly behaviourId: string;
  readonly parameters: Readonly<Record<string, unknown>>;
}

export interface AuthoredObjectRecord {
  readonly objectId: string;
  readonly assetId: string;
  readonly regionId: string;
  readonly sceneId: string;
  /** 16 finite numbers, row-major, in the reconstruction scene's own recovered frame. */
  readonly sceneFromObject: readonly number[];
  readonly origin: ObjectOrigin;
  readonly behaviour: AuthoredObjectBehaviourRecord | null;
  readonly basedOnWorldVersionId: string | null;
  readonly recordedSha256: string;
}

export interface AuthoredWorldVersion {
  readonly worldVersionId: string;
  readonly basedOnWorldVersionId: string | null;
  readonly recordedSha256: string;
  readonly objects: readonly AuthoredObjectRecord[];
}

export interface ObjectWriteReceipt {
  readonly objectId: string;
  readonly worldVersionId: string;
  readonly basedOnWorldVersionId: string | null;
  readonly recordedSha256: string;
  /** True when this proposal id had already been recorded. The write was a replay, not a second one. */
  readonly alreadyRecorded: boolean;
}

export type ObjectWriteResult =
  | { readonly kind: 'recorded'; readonly receipt: ObjectWriteReceipt }
  /** The base this edit was made against has moved. Re-read and ask the person again. */
  | { readonly kind: 'stale'; readonly current: AuthoredWorldVersion };

export class WorldObjectsContractError extends Error {
  constructor(readonly code: string, message: string) {
    super(message);
    this.name = 'WorldObjectsContractError';
  }
}

// -- the requests --------------------------------------------------------------------------------

export interface ObjectPlacementRequest {
  readonly assetId: string;
  readonly regionId: string;
  readonly sceneId: string;
  readonly sceneFromObject: readonly number[];
  readonly origin: ObjectOrigin;
  readonly behaviour: AuthoredObjectBehaviourRecord | null;
}

type IdFactory = () => string;

export class WorldObjectsClient {
  readonly #transport: Transport;
  readonly #ids: IdFactory;
  #registry: ObjectAssetRegistry | null = null;
  #version: AuthoredWorldVersion | null = null;
  /**
   * Mutations are serialized, for the same reason `world-style-api.ts` serializes previews: two
   * writes in flight against the same base would have one of them refused as stale by a version
   * the person never saw, and the recovery would be a question about a state that no longer
   * existed by the time they read it.
   */
  #queue: Promise<void> = Promise.resolve();

  constructor(options: TransportOptions & { readonly ids?: IdFactory }) {
    this.#transport = new Transport(options);
    this.#ids = options.ids ?? (() => globalThis.crypto.randomUUID());
  }

  registry(): ObjectAssetRegistry | null {
    return this.#registry;
  }

  version(): AuthoredWorldVersion | null {
    return this.#version;
  }

  /** Read the reviewed registry and one world version's objects together. */
  async connect(worldVersionId: string): Promise<{
    readonly registry: ObjectAssetRegistry;
    readonly version: AuthoredWorldVersion;
  }> {
    const [registry, version] = await Promise.all([
      this.#transport.getJson<unknown>('/world-objects/assets'),
      this.#transport.getJson<unknown>(objectsPath(worldVersionId)),
    ]);
    this.#registry = parseRegistry(registry);
    this.#version = parseVersion(version);
    return Object.freeze({ registry: this.#registry, version: this.#version });
  }

  async refreshAssets(): Promise<ObjectAssetRegistry> {
    this.#registry = parseRegistry(await this.#transport.getJson<unknown>('/world-objects/assets'));
    return this.#registry;
  }

  async refreshObjects(worldVersionId: string): Promise<AuthoredWorldVersion> {
    this.#version = parseVersion(
      await this.#transport.getJson<unknown>(objectsPath(worldVersionId)),
    );
    return this.#version;
  }

  async place(base: AuthoredWorldVersion, request: ObjectPlacementRequest): Promise<ObjectWriteResult> {
    assertTransform(request.sceneFromObject);
    return this.#write(base, objectsPath(base.worldVersionId), {
      assetId: request.assetId,
      regionId: request.regionId,
      sceneId: request.sceneId,
      sceneFromObject: [...request.sceneFromObject],
      origin: request.origin,
      behaviour: request.behaviour === null ? null : {
        behaviourId: request.behaviour.behaviourId,
        parameters: { ...request.behaviour.parameters },
      },
    });
  }

  async move(
    base: AuthoredWorldVersion,
    objectId: string,
    sceneFromObject: readonly number[],
  ): Promise<ObjectWriteResult> {
    assertTransform(sceneFromObject);
    return this.#write(base, `${objectPath(base.worldVersionId, objectId)}/transform`, {
      sceneFromObject: [...sceneFromObject],
    });
  }

  setBehaviour(
    base: AuthoredWorldVersion,
    objectId: string,
    behaviour: AuthoredObjectBehaviourRecord | null,
  ): Promise<ObjectWriteResult> {
    return this.#write(base, `${objectPath(base.worldVersionId, objectId)}/behaviour`, {
      behaviour: behaviour === null ? null : {
        behaviourId: behaviour.behaviourId,
        parameters: { ...behaviour.parameters },
      },
    });
  }

  remove(base: AuthoredWorldVersion, objectId: string): Promise<ObjectWriteResult> {
    return this.#write(base, `${objectPath(base.worldVersionId, objectId)}/removal`, {});
  }

  /**
   * One mutation, with its proposal id and both base tokens, serialized behind the last one.
   *
   * `stale_world_version` is caught by CODE and turned into a result the surface can act on. Every
   * other failure is rethrown as it arrived: a client that swallowed `unknown_reference` or
   * `unavailable_asset` here would be deciding on the person's behalf that a refusal did not
   * matter.
   */
  #write(
    base: AuthoredWorldVersion,
    path: string,
    body: Readonly<Record<string, unknown>>,
  ): Promise<ObjectWriteResult> {
    const run = async (): Promise<ObjectWriteResult> => {
      const payload = {
        ...body,
        proposalId: this.#ids(),
        baseWorldVersionId: base.worldVersionId,
        baseRecordedSha256: base.recordedSha256,
      };
      try {
        const receipt = parseReceipt(await this.#transport.postJson<unknown>(path, payload));
        return Object.freeze({ kind: 'recorded' as const, receipt });
      } catch (error) {
        if (error instanceof ApiError && error.code === 'stale_world_version') {
          const current = await this.refreshObjects(base.worldVersionId);
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

function objectsPath(worldVersionId: string): string {
  return `/world-objects/versions/${encodeURIComponent(worldVersionId)}/objects`;
}

function objectPath(worldVersionId: string, objectId: string): string {
  return `${objectsPath(worldVersionId)}/${encodeURIComponent(objectId)}`;
}

/**
 * The shape `geometry-api.ts` requires of an artifact path, for the same reason.
 *
 * Duplicated rather than imported: `safeGeometryPath` is module-private there, and the prefix is
 * different, which is the whole content of the check.
 */
export function safeObjectHref(value: string): boolean {
  return value.startsWith('/world-objects/')
    && !value.includes('://')
    && !value.includes('?')
    && !value.includes('#');
}

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

function nullableText(value: unknown, label: string): string | null {
  if (value === null || value === undefined) return null;
  return text(value, label);
}

function count(value: unknown, label: string): number {
  if (!Number.isSafeInteger(value) || (value as number) < 0) throw invalid(label);
  return value as number;
}

function positive(value: unknown, label: string): number {
  const parsed = count(value, label);
  if (parsed === 0) throw invalid(label);
  return parsed;
}

function measure(value: unknown, label: string): number {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) throw invalid(label);
  return value;
}

function digest(value: unknown, label: string): string {
  const parsed = text(value, label);
  if (!/^[0-9a-f]{64}$/.test(parsed)) throw invalid(label);
  return parsed;
}

function origin(value: unknown): ObjectOrigin {
  const parsed = text(value, 'object origin');
  if (!OBJECT_ORIGINS.includes(parsed as ObjectOrigin)) throw invalid('object origin');
  return parsed as ObjectOrigin;
}

/** A row-major similarity of 16 finite numbers. Checked here so no renderer receives a `NaN`. */
function transform(value: unknown): readonly number[] {
  const raw = array(value, 'object transform');
  if (raw.length !== 16 || raw.some((n) => typeof n !== 'number' || !Number.isFinite(n))) {
    throw invalid('object transform');
  }
  return Object.freeze(raw as number[]);
}

export function assertTransform(value: readonly number[]): void {
  transform(value);
}

function parseAssetReference(value: unknown): ObjectAssetBytesReference | null {
  if (value === null || value === undefined) return null;
  const row = record(value, 'object asset reference');
  // The same refusal `world.py` makes of a remote asset URL, on the receiving side.
  if (row['authorization'] !== 'workspace-bearer') throw invalid('object asset authorization');
  const href = text(row['href'], 'object asset href');
  if (!safeObjectHref(href)) throw invalid('object asset href');
  return Object.freeze({
    href,
    contentSha256: digest(row['content_sha256'], 'object asset content hash'),
    byteSize: positive(row['byte_size'], 'object asset byte size'),
  });
}

function parseAsset(value: unknown): ReviewedObjectAsset {
  const row = record(value, 'reviewed object asset');
  const footprint = record(row['footprint'], 'object asset footprint');
  return Object.freeze({
    assetId: text(row['asset_id'], 'object asset id'),
    label: text(row['label'], 'object asset label'),
    container: text(row['container'], 'object asset container'),
    reference: parseAssetReference(row['reference']),
    origin: origin(row['origin']),
    footprint: Object.freeze({
      radius: measure(footprint['radius'], 'object asset radius'),
      height: measure(footprint['height'], 'object asset height'),
    }),
    supportedBehaviours: Object.freeze(
      array(row['supported_behaviours'], 'object asset behaviours')
        .map((entry) => text(entry, 'object asset behaviour id')),
    ),
  });
}

export function parseRegistry(value: unknown): ObjectAssetRegistry {
  const row = record(value, 'object asset registry');
  const assets = array(row['assets'], 'object asset list').map(parseAsset);
  const ids = new Set(assets.map((asset) => asset.assetId));
  if (ids.size !== assets.length) throw invalid('object asset registry');
  return Object.freeze({
    registryVersion: positive(row['registry_version'], 'object registry version'),
    assets: Object.freeze(assets),
  });
}

function parseBehaviour(value: unknown): AuthoredObjectBehaviourRecord | null {
  if (value === null || value === undefined) return null;
  const row = record(value, 'object behaviour');
  return Object.freeze({
    behaviourId: text(row['behaviour_id'], 'object behaviour id'),
    // Parameters stay UNPARSED here on purpose. Which parameters exist, and what they may be, is
    // the behaviour registry's to say, not the transport's; validating them twice in two
    // vocabularies is how the two drift apart.
    parameters: Object.freeze({ ...record(row['parameters'], 'object behaviour parameters') }),
  });
}

export function parseObject(value: unknown): AuthoredObjectRecord {
  const row = record(value, 'authored object');
  return Object.freeze({
    objectId: text(row['object_id'], 'authored object id'),
    assetId: text(row['asset_id'], 'authored object asset id'),
    regionId: text(row['region_id'], 'authored object region'),
    sceneId: text(row['scene_id'], 'authored object scene'),
    sceneFromObject: transform(row['scene_from_object']),
    origin: origin(row['origin']),
    behaviour: parseBehaviour(row['behaviour']),
    basedOnWorldVersionId: nullableText(row['based_on_world_version_id'], 'authored object base'),
    recordedSha256: digest(row['recorded_sha256'], 'authored object record hash'),
  });
}

export function parseVersion(value: unknown): AuthoredWorldVersion {
  const row = record(value, 'authored world version');
  const objects = array(row['objects'], 'authored object list').map(parseObject);
  const ids = new Set(objects.map((object) => object.objectId));
  if (ids.size !== objects.length) throw invalid('authored object list');
  return Object.freeze({
    worldVersionId: text(row['world_version_id'], 'world version id'),
    basedOnWorldVersionId: nullableText(row['based_on_world_version_id'], 'world version base'),
    recordedSha256: digest(row['recorded_sha256'], 'world version record hash'),
    objects: Object.freeze(objects),
  });
}

export function parseReceipt(value: unknown): ObjectWriteReceipt {
  const row = record(value, 'object write receipt');
  const replayed = row['already_recorded'];
  if (typeof replayed !== 'boolean') throw invalid('object write receipt');
  return Object.freeze({
    objectId: text(row['object_id'], 'authored object id'),
    worldVersionId: text(row['world_version_id'], 'world version id'),
    basedOnWorldVersionId: nullableText(row['based_on_world_version_id'], 'world version base'),
    recordedSha256: digest(row['recorded_sha256'], 'world version record hash'),
    alreadyRecorded: replayed,
  });
}

/** What a refusal from this authority means, in the words a surface can show. */
export function objectWriteFailure(error: unknown): string {
  if (error instanceof WorldObjectsContractError) return error.message;
  if (!(error instanceof ApiError)) {
    return error instanceof Error ? error.message : 'the write was refused';
  }
  if (error.isUnauthenticated) return 'This session is not authorized to change this world.';
  switch (error.code) {
    case 'unknown_reference':
      return 'That object or world version is not in this workspace.';
    case 'tombstoned':
      return 'That object was withdrawn and cannot be changed.';
    case 'unavailable_asset':
      return 'The bytes for that asset are not in storage, so it cannot be placed.';
    case 'unsupported_behaviour':
      return 'That behaviour is not one this world supports.';
    case 'invalid_object_state':
      return `The authority refused this placement: ${error.message.replace(`${error.code}: `, '')}`;
    default:
      return `${error.code}: ${error.message.replace(`${error.code}: `, '')}`;
  }
}
