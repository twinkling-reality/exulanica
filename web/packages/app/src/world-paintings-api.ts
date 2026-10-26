// A world's paintings (exulanica/api/routes/world_paintings.py, migration 0226): its own views painted by an open
// model from its words, held to its exact layout, kept by the operator's painting run and read by everyone who may
// read the world. Each is invented appearance and says so wherever it is shown.
import { Transport, type TransportOptions } from '@exulanica/graph-client';
import { worldPath } from './world-scope.js';

/** What `GET /world/paintings` answers. */
export const PAINTINGS_PROFILE = 'exulanica.world-paintings/v1';
/** The label every painting carries on screen. */
export const PAINTING_LABEL = 'invented appearance';

/** Where a painting was painted from: the camera the world's structure was drawn by. */
export interface PaintingCamera {
  /** East, up and south, in metres: the renderer's own axes. */
  readonly position: readonly [number, number, number];
  /** The renderer's yaw in radians: 0 looks north, forward (-sin yaw, 0, -cos yaw). */
  readonly yaw: number;
  /** Radians above level. */
  readonly pitch: number;
  /** The lens's vertical field of view, degrees, and the picture's own size. */
  readonly fovDeg: number;
  readonly width: number;
  readonly height: number;
}

export interface WorldPainting {
  readonly view: string;
  readonly sha256: string;
  readonly width: number;
  readonly height: number;
  readonly camera: PaintingCamera | null;
  /** The painter's first model, by the last part of its repository's name (`Z-Image`). */
  readonly painter: string | null;
  readonly heldPermille: number;
  readonly madeAt: string;
}

const DIGEST = /^[0-9a-f]{64}$/;
const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);

function cameraOf(raw: unknown): PaintingCamera | null {
  const camera = raw as Record<string, unknown> | null;
  const position = camera?.['position_m'];
  if (!Array.isArray(position) || position.length !== 3 || !position.every(finite)) return null;
  const yaw = camera?.['yaw'], pitch = camera?.['pitch'] ?? 0, fov = camera?.['fov_deg'];
  const width = camera?.['width'], height = camera?.['height'];
  if (!finite(yaw) || !finite(pitch) || !finite(fov) || !finite(width) || !finite(height)) return null;
  const [x, y, z] = position as [number, number, number];
  return Object.freeze({ position: Object.freeze([x, y, z] as const), yaw, pitch, fovDeg: fov, width, height });
}

function painterOf(raw: unknown): string | null {
  const models = (raw as Record<string, unknown> | null)?.['models'];
  const first = Array.isArray(models) ? (models[0] as Record<string, unknown> | undefined) : undefined;
  const repository = first?.['repository'];
  return typeof repository === 'string' && repository.length > 0 ? repository.split('/').pop() ?? null : null;
}

export function parseWorldPainting(raw: unknown): WorldPainting {
  const held = raw as Record<string, unknown> | null;
  const sha256 = held?.['sha256'], view = held?.['view'], width = held?.['width'], height = held?.['height'];
  const heldPermille = held?.['held_permille'], madeAt = held?.['made_at'];
  if (typeof sha256 !== 'string' || !DIGEST.test(sha256) || typeof view !== 'string' || !finite(width)
    || !finite(height) || !finite(heldPermille) || typeof madeAt !== 'string' || held?.['label'] !== PAINTING_LABEL) {
    throw new TypeError('The server returned an invalid painting.');
  }
  return Object.freeze({
    view, sha256, width, height, camera: cameraOf(held?.['camera']), painter: painterOf(held?.['painter']),
    heldPermille, madeAt,
  });
}

export class WorldPaintingsClient {
  readonly #transport: Transport;

  constructor(options: TransportOptions) {
    this.#transport = new Transport(options);
  }

  /** The world's paintings, newest first. */
  async paintings(worldId: string): Promise<readonly WorldPainting[]> {
    const body = await this.#transport.getJson<Record<string, unknown>>(worldPath('/world/paintings', worldId));
    if (body['profile'] !== PAINTINGS_PROFILE || !Array.isArray(body['paintings'])) {
      throw new TypeError('The server returned invalid paintings.');
    }
    return Object.freeze(body['paintings'].map(parseWorldPainting));
  }

  /** A painting's bytes in the world, by its digest (`GET /world/paintings/{sha256}`). */
  async picture(worldId: string, sha256: string): Promise<Blob> {
    const response = await this.#transport.getBytes(worldPath(`/world/paintings/${encodeURIComponent(sha256)}`, worldId));
    return response.blob();
  }
}
