/**
 * Alternate world versions and the objects a person authored into them, from the client's side.
 *
 * This speaks [docs/world-objects-contract.md](../../../../docs/world-objects-contract.md), which
 * is implemented: migration `0042_authored_world_objects.sql`, `exulanica/world/objects.py`, and
 * the `/world/versions` and `/world/assets` routes. Every shape below comes from that published
 * contract, and `packages/graph-client/test/fixtures/world-objects.json` is a real `GET
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
import { KIND_SIDES, type KindPlace, type KindSide, type KindUse } from '@exulanica/atlas-react/playcanvas';
import { worldPath } from './world-scope.js';

// -- the read model ------------------------------------------------------------------------------

/** `origin.role`, chosen by the person and never inferred. */
export type ObjectRole = 'fictional' | 'personal';

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

/** Whether a value is one of the roles above. The label table is the one list of roles. */
export function isObjectRole(value: unknown): value is ObjectRole {
  return typeof value === 'string' && Object.hasOwn(OBJECT_ROLE_LABELS, value);
}

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
  /**
   * Whether a person may place this asset as an object, as the kind the server's registry
   * declares for it says. `GET /world/assets` lists only placeable assets; an object a version
   * already holds carries its asset whatever this says, and keeps drawing.
   */
  readonly placeable: boolean;
  /**
   * What inhabitants do with the kind and where, as the registry reads serve it from the world
   * object catalog: each place in the kind's part frame, the way a person there faces, and the
   * seat a resting person is drawn on. Null for an asset the catalog does not state; absent where
   * the row was read embedded in a version, which does not carry it.
   */
  readonly use?: KindUse | null;
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
  readonly environmentInstanceId?: string | null;
  readonly pointMapInstanceId?: string | null;
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
  readonly environmentInstances?: readonly EnvironmentInstance[];
  readonly pointMapInstances?: readonly PointMapInstance[];
  readonly edits: readonly VersionEdit[];
}

export interface EnvironmentInstance {
  readonly instanceId: string;
  readonly source: Readonly<Record<string, unknown>>;
  readonly regionId: string;
  readonly transform: ObjectTransform;
  readonly origin: { readonly kind: string; readonly role: ObjectRole };
  readonly removed: boolean;
  readonly availability: string;
}

/** Why a placed estimate cannot be drawn right now, as the server computed it. */
export type PointMapAvailability =
  | 'available'
  | 'unavailable_bytes'
  | 'withdrawn'
  | 'detached'
  | 'binding_drift'
  | 'unknown'
  | string;

/**
 * A depth estimate from one reviewed photograph, placed in this version.
 *
 * ``truth``, ``scale`` and ``coverage`` are sentences the SERVER wrote. They are carried rather
 * than composed here on purpose: what a person is told about whether this is a measurement, and
 * about what it does not show, must not be able to drift from what was actually placed because a
 * client was updated separately.
 */
export interface PointMapInstance {
  readonly instanceId: string;
  readonly source: Readonly<Record<string, unknown>>;
  readonly regionId: string;
  readonly transform: ObjectTransform;
  readonly origin: { readonly kind: string; readonly role: ObjectRole };
  readonly removed: boolean;
  readonly availability: PointMapAvailability;
  /** Which end of permission it was, for the ``withdrawn`` state. Null otherwise. */
  readonly unavailableReason: string | null;
  readonly truth: string;
  readonly scale: string;
  readonly coverage: string;
}

/**
 * The placed estimates a renderer may draw, and nothing else.
 *
 * A removed one is gone; anything not ``available`` draws NOTHING, with no placeholder and no
 * outline. Something drawn where a stopped estimate used to be would be the system keeping a
 * shape of somebody's home after they said no, and a grey box is still a shape.
 */
export function drawablePointMaps(
  version: AlternateVersion,
): readonly PointMapInstance[] {
  return (version.pointMapInstances ?? []).filter(
    (instance) => !instance.removed && instance.availability === 'available',
  );
}

export class WorldObjectsContractError extends Error {
  constructor(readonly code: string, message: string) {
    super(message);
    this.name = 'WorldObjectsContractError';
  }
}

