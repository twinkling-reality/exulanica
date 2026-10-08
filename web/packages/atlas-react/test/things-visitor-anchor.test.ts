// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { SocietyCrowd } from '../src/playcanvas/society/crowd.js';
import type { OwnedSocietyState, SocietyInhabitantSnapshot } from '../src/playcanvas/society/types.js';
import { ThingCrowdFigures } from '../src/playcanvas/things/crowd-figures.js';
import { ThingFigureMaker } from '../src/playcanvas/things/figure-maker.js';
import type { Named } from '../src/playcanvas/things/library.js';
import { ThingLibrary } from '../src/playcanvas/things/library.js';
import { serveFixturePeople } from './served-people.js';
import { servedLibrary } from './things-fixtures.js';

/*
 * An outside agent's own body crosses in as a visitor of a kind with no look of its own, wearing the
 * look its crossing chose (the outside agents' mapping chooses the people catalog's). Its pill hangs
 * where the crowd anchors it, before the looks chosen are read and after, as for anyone the crowd
 * draws. The kinds and looks are the shipped catalogs'.
 */

function setup() {
  const canvas = document.createElement('canvas');
  const device = new pc.NullGraphicsDevice(canvas);
  const app = new pc.AppBase(canvas);
  const options = new pc.AppOptions();
  options.graphicsDevice = device;
  options.componentSystems = [pc.RenderComponentSystem, pc.LightComponentSystem, pc.CameraComponentSystem];
  app.init(options);
  serveFixturePeople(app);
  const root = new pc.Entity('society');
  app.root.addChild(root);
  const served = servedLibrary();
  const library = new ThingLibrary(served.list, (digest) => served.fetch(digest));
  return { app, device, root, served, library };
}

const settle = async () => {
  for (let i = 0; i < 8; i += 1) await new Promise((resolve) => setTimeout(resolve, 0));
};

describe('an outside agent\'s body in the crowd', () => {
  it('is anchored for its pill before its chosen look is read and after, as one of the world\'s people', async () => {
    const { app, device, root, served, library } = setup();
    const visitorKind = served.kindRef('visitor', 1);
    expect(served.list.kinds.find((one) => one.kind === 'visitor')!.looks).toEqual([]);
    const peopleLook = served.list.looks.find((one) => one.lookKind === 'catalog_person')!;
    let chosen: Named | null = null;
    const figures = new ThingCrowdFigures({ maker: new ThingFigureMaker({ app, library }), lookOf: () => chosen });
    const crowd = new SocietyCrowd(device, root, {});
    crowd.setFigures(figures);
    const agent: SocietyInhabitantSnapshot = {
      id: 'agent-0', synthetic: true, position_mm: [3000, 0], motion_path_mm: [[3000, 0]], kind: visitorKind,
      came_by: 'crossed', placed_id: null, crossing: { arrival_id: 'arrival-0', bridge: 'agents', grant_id: 'grant-a' },
    };
    const state: OwnedSocietyState = { profile: 'exulanica-society/v7', society_id: 's', branch_id: 'b', tick: 1, inhabitants: [agent], things: [] };
    crowd.set(state, [0, 0]);
    crowd.update(1000);
    await settle();
    crowd.update(1000 + 1000 / 60);
    const at = new pc.Vec3();
    // Before the read: its kind has no look, so it is drawn as a thing with none, and anchored over it.
    expect(crowd.anchorOf('agent-0', at)).toBe(true);
    expect(at.x).toBeCloseTo(3, 6);
    // The read names the people catalog's look: it is drawn as one of the world's people, still anchored.
    chosen = { key: peopleLook.look, version: peopleLook.version, sha256: peopleLook.sha256 };
    crowd.refreshFigures();
    crowd.update(2000);
    await settle();
    crowd.update(2000 + 1000 / 60);
    expect(crowd.detailOf('agent-0')).toBe('near');
    expect(crowd.anchorOf('agent-0', at)).toBe(true);
    expect(at.x).toBeCloseTo(3, 6);
  });
});
