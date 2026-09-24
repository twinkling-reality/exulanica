/**
 * A small square in one request: the arrangement routes, read and written through the objects client.
 *
 * `POST /world/versions/{version_id}/arrangements/preview` says where every object of an arrangement
 * would stand in front of the person, or refuses by name; `.../apply` adds exactly those objects as
 * ordinary edits, one change each, or refuses with the same name. The body carries what the person
 * asked for and where they stand and face. Where each object goes is the server's to work out, so
 * nothing here places one.
 *
 * The arrangement the Create panel offers is named by the key and version the server publishes it
 * under (`assets/catalogs/world-objects/world-arrangement.v1.json`); a test reads that file, so the
 * two cannot drift apart quietly. The refusal codes are the server's own list
 * (`exulanica/world/arrangements.py`, `ARRANGEMENT_REFUSALS`), read by a test the same way.
 */

import {
  parseVersion,
  type AlternateVersion,
  type ObjectRole,
  type ObjectWriteResult,
  type WorldObjectsClient,
} from './world-objects-api.js';

/** The arrangement the Create panel offers, as the server publishes it. */
export const SMALL_SQUARE = Object.freeze({ key: 'small_square', version: 1 });

/**
 * Every code an arrangement refusal carries, as `ARRANGEMENT_REFUSALS` declares it. A code outside
 * this list is still shown, with the generic sentence, rather than dropped or guessed at.
 */
export const ARRANGEMENT_REFUSALS = Object.freeze([
  'arrangement_unknown',
  'arrangement_needs_authored_ground',
  'arrangement_outside_ground',
  'arrangement_covers_arrival',
  'arrangement_overlaps',
  'stale_base',
  'source_invalidated',
  'asset_bytes_unavailable',
  'invalid_placement',
  'subject_already_present',
] as const);

export type ArrangementRefusal = typeof ARRANGEMENT_REFUSALS[number];

export function isArrangementRefusal(value: unknown): value is ArrangementRefusal {
  return typeof value === 'string' && (ARRANGEMENT_REFUSALS as readonly string[]).includes(value);
}

/** Where the person stands in the world's authored region, and the yaw of their facing. */
export interface ArrangementViewer {
  readonly xMm: number;
  readonly zMm: number;
  /** The yaw an object placed facing the person would take. */
  readonly yawMicroradians: number;
}

export interface ArrangementRequest {
  readonly key: string;
  readonly version: number;
  readonly viewer: ArrangementViewer;
  readonly originRole: ObjectRole;
}

export interface ArrangementIdentity {
  readonly key: string;
  readonly version: number;
  readonly title: string;
  readonly summary: string;
}

export interface ArrangementPreview {
  readonly availability: 'ready' | 'blocked';
  /** Null exactly when ready. An unrecognised code is kept as it arrived. */
  readonly blockedReason: string | null;
  /** The server's own sentence, for details. Never branched on. */
  readonly blockedDetail: string | null;
  /** Null when the key and version name no published arrangement. */
  readonly arrangement: ArrangementIdentity | null;
  /** The version as stored when the server answered. */
  readonly version: {
    readonly authoredVersionId: string;
    readonly worldId: string;
    readonly stateSha256: string;
    readonly editSeq: number;
  };
  /** What apply would add, in the order it adds them. Empty when blocked. */
  readonly wouldAdd: readonly { readonly objectId: string; readonly assetKey: string; readonly title: string }[];
}

export interface ArrangementApplied {
  readonly arrangement: ArrangementIdentity;
  /** Each object added, in the order it was added: taking back removes the newest first. */
  readonly addedObjectIds: readonly string[];
  readonly version: AlternateVersion;
}

export type ArrangementWriteResult =
  | { readonly kind: 'recorded'; readonly version: AlternateVersion; readonly applied: ArrangementApplied }
  | { readonly kind: 'stale'; readonly current: AlternateVersion };

export class ArrangementContractError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ArrangementContractError';
  }
}

function record(value: unknown, label: string): Readonly<Record<string, unknown>> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new ArrangementContractError(`${label} is not an object`);
  }
  return value as Readonly<Record<string, unknown>>;
}

function text(value: unknown, label: string): string {
  if (typeof value !== 'string' || value.length === 0) throw new ArrangementContractError(`${label} is not text`);
  return value;
}

