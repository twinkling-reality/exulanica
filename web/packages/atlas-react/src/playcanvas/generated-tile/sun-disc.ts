import * as pc from 'playcanvas';
import type { RenderMoon, RenderStars, Rgb } from './look.js';
import { SUN_DISC_COS } from './sky.js';

/*
 * The sun's disc, drawn by the sky's own shader instead of baked into the sky's faces.
 *
 * A render look's sky is baked into a cubemap of 128 or 256 texels a face, where a disc of about
 * 1.6 degrees covers two or three texels and reads as a pixelated blob. Drawn in the shader, the disc
 * is a smooth circle at any screen size: the same direction, angular radius and radiance the faces
 * drew (`SUN_DISC_COS`, `sunDiscRadiance`), behind the same cloud, with an edge one pixel wide. The
 * faces are then baked without it (`renderSkyFaces(..., disc false)`).
 *
 * It inserts one guarded block into the device's skybox chunk, after the sky's colour is sampled and
 * before its intensity and tone mapping, as `aerial-haze.ts` does for the lit end chunk: while no look
 * states a disc the block is skipped and the chunk computes exactly what it did. The skybox shader is
 * built when the sky is first drawn, after the environment installs this. The sky is drawn in world
 * axes (no skybox rotation is set anywhere), which the block relies on.
 *
 * The same block draws what a look states of the night (`sky.stars`, `sky.moon`). The disc becomes a
 * moon with darker seas and a limb a little darker than its middle, worked out only inside the disc.
 * Stars are points a pixel wide, one at most in each cell of a grid of `STAR_CELLS` a cube face, placed
 * in the middle half of its cell. A star's size is the angle from it to the pixel, so it is the same at
 * a face's middle, its edges and its corners, and each pixel draws the stars of its own cell and the
 * three round its nearest corner, so a star is drawn whole where a cell is only a few pixels across.
 * A star keeps its light for its share of the sky at any picture size: where a pixel spans more of
 * the sky than a full-size view's (`STAR_FULL_PIXEL`) it is drawn dimmer, never bigger, so a small
 * picture shows the stars a large one does, shrunk, and not a sky of snow.
 * They are behind the clouds by the share of the sky they leave clear (the drawn sky's alpha,
 * `renderSkyFaces`) and fade out over the lowest 7 degrees. Their hashes are integer only, so the same
 * seed draws the same stars on every GPU. A look that states neither skips both branches.
 *
 * GLSL only: on a WebGPU device nothing is installed and the faces keep their baked disc.
 */

/** Cells along a cube face's edge for the stars: about 0.7 degrees each, ten pixels at a 70 degree view a thousand high. */
export const STAR_CELLS = 128;

/**
 * The pixel a star is drawn at full brightness on, in radians: one of a view 1,080 pixels high with a
 * 70 degree field, the workspace's own. A pixel spanning more of the sky draws each star dimmer by the
 * square of the ratio, the light the same star gives over the same share of the sky.
 */
export const STAR_FULL_PIXEL = (2 * Math.tan((35 * Math.PI) / 180)) / 1080;

