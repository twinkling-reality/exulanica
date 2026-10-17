import { sunDirection, type RenderLook, type RenderSkyModel, type Rgb } from './look.js';

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

const unit = (d: readonly [number, number, number]): readonly [number, number, number] => {
  const length = Math.hypot(d[0], d[1], d[2]);
  return [d[0] / length, d[1] / length, d[2] / length];
};

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

/*
 * THE ANALYTIC SKY. Preetham, Shirley and Smits, "A Practical Analytic Model for Daylight"
 * (SIGGRAPH 1999): Rayleigh and Mie in-scattering of one sun along an optical path that lengthens
 * toward the horizon. The constants and the way the terms are combined follow the three.js `Sky`
 * shader (MIT, three.js authors: Simon Wallner, Martin Upitis, Joshua Koo), as read in PlayCanvas's
 * port `scripts/esm/sky/procedural-sky.mjs` (MIT); see THIRD_PARTY_NOTICES.md. It is evaluated here
 * on the CPU into the same cube faces as the gradient, so the engine needs no script for it.
 */
const TOTAL_RAYLEIGH: Rgb = [5.804542996261093e-6, 1.3562911419845635e-5, 3.0265902468824876e-5];
const MIE_CONST: Rgb = [1.8399918514433978e14, 2.7798023919660528e14, 4.0790479543861094e14];
const SUN_EE = 1000;
const SUN_CUTOFF = 1.6110731556870734;
const SUN_STEEPNESS = 1.5;
const RAYLEIGH_ZENITH_M = 8400;
const MIE_ZENITH_M = 1250;

/** Linear radiance of the analytic sky toward a unit `dir` at or above the horizon, with no sun disc. */
export function analyticSkyRadiance(model: RenderSkyModel, toSun: readonly [number, number, number], dir: readonly [number, number, number]): Rgb {
  const sunY = toSun[1];
  const fade = 1 - Math.min(Math.max(1 - Math.exp(sunY), 0), 1);
  const rayleigh = model.rayleigh - (1 - fade);
  const mie = 0.434 * (0.2 * model.turbidity * 1e-18) * model.mie;
  const sunE = SUN_EE * Math.max(0, 1 - Math.exp(-((SUN_CUTOFF - Math.acos(Math.max(-1, Math.min(1, sunY)))) / SUN_STEEPNESS)));
  const zenith = Math.acos(Math.max(0, dir[1]));
  const denominator = Math.cos(zenith) + 0.15 * Math.pow(Math.max(93.885 - (zenith * 180) / Math.PI, 0), -1.253);
  const pathRayleigh = RAYLEIGH_ZENITH_M / denominator;
  const pathMie = MIE_ZENITH_M / denominator;
  const cosTheta = linearDot(dir, toSun);
  const rayleighPhase = (3 / (16 * Math.PI)) * (1 + Math.pow(cosTheta * 0.5 + 0.5, 2));
  const g = model.mieDirection;
  const miePhase = (1 / (4 * Math.PI)) * ((1 - g * g) / Math.pow(Math.max(1 - 2 * g * cosTheta + g * g, 0), 1.5));
  const towardHorizon = Math.min(Math.max(Math.pow(1 - sunY, 5), 0), 1);
  const out: [number, number, number] = [0, 0, 0];
  for (let channel = 0; channel < 3; channel += 1) {
    const betaR = TOTAL_RAYLEIGH[channel]! * rayleigh;
    const betaM = MIE_CONST[channel]! * mie;
    const extinction = Math.exp(-(betaR * pathRayleigh + betaM * pathMie));
    const share = (betaR * rayleighPhase + betaM * miePhase) / (betaR + betaM);
    let inScatter = Math.pow(sunE * share * (1 - extinction), 1.5);
    inScatter *= 1 + (Math.pow(sunE * share * extinction, 0.5) - 1) * towardHorizon;
    out[channel] = (inScatter + 0.1 * extinction) * 0.04 + [0, 0.0003, 0.00075][channel]!;
  }
  return out;
}

/** The cosine of the sun disc's angular radius: the disc is every direction within it of the sun. */
export const SUN_DISC_COS = 0.9996;

/** The share of the sky the look's clouds cover toward a unit `dir`, 0 to 0.95. */
function cloudAlpha(clouds: NonNullable<RenderLook['sky']['clouds']>, dir: readonly [number, number, number]): number {
  const up = dir[1];
  if (up <= 0.02) return 0;
  // Cloud points are projected onto a flat layer above, so clouds shrink toward the horizon.
  const reach = (clouds.scale * 2.2) / (up + 0.08);
  const density = cloudNoise(dir[0] * reach + 13.7, dir[2] * reach - 4.1, clouds.seed);
  const cover = Math.max(0, Math.min(1, (density - (1 - clouds.cover)) * 4.5));
  return cover * Math.min(1, (up - 0.02) * 8) * 0.95;
}

/**
 * Linear radiance of the render look's sky toward `direction` (any length; +Y up). With `disc`
 * false the sun's disc is left out, for a sky whose disc is drawn by its shader (`sun-disc.ts`).
 */
