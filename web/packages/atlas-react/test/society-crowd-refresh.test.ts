// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { SocietyCrowd, type CrowdFigures } from '../src/playcanvas/society/crowd.js';
import type { OwnedSocietyState, SocietyInhabitantSnapshot } from '../src/playcanvas/society/types.js';
import { serveFixturePeople } from './served-people.js';

/*
 * The looks chosen for a society's things change: the crowd asks its figures again, makes again
 * only the people whose figure is now another look's, where they stand, and touches nobody else.
 */

function setup() {
  const canvas = document.createElement('canvas');
  const device = new pc.NullGraphicsDevice(canvas);
  const app = new pc.AppBase(canvas);
  const options = new pc.AppOptions();
  options.graphicsDevice = device;
  options.componentSystems = [pc.RenderComponentSystem];
  app.init(options);
  serveFixturePeople(app);
  const root = new pc.Entity('society');
  app.root.addChild(root);
  return new SocietyCrowd(device, root);
}

const KNIGHT = { kind: 'knight', version: 1, sha256: 'a'.repeat(64) };
const SPIRIT = { kind: 'lantern_spirit', version: 1, sha256: 'b'.repeat(64) };
const person = (id: string, kind: typeof KNIGHT, at: readonly [number, number]): SocietyInhabitantSnapshot =>
  ({ id, synthetic: true, position_mm: at, motion_path_mm: [at], kind, came_by: 'placed' });
const state: OwnedSocietyState = {
  profile: 'exulanica-society/v7', society_id: 'society', branch_id: 'branch', tick: 1,
  inhabitants: [person('knight-1', KNIGHT, [2000, 0]), person('spirit-1', SPIRIT, [3000, 1000])],
};

/** Figures whose look for each person is read from `looks` when asked, recording what they make. */
function figures(looks: Map<string, string>, made: { id: string; look: string; destroyed: boolean }[]): CrowdFigures {
  return {
    figureFor(p) {
      const look = looks.get(p.id) ?? 'first';
      return {
        key: `${p.kind!.kind}|${look}`,
        factory: (_device, parent, identity) => {
          const record = { id: identity.inhabitantId, look, destroyed: false };
          made.push(record);
          const root = new pc.Entity(`thing:${identity.inhabitantId}`);
          parent.addChild(root);
          return {
            root, subject: { kind: 'synthetic-inhabitant', ...identity }, standingHeight: 1.8, facing: 0,
            pose: (pose) => root.setLocalPosition(...pose.position),
            setVisible: (visible) => { root.enabled = visible; },
            destroy: () => { record.destroyed = true; root.destroy(); },
          };
        },
      };
    },
  };
}

describe('the looks chosen for a society\'s things change', () => {
  it('makes again only the person whose look changed, where they stand', () => {
    const crowd = setup();
    const looks = new Map<string, string>();
    const made: { id: string; look: string; destroyed: boolean }[] = [];
    crowd.setFigures(figures(looks, made));
    crowd.set(state, [0, 0]);
    expect(made.map((one) => [one.id, one.look, one.destroyed])).toEqual([['knight-1', 'first', false], ['spirit-1', 'first', false]]);
    const before = crowd.positionOf('knight-1');
    looks.set('knight-1', 'chosen');
    crowd.refreshFigures();
    expect(made.map((one) => [one.id, one.look, one.destroyed])).toEqual([
      ['knight-1', 'first', true], ['spirit-1', 'first', false], ['knight-1', 'chosen', false],
    ]);
    expect(crowd.positionOf('knight-1')).toEqual(before);
    // Asked again with nothing changed, nobody is made again.
    crowd.refreshFigures();
    expect(made).toHaveLength(3);
  });

  it('does nothing for a crowd that draws everyone as one of the world\'s people', () => {
    const crowd = setup();
    crowd.set(state, [0, 0]);
    expect(() => crowd.refreshFigures()).not.toThrow();
    expect(crowd.detailOf('knight-1')).toBe('near');
  });
});
