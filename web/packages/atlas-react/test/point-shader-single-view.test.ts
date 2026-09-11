import { describe, expect, it } from 'vitest';
import { POINT_VERTEX_GLSL, POINT_VERTEX_WGSL } from '../src/playcanvas/point-shader.js';
import {
  SINGLE_VIEW_EDGE_MARGIN,
  SINGLE_VIEW_FADE_END_DEG,
  SINGLE_VIEW_FADE_START_DEG,
  SINGLE_VIEW_STANDPOINT_END,
  SINGLE_VIEW_STANDPOINT_START,
} from '../src/playcanvas/point-cloud.js';

/**
 * One photograph's own view, as both graphics paths draw it. The two sources are hand-written
 * twins (see the head of point-shader.ts), so the only protection against a fade landing in one
 * and not the other is a test that reads both.
 */
const UNIFORMS = ['uFrame', 'uViewpoint', 'uCapture', 'uViewFade'] as const;

describe('single-view point fading', () => {
  it('declares the same four uniforms on both graphics paths', () => {
    for (const name of UNIFORMS) {
      expect(POINT_VERTEX_GLSL).toMatch(new RegExp(`uniform vec4 ${name};`));
      expect(POINT_VERTEX_WGSL).toMatch(new RegExp(`uniform ${name} : vec4f;`));
    }
  });

  it('applies the frame, line-of-sight and standpoint fades on both paths, each behind its switch', () => {
    const glsl = POINT_VERTEX_GLSL.replace(/\s+/g, ' ');
    const wgsl = POINT_VERTEX_WGSL.replace(/\s+/g, ' ').replace(/uniform\./g, '');
    for (const source of [glsl, wgsl]) {
      expect(source).toContain('if (uFrame.w > 0.5)');
      expect(source).toContain('smoothstep(0.0, uFrame.z, 1.0 - edge)');
      expect(source).toContain('if (uCapture.w > 0.5)');
      expect(source).toMatch(/smoothstep\(uViewFade\.y, uViewFade\.x, (along|dot\(fromCamera, fromViewer\))\)/);
      expect(source).toMatch(/1\.0 - smoothstep\(uViewFade\.z, uViewFade\.w, length\(view_position - uCapture\.xyz\)\)/);
    }
    // The GLSL surface variant's seams: bit 1 of the flags word, faded far sooner than a surface.
    expect(glsl).toContain('if (mod(floor(aTags.y / 2.0), 2.0) > 0.5) survive *= smoothstep(uSeamFade.y, uSeamFade.x, along);');
  });

  it('fades over the ranges the renderer documents', () => {
    expect(SINGLE_VIEW_EDGE_MARGIN).toBeGreaterThan(0);
    expect(SINGLE_VIEW_EDGE_MARGIN).toBeLessThan(0.5);
    expect(SINGLE_VIEW_FADE_START_DEG).toBeLessThan(SINGLE_VIEW_FADE_END_DEG);
    expect(SINGLE_VIEW_FADE_END_DEG).toBeLessThan(90);
    expect(SINGLE_VIEW_STANDPOINT_START).toBeLessThan(SINGLE_VIEW_STANDPOINT_END);
  });
});