export interface SavedEntryWriteBinding {
  readonly entryId: string;
  readonly revision: number;
  readonly authoredVersionId: string;
  readonly authoredStateSha256: string;
  readonly authoredEditSeq: number;
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

const wireBehaviour = (value: ObjectBehaviour): Readonly<Record<string, unknown>> => Object.freeze({
  behaviour_key: value.behaviourKey,
  behaviour_version: value.behaviourVersion,
  parameters: { ...value.parameters },
});

// -- the client ----------------------------------------------------------------------------------

export class WorldObjectsClient {
  readonly #transport: Transport;
  readonly #worldId: string | undefined;
  readonly #defaultVersionId: string | undefined;
  readonly #onVersionChange: ((version: AlternateVersion) => Promise<void>) | undefined;
  readonly #savedEntry: (() => SavedEntryWriteBinding) | undefined;
  readonly #onSavedEntryAdvanced:
    | ((version: AlternateVersion, base: SavedEntryWriteBinding) => Promise<void>)
    | undefined;
  #assets: readonly ReviewedAsset[] = Object.freeze([]);
  #version: AlternateVersion | null = null;
  /**
   * Mutations are serialized, for the same reason `world-style-api.ts` serializes previews. Two
   * writes in flight against one `state_sha256` would have the second refused as stale by a
   * version the person never saw, and the recovery would be a question about a state that no
   * longer existed by the time they read it.
   */
  #queue: Promise<void> = Promise.resolve();

  constructor(options: TransportOptions & {
    /**
     * The world every world request of this client reads or changes. Without one, each world
     * request refuses by name: there is no default world to send it to.
     */
    readonly worldId?: string;
    readonly defaultVersionId?: string;
    readonly onVersionChange?: (version: AlternateVersion) => Promise<void>;
    readonly savedEntry?: () => SavedEntryWriteBinding;
    readonly onSavedEntryAdvanced?: (
      version: AlternateVersion,
      base: SavedEntryWriteBinding,
    ) => Promise<void>;
  }) {
    this.#transport = new Transport(options);
    this.#worldId = options.worldId;
    this.#defaultVersionId = options.defaultVersionId;
    this.#onVersionChange = options.onVersionChange;
    this.#savedEntry = options.savedEntry;
    this.#onSavedEntryAdvanced = options.onSavedEntryAdvanced;
  }

  assets(): readonly ReviewedAsset[] {
    return this.#assets;
  }

  version(): AlternateVersion | null {
    return this.#version;
  }

  /** Every alternate version in this workspace, newest first. */
  async versions(): Promise<readonly AlternateVersion[]> {
    const body = await this.#transport.getJson<unknown>(this.#path('/world/versions'));
    return Object.freeze(array(body, 'alternate version list').map(parseVersion));
  }

  async reviewedAssets(): Promise<readonly ReviewedAsset[]> {
    // The reviewed catalog is the same for every world, so this read names none.
    const body = await this.#transport.getJson<unknown>('/world/assets');
    this.#assets = Object.freeze(array(body, 'reviewed asset list').map(parseAsset));
    return this.#assets;
  }

  async readVersion(versionId: string): Promise<AlternateVersion> {
    this.#version = await this.#fetchVersion(versionId);
    return this.#version;
  }

