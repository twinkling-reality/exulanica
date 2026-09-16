import { hash3 } from '../hash.js';
import { clamp, floorDiv, isqrt } from '../integer.js';
import type { Maps } from '../maps.js';
import { SRGB_TO_LINEAR, encodeChannel } from '../srgb.js';
import type { DatasetPlan } from './plan.js';
import { LIGHT_SLOT, VIEW_SLOT, pickWide } from './sample.js';

/**
 * A picture of a bake: a square window of the tiled surface under one light, in integers.
 *
 * The surface is seen straight on, with no perspective and no parallax, and lit by one
 * directional light plus an even surround: diffuse from the normal map, a highlight whose
 * tightness follows roughness, a reflection of the surround in each surface's own reflectance (so
 * a metal shows its colour even where the light's highlight is not), crevices darkened by the
 * occlusion channel, and a slight per-channel colour cast. It is a picture for a model to learn
 * from, not the product's renderer, and a change that moves any pixel is a new `RENDERER`.
 *
 * Directions are tangent-space vectors in 1/4096ths, in the normal map's own convention: +X toward
 * increasing u, +Y toward row 0, +Z out of the surface. Every product in the shading loop stays
 * under 2^34.
 */
const Q = 4096;
/** A dielectric's reflectance at normal incidence, 0.04, in 1/65536ths. */
const DIELECTRIC_F0 = 2621;
/** Tries for a light direction inside the plan's elevation range before the plan is refused. */
const DIRECTION_TRIES = 64;
/** Purposes for the light's other draws start here, clear of the direction's tries. */
const LIGHT_LEVELS = 1000;

export interface Light {
  readonly direction_q12: readonly [number, number, number];
  readonly intensity_permille: number;
  readonly ambient_permille: number;
  readonly gain_permille: readonly [number, number, number];
}

/** The top-left texel of the window, anywhere on the tile; the window wraps. */
export interface View {
  readonly u: number;
  readonly v: number;
}

/**
 * A unit vector in 1/4096ths. The length is taken of the vector scaled by 4096 first, so the
 * division keeps twelve more bits and a component is off by less than one unit. Inputs stay small
 * enough (at most 8192 a component) that the scaled square sum is below 2^52, where `isqrt` is exact.
 */
function normalise(x: number, y: number, z: number): [number, number, number] {
  const length = isqrt((x * x + y * y + z * z) * Q * Q);
  return [
    floorDiv(x * Q * Q, length),
    floorDiv(y * Q * Q, length),
    floorDiv(z * Q * Q, length),
  ];
}

function sampleDirection(
  draw: (purpose: number) => number,
  elevation: readonly [number, number],
): [number, number, number] {
  for (let attempt = 0; attempt < DIRECTION_TRIES; attempt += 1) {
    const x = pickWide(draw(attempt * 3), -1000, 1000);
    const y = pickWide(draw(attempt * 3 + 1), -1000, 1000);
    const z = pickWide(draw(attempt * 3 + 2), 1, 1000);
    const length = isqrt(x * x + y * y + z * z);
    if (z * 1000 >= elevation[0] * length && z * 1000 <= elevation[1] * length) {
      return normalise(x, y, z);
    }
  }
  throw new Error(`no light direction in ${DIRECTION_TRIES} tries sits inside the plan's elevation`);
}

export function sampleLight(plan: DatasetPlan, recordSeed: number): Light {
  const draw = (purpose: number): number => hash3(LIGHT_SLOT, 0, purpose, recordSeed);
  const { lighting } = plan;
  const within = (purpose: number, range: readonly [number, number]): number =>
    pickWide(draw(LIGHT_LEVELS + purpose), range[0], range[1]);
  return {
    direction_q12: sampleDirection(draw, lighting.elevation_permille),
    intensity_permille: within(0, lighting.intensity_permille),
    ambient_permille: within(1, lighting.ambient_permille),
    gain_permille: [
      within(2, lighting.gain_permille),
      within(3, lighting.gain_permille),
      within(4, lighting.gain_permille),
    ],
  };
}

export function sampleView(recordSeed: number, width: number, height: number): View {
  return {
    u: pickWide(hash3(VIEW_SLOT, 0, 1, recordSeed), 0, width - 1),
    v: pickWide(hash3(VIEW_SLOT, 0, 2, recordSeed), 0, height - 1),
  };
}

const unit = (byte: number): number => floorDiv((2 * byte - 255) * Q, 255);

/** `size` x `size` pixels of sRGB, rows top to bottom, starting at the view's texel. */
export function renderView(maps: Maps, view: View, light: Light, size: number): Uint8Array {
  const { width, height } = maps;
  const out = new Uint8Array(size * size * 3);
  const [lx, ly, lz] = light.direction_q12;
  const [hx, hy, hz] = normalise(lx, ly, lz + Q);
  const ambient = floorDiv(light.ambient_permille * Q, 1000);
  for (let row = 0; row < size; row += 1) {
    const texelRow = ((view.v + row) % height) * width;
    for (let column = 0; column < size; column += 1) {
      const texel = texelRow + ((view.u + column) % width);
      const at = texel * 3;
      const nx = unit(maps.normal[at]!);
      const ny = unit(maps.normal[at + 1]!);
      const nz = unit(maps.normal[at + 2]!);
      const facing = Math.max(0, floorDiv(nx * lx + ny * ly + nz * lz, Q));
      const alignment = Math.max(0, floorDiv(nx * hx + ny * hy + nz * hz, Q));
      const occlusion = maps.orm[at]!;
      const roughness = maps.orm[at + 1]!;
      const metalness = maps.orm[at + 2]!;
      // A smoother surface squares the alignment more times, which tightens the highlight.
      const steps = 1 + floorDiv((255 - roughness) * 7, 255);
      let lobe = alignment;
      for (let step = 0; step < steps; step += 1) lobe = floorDiv(lobe * lobe, Q);
      const direct = floorDiv(facing * light.intensity_permille, 1000);
      const shading = ambient + direct;
      for (let channel = 0; channel < 3; channel += 1) {
        const albedo = SRGB_TO_LINEAR[maps.baseColor[at + channel]!]!;
        const diffuse = floorDiv(floorDiv(albedo * (255 - metalness), 255) * shading, Q);
        const f0 = floorDiv(DIELECTRIC_F0 * (255 - metalness) + albedo * metalness, 255);
        const specular = floorDiv(floorDiv(f0 * lobe, Q) * direct * (1 + steps), 4 * Q);
        // The surround, reflected: twice the ambient level, in the surface's own reflectance.
        const reflection = floorDiv(f0 * 2 * ambient, Q);
        const lit = floorDiv((diffuse + specular + reflection) * occlusion, 255);
        const graded = floorDiv(lit * light.gain_permille[channel]!, 1000);
        out[(row * size + column) * 3 + channel] = encodeChannel(clamp(graded, 0, 65535));
      }
    }
  }
  return out;
}
