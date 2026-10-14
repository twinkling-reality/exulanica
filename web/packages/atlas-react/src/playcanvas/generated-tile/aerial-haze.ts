import * as pc from 'playcanvas';
import type { RenderHaze, Rgb } from './look.js';

/*
 * Haze that thins with height, for a render look that states it.
 *
 * Exponential height fog integrated along each view ray: a valley far away fades into the haze
 * while a ridge high above it stays a silhouette, which a distance-only fog cannot do. Looking toward
 * the sun the haze turns toward the sun's colour. It is mixed in linear light before tone mapping,
 * as the engine's own fog is, and the look's fog is switched off while it draws.
 *
 * It replaces the lit end chunk for every lit material on the device, inserting one block before
 * tone mapping into whatever end chunk the device holds, and guards that block with a uniform: while
 * no look states haze the block is skipped and the end chunk computes exactly what it did. A program
 * built before the chunk was installed keeps the old one (see `installDisplaySpaceFog` in
 * `atmosphere.ts`), so a material compiled before a hazy world opened draws without haze.
 *
 * GLSL only: on a WebGPU device nothing is installed and the look's fog is drawn instead.
 */

const HAZE_DECLARATIONS = `
uniform vec4 exuHaze;        // x density at the base, y falloff, z base height, w optical depth cap (0: off)
uniform vec3 exuHazeColour;  // linear, away from the sun
uniform vec3 exuHazeSun;     // linear, toward the sun
uniform vec3 exuHazeSunDir;  // toward the sun
`;

const HAZE_BLOCK = `
    if (exuHaze.w > 0.0) {
        vec3 hazeRay = vPositionW - view_position;
        float hazeDistance = length(hazeRay);
        vec3 hazeDir = hazeRay / max(hazeDistance, 1e-4);
        float hazeRy = abs(hazeDir.y) < 1e-3 ? (hazeDir.y < 0.0 ? -1e-3 : 1e-3) : hazeDir.y;
        float hazeDepth = (exuHaze.x / exuHaze.y) * exp(-(view_position.y - exuHaze.z) * exuHaze.y)
            * (1.0 - exp(-hazeDistance * hazeRy * exuHaze.y)) / hazeRy;
        hazeDepth = clamp(hazeDepth, 0.0, exuHaze.w);
        float hazeSun = pow(max(dot(hazeDir, exuHazeSunDir), 0.0), 6.0);
        gl_FragColor.rgb = mix(mix(exuHazeColour, exuHazeSun, hazeSun), gl_FragColor.rgb, exp(-hazeDepth));
    }
`;

const TONE_MAP_LINE = 'gl_FragColor.rgb = toneMap(';

/** The end chunk with the haze block before tone mapping, or null when it has no tone mapping line. */
export function hazeEndChunk(end: string): string | null {
  const at = end.indexOf(TONE_MAP_LINE);
  return at < 0 ? null : end.slice(0, at) + HAZE_BLOCK + '    ' + end.slice(at);
}

const installed = new WeakSet<pc.GraphicsDevice>();

/**
 * Put the guarded haze block into the device's end chunk, once. Returns false when it cannot
 * (a WebGPU device, or an end chunk with no tone mapping line), and the look's fog then stays.
 */
export function installAerialHaze(device: pc.GraphicsDevice): boolean {
  if (installed.has(device)) return true;
  if (device.isWebGPU) return false;
  const chunks = pc.ShaderChunks.get(device, pc.SHADERLANGUAGE_GLSL);
  const end = hazeEndChunk(chunks.get('endPS') as string);
  if (end === null) return false;
  chunks.set('endPS', end);
  chunks.set('fogPS', (chunks.get('fogPS') as string) + HAZE_DECLARATIONS);
  installed.add(device);
  return true;
}

/** Linear colour of the haze toward the sun: the sun's own, never darker than the haze. */
function sunward(haze: Rgb, sun: Rgb): Rgb {
  return [Math.max(sun[0] * 0.9, haze[0]), Math.max(sun[1] * 0.9, haze[1]), Math.max(sun[2] * 0.9, haze[2])];
}

/** Aim the haze: on with the look's values, or off (null) so the end chunk computes as before. */
export function setAerialHaze(
  device: pc.GraphicsDevice,
  haze: RenderHaze | null,
  horizon: Rgb,
  sunColour: Rgb,
  towardSun: readonly [number, number, number],
): void {
  const scope = device.scope;
  if (haze === null) {
    scope.resolve('exuHaze').setValue([0, 1, 0, 0]);
    return;
  }
  const colour = haze.colour ?? horizon;
  scope.resolve('exuHaze').setValue([haze.density, haze.falloff, haze.baseM, haze.maxDepth]);
  scope.resolve('exuHazeColour').setValue([...colour]);
  scope.resolve('exuHazeSun').setValue([...sunward(colour, sunColour)]);
  scope.resolve('exuHazeSunDir').setValue([...towardSun]);
}
