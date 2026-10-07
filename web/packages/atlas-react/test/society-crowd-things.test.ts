// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { SocietyCrowd, type CrowdFigures } from '../src/playcanvas/society/crowd.js';
import type { CrowdPose, CrowdRenderableFactory, OwnedSocietyState, SocietyInhabitantSnapshot, ThingKindReference } from '../src/playcanvas/society/types.js';
import { serveFixturePeople } from './served-people.js';

/*
 * A society of things: the crowd still walks everyone, and draws a thing by the factory its look
 * names, in full wherever it is within the far radius; one of the world's people is drawn as today.
 */

function setup(nearLimit?: number) {
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
  return new SocietyCrowd(device, root, nearLimit === undefined ? {} : { nearLimit });
}

const KNIGHT = { kind: 'knight', version: 1, sha256: 'a'.repeat(64) };
const SPIRIT = { kind: 'lantern_spirit', version: 1, sha256: 'b'.repeat(64) };
const VILLAGER = { kind: 'villager', version: 1, sha256: 'c'.repeat(64) };

function person(id: string, kind: ThingKindReference, at: readonly [number, number]): SocietyInhabitantSnapshot {
  return { id, synthetic: true, position_mm: at, motion_path_mm: [at], kind, came_by: kind === VILLAGER ? 'populated' : 'placed' };
}

const state = (people: SocietyInhabitantSnapshot[], tick = 1): OwnedSocietyState => ({
  profile: 'exulanica-society/v7', society_id: 'society', branch_id: 'branch', tick, inhabitants: people,
});

/** Figures drawing every kind but the villager's, keyed by `look`, recording what they draw. */
function figures(look: string, made: { id: string; look: string; poses: CrowdPose[]; destroyed: boolean }[]): CrowdFigures {
  return {
    figureFor(p) {
      if (p.kind === undefined || p.kind.kind === 'villager') return null;
      const factory: CrowdRenderableFactory = (_device, parent, identity) => {
        const record = { id: identity.inhabitantId, look, poses: [] as CrowdPose[], destroyed: false };
        made.push(record);
        const root = new pc.Entity(`thing:${identity.inhabitantId}`);
        parent.addChild(root);
        return {
          root, subject: { kind: 'synthetic-inhabitant', ...identity }, standingHeight: 1.8, facing: 0,
          pose: (pose) => { record.poses.push(pose); root.setLocalPosition(...pose.position); },
          setVisible: (visible) => { root.enabled = visible; },
          destroy: () => { record.destroyed = true; root.destroy(); },
        };
      };
      return { key: `${p.kind.kind}|${look}`, factory };
    },
  };
}

describe('a society of things drawn through the crowd', () => {
  it('draws a thing by its own figure wherever it is within the far radius, and people as today', () => {
    const crowd = setup();
    const made: { id: string; look: string; poses: CrowdPose[]; destroyed: boolean }[] = [];
    crowd.setFigures(figures('first', made));
    // The spirit is 300 m away: beyond the full form's 60 m, within the far radius's 700 m.
    const counts = crowd.set(state([
      person('knight-1', KNIGHT, [2000, 0]),
      person('spirit-1', SPIRIT, [300_000, 0]),
      person('villager-1', VILLAGER, [3000, 0]),
      person('villager-2', VILLAGER, [300_000, 1000]),
    ]), [0, 0]);
    expect(made.map((one) => one.id).sort()).toEqual(['knight-1', 'spirit-1']);
    expect(crowd.detailOf('spirit-1')).toBe('near');
    expect(crowd.detailOf('villager-1')).toBe('near');
    // A far villager keeps its far form; a far thing has none and is drawn in full.
    expect(crowd.detailOf('villager-2')).toBe('far');
    expect(counts.near).toBe(3);
    // The crowd walks a thing as it walks anyone: it is posed at its recorded point.
    const knight = made.find((one) => one.id === 'knight-1')!;
    expect(knight.poses.at(-1)!.position).toEqual([2, 0, 0]);
  });

  it('makes a thing again when its look changes, and never moves anyone for it', () => {
    const crowd = setup();
    const made: { id: string; look: string; poses: CrowdPose[]; destroyed: boolean }[] = [];
    crowd.setFigures(figures('first', made));
    crowd.set(state([person('knight-1', KNIGHT, [2000, 0])]), [0, 0]);
    const before = crowd.positionOf('knight-1');
    crowd.setFigures(figures('second', made));
    expect(made.map((one) => [one.look, one.destroyed])).toEqual([['first', true], ['second', false]]);
    expect(crowd.positionOf('knight-1')).toEqual(before);
  });

  it('makes a thing again when a later state draws it in another look', () => {
    const crowd = setup();
    const made: { id: string; look: string; poses: CrowdPose[]; destroyed: boolean }[] = [];
    let look = 'first';
    const switching: CrowdFigures = { figureFor: (p) => figures(look, made).figureFor(p) };
    crowd.setFigures(switching);
    crowd.set(state([person('knight-1', KNIGHT, [2000, 0])], 1), [0, 0]);
    crowd.set(state([person('knight-1', KNIGHT, [2000, 0])], 2), [0, 0]);
    expect(made.map((one) => [one.look, one.destroyed])).toEqual([['first', false]]);
    look = 'second';
    crowd.set(state([person('knight-1', KNIGHT, [2000, 0])], 3), [0, 0]);
    expect(made.map((one) => [one.look, one.destroyed])).toEqual([['first', true], ['second', false]]);
  });

  it('gives things the budget\'s full places before people, after a selected person', () => {
    const crowd = setup(2);
    const made: { id: string; look: string; poses: CrowdPose[]; destroyed: boolean }[] = [];
    crowd.setFigures(figures('first', made));
    crowd.set(state([
      person('villager-1', VILLAGER, [1000, 0]),
      person('villager-2', VILLAGER, [1500, 0]),
      person('knight-1', KNIGHT, [40_000, 0]),
    ]), [0, 0]);
    expect(crowd.detailOf('knight-1')).toBe('near');
    expect(crowd.detailOf('villager-1')).toBe('near');
    expect(crowd.detailOf('villager-2')).toBe('far');
    crowd.select('villager-2');
    expect(crowd.detailOf('villager-2')).toBe('near');
    expect(crowd.detailOf('knight-1')).toBe('near');
  });

  it('draws everyone as today without figures', () => {
    const crowd = setup();
    crowd.set(state([person('knight-1', KNIGHT, [2000, 0]), person('spirit-1', SPIRIT, [300_000, 0])]), [0, 0]);
    expect(crowd.detailOf('knight-1')).toBe('near');
    expect(crowd.detailOf('spirit-1')).toBe('far');
  });
});