export const SKY_DECLARATIONS = `
uniform vec4 exuSunDisc;        // xyz toward the sun, w the cosine of the disc's radius (0: off)
uniform vec3 exuSunDiscColour;  // linear radiance of the disc
uniform vec4 exuMoon;           // x how much darker its seas, y the seed, z 1 to draw the disc as a moon (0: off)
uniform vec4 exuStars;          // x the share of cells with a star, y the brightest one's radiance, z the seed, w 1 to draw (0: off)
const float EXU_STAR_CELLS = ${STAR_CELLS.toFixed(1)};
const float EXU_STAR_PIXEL = ${(Math.SQRT2 * STAR_FULL_PIXEL).toExponential(8)}; // STAR_FULL_PIXEL as the block's pixel angle measures it

uint exuHash(uint v) {
    v ^= v >> 16u; v *= 0x7feb352du;
    v ^= v >> 15u; v *= 0x846ca68bu;
    return v ^ (v >> 16u);
}
float exuUnit(uint v) { return float(v >> 8u) / 16777216.0; }
float exuLattice(ivec2 at, uint seed) { return exuUnit(exuHash(uint(at.x) * 0x8da6b343u ^ exuHash(uint(at.y) * 0xd8163841u ^ seed))); }
float exuNoise(vec2 p, uint seed) {
    ivec2 at = ivec2(floor(p));
    vec2 f = fract(p);
    vec2 w = f * f * (3.0 - 2.0 * f);
    float a = exuLattice(at, seed), b = exuLattice(at + ivec2(1, 0), seed);
    float c = exuLattice(at + ivec2(0, 1), seed), d = exuLattice(at + ivec2(1, 1), seed);
    return mix(mix(a, b, w.x), mix(c, d, w.x), w.y);
}
// The moon's face toward unit d: its limb a little darker, its seas darker by exuMoon.x.
float exuMoonFace(vec3 d) {
    vec3 c = exuSunDisc.xyz;
    float radius = sqrt(max(2.0 * (1.0 - exuSunDisc.w), 1e-12));
    vec3 side = normalize(cross(abs(c.y) < 0.99 ? vec3(0.0, 1.0, 0.0) : vec3(1.0, 0.0, 0.0), c));
    vec2 p = vec2(dot(d, side), dot(d, cross(c, side))) / radius;
    float limb = 0.72 + 0.28 * sqrt(1.0 - min(dot(p, p), 1.0));
    uint seed = uint(exuMoon.y);
    float seas = smoothstep(0.5, 0.64, 0.6 * exuNoise(p * 2.2 + 7.0, seed) + 0.4 * exuNoise(p * 5.0 - 3.0, seed + 1u));
    return limb * (1.0 - exuMoon.x * seas);
}
`;

// Both of the chunk's sampling branches flip x before sampling (`dir.x *= -1.0` for a cubemap),
// so the world direction is the flip undone.
export const SKY_BLOCK = `
            vec3 exuDir = normalize(dir * vec3(-1.0, 1.0, 1.0));
            if (exuSunDisc.w > 0.0) {
                float discCos = dot(exuDir, exuSunDisc.xyz);
                float discEdge = max(fwidth(discCos), 1e-7);
                float inDisc = smoothstep(exuSunDisc.w - discEdge, exuSunDisc.w + discEdge, discCos);
                // The moon's face is worked out only where its disc is drawn.
                if (inDisc > 0.0) linear += exuSunDiscColour * (exuMoon.z > 0.0 ? exuMoonFace(exuDir) : 1.0) * inDisc;
            }
            if (exuStars.w > 0.0) {
                // A pixel's angle, taken before any branch a pixel decides for itself: its two screen steps, as
                // the length of fwidth gives it for a view along the sky's axes, but the same at any heading.
                float pixelAngle = max(0.70710678 * (length(dFdx(exuDir)) + length(dFdy(exuDir))), 1e-6);
                // A star's light for its share of the sky: dimmer where a pixel spans more than a full-size view's.
                float starLight = min(1.0, (EXU_STAR_PIXEL / pixelAngle) * (EXU_STAR_PIXEL / pixelAngle));
                #ifdef SKY_CUBEMAP
                    float clearShare = textureCube(texture_cubeMap, dir).a;
                #else
                    float clearShare = 1.0;
                #endif
                vec3 a = abs(exuDir);
                float major;
                vec2 across;
                uint face;
                if (a.x >= a.y && a.x >= a.z) { major = a.x; across = exuDir.yz; face = exuDir.x > 0.0 ? 0u : 1u; }
                else if (a.y >= a.z) { major = a.y; across = exuDir.xz; face = exuDir.y > 0.0 ? 2u : 3u; }
                else { major = a.z; across = exuDir.xy; face = exuDir.z > 0.0 ? 4u : 5u; }
                vec2 grid = (across / major * 0.5 + 0.5) * EXU_STAR_CELLS;
                vec2 cell = floor(grid);
                // The pixel's own cell and the three round the corner it is nearest, so a star wider than its
                // cell's margin is drawn whole where a cell is only a few pixels across.
                vec2 toward = vec2(grid.x - cell.x < 0.5 ? -1.0 : 1.0, grid.y - cell.y < 0.5 ? -1.0 : 1.0);
                float side = (face & 1u) == 0u ? 1.0 : -1.0;
                if (exuDir.y > 0.0) {
                    for (int k = 0; k < 4; k++) {
                        vec2 near = cell + toward * vec2(float(k & 1), float(k >> 1));
                        if (any(lessThan(near, vec2(0.0))) || any(greaterThanEqual(near, vec2(EXU_STAR_CELLS)))) continue;
                        uint h = exuHash(face * 0x9e3779b9u ^ exuHash(uint(near.x) * 0x85ebca6bu ^ exuHash(uint(near.y) * 0xc2b2ae35u ^ uint(exuStars.z))));
                        if (exuUnit(h) >= exuStars.x) continue;
                        uint h2 = exuHash(h);
                        uint h3 = exuHash(h2 ^ 0x68e31da4u);
                        vec2 at = near + 0.25 + 0.5 * vec2(exuUnit(h2), exuUnit(exuHash(h2)));
                        // The star's own direction, from its point on the face as the grid was taken from the
                        // pixel's: its distance is an angle, so a star keeps its size across the face.
                        vec2 onFace = (at / EXU_STAR_CELLS - 0.5) * 2.0;
                        vec3 star = face < 2u ? vec3(side, onFace) : face < 4u ? vec3(onFace.x, side, onFace.y) : vec3(onFace, side);
                        float pixels = length(exuDir - normalize(star)) / pixelAngle;
                        float brightness = 0.08 + 0.92 * pow(exuUnit(h3), 6.0);
                        vec3 tint = mix(vec3(1.0, 0.86, 0.72), vec3(0.78, 0.86, 1.0), exuUnit(exuHash(h3)));
                        linear += exuStars.y * starLight * brightness * tint * exp(-pixels * pixels * 1.6) * clearShare * smoothstep(0.0, 0.12, exuDir.y);
                    }
                }
            }
`;

