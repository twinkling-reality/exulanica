import * as pc from 'playcanvas';
import type { Rgb } from './look.js';
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
 * GLSL only: on a WebGPU device nothing is installed and the faces keep their baked disc.
 */

const DECLARATIONS = `
uniform vec4 exuSunDisc;        // xyz toward the sun, w the cosine of the disc's radius (0: off)
uniform vec3 exuSunDiscColour;  // linear radiance of the disc
`;

// Both of the chunk's sampling branches flip x before sampling (`dir.x *= -1.0` for a cubemap),
// so the world direction is the flip undone.
const BLOCK = `
            if (exuSunDisc.w > 0.0) {
                float discCos = dot(normalize(dir * vec3(-1.0, 1.0, 1.0)), exuSunDisc.xyz);
                float discEdge = max(fwidth(discCos), 1e-7);
                linear += exuSunDiscColour * smoothstep(exuSunDisc.w - discEdge, exuSunDisc.w + discEdge, discCos);
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
  return skybox.slice(0, main) + DECLARATIONS + skybox.slice(main, at) + BLOCK.trimStart() + '            ' + skybox.slice(at);
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
