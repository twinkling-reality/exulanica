import type { BodyRecipe } from './ui/character-body.js';
import {
  readServedCatalog,
  type CatalogPublicationEntry,
  type CharacterByteLoader,
  type FirstPersonGestureDescriptor,
  type NativeCharacterAppearance,
  type NativeCharacterDescriptor,
  type ServedCharacterCatalog,
} from '@exulanica/atlas-react/playcanvas';
import type { CharacterSubject } from '@exulanica/atlas-core';
import { ApiError, Transport, type TransportOptions } from '@exulanica/graph-client';

export interface CharacterLook {
  readonly generated?: boolean;
  readonly recipe?: BodyRecipe;
  readonly familyId?: string;
  readonly lookId: string;
  readonly label: string;
  readonly file: string;
  readonly creator: string;
  readonly license: string;
  readonly descriptor: NativeCharacterDescriptor;
  readonly defaultColors: Readonly<Record<string, string>>;
  /** Prepared garment slots, excluding materials shared with the source head/hair. */
  readonly variationSlots?: readonly string[];
  readonly gesture?: { readonly file: string; readonly descriptor: FirstPersonGestureDescriptor };
}
export interface CharacterSelection {
  readonly lookId: string;
  readonly appearance: NativeCharacterAppearance;
}

/** Validate a stylized look list; only the development preview supplies one. */
export function parseCharacterLooks(catalog: unknown): readonly CharacterLook[] {
  if (!Array.isArray(catalog) || catalog.length === 0) throw new Error('No character looks are available.');
  const ids = new Set<string>();
  for (const item of catalog as CharacterLook[]) {
    if (!item || typeof item.lookId !== 'string' || ids.has(item.lookId) || typeof item.label !== 'string' ||
      !/^[a-zA-Z0-9-]+\.glb$/.test(item.file) || !item.descriptor?.asset || !item.defaultColors ||
      Object.values(item.defaultColors).some(value => !/^#[a-f\d]{6}$/i.test(value))) {
      throw new Error('The character catalogue could not be read.');
    }
    ids.add(item.lookId);
    if (item.variationSlots && (!Array.isArray(item.variationSlots) || item.variationSlots.some(slot =>
      typeof slot !== 'string' || !item.descriptor.materialSlots?.[slot] || !item.defaultColors[slot]))) {
      throw new Error('Invalid character variation slots.');
    }
    if (item.gesture && !/^[a-zA-Z0-9-]+\.glb$/.test(item.gesture.file)) throw new Error('Invalid character gesture reference.');
  }
  return catalog as CharacterLook[];
}

function appearanceSeed(text: string): number {
  let value = 2166136261;
  for (const character of text) value = Math.imul(value ^ character.charCodeAt(0), 16777619);
  return value >>> 0;
}

/** Fictional preview defaults; independent of draw order, position and simulation branch. */
export function previewInhabitantSelection(
  catalog: readonly CharacterLook[], subject: CharacterSubject,
): CharacterSelection | null {
  if (subject.kind !== 'synthetic-inhabitant' || catalog.length === 0) return null;
  if (catalog.every(item => item.familyId)) return null;
  const seed = `preview-inhabitant/v1:${subject.societyId}:${subject.inhabitantId}`;
  const looks = catalog.filter(item => !item.familyId).sort((a, b) => a.lookId.localeCompare(b.lookId));
  const look = looks[appearanceSeed(seed) % looks.length]!;
  const hue = appearanceSeed(`${seed}:hue`) / 0x100000000;
  const colors: Record<string, string> = {};
  for (const slot of look.variationSlots ?? []) {
    const original = look.defaultColors[slot]!;
    const channels = [1, 3, 5].map(offset => parseInt(original.slice(offset, offset + 2), 16) / 255);
    const lightness = (Math.min(...channels) + Math.max(...channels)) / 2;
    const saturation = .18 + (appearanceSeed(`${seed}:${slot}`) % 22) / 100;
    // Retain source light/dark relationships, varying only declared clothing colors.
    const l = Math.max(.16, Math.min(.84, lightness));
    const a = saturation * Math.min(l, 1 - l);
    const channel = (n: number) => {
      const k = (n + hue * 12) % 12;
      return Math.round(255 * (l - a * Math.max(-1, Math.min(k - 3, 9 - k, 1))));
    };
    colors[slot] = '#' + [channel(0), channel(8), channel(4)].map(value => value.toString(16).padStart(2, '0')).join('');
  }
  return { lookId: look.lookId, appearance: { colors } };
}

/** Bodies the development character builder generated for an edited recipe. */
export function characterByteLoader(generated: readonly CharacterLook[]): CharacterByteLoader {
  return async (reference, signal) => {
    const look = generated.find(item => item.generated && item.descriptor.asset.contentSha256 === reference.contentSha256);
    if (!look) throw new Error('That character is outside the available catalogue.');
    const response = await fetch(`/__character/assets/${look.file}`, { signal });
    if (!response.ok) throw new Error('This character could not be loaded. Choose another look or try again.');
    return response.arrayBuffer(); // The shared renderer verifies exact size and SHA-256 before decoding.
  };
}

/** How a saved look names a body prepared for its workspace: `preparation:<preparation id>`. */
export const PREPARATION_PREFIX = 'preparation:';

/**
 * A signed-in world's loader: every catalog container is a reviewed asset, fetched by its key from
 * `/world/assets/<asset key>/bytes`, and a body prepared for this workspace is fetched from the
 * character route `prepared` names for it. The character host refuses bytes whose length or
 * SHA-256 differ from what was published or prepared, so the key only says where to look, never
 * what to trust.
 */
export function workspaceCharacterLoader(
  options: TransportOptions,
  prepared: (preparationId: string) => string | null = () => null,
  pace: CharacterReadPace = {},
): CharacterByteLoader {
  const most = pace.concurrent ?? CHARACTER_READS_AT_ONCE;
  const tries = pace.tries ?? CHARACTER_READ_TRIES;
  const wait = pace.wait ?? ((ms: number, signal?: AbortSignal) => new Promise<void>((resolve) => {
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener('abort', () => { clearTimeout(timer); resolve(); }, { once: true });
  }));
  // A town asks for every person's parts at once; the host admits a few reads a workspace at a time
  // and refuses the rest with Retry-After, so reads queue here and a refusal is asked again.
  let running = 0;
  const queued: (() => void)[] = [];
  const slot = async (): Promise<void> => {
    if (running < most) { running += 1; return; }
    await new Promise<void>((resolve) => queued.push(resolve));
  };
  const release = (): void => {
    const next = queued.shift();
    if (next !== undefined) next(); else running -= 1;
  };
  return async (reference, signal) => {
    const path = reference.assetKey.startsWith(PREPARATION_PREFIX)
      ? prepared(reference.assetKey.slice(PREPARATION_PREFIX.length))
      : `/world/assets/${encodeURIComponent(reference.assetKey)}/bytes`;
    if (path === null) throw new Error('preparation_unavailable');
    await slot();
    try {
      for (let attempt = 1; ; attempt += 1) {
        try {
          const response = await new Transport({ ...options, ...(signal === undefined ? {} : { signal }) }).getBytes(path);
          return await response.arrayBuffer();
        } catch (error) {
          const busy = error instanceof ApiError && (error.status === 429 || error.status === 503);
          if (!busy || attempt >= tries || signal?.aborted === true) throw error;
          // Its Retry-After where it sent one, else a growing pause; never less than half a second.
          await wait(Math.max(500, (error.retryAfterSeconds ?? attempt) * 1000), signal);
        }
      }
    } finally {
      release();
    }
  };
}

/** How many character reads one page keeps in flight, beside the world's other reads. */
export const CHARACTER_READS_AT_ONCE = 6;
/** How many times a read the host was too busy for is asked, in all. */
export const CHARACTER_READ_TRIES = 5;

/** Overrides of the loader's pacing, for a test. */
export interface CharacterReadPace {
  readonly concurrent?: number;
  readonly tries?: number;
  readonly wait?: (ms: number, signal?: AbortSignal) => Promise<void>;
}

/** `GET /world/character-catalogs`, the host's list of the catalogs it serves. */
interface CatalogList {
  readonly profile: 'exulanica.character-catalog-list/v1';
  readonly publications: readonly CatalogPublicationEntry[];
}

/** Published documents by digest. A digest names exact bytes, so a document is fetched once. */
const SERVED = new Map<string, Promise<ServedCharacterCatalog>>();

/** The catalogs the host serves, as it lists them: current and retained, each by its digest. */
export async function characterCatalogList(options: TransportOptions): Promise<readonly CatalogPublicationEntry[]> {
  const list = await new Transport(options).getJson<CatalogList>('/world/character-catalogs');
  if (list.profile !== 'exulanica.character-catalog-list/v1' || !Array.isArray(list.publications)) {
    throw new Error('The character catalog list could not be read.');
  }
  return list.publications;
}

/** One publication's document, fetched and checked once per page. */
export function servedCharacterCatalog(
  options: TransportOptions,
  entry: CatalogPublicationEntry,
): Promise<ServedCharacterCatalog> {
  let held = SERVED.get(entry.catalog_sha256);
  if (!held) {
    held = new Transport(options)
      .getBytes(`/world/character-catalogs/${encodeURIComponent(entry.catalog_sha256)}`)
      .then(async (response) => readServedCatalog(entry, new Uint8Array(await response.arrayBuffer())));
    held.catch(() => SERVED.delete(entry.catalog_sha256));
    SERVED.set(entry.catalog_sha256, held);
  }
  return held;
}