  async #fetchVersion(versionId: string): Promise<AlternateVersion> {
    return parseVersion(
      await this.#transport.getJson<unknown>(
        this.#path(`/world/versions/${encodeURIComponent(versionId)}`),
      ),
    );
  }

  /**
   * Read the reviewed registry and one version together, or the newest version when none is named.
   *
   * There is no version picker on this surface. Opening the newest is a presentation decision and it
   * is made here rather than pretending the contract has a current pointer: it deliberately does
   * not, because "two alternate versions of one place could not coexist at all" is exactly the
   * limitation this plane exists to remove.
   */
  async connect(versionId?: string): Promise<{
    readonly assets: readonly ReviewedAsset[];
    readonly version: AlternateVersion | null;
  }> {
    const expected = this.#savedEntry?.();
    const selectedVersionId = versionId ?? this.#defaultVersionId ?? expected?.authoredVersionId;
    const [assets, version] = await Promise.all([
      this.reviewedAssets(),
      selectedVersionId === undefined
        ? this.versions().then((all) => all[0] ?? null)
        : this.#fetchVersion(selectedVersionId),
    ]);
    if (expected !== undefined) {
      const active = this.#savedEntry?.();
      const cursorStayedActive = active !== undefined
        && active.entryId === expected.entryId
        && active.revision === expected.revision
        && active.authoredVersionId === expected.authoredVersionId
        && active.authoredStateSha256 === expected.authoredStateSha256
        && active.authoredEditSeq === expected.authoredEditSeq;
      const versionMatches = version !== null
        && version.versionId === expected.authoredVersionId
        && version.stateSha256 === expected.authoredStateSha256
        && version.editSeq === expected.authoredEditSeq
        && !version.sourceInvalidated;
      if (!cursorStayedActive || !versionMatches) {
        this.#version = null;
        throw new WorldObjectsContractError(
          'saved_entry_reconciliation_required',
          'This saved world changed elsewhere or its source became unavailable. Reload to compare '
            + 'the latest changes before opening or editing it.',
        );
      }
    }
    this.#version = version;
    return Object.freeze({ assets, version });
  }

  /** Read the topology base before the person confirms opening an alternate version. */
  async bootstrapBase(): Promise<string> {
    const current = record(
      await this.#transport.getJson<unknown>(this.#path('/world/styles/current')),
      'world style state',
    );
    return text(current['current_topology_digest'], 'topology digest');
  }

  /** Bootstrap preserves the source slots; only the reviewed topology base is submitted. */
  async bootstrapVersion(baseTopologyDigest: string): Promise<string> {
    const opened = record(await this.#transport.postJson<unknown>(
      this.#path('/world/versions/bootstrap'), {
      base_topology_digest: text(baseTopologyDigest, 'topology digest'),
      },
    ), 'opened alternate version');
    return text(opened['version_id'], 'version id');
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
    this.#version = parseVersion(
      await this.#transport.postJson<unknown>(this.#path('/world/versions'), body),
    );
    await this.#onVersionChange?.(this.#version);
    return this.#version;
  }

  async place(base: AlternateVersion, request: ObjectPlacementRequest): Promise<ObjectWriteResult> {
    assertTransform(request.transform);
    return this.#write(base, this.#path(objectsPath(base.versionId)), {
      object_id: request.objectId,
      asset_sha256: request.assetSha256,
      region_id: request.regionId,
      transform: wireTransform(request.transform),
      origin_role: request.originRole,
      behaviour: request.behaviour === null ? null : wireBehaviour(request.behaviour),
    });
  }

  /**
   * Give a placed object a reviewed behaviour, replace the one it has, or take it away with null.
   *
   * `behaviour` is always in the body, null included: the route refuses a body that leaves it out
   * rather than reading an omission as a clear nobody asked for. The parameters are not checked
   * here. The server's registry is the one that decides, and its refusal is what the person is
   * shown, in its own words.
   */
  setBehaviour(
    base: AlternateVersion,
    objectId: string,
    behaviour: ObjectBehaviour | null,
  ): Promise<ObjectWriteResult> {
    return this.#write(base, this.#path(`${objectPath(base.versionId, objectId)}/behaviour`), {
      behaviour: behaviour === null ? null : wireBehaviour(behaviour),
    });
  }

  async move(
    base: AlternateVersion,
    objectId: string,
    transform: TransformInput,
  ): Promise<ObjectWriteResult> {
    assertTransform(transform);
    return this.#write(base, this.#path(`${objectPath(base.versionId, objectId)}/move`), {
      transform: wireTransform(transform),
    });
  }

  remove(base: AlternateVersion, objectId: string): Promise<ObjectWriteResult> {
    return this.#write(base, this.#path(`${objectPath(base.versionId, objectId)}/remove`), {});
  }

  /** Reverse the newest edit no undo already names. Refused with `invalid_object_state` when none. */
  undo(base: AlternateVersion): Promise<ObjectWriteResult> {
    return this.#write(base, this.#path(`${objectsPath(base.versionId)}/undo`), {});
  }

  /**
   * `POST .../compositions/preview` for a body `composition-preview-api.ts` built. Never writes.
   *
   * It carries the base this client read and never a saved-entry binding, which preview refuses.
   * The version's own world is always named: a starter world that omitted it would resolve in the
   * default world and answer as absent. A photo estimate goes to its own route instead; see
   * `compositionRoute`.
   */
  async compositionPreview(
    base: AlternateVersion,
    body: Readonly<Record<string, unknown>>,
  ): Promise<unknown> {
    return this.#transport.postJson<unknown>(
      this.#versionWorldPath(`${compositionRoute(base.versionId, body)}/preview`, base),
      { ...body, base_state_sha256: base.stateSha256 },
    );
  }

  /**
   * `POST .../compositions/apply`, through the same serialized write as every other edit.
   *
   * So it carries the base and the saved-entry binding, advances the entry cursor on success, and
   * turns a stale base into a re-read. Composition reports a stale base as `composition_blocked`
   * with the code `stale_base`, and that is the same fact as `stale_object_base`.
   */
  compositionApply(
    base: AlternateVersion,
    body: Readonly<Record<string, unknown>>,
  ): Promise<ObjectWriteResult> {
    return this.#write(
      base,
      this.#versionWorldPath(`${compositionRoute(base.versionId, body)}/apply`, base),
      body,
      (error) => error.code === 'composition_blocked' && problemDetail(error) === 'stale_base',
    );
  }

  /**
   * `POST .../arrangements/preview` for a body `arrangement-api.ts` built. Never writes.
   *
   * It carries the base this client read and never a saved-entry binding, as composition preview
   * does, and names the version's own world.
   */
  async arrangementPreview(
    base: AlternateVersion,
    body: Readonly<Record<string, unknown>>,
  ): Promise<unknown> {
    return this.#transport.postJson<unknown>(
      this.#versionWorldPath(`${arrangementsPath(base.versionId)}/preview`, base),
      { ...body, base_state_sha256: base.stateSha256 },
    );
  }

  /**
   * `POST .../arrangements/apply`, through the same serialized write as every other edit.
   *
   * Its answer is the version and what was added, so `read` takes the version out of it and keeps
   * the rest. A stale base comes back as `arrangement_refused` with the code `stale_base`, the same
   * fact as `stale_object_base`, and is turned into a re-read.
   */
  arrangementApply(
    base: AlternateVersion,
    body: Readonly<Record<string, unknown>>,
    read: (value: unknown) => AlternateVersion,
  ): Promise<ObjectWriteResult> {
    return this.#write(
      base,
      this.#versionWorldPath(`${arrangementsPath(base.versionId)}/apply`, base),
      body,
      (error) => error.code === 'arrangement_refused' && problemDetail(error) === 'stale_base',
      read,
    );
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
    const response = await this.#transport.getBytes(
      `${assetPath(asset.assetKey)}/licence`,
    );
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
    scopedPath: string,
    body: Readonly<Record<string, unknown>>,
    alsoStale: (error: ApiError) => boolean = () => false,
    read: (value: unknown) => AlternateVersion = parseVersion,
  ): Promise<ObjectWriteResult> {
    const run = async (): Promise<ObjectWriteResult> => {
      const savedEntry = this.#savedEntry?.();
      try {
        const version = read(await this.#transport.postJson<unknown>(scopedPath, {
          ...body,
          base_state_sha256: base.stateSha256,
          ...(savedEntry === undefined ? {} : {
            saved_entry: {
              entry_id: savedEntry.entryId,
              base_revision: savedEntry.revision,
              authored_state_sha256: savedEntry.authoredStateSha256,
              authored_edit_seq: savedEntry.authoredEditSeq,
            },
          }),
        }));
        this.#version = version;
        await this.#onVersionChange?.(version);
        if (savedEntry !== undefined) {
          await this.#onSavedEntryAdvanced?.(version, savedEntry);
        }
        return Object.freeze({ kind: 'recorded' as const, version });
      } catch (error) {
        if (error instanceof ApiError && (error.code === 'stale_object_base' || alsoStale(error))) {
          const current = await this.readVersion(base.versionId);
          return Object.freeze({ kind: 'stale' as const, current });
        }
        if (error instanceof ApiError && error.code === 'stale_saved_world_entry') {
          throw new WorldObjectsContractError(
            'saved_entry_conflict',
            'This saved world changed elsewhere. The edit was not recorded. Reload before trying again.',
          );
        }
        throw error;
      }
    };
    const result = this.#queue.then(run, run);
    this.#queue = result.then(() => undefined, () => undefined);
    return result;
  }

  #path(path: string): string {
    return worldPath(path, this.#openWorld());
  }

  /**
   * A write addressed to a version names the version's own world: the one the server returned it
   * with. A client given a world refuses a version of any other.
   */
  #versionWorldPath(path: string, base: AlternateVersion): string {
    if (this.#worldId !== undefined && base.worldId !== this.#worldId) {
      throw new WorldObjectsContractError(
        'world_mismatch',
        'This version belongs to another world than the one this surface has open.',
      );
    }
    return worldPath(path, base.worldId);
  }

  #openWorld(): string {
    if (this.#worldId === undefined) {
      throw new WorldObjectsContractError(
        'no_open_world',
        'No world is open, so there is no world to read or change.',
      );
    }
    return this.#worldId;
  }
}

