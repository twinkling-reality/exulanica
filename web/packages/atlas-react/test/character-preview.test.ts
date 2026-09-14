import { describe, expect, it } from 'vitest';
import { characterInspectionFrame } from '../src/playcanvas/character-preview.js';

function screenY(height: number, zoom = 1): number {
  const frame = characterInspectionFrame(zoom);
  const distance = frame.position[2];
  const cameraAngle = Math.atan2(frame.target[1] - frame.position[1], distance);
  const pointAngle = Math.atan2(height - frame.position[1], distance);
  return Math.tan(pointAngle - cameraAngle) / Math.tan(frame.verticalFovDegrees * Math.PI / 360);
}
describe('metric character inspection stage', () => {
  it('shows supported heights at different extents with one frame and no default clipping', () => {
    const frame = characterInspectionFrame(1);
    expect(frame).toEqual(characterInspectionFrame(1));
    const small = screenY(1.45) - screenY(0);
    const large = screenY(2.05) - screenY(0);
    expect(large / small).toBeGreaterThan(1.39);
    for (const height of [0, 1.45, 2.05]) expect(Math.abs(screenY(height))).toBeLessThan(1);
  });
  it('keeps a user-selected zoom independent of generated body height', () => {
    const selected = characterInspectionFrame(1.15);
    expect(selected).toEqual(characterInspectionFrame(1.15));
    expect(selected).not.toEqual(characterInspectionFrame(1));
  });
  it('lifts the inspection target for a close face view', () => {
    const body = characterInspectionFrame(1);
    const face = characterInspectionFrame(1.7);
    expect(face.target[1]).toBeGreaterThan(body.target[1] + .3);
    expect(face.position[1] - face.target[1]).toBeCloseTo(body.position[1] - body.target[1]);
  });
});