const ANCHOR = 'if (any(greaterThanEqual(linear, vec3(64.0)))) {';
const MAIN = 'void main(void) {';
const FLIP = 'dir.x *= -1.0;';

/** The skybox chunk with the disc block, or null when the chunk is not the one this was written for. */
export function sunDiscSkyChunk(skybox: string): string | null {
  const at = skybox.indexOf(ANCHOR);
  const main = skybox.indexOf(MAIN);
  if (at < 0 || main < 0 || main > at || skybox.indexOf(FLIP) < 0 || skybox.indexOf(FLIP) > at) return null;
  return skybox.slice(0, main) + SKY_DECLARATIONS + skybox.slice(main, at) + SKY_BLOCK.trimStart() + '            ' + skybox.slice(at);
}

const installed = new WeakSet<pc.GraphicsDevice>();

/** Put the guarded disc block into the device's skybox chunk, once; false when it cannot. */
export function installSunDisc(device: pc.GraphicsDevice): boolean {
  if (installed.has(device)) return true;
  if (device.isWebGPU) return false;
  const chunks = pc.ShaderChunks.get(device, pc.SHADERLANGUAGE_GLSL);
  const sky = sunDiscSkyChunk(chunks.get('skyboxPS') as string);
  if (sky === null) return false;
  chunks.set('skyboxPS', sky);
  installed.add(device);
  return true;
}

/** Draw the disc toward `toSun` (a unit vector) at `radiance`, or none (null). */
export function setSunDisc(device: pc.GraphicsDevice, toSun: readonly [number, number, number] | null, radiance: Rgb): void {
  const scope = device.scope;
  if (toSun === null) {
    scope.resolve('exuSunDisc').setValue([0, 1, 0, 0]);
    return;
  }
  scope.resolve('exuSunDisc').setValue([toSun[0], toSun[1], toSun[2], SUN_DISC_COS]);
  scope.resolve('exuSunDiscColour').setValue([radiance[0], radiance[1], radiance[2]]);
}

/**
 * Draw what `sky` states of the night: its stars (their radiance scaled by the sky's own intensity, as
 * the disc's is) and its disc as a moon; neither for a sky that states none, or for null. A seed is
 * taken below 2^24, where a float uniform holds it exactly.
 */
export function setSkyMarks(device: pc.GraphicsDevice, sky: { readonly intensity: number; readonly stars?: RenderStars; readonly moon?: RenderMoon } | null): void {
  const scope = device.scope;
  const stars = sky?.stars;
  scope.resolve('exuStars').setValue(stars === undefined || sky === null ? [0, 0, 0, 0] : [stars.density, stars.intensity * sky.intensity, stars.seed % 16_777_216, 1]);
  const moon = sky?.moon;
  scope.resolve('exuMoon').setValue(moon === undefined ? [0, 0, 0, 0] : [moon.maria, moon.seed % 16_777_216, 1, 0]);
}
