import { describe, expect, it } from 'vitest';
import {
  POINT_FRAGMENT_GLSL,
  POINT_FRAGMENT_WGSL,
  POINT_VERTEX_GLSL,
  POINT_VERTEX_WGSL,
} from '../src/playcanvas/point-shader.js';
import { RELIEF_PARALLAX_DEG, SINGLE_VIEW_EDGE_MARGIN } from '../src/playcanvas/point-cloud.js';
import { reliefFor } from '../src/playcanvas/atlas-binding.js';

/**
 * One photograph's own view, as both graphics paths draw it. The two sources are hand-written
 * twins (see the head of point-shader.ts), so the only protection against the relief flattening in
 * one and not the other is a test that reads both.
 */
const UNIFORMS = ['uFrame', 'uViewpoint', 'uCapture', 'uRelief'] as const;
/** Flattening in inverse depth, which is what makes the parallax left over linear in `uRelief.y`. */
const FLATTEN = 'fromEye / mix(1.0, max(-fromEye.z, 0.001) / uRelief.x, uRelief.y)';

describe('single-view relief', () => {
  it('declares the same four uniforms on both graphics paths', () => {
    for (const name of UNIFORMS) {
      expect(POINT_VERTEX_GLSL).toMatch(new RegExp(`uniform vec4 ${name};`));
      expect(POINT_VERTEX_WGSL).toMatch(new RegExp(`uniform ${name} : vec4f;`));
    }
    expect(POINT_FRAGMENT_GLSL).toMatch(/uniform vec4 uRelief;/);
    expect(POINT_FRAGMENT_WGSL).toMatch(/uniform uRelief : vec4f;/);
  });

  it('flattens along the camera rays and keeps the frame on both paths, each behind its switch', () => {
    const glsl = POINT_VERTEX_GLSL.replace(/\s+/g, ' ');
    const wgsl = POINT_VERTEX_WGSL.replace(/\s+/g, ' ').replace(/uniform\./g, '');
    for (const source of [glsl, wgsl]) {
      expect(source).toContain('if (uFrame.w > 0.5)');
      expect(source).toContain('smoothstep(0.0, uFrame.z, 1.0 - edge)');
      expect(source).toContain('if (uCapture.w > 0.5)');
      expect(source).toContain(FLATTEN);
      // Nothing dissolves with angle or distance any more: the operator saw photographs vanish,
      // and nothing drops a seam either, because flattening bounds how far one can stretch.
      expect(source).not.toContain('uViewFade');
      expect(source).not.toContain('uSeamFade');
    }
  });

  it('paints the back of the print one card colour, with nothing per point left on it', () => {
    expect(POINT_FRAGMENT_GLSL).toContain('const vec3 PRINT_BACK = vec3(0.62, 0.60, 0.56);');
    expect(POINT_FRAGMENT_GLSL).toContain('if (uRelief.z > 0.5) {');
    expect(POINT_FRAGMENT_GLSL).toContain('rgb = mix(PRINT_BACK * uExposure, uFogColor, vFogAmount);');
    expect(POINT_FRAGMENT_WGSL).toContain('if (uniform.uRelief.z > 0.5) {');
    expect(POINT_FRAGMENT_WGSL).toContain(
      'rgb = mix(vec3f(0.62, 0.60, 0.56) * uniform.uExposure, uniform.uFogColor, input.vFogAmount);');
    // Nothing that varies per point may reach the back: it is a card, not evidence.
    for (const source of [POINT_FRAGMENT_GLSL, POINT_FRAGMENT_WGSL]) {
      const back = source.slice(source.indexOf('uRelief.z > 0.5'), source.indexOf('} else {'));
      for (const perPoint of ['vColor', 'vSemantic', 'tint', 'breathe', 'uPhotograph']) {
        expect(back).not.toContain(perPoint);
      }
    }
  });

  it('bounds the parallax over a range the renderer documents', () => {
    expect(SINGLE_VIEW_EDGE_MARGIN).toBeGreaterThan(0);
    expect(SINGLE_VIEW_EDGE_MARGIN).toBeLessThan(0.5);
    expect(RELIEF_PARALLAX_DEG).toBeGreaterThan(0);
    expect(RELIEF_PARALLAX_DEG).toBeLessThan(10);
  });
});

describe('reliefFor', () => {
  // A camera at the origin looking down -z at a print 4 m away, with a photograph whose nearest
  // sample is 2 m out and whose furthest is far enough away to contribute nothing.
  const camera = { x: 0, y: 0, z: 0 };
  const print = { x: 0, y: 0, z: -4 };
  const perUnit = 1 / 2 - 1 / 200;
  const limit = (RELIEF_PARALLAX_DEG * Math.PI) / 180;
  const at = (degrees: number, distance: number) => {
    const a = (degrees * Math.PI) / 180;
    return { x: Math.sin(a) * distance, y: 0, z: -4 + Math.cos(a) * distance };
  };

  it('keeps the full relief while the parallax stays within the limit', () => {
    const reach = limit / perUnit;
    expect(reliefFor(camera, print, { x: 0, y: 0, z: -reach * 0.99 }, perUnit))
      .toEqual({ flatten: 0, behind: false });
    expect(reliefFor(camera, print, { x: reach * 0.5, y: 0, z: 0 }, perUnit).flatten).toBe(0);
  });

  it('flattens exactly enough to hold the parallax at the limit, from any direction', () => {
    for (const viewer of [at(0, 12), at(20, 6), at(80, 3), { x: 0.4, y: 0.3, z: -3 }]) {
      const { flatten, behind } = reliefFor(camera, print, viewer, perUnit);
      expect(behind).toBe(false);
      const distance = Math.hypot(viewer.x - camera.x, viewer.y - camera.y, viewer.z - camera.z);
      expect(distance * perUnit * (1 - flatten)).toBeCloseTo(limit, 9);
    }
  });

  it('is a flat print with no parallax at all from far away', () => {
    expect(reliefFor(camera, print, at(0, 400), perUnit).flatten).toBeGreaterThan(0.999);
  });

  it('is the back of the print from anywhere beyond its plane', () => {
    for (const degrees of [100, 135, 180]) {
      expect(reliefFor(camera, print, at(degrees, 6), perUnit)).toEqual({ flatten: 1, behind: true });
    }
  });
});