function textOrNull(value: unknown, label: string): string | null {
  return value === null ? null : text(value, label);
}

function whole(value: unknown, label: string): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value)) {
    throw new ArrangementContractError(`${label} is not a whole number`);
  }
  return value;
}

function identity(value: unknown): ArrangementIdentity {
  const row = record(value, 'arrangement');
  return Object.freeze({
    key: text(row['key'], 'arrangement key'),
    version: whole(row['version'], 'arrangement version'),
    title: text(row['title'], 'arrangement title'),
    summary: text(row['summary'], 'arrangement summary'),
  });
}

/** The wire body for either route, less the base the client adds. Integers only, as the server takes them. */
export function arrangementRequestBody(request: ArrangementRequest): Record<string, unknown> {
  return {
    arrangement_key: request.key,
    arrangement_version: request.version,
    viewer: {
      x_mm: Math.round(request.viewer.xMm),
      z_mm: Math.round(request.viewer.zMm),
      yaw_microradians: Math.round(request.viewer.yawMicroradians),
    },
    origin_role: request.originRole,
  };
}

export function parseArrangementPreview(value: unknown): ArrangementPreview {
  const row = record(value, 'arrangement preview');
  const availability = row['availability'];
  if (availability !== 'ready' && availability !== 'blocked') {
    throw new ArrangementContractError('arrangement preview availability is not ready or blocked');
  }
  const blockedReason = textOrNull(row['blocked_reason'], 'arrangement blocked reason');
  if ((availability === 'ready') !== (blockedReason === null)) {
    throw new ArrangementContractError('arrangement preview availability and reason disagree');
  }
  const version = record(row['version'], 'arrangement preview version');
  const wouldAdd = row['would_add'];
  if (!Array.isArray(wouldAdd)) throw new ArrangementContractError('would_add is not a list');
  return Object.freeze({
    availability,
    blockedReason,
    blockedDetail: textOrNull(row['blocked_detail'], 'arrangement blocked detail'),
    arrangement: row['arrangement'] === null ? null : identity(row['arrangement']),
    version: Object.freeze({
      authoredVersionId: text(version['authored_version_id'], 'authored version id'),
      worldId: text(version['world_id'], 'world id'),
      stateSha256: text(version['state_sha256'], 'state digest'),
      editSeq: whole(version['edit_seq'], 'edit sequence'),
    }),
    wouldAdd: Object.freeze(wouldAdd.map((item) => {
      const added = record(item, 'arrangement object');
      return Object.freeze({
        objectId: text(added['object_id'], 'arrangement object id'),
        assetKey: text(added['asset_key'], 'arrangement asset key'),
        title: text(added['title'], 'arrangement object title'),
      });
    })),
  });
}

export function parseArrangementApplied(value: unknown): ArrangementApplied {
  const row = record(value, 'arrangement answer');
  const added = row['added_object_ids'];
  if (!Array.isArray(added)) throw new ArrangementContractError('added_object_ids is not a list');
  return Object.freeze({
    arrangement: identity(row['arrangement']),
    addedObjectIds: Object.freeze(added.map((id) => text(id, 'added object id'))),
    version: parseVersion(row['version']),
  });
}

export type ArrangementTransport = Pick<WorldObjectsClient, 'arrangementPreview' | 'arrangementApply'>;

/** Ask the server where the arrangement would stand against the version the caller read. */
export async function previewArrangement(
  client: ArrangementTransport,
  base: AlternateVersion,
  request: ArrangementRequest,
): Promise<ArrangementPreview> {
  return parseArrangementPreview(await client.arrangementPreview(base, arrangementRequestBody(request)));
}

/** Apply the same request: the server resolves it again and adds exactly those objects, or refuses. */
export async function applyArrangement(
  client: ArrangementTransport,
  base: AlternateVersion,
  request: ArrangementRequest,
): Promise<ArrangementWriteResult> {
  let applied: ArrangementApplied | null = null;
  const result: ObjectWriteResult = await client.arrangementApply(
    base,
    arrangementRequestBody(request),
    (value) => {
      applied = parseArrangementApplied(value);
      return applied.version;
    },
  );
  if (result.kind === 'stale') return result;
  if (applied === null) throw new ArrangementContractError('the arrangement answer was not read');
  return Object.freeze({ kind: 'recorded' as const, version: result.version, applied });
}
