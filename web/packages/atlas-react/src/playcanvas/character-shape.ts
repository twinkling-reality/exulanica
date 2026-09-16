import {
  DEFAULT_CHARACTER_BODY,
  CHARACTER_PROFILE,
  ABSTRACT_CHARACTER_RIG,
  resolveCharacterRepresentation,
  type CharacterBody,
  type CharacterSubject,
  type ResolvedCharacterRepresentation,
} from '@exulanica/atlas-core';
import type { V3 } from './player-sculpt.js';
import type { Bone } from './player-rig.js';

/** Renderer view of the reviewed dimension fields. Presets are choices, never measurements. */
export type CharacterDimensions = Pick<
  CharacterBody,
  | 'heightMm'
  | 'shoulderWidthMm'
  | 'hipWidthMm'
  | 'headRatioMilli'
  | 'legRatioMilli'
  | 'armRatioMilli'
>;
export interface CharacterPalette {
  readonly head: string;
  readonly torso: string;
  readonly limbs: string;
  readonly accent: string;
}
export const BASE_DIMENSIONS: CharacterDimensions = DEFAULT_CHARACTER_BODY;
export const BASE_PALETTE: CharacterPalette = {
  head: '#e9efee',
  torso: '#15234c',
  limbs: '#192a4e',
  accent: '#a1c7d2',
};
export function shapePoint(p: V3, body: CharacterDimensions): V3 {
  const h = body.heightMm / 1820,
    leg = body.legRatioMilli / 484,
    head = body.headRatioMilli / 167;
  const y =
    p[1] < 0.88
      ? p[1] * leg
      : p[1] < 1.55
        ? 0.88 * leg +
          ((p[1] - 0.88) * (1.82 - 0.88 * leg - 0.27 * head)) / 0.67
        : 0.88 * leg + (1.82 - 0.88 * leg - 0.27 * head) + (p[1] - 1.55) * head;
  const shoulder = Math.max(0, Math.min(1, (p[1] - 0.88) / 0.42));
  const width =
    (body.hipWidthMm / 270) * (1 - shoulder) +
    (body.shoulderWidthMm / 400) * shoulder;
  const arm =
    Math.abs(p[0]) > 0.205 && p[1] < 1.4
      ? (1.367 - p[1]) * (body.armRatioMilli / 320 - 1)
      : 0;
  return [p[0] * width * h, (y - arm) * h, p[2] * h * Math.sqrt(width)];
}
export function shapeBone(b: Bone, body: CharacterDimensions): Bone {
  return { a: shapePoint(b.a, body), b: shapePoint(b.b, body) };
}
const palettes: readonly CharacterPalette[] = [
  BASE_PALETTE,
  { head: '#eee8d8', torso: '#3d5f60', limbs: '#38595a', accent: '#b8c6b7' },
  { head: '#eadfd9', torso: '#735252', limbs: '#664b50', accent: '#d5b3a5' },
  { head: '#e4e9eb', torso: '#474b6a', limbs: '#464865', accent: '#b4bcd8' },
];
/** Stable, authored preset families selected by synthetic subject ID; no inferred human traits. */
export function syntheticCharacterStyle(id: string): {
  body: CharacterDimensions;
  palette: CharacterPalette;
} {
  let hash = 2166136261;
  for (const c of id) {
    hash = Math.imul(hash ^ c.charCodeAt(0), 16777619) >>> 0;
  }
  const variants = [
    { heightMm: 1680, shoulderWidthMm: 380, hipWidthMm: 280 },
    { heightMm: 1780, shoulderWidthMm: 400, hipWidthMm: 270 },
    { heightMm: 1870, shoulderWidthMm: 425, hipWidthMm: 290 },
    { heightMm: 1750, shoulderWidthMm: 440, hipWidthMm: 310 },
  ];
  return {
    body: { ...BASE_DIMENSIONS, ...variants[hash % variants.length]! },
    palette: palettes[(hash >>> 4) % palettes.length]!,
  };
}

/** Admission applies only to the caller's existing local player or synthetic snapshot subject. */
export function abstractCharacter(
  subject: CharacterSubject,
  detail: 'near' | 'mid',
  style = { body: BASE_DIMENSIONS, palette: BASE_PALETTE },
): ResolvedCharacterRepresentation {
  if (subject.kind === 'scene-person')
    throw new Error('Scene-person presence requires the integration authority');
  const key =
    subject.kind === 'player'
      ? `player:${subject.playerId}`
      : `synthetic:${subject.societyId}:${subject.branchId}:${subject.inhabitantId}`;
  return resolveCharacterRepresentation(
    {
      profile: CHARACTER_PROFILE,
      representationId: `abstract:${key}`,
      revision: 1,
      subject,
      body: { ...DEFAULT_CHARACTER_BODY, ...style.body },
      appearance: {
        kind: 'abstract',
        preset: 'soft-human/v1',
        surface: 'color',
        palette: style.palette,
        origin: 'authored',
      },
      rig: {
        profile: ABSTRACT_CHARACTER_RIG,
        motions: ['idle', 'walk', 'run', 'start', 'stop', 'turn'],
        traversal: null,
      },
      lod: { level: detail },
    },
    { presence: 'allowed' },
  );
}
