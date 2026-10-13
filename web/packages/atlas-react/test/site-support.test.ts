// @vitest-environment happy-dom
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { canonicalJson } from '@exulanica/atlas-core';
import { sha256Hex } from '../src/playcanvas/character/digest.js';
import { parseStructuredSiteDrawing } from '../src/playcanvas/generated-site/site-drawing.js';
import { siteNavigationWorld, siteStart } from '../src/playcanvas/generated-site/site-navigation.js';
import { FirstPersonControls } from '../src/playcanvas/controls.js';
const fixture = JSON.parse(readFileSync('packages/atlas-react/test/fixtures/site-support.v2.json', 'utf8'));
describe('saved support drawing and person controls', () => {
  it('draws exact canonical support top planes and binds the declared person envelope', () => {
    const d = parseStructuredSiteDrawing(fixture.drawing), w = siteNavigationWorld(d);
    expect(w.support?.document.actor).toEqual({ radius_mm: 340, height_mm: 1800, maximum_step_mm: 180 });
    const plane = d.slots.find(s => s.part === 'walking_support')!;
    expect(plane.positionMm).toEqual([51000, 5340, 150]);
    expect(plane.boxMm).toEqual([2000, 2000, 0]);
    expect(w.surface.sample(51, -5.34)).toBeNull();
    expect(w.support!.entry.surfaceId).toBe('base-ground');
  });
  it('requires an explicit surface for ground reset and retains it during last-safe recovery', () => {
    const d = parseStructuredSiteDrawing(fixture.drawing), w = siteNavigationWorld(d), canvas = document.createElement('canvas');
    document.body.append(canvas);
    const controls = new FirstPersonControls(canvas, siteStart(d, w), undefined, w);
    const before = { ...controls.state };
    controls.setView({ x: 51, y: 1.75, z: -5.34, yaw: 0, pitch: 0 }, 'ground');
    expect(controls.state).toEqual(before);
    const state = w.support!.move(w.support!.entry, [51000, -3340], [51000, -5340]).state;
    controls.setView({ x: 51, y: 1.75, z: -5.34, yaw: 0, pitch: 0, support: state }, 'ground');
    expect(controls.state.support).toEqual(state);
    controls.state.x = 500;
    controls.update(.02);
    expect(controls.state.x).toBe(51);
    expect(controls.state.y).toBe(1.75);
    expect(controls.state.support).toEqual(state);
    controls.setView({ x: 51, y: 50, z: -5.34, yaw: 0, pitch: 0, support: {...state,networkSha256:'f'.repeat(64)} }, 'altitude');
    expect(controls.state.support).toEqual(state);
    expect(controls.state.y).toBe(50);
    controls.holdGround(); controls.update(.02);
    expect(controls.state.y).toBe(1.75); expect(controls.state.support).toEqual(state);
    controls.setView({x:NaN,y:NaN,z:NaN,yaw:0,pitch:0},'ground');
    expect(controls.state.y).toBe(1.75);
    controls.setView(siteStart(d, w), 'ground');
    expect(controls.state.support).toEqual(w.support!.entry);
    controls.destroy();
    expect(canvas.dataset['navigationSupport']).toBeUndefined();
    canvas.remove();
  });
});
it('refuses incomplete v2 drawings and actor bindings that do not describe a person', () => {
  expect(() => parseStructuredSiteDrawing({ ...fixture.drawing, support: null })).toThrow('support adapter');
  const unsupported = structuredClone(fixture.drawing);
  unsupported.support.network.actor.height_mm = 1700;
  const { document_sha256: _digest, ...unsigned } = unsupported.support.network;
  unsupported.support.network.document_sha256 = sha256Hex(new TextEncoder().encode(canonicalJson(unsigned)));
  expect(() => siteNavigationWorld(parseStructuredSiteDrawing(unsupported))).toThrow('person actor');
});
