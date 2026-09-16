// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import {
  atlasLandscapeHeight,
  DEFAULT_WORLD_MODULES,
  DEFAULT_WORLD_RECIPES,
  WORLD_DECLARABLE_FORM_KINDS,
  WORLD_EVIDENCE_FORM_KINDS,
  WORLD_EXPANSION_FORM_KINDS,
  WORLD_FORM_KINDS_BY_ROLE,
  WORLD_LANDMARK_FORM_KINDS,
  WORLD_MODULE_FORM_KINDS,
  WORLD_UNRENDERED_FORM_KINDS,
  WorldModuleRegistry,
  WorldRecipeRegistry,
  composeAtlasWorld,
  entityId,
  makeIsland,
  type WorldModuleFormKind,
} from '@exulanica/atlas-core';
import { ORIGIN_LANDSCAPE, SURVEY_RELIEF } from '@exulanica/presentation';
import { RENDERED_WORLD_MODULE_FORMS, createComposedWorld } from '../src/playcanvas/composed-world.js';
import { island, scene } from '../../atlas-core/test/fixture.js';

/*
 * `world-memory-model.md` 11.6 refuses visual work whose meaning exists only in mesh-generation
 * loops, and 5.1 refuses unrecorded procedural meaning. Both were prose, so nothing failed when a
 * module declared four LOD forms no renderer read, or when the style registry and the presentation
 * package bound one profile to different module counts and killed every world style change in the
 * browser.
 *
 * The first version of this file replaced that prose with two hand-written lists and compared
 * them. Both named `memory-lens` and `indexed-bays`, which nothing in the workspace draws, so it
 * passed while asserting something false. Comparing a claim against a claim is not a check. These
 * tests build the form and look for geometry.
 */

function stage() {
  const canvas = document.createElement('canvas');
  const device = new pc.NullGraphicsDevice(canvas);
  const app = new pc.AppBase(canvas);
  const options = new pc.AppOptions();
  options.graphicsDevice = device;
  options.componentSystems = [pc.RenderComponentSystem];
  app.init(options);
  return { device, app };
}

const region = (key: string, ordinal: number, position: readonly [number, number, number]) =>
  makeIsland({
    ...island({ key, createdAt: 1_000 + ordinal, position, footprint: 8, entities: ['shared'], anchors: [] }),
    rung: 4,
    creationOrdinal: ordinal,
    layoutEntities: new Set([entityId('shared')]),
  });

/** One world in which every module of `role` declares `kind`, and what it drew for them. */
function drawnFor(role: string, kind: WorldModuleFormKind): number {
  const canonical = DEFAULT_WORLD_MODULES.definitions.find(
    (value) => value.role === role && value.variantOf === null,
  )!;
  const modules = new WorldModuleRegistry(99, [
    ...DEFAULT_WORLD_MODULES.definitions.filter((value) => value.variantOf !== null
      ? value.variantOf !== canonical.key
      : value.key !== canonical.key),
    { ...canonical, form: { kind, parameters: {} } },
  ]);
  const recipes = new WorldRecipeRegistry(
    DEFAULT_WORLD_RECIPES.version, DEFAULT_WORLD_RECIPES.recipes, modules,
  );
  const topology = composeAtlasWorld(scene([region('r1', 0, [-12, 0, -4])]), { modules, recipes });
  const { device, app } = stage();
  const world = createComposedWorld(device, topology, ORIGIN_LANDSCAPE);
  const target = topology.instances.find((value) => value.role === role)!;
  const group = world.entity.findByName(target.instanceId);
  // Anywhere under the group: `survey-stakes` puts primitives on it directly, `living-buds` nests
  // each bud a level down, and both are geometry the person sees.
  const drawn = group === null ? 0 : (group as pc.Entity).findComponents('render').length;
  world.destroy();
  app.destroy();
  return drawn;
}

describe('a declared form has to produce something', () => {
  it.each(WORLD_DECLARABLE_FORM_KINDS.map((kind) => [kind] as const))(
    'draws geometry for %s',
    (kind) => {
      const role = [...WORLD_FORM_KINDS_BY_ROLE].find(([, kinds]) => kinds.includes(kind))![0];
      expect(drawnFor(role, kind)).toBeGreaterThan(0);
    },
  );

  it('would have caught the forms that are registered but drawn by nothing', () => {
    expect(WORLD_UNRENDERED_FORM_KINDS).toEqual([
      ...WORLD_EVIDENCE_FORM_KINDS,
      ...WORLD_LANDMARK_FORM_KINDS,
    ]);
    for (const kind of WORLD_UNRENDERED_FORM_KINDS) {
      expect(WORLD_DECLARABLE_FORM_KINDS).not.toContain(kind);
      expect(RENDERED_WORLD_MODULE_FORMS.has(kind)).toBe(false);
    }
  });
});

/*
 * A located region still receives a landmark instance: the composer's location gate decides that
 * much. What it may not receive is a body. The beacon and the survey strata were invented shapes,
 * and this is the assertion that keeps a later change from quietly standing one there again.
 */