/** The `detail` of a problem, without the `code: ` prefix `ApiError` puts on its message. */
export function problemDetail(error: ApiError): string {
  const prefix = `${error.code}: `;
  return error.message.startsWith(prefix) ? error.message.slice(prefix.length) : error.message;
}

// -- paths ---------------------------------------------------------------------------------------

const objectsPath = (versionId: string): string =>
  `/world/versions/${encodeURIComponent(versionId)}/objects`;

const compositionsPath = (versionId: string): string =>
  `/world/versions/${encodeURIComponent(versionId)}/compositions`;

const arrangementsPath = (versionId: string): string =>
  `/world/versions/${encodeURIComponent(versionId)}/arrangements`;

/**
 * Where a composition body is sent, read from the body itself so the two cannot disagree.
 *
 * Resolving a 3D estimate from a photo reads that photo's admission state, so the server declares
 * it on routes of its own, which also require `admission.read`, and the generic routes refuse the
 * kind with `photo_point_map_route_required`.
 */
function compositionRoute(versionId: string, body: Readonly<Record<string, unknown>>): string {
  const source = body['source'];
  const kind = typeof source === 'object' && source !== null
    ? (source as Readonly<Record<string, unknown>>)['kind']
    : undefined;
  return kind === 'photo_point_map'
    ? `${compositionsPath(versionId)}/photo-point-maps`
    : compositionsPath(versionId);
}

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

