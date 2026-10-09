// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { SocietyCrowd, type CrowdFigures } from '../src/playcanvas/society/crowd.js';
import type { OwnedSocietyState, SocietyInhabitantSnapshot } from '../src/playcanvas/society/types.js';
import { serveFixturePeople } from './served-people.js';

/*
 * Where a mark over a person hangs: over the top of the box they are drawn and picked by, in world
 * space. The crowd's root is moved and turned here, so the expected points are worked by hand from
 * that turn (a quarter turn about +Y carries local (x, y, z) to (z, y, -x)).
 */

const KNIGHT = { kind: 'knight', version: 1, sha256: 'a'.repeat(64) };
const STANDING = 1.8;
const CLEARANCE = 0.18;

function setup() {
  const canvas = document.createElement('canvas');
  const device = new pc.NullGraphicsDevice(canvas);
  const app = new pc.AppBase(canvas);
  const options = new pc.AppOptions();
  options.graphicsDevice = device;
  options.componentSystems = [pc.RenderComponentSystem];
  app.init(options);
  serveFixturePeople(app);
  const region = new pc.Entity('region');
  region.setLocalPosition(10, 0, 5);
  region.setLocalEulerAngles(0, 90, 0);
  app.root.addChild(region);
  const root = new pc.Entity('society');
  region.addChild(root);
  return new SocietyCrowd(device, root);
}

/** Things of the knight's kind are drawn by a figure STANDING metres tall. */
const figures: CrowdFigures = {
  figureFor(person) {
    if (person.kind?.kind !== 'knight') return null;
    return {
      key: 'knight',
      factory: (_device, parent, identity) => {
        const root = new pc.Entity(`thing:${identity.inhabitantId}`);
        parent.addChild(root);
        return {
          root, subject: { kind: 'synthetic-inhabitant', ...identity }, standingHeight: STANDING, facing: 0,
          pose: (pose) => root.setLocalPosition(...pose.position),
          setVisible: (visible) => { root.enabled = visible; },
          destroy: () => root.destroy(),
        };
      },
    };
  },
};

const person = (id: string, at: readonly [number, number], extra: Partial<SocietyInhabitantSnapshot> = {}): SocietyInhabitantSnapshot =>
  ({ id, synthetic: true, position_mm: at, motion_path_mm: [at], ...extra });

const state = (people: SocietyInhabitantSnapshot[]): OwnedSocietyState => ({
  profile: 'exulanica-society/v7', society_id: 'society', branch_id: 'branch', tick: 1, inhabitants: people,
});

describe('where a mark over a person hangs', () => {
  it('hangs over the top of a drawn person, in the world the region is turned into', () => {
    const crowd = setup();
    crowd.setFigures(figures);
    crowd.set(state([
      person('knight-1', [2000, 0], { kind: KNIGHT }),
      person('villager-far', [300_000, 1000]),
      person('indoors-1', [1000, 0], { indoors: true }),
    ]), [0, 0]);
    const out = new pc.Vec3();
    // Local (2, 0 + 1.8 + 0.18, 0), a quarter turn to (0, 1.98, -2), then moved by (10, 0, 5).
    expect(crowd.anchorOf('knight-1', out)).toBe(true);
    expect(out.x).toBeCloseTo(10, 9);
    expect(out.y).toBeCloseTo(STANDING + CLEARANCE, 9);
    expect(out.z).toBeCloseTo(3, 9);
    // A far figure hangs its mark over its far form's height.
    expect(crowd.detailOf('villager-far')).toBe('far');
    expect(crowd.anchorOf('villager-far', out)).toBe(true);
    expect(out.y).toBeCloseTo(crowd.farAppearance('villager-far').heightMetres + CLEARANCE, 9);
    expect(out.x).toBeCloseTo(10 + 1, 9);
    expect(out.z).toBeCloseTo(5 - 300, 9);
    // Inside premises, or unknown: no mark hangs anywhere.
    expect(crowd.anchorOf('indoors-1', out)).toBe(false);
    expect(crowd.anchorOf('nobody', out)).toBe(false);
  });

  it('hangs no mark over a person while their figure is hidden', () => {
    const crowd = setup();
    crowd.setFigures(figures);
    crowd.set(state([person('knight-1', [2000, 0], { kind: KNIGHT })]), [0, 0]);
    const out = new pc.Vec3();
    expect(crowd.anchorOf('knight-1', out)).toBe(true);
    const root = (crowd as unknown as { near: Map<string, { root: pc.Entity }> }).near.get('knight-1')!.root;
    root.enabled = false;
    expect(crowd.anchorOf('knight-1', out)).toBe(false);
  });
});

describe('where a ring at a person\'s feet stands', () => {
  it('stands where the person is drawn, on the ground, in the world the region is turned into; nowhere for one not drawn outdoors', () => {
    const crowd = setup();
    crowd.setFigures(figures);
    crowd.set(state([person('knight-1', [2000, 0], { kind: KNIGHT }), person('indoors-1', [1000, 0], { indoors: true })]), [0, 0]);
    const out = new pc.Vec3();
    // Local (2, 0, 0), a quarter turn to (0, 0, -2), then moved by (10, 0, 5).
    expect(crowd.groundOf('knight-1', out)).toBe(true);
    expect(out.x).toBeCloseTo(10, 9);
    expect(out.y).toBeCloseTo(0, 9);
    expect(out.z).toBeCloseTo(3, 9);
    expect(crowd.groundOf('indoors-1', out)).toBe(false);
    expect(crowd.groundOf('nobody', out)).toBe(false);
    const root = (crowd as unknown as { near: Map<string, { root: pc.Entity }> }).near.get('knight-1')!.root;
    root.enabled = false;
    expect(crowd.groundOf('knight-1', out)).toBe(false);
  });
});