describe('a landmark has no body until a grammar record gives it one', () => {
  it('draws nothing for a located region\'s landmark instance', () => {
    const topology = composeAtlasWorld(scene([region('r1', 0, [-12, 0, -4])]));
    const landmarks = topology.instances.filter((value) => value.role === 'landmark');
    expect(landmarks.length).toBeGreaterThan(0);
    const { device, app } = stage();
    for (const profile of [ORIGIN_LANDSCAPE, SURVEY_RELIEF]) {
      const world = createComposedWorld(device, topology, profile);
      for (const landmark of landmarks) {
        const group = world.entity.findByName(landmark.instanceId);
        const drawn = group === null ? 0 : (group as pc.Entity).findComponents('render').length;
        expect(drawn).toBe(0);
      }
      world.destroy();
    }
    app.destroy();
  });

  it('lets no landmark module declare a form', () => {
    expect(WORLD_FORM_KINDS_BY_ROLE.has('landmark')).toBe(false);
    for (const kind of WORLD_LANDMARK_FORM_KINDS) {
      expect(WORLD_DECLARABLE_FORM_KINDS).not.toContain(kind);
      expect(RENDERED_WORLD_MODULE_FORMS.has(kind)).toBe(false);
    }
    expect(DEFAULT_WORLD_MODULES.definitions.filter((value) => value.role === 'landmark')
      .map((value) => value.form)).toEqual([null]);
  });
});

describe('the catalog and the renderer agree on what a world can be built from', () => {
  it('draws every form a module is allowed to declare', () => {
    expect(WORLD_DECLARABLE_FORM_KINDS.filter((kind) => !RENDERED_WORLD_MODULE_FORMS.has(kind)))
      .toEqual([]);
  });

  it('declares every form it draws, so no shape exists only in the renderer', () => {
    expect([...RENDERED_WORLD_MODULE_FORMS].filter((kind) => !WORLD_DECLARABLE_FORM_KINDS.includes(kind)))
      .toEqual([]);
  });

  /*
   * `@exulanica/presentation` keeps its own copy of these names for world style profiles. It sits
   * above atlas-core and could import them instead; until it does, this is the tripwire.
   */
  it('uses the same form names the world style profiles use', () => {
    // The profiles name only a growth form now: their landmark and evidence tokens were deleted
    // with the renderer loops that read them.
    for (const profile of [ORIGIN_LANDSCAPE, SURVEY_RELIEF]) {
      expect(WORLD_MODULE_FORM_KINDS).toContain(profile.geometry.expansion);
      expect(WORLD_EXPANSION_FORM_KINDS).toContain(profile.geometry.expansion);
      expect(profile.geometry).not.toHaveProperty('landmark');
      expect(profile.geometry).not.toHaveProperty('evidence');
    }
  });

  it('keeps every declared form legal for the role that declares it', () => {
    const declared = DEFAULT_WORLD_MODULES.definitions.filter((value) => value.form !== null);
    expect(declared.length).toBeGreaterThan(0);
    for (const module of declared) {
      expect(WORLD_FORM_KINDS_BY_ROLE.get(module.role)).toContain(module.form!.kind);
      expect(RENDERED_WORLD_MODULE_FORMS.has(module.form!.kind)).toBe(true);
    }
  });

  it('leaves the canonical modules under the world style, not the catalog', () => {
    for (const key of ['landmark.orientation-register', 'growth.open-register']) {
      expect(DEFAULT_WORLD_MODULES.get(key).form).toBeNull();
    }
  });
});

/*
 * Where a memory stands when the ground under it is not the ground it was authored for.
 *
 * `atInstance` added `atlasLandscapeHeight` to every module unconditionally. That is right when the
 * Atlas landscape is the surface you are standing on, and wrong over an owned district, which draws
 * its own flat street at y = 0 and does not draw the Atlas landscape at all. The height of an
 * invisible surface is not a small error: on the Flatiron district every region sampled between
 * -0.74 and -1.39 metres, so a 3.4 metre landmark arrived with a third of itself inside the road.
 */
describe('composed world grounding', () => {
  const at: readonly [number, number, number] = [-12, 0, -4];

  // The growth register is the module that still draws, so it is what grounding is measured on.
  function growthBaseY(groundHeight?: (x: number, z: number) => number): number {
    const topology = composeAtlasWorld(scene([region('r1', 0, at)]));
    const { device } = stage();
    const world = groundHeight === undefined
      ? createComposedWorld(device, topology, ORIGIN_LANDSCAPE)
      : createComposedWorld(device, topology, ORIGIN_LANDSCAPE, undefined, groundHeight);
    const target = topology.instances.find((value) => value.role === 'expansion-point')!;
    return world.entity.findByName(target.instanceId)!.getPosition().y;
  }

  it('stands on the authored Atlas landscape by default', () => {
    const target = composeAtlasWorld(scene([region('r1', 0, at)]))
      .instances.find((value) => value.role === 'expansion-point')!;
    expect(growthBaseY()).toBeCloseTo(
      target.transform.position.y
        + atlasLandscapeHeight(target.transform.position.x, target.transform.position.z),
      5,
    );
  });

  it('stands on the caller\'s ground when the caller owns it', () => {
    // The district's own street. Not "close to zero": a flat surface means exactly its own height.
    expect(growthBaseY(() => 0)).toBe(0);
    // And the two differ by exactly the landscape this district does not draw, which is the whole
    // displacement the fix removes. Asserted against the function rather than a chosen tolerance,
    // so it stays true if the fixture moves.
    const target = composeAtlasWorld(scene([region('r1', 0, at)]))
      .instances.find((value) => value.role === 'expansion-point')!;
    const buried = atlasLandscapeHeight(target.transform.position.x, target.transform.position.z);
    expect(buried).not.toBe(0);
    expect(growthBaseY() - growthBaseY(() => 0)).toBeCloseTo(buried, 5);
  });
});
