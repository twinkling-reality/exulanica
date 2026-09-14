import type { BodyRecipe } from './ui/character-body.js';
import type { NativeCharacterAppearance, NativeCharacterDescriptor, CharacterByteLoader, FirstPersonGestureDescriptor } from '@exulanica/atlas-react/playcanvas';
import type { CharacterSubject } from '@exulanica/atlas-core';

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

/** Only the development preview supplies this catalogue; no production permission is inferred. */
export async function loadPreviewCharacterCatalog(signal: AbortSignal): Promise<readonly CharacterLook[]> {
  const response = await fetch('/fixtures/characters/catalog.json', { signal });
  if (!response.ok) throw new Error('Character examples are unavailable. Reload to try again.');
  const catalog: unknown = await response.json();
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

export function characterByteLoader(catalog: readonly CharacterLook[]): CharacterByteLoader {
  return async (reference, signal) => {
    const look = catalog.find(item => item.descriptor.asset.contentSha256 === reference.contentSha256);
    const gesture = catalog.find(item => item.gesture?.descriptor.character.asset.contentSha256 === reference.contentSha256)?.gesture;
    const file = look?.file ?? gesture?.file;
    if (!file) throw new Error('That character is outside the available catalogue.');
    const response = await fetch(look?.generated ? `/__character/assets/${file}` : `/fixtures/characters/${file}`, { signal });
    if (!response.ok) throw new Error('This character could not be loaded. Choose another look or try again.');
    return response.arrayBuffer(); // The shared renderer verifies exact size and SHA-256 before decoding.
  };
}