function side(value: unknown, label: string): KindSide {
  if (!KIND_SIDES.includes(value as KindSide)) throw invalid(label);
  return value as KindSide;
}

/** Whole millimetres, exactly `count` of them. */
function millimetres(value: unknown, count: number, label: string): readonly number[] {
  const items = array(value, label);
  if (items.length !== count) throw invalid(label);
  return Object.freeze(items.map((item) => integer(item, label)));
}

function parseUse(value: unknown): KindUse | null {
  if (value === null) return null;
  const row = record(value, 'asset use');
  const places = row['places'] === null ? null : array(row['places'], 'asset use places').map((item): KindPlace => {
    const place = record(item, 'asset use place');
    const seat = place['seat'] === null ? null : record(place['seat'], 'asset use seat');
    return Object.freeze({
      positionMm: millimetres(place['position_mm'], 2, 'asset use place position') as readonly [number, number],
      faces: side(place['faces'], 'asset use place facing'),
      seat: seat === null ? null : Object.freeze({
        positionMm: millimetres(seat['position_mm'], 3, 'asset use seat position') as readonly [number, number, number],
        faces: side(seat['faces'], 'asset use seat facing'),
      }),
    });
  });
  return Object.freeze({ affordance: text(row['affordance'], 'asset use affordance'), places: places && Object.freeze(places) });
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
    placeable: flag(row['placeable'], 'reviewed asset placeability'),
    ...('use' in row ? { use: parseUse(row['use']) } : {}),
  });
}