export function renderSkyRadiance(look: RenderLook, direction: readonly [number, number, number], forLighting = false, disc = true): Rgb {
  const length = Math.hypot(direction[0], direction[1], direction[2]);
  const dir = [direction[0] / length, direction[1] / length, direction[2] / length] as const;
  const sky = look.sky;
  const up = dir[1];
  // Toward the sun: the light travels along sunDirection, so the sun sits at its negation.
  const travel = sunDirection(look);
  const toSun = [-travel[0], -travel[1], -travel[2]] as const;
  let colour: Rgb;
  if (sky.model === undefined) {
    colour = up >= 0
      ? mix(sky.horizon, sky.zenith, Math.pow(up, 0.55))
      : mix(sky.horizon, forLighting ? sky.bounceGround : sky.ground, Math.min(1, -up * 6));
  } else {
    // Below the horizon the analytic horizon gives way to the ground, as the gradient's does.
    const flat = Math.hypot(dir[0], dir[2]) || 1;
    const above = up >= 0 ? dir : ([dir[0] / flat, 0, dir[2] / flat] as const);
    const analytic = analyticSkyRadiance(sky.model, toSun, above);
    colour = up >= 0 ? analytic : mix(analytic, forLighting ? sky.bounceGround : sky.ground, Math.min(1, -up * 6));
  }
  const facing = Math.max(0, linearDot(dir, toSun));
  const glow = sky.sunGlow * (Math.pow(facing, 8) * 0.6 + Math.pow(facing, 64) * 1.5);
  const sunDisc = forLighting || !disc || facing <= SUN_DISC_COS ? 0 : sky.sunDisc;
  const sun = look.sun.colour;
  colour = [colour[0] + sun[0] * (glow + sunDisc), colour[1] + sun[1] * (glow + sunDisc), colour[2] + sun[2] * (glow + sunDisc)];
  const clouds = sky.clouds;
  if (clouds !== null && up > 0.02) {
    const reach = (clouds.scale * 2.2) / (up + 0.08);
    const px = dir[0] * reach;
    const pz = dir[2] * reach;
    const lit = 0.55 + 0.45 * Math.min(1, facing * 1.4 + cloudNoise(px * 1.7 + 3.1, pz * 1.7 + 9.2, clouds.seed + 7) * 0.5);
    const cloud = mix(clouds.shade, clouds.colour, lit);
    const alpha = cloudAlpha(clouds, dir);
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

/**
 * The linear radiance of the sun's disc as the baked sky would draw it, behind whatever cloud the
 * sky draws in front of the sun: for a shader that draws the disc itself (`sun-disc.ts`).
 */
export function sunDiscRadiance(look: RenderLook): Rgb {
  const travel = sunDirection(look);
  const toSun = [-travel[0], -travel[1], -travel[2]] as const;
  const clear = look.sky.clouds === null ? 1 : 1 - cloudAlpha(look.sky.clouds, toSun);
  const k = look.sky.sunDisc * look.sky.intensity * clear;
  const sun = look.sun.colour;
  return [sun[0] * k, sun[1] * k, sun[2] * k];
}

/**
 * The world direction a cubemap texel shows. The engine's sky and image light read a cubemap with
 * x negated (`dir.x *= -1.0` in its skybox chunk, and the same in its image light), so a texel at
 * cube direction (x, y, z) is seen toward world (-x, y, z).
 */
export function cubeTexelWorldDirection(face: number, u: number, v: number): readonly [number, number, number] {
  const d = cubeFaceDirection(face, u, v);
  return [-d[0], d[1], d[2]];
}

/**
 * The share of the sky left clear of the look's clouds toward a unit `dir`, 0 to 1: how much of a star
 * shows there (`sun-disc.ts` reads it from the drawn sky's alpha). Below the horizon no cloud is drawn.
 */
export function skyClearShare(look: RenderLook, dir: readonly [number, number, number]): number {
  return look.sky.clouds === null ? 1 : 1 - cloudAlpha(look.sky.clouds, dir);
}

/**
 * The sky's six cubemap faces, `size` texels square, as linear RGBA floats sampled at texel centres.
 * Alpha is 1, except in the drawn sky (not the image light's) of a look with stars, where it is the
 * share of the sky its clouds leave clear, so the shader draws the stars behind them.
 */
export function renderSkyFaces(look: RenderLook, size: number, forLighting = false, disc = true): Float32Array[] {
  const clearShare = !forLighting && look.sky.stars !== undefined;
  const faces: Float32Array[] = [];
  for (let face = 0; face < 6; face += 1) {
    const texels = new Float32Array(size * size * 4);
    for (let row = 0; row < size; row += 1) {
      for (let column = 0; column < size; column += 1) {
        const u = ((column + 0.5) / size) * 2 - 1;
        const v = ((row + 0.5) / size) * 2 - 1;
        const direction = cubeTexelWorldDirection(face, u, v);
        const radiance = renderSkyRadiance(look, direction, forLighting, disc);
        const at = (row * size + column) * 4;
        texels[at] = radiance[0];
        texels[at + 1] = radiance[1];
        texels[at + 2] = radiance[2];
        texels[at + 3] = clearShare ? skyClearShare(look, unit(direction)) : 1;
      }
    }
    faces.push(texels);
  }
  return faces;
}
