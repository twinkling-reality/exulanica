import { sunDirection, type RenderLook, type Rgb } from './look.js';

/**
 * The sky a render look describes, as a pure function of direction: no engine, no GPU.
 *
 * Above the horizon the colour runs from the horizon to the zenith along the height's 0.55th power,
 * so most of the dome is near the zenith colour and the bright band hugs the horizon; below it, the
 * horizon gives way to the ground within about 10 degrees. A glow and a disc are added toward the
 * sun, then clouds are laid over the dome above the horizon. Everything is linear light and then
 * scaled by the sky's intensity.
 *
 * THE IMAGE LIGHT SEES A DIFFERENT GROUND AND NO DISC. `forLighting` swaps the ground for the
 * look's `bounceGround`, so a green field drawn under the horizon does not tint every wall green
 * (measured in the lab: every facade went green), and leaves the disc out, because the sun's direct
 * light is the directional light's and a disc in the probe would add it twice.
 *
 * THE CLOUDS ARE THE SAME EVERYWHERE. Their noise hashes integer lattice points with integer
 * multiplication only, so the same seed draws the same sky on every machine and engine; nothing
 * here reads a sine of a large number, which loses its spread on some GPUs and in some libraries.
 */

const linearDot = (a: readonly number[], b: readonly number[]): number => a[0]! * b[0]! + a[1]! * b[1]! + a[2]! * b[2]!;

/** One round of a 32-bit integer mixer (Wellons's lowbias32 constants). */
function mix32(value: number): number {
  let h = Math.imul(value ^ (value >>> 16), 0x7feb352d);
  h = Math.imul(h ^ (h >>> 15), 0x846ca68b);
  return h ^ (h >>> 16);
}

/**
 * A 32-bit integer hash of a lattice point and a seed, as a fraction in [0, 1). The seed, x and y
 * are mixed in one after another, never combined first: combining them first let (x, y) and
 * (-x, -y) collide.
 */
export function latticeHash(x: number, y: number, seed: number): number {
  let h = mix32((seed | 0) ^ 0x2545f491);
  h = mix32(h ^ (x | 0));
  h = mix32(h ^ Math.imul(y | 0, 0x27d4eb2d));
  return (h >>> 0) / 4294967296;
}

function valueNoise(x: number, y: number, seed: number): number {
  const xi = Math.floor(x);
  const yi = Math.floor(y);
  const xf = x - xi;
  const yf = y - yi;
  const u = xf * xf * (3 - 2 * xf);
  const v = yf * yf * (3 - 2 * yf);
  const a = latticeHash(xi, yi, seed);
  const b = latticeHash(xi + 1, yi, seed);
  const c = latticeHash(xi, yi + 1, seed);
  const d = latticeHash(xi + 1, yi + 1, seed);
  return a + (b - a) * u + (c - a) * v + (a - b - c + d) * u * v;
}

/** Four octaves of value noise, each half the amplitude and about twice the frequency of the last. */
export function cloudNoise(x: number, y: number, seed: number): number {
  let total = 0;
  let amplitude = 0.5;
  let frequency = 1;
  for (let octave = 0; octave < 4; octave += 1) {
    total += amplitude * valueNoise(x * frequency, y * frequency, seed + octave * 1013);
    frequency *= 2.03;
    amplitude *= 0.5;
  }
  return total;
}

const mix = (a: Rgb, b: Rgb, t: number): Rgb => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];

/** Linear radiance of the render look's sky toward `direction` (any length; +Y up). */
export function renderSkyRadiance(look: RenderLook, direction: readonly [number, number, number], forLighting = false): Rgb {
  const length = Math.hypot(direction[0], direction[1], direction[2]);
  const dir = [direction[0] / length, direction[1] / length, direction[2] / length] as const;
  const sky = look.sky;
  const up = dir[1];
  let colour: Rgb = up >= 0
    ? mix(sky.horizon, sky.zenith, Math.pow(up, 0.55))
    : mix(sky.horizon, forLighting ? sky.bounceGround : sky.ground, Math.min(1, -up * 6));
  // Toward the sun: the light travels along sunDirection, so the sun sits at its negation.
  const travel = sunDirection(look);
  const toSun = [-travel[0], -travel[1], -travel[2]];
  const facing = Math.max(0, linearDot(dir, toSun));
  const glow = sky.sunGlow * (Math.pow(facing, 8) * 0.6 + Math.pow(facing, 64) * 1.5);
  const disc = forLighting || facing <= 0.9996 ? 0 : sky.sunDisc;
  const sun = look.sun.colour;
  colour = [colour[0] + sun[0] * (glow + disc), colour[1] + sun[1] * (glow + disc), colour[2] + sun[2] * (glow + disc)];
  const clouds = sky.clouds;
  if (clouds !== null && up > 0.02) {
    // Cloud points are projected onto a flat layer above, so clouds shrink toward the horizon.
    const reach = (clouds.scale * 2.2) / (up + 0.08);
    const px = dir[0] * reach;
    const pz = dir[2] * reach;
    const density = cloudNoise(px + 13.7, pz - 4.1, clouds.seed);
    const cover = Math.max(0, Math.min(1, (density - (1 - clouds.cover)) * 4.5));
    const fade = Math.min(1, (up - 0.02) * 8);
    const lit = 0.55 + 0.45 * Math.min(1, facing * 1.4 + cloudNoise(px * 1.7 + 3.1, pz * 1.7 + 9.2, clouds.seed + 7) * 0.5);
    const cloud = mix(clouds.shade, clouds.colour, lit);
    const alpha = cover * fade * 0.95;
    colour = [
      colour[0] * (1 - alpha) + cloud[0] * alpha * 1.15,
      colour[1] * (1 - alpha) + cloud[1] * alpha * 1.15,
      colour[2] * (1 - alpha) + cloud[2] * alpha * 1.15,
    ];
  }
  return [colour[0] * sky.intensity, colour[1] * sky.intensity, colour[2] * sky.intensity];
}

/** The six faces PlayCanvas expects, in order: +X, -X, +Y, -Y, +Z, -Z. */
export function cubeFaceDirection(face: number, u: number, v: number): readonly [number, number, number] {
  switch (face) {
    case 0: return [1, -v, -u];
    case 1: return [-1, -v, u];
    case 2: return [u, 1, v];
    case 3: return [u, -1, -v];
    case 4: return [u, -v, 1];
    default: return [-u, -v, -1];
  }
}

/** The sky's six cubemap faces, `size` texels square, as linear RGBA floats sampled at texel centres. */
export function renderSkyFaces(look: RenderLook, size: number, forLighting = false): Float32Array[] {
  const faces: Float32Array[] = [];
  for (let face = 0; face < 6; face += 1) {
    const texels = new Float32Array(size * size * 4);
    for (let row = 0; row < size; row += 1) {
      for (let column = 0; column < size; column += 1) {
        const u = ((column + 0.5) / size) * 2 - 1;
        const v = ((row + 0.5) / size) * 2 - 1;
        const radiance = renderSkyRadiance(look, cubeFaceDirection(face, u, v), forLighting);
        const at = (row * size + column) * 4;
        texels[at] = radiance[0];
        texels[at + 1] = radiance[1];
        texels[at + 2] = radiance[2];
        texels[at + 3] = 1;
      }
    }
    faces.push(texels);
  }
  return faces;
}
