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
  readonly createdAt: string;
  readonly updatedAt: string;
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
    createdAt: text(row['created_at'], 'created time'),
    updatedAt: text(row['updated_at'], 'updated time'),
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