export function parseTransform(value: unknown): ObjectTransform {
  const row = record(value, 'object transform');
  return Object.freeze({
    // Carried on the wire so "a reader never has to know them from context". Read rather than
    // assumed, and refused when they are not the ones this client converts.
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
  if (!isObjectRole(role)) throw invalid('authored object role');
  return Object.freeze({
    objectId: text(row['object_id'], 'authored object id'),
    asset: parseAsset(row['asset']),
    regionId: text(row['region_id'], 'authored object region'),
    transform: parseTransform(row['transform']),
    origin: Object.freeze({
      kind: text(origin['kind'], 'authored object origin kind'),
      role,
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
    environmentInstanceId: optionalText(
      row['environment_instance_id'], 'version edit environment instance',
    ),
    pointMapInstanceId: optionalText(
      row['point_map_instance_id'], 'version edit point map instance',
    ),
    undoneEditId: optionalText(row['undone_edit_id'], 'version edit undone id'),
    baseStateSha256: digest(row['base_state_sha256'], 'version edit base hash'),
    resultStateSha256: digest(row['result_state_sha256'], 'version edit result hash'),
    actor: text(row['actor'], 'version edit actor'),
    recordedAt: text(row['recorded_at'], 'version edit timestamp'),
  });
}

function parseEnvironmentInstance(value: unknown): EnvironmentInstance {
  const row = record(value, 'environment instance');
  const origin = record(row['origin'], 'environment instance origin');
  const role = text(origin['role'], 'environment instance role');
  if (!isObjectRole(role)) throw invalid('environment instance role');
  return Object.freeze({
    instanceId: text(row['instance_id'], 'environment instance id'),
    source: Object.freeze({ ...record(row['source'], 'environment instance source') }),
    regionId: text(row['region_id'], 'environment instance region'),
    transform: parseTransform(row['transform']),
    origin: Object.freeze({
      kind: text(origin['kind'], 'environment instance origin kind'),
      role,
    }),
    removed: flag(row['removed'], 'environment instance removal'),
    availability: text(row['availability'], 'environment instance availability'),
  });
}

function parsePointMapInstance(value: unknown): PointMapInstance {
  const row = record(value, 'point map instance');
  const origin = record(row['origin'], 'point map instance origin');
  const role = text(origin['role'], 'point map instance role');
  if (!isObjectRole(role)) throw invalid('point map instance role');
  return Object.freeze({
    instanceId: text(row['instance_id'], 'point map instance id'),
    source: Object.freeze({ ...record(row['source'], 'point map instance source') }),
    regionId: text(row['region_id'], 'point map instance region'),
    transform: parseTransform(row['transform']),
    origin: Object.freeze({ kind: text(origin['kind'], 'point map origin kind'), role }),
    removed: flag(row['removed'], 'point map instance removal'),
    availability: text(row['availability'], 'point map instance availability'),
    unavailableReason: optionalText(row['unavailable_reason'], 'point map unavailable reason'),
    truth: text(row['truth'], 'point map truth line'),
    scale: text(row['scale'], 'point map scale line'),
    coverage: text(row['coverage'], 'point map coverage line'),
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
    environmentInstances: Object.freeze(
      array(row['environment_instances'] ?? [], 'environment instance list')
        .map(parseEnvironmentInstance),
    ),
    pointMapInstances: Object.freeze(
      array(row['point_map_instances'] ?? [], 'point map instance list')
        .map(parsePointMapInstance),
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
    return 'The authority refused the shape of this edit. That is a fault in this client rather '
      + 'than something you did.';
  }
  switch (error.code) {
    case 'unknown_reference':
      return 'That version, object or asset is not in this workspace.';
    case 'protected_topology_conflict':
      return 'This world changed. Choose “Place before me” again to review its current version.';
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
