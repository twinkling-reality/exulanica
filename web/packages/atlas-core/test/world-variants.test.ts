import { describe, expect, it } from 'vitest';
import {
  DEFAULT_WORLD_MODULES,
  DEFAULT_WORLD_RECIPES,
  WorldModuleRegistry,
  WorldRecipeRegistry,
  composeAtlasWorld,
  entityId,
  makeIsland,
} from '../src/index.js';
import { island, scene } from './fixture.js';

const region = (key: string, ordinal: number, position: readonly [number, number, number]) =>
  makeIsland({
    ...island({ key, createdAt: 1_000 + ordinal, position, footprint: 8, entities: ['shared'], anchors: [] }),
    rung: 4,
    creationOrdinal: ordinal,
    layoutEntities: new Set([entityId('shared')]),
  });

const canonical = DEFAULT_WORLD_MODULES.get('region.soft-footprint');

/** A substitutable footprint: same contracts, same socket keys, different socket placement. */
const shifted = (key: string, offset: number) => ({
  ...canonical,
  key,
  variantOf: 'region.soft-footprint',
  sockets: canonical.sockets.map((socket) => ({
    ...socket,
    local: { ...socket.local, x: socket.local.x + offset },
  })),
});

/** The catalog as it stands with every substitute removed, so a pool holds exactly one module. */
const canonicalOnly = DEFAULT_WORLD_MODULES.definitions.filter((value) => value.variantOf === null);

const withVariants = (...extra: readonly ReturnType<typeof shifted>[]) => {
  const modules = new WorldModuleRegistry(2, [...canonicalOnly, ...extra]);
  return {
    modules,
    recipes: new WorldRecipeRegistry(
      DEFAULT_WORLD_RECIPES.version,
      DEFAULT_WORLD_RECIPES.recipes,
      modules,
    ),
  };
};

describe('seeded module variants', () => {
  const atlas = scene([region('r1', 0, [-12, 0, -4]), region('r2', 1, [5, 0, 6])]);

  /*
   * The existing catalog declares no variants, so every pool holds one module and the choice is
   * forced. That is what keeps composition byte-identical for worlds already recorded against
   * this composer: variation arrives with a catalog version, never by surprise.
   */
  it('changes nothing until a catalog offers an alternative', () => {
    const modules = new WorldModuleRegistry(1, canonicalOnly);
    const catalog = {
      modules,
      recipes: new WorldRecipeRegistry(DEFAULT_WORLD_RECIPES.version, DEFAULT_WORLD_RECIPES.recipes, modules),
    };
    const a = composeAtlasWorld(atlas, { seed: 'one', ...catalog });
    const b = composeAtlasWorld(atlas, { seed: 'two', ...catalog });
    expect(a.topologyDigest).toBe(b.topologyDigest);
    expect(a.instances.every((value) => value.moduleKey === value.slotModuleKey)).toBe(true);
  });

  /* The shipped catalog does offer alternatives, which is the whole point of version 2. */
  it('gives the default catalog more than one world', () => {
    const digests = ['one', 'two', 'three', 'four', 'five', 'six']
      .map((seed) => composeAtlasWorld(atlas, { seed }).topologyDigest);
    expect(new Set(digests).size).toBeGreaterThan(1);
    expect(DEFAULT_WORLD_MODULES.variantsOf('region.soft-footprint').length).toBeGreaterThan(1);
  });

  /*
   * The visible payoff: regions in one world stop being arranged identically. The footprint
   * decides where a region's orientation register and growth register stand, so a mixture here is
   * a mixture on screen, with no renderer change and no per-region authoring.
   */
  it('arranges the regions of a single world differently from each other', () => {
    const wide = scene([
      region('r1', 0, [-24, 0, -8]),
      region('r2', 1, [10, 0, 12]),
      region('r3', 2, [26, 0, -14]),
      region('r4', 3, [-6, 0, 22]),
      region('r5', 4, [2, 0, -26]),
      region('r6', 5, [-30, 0, 18]),
    ]);
    const footprints = composeAtlasWorld(wide, { seed: 'a-lived-in-world' }).instances
      .filter((value) => value.role === 'region-foundation')
      .map((value) => value.moduleKey);
    expect(footprints).toHaveLength(6);
    expect(new Set(footprints).size).toBeGreaterThan(1);
    for (const key of new Set(footprints)) {
      expect(DEFAULT_WORLD_MODULES.variantsOf('region.soft-footprint').map((v) => v.key)).toContain(key);
    }
  });

  it('composes a different world per seed, and the same world for the same seed', () => {
    const catalog = withVariants(shifted('region.test-alpha', 0.4), shifted('region.test-beta', -0.4));
    const seeds = ['one', 'two', 'three', 'four', 'five', 'six'];
    const digests = seeds.map((seed) => composeAtlasWorld(atlas, { seed, ...catalog }).topologyDigest);
    expect(new Set(digests).size).toBeGreaterThan(1);
    for (const [index, seed] of seeds.entries()) {
      expect(composeAtlasWorld(atlas, { seed, ...catalog }).topologyDigest).toBe(digests[index]);
    }
  });

  /*
   * Selection hashes the seed against each instance's own identity rather than pulling from a
   * running generator, so composing a larger world cannot reshuffle the parts of it that already
   * existed. Growing an archive must not redecorate the regions a person already knows.
   */
  it('leaves an existing region alone when the world grows around it', () => {
    const catalog = withVariants(shifted('region.test-alpha', 0.4), shifted('region.test-beta', -0.4));
    const chosen = (snapshot: ReturnType<typeof composeAtlasWorld>, id: string) =>
      snapshot.instances.find((value) => value.instanceId === id)!.moduleKey;
    const small = composeAtlasWorld(atlas, { seed: 'stable', ...catalog });
    const grown = composeAtlasWorld(
      scene([...atlas.islands, region('r3', 2, [20, 0, -9]), region('r4', 3, [-22, 0, 11])]),
      { seed: 'stable', ...catalog },
    );
    const foundations = small.instances.filter((value) => value.role === 'region-foundation');
    expect(foundations.length).toBeGreaterThan(0);
    for (const instance of foundations) {
      expect(chosen(grown, instance.instanceId)).toBe(instance.moduleKey);
    }
  });

  it('records what the recipe asked for beside what the seed chose', () => {
    const catalog = withVariants(shifted('region.test-alpha', 0.4));
    const seeds = ['one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight'];
    const substituted = seeds
      .flatMap((seed) => composeAtlasWorld(atlas, { seed, ...catalog }).instances)
      .filter((value) => value.moduleKey !== value.slotModuleKey);
    expect(substituted.length).toBeGreaterThan(0);
    for (const instance of substituted) {
      expect(instance.slotModuleKey).toBe('region.soft-footprint');
      expect(instance.moduleKey).toBe('region.test-alpha');
      expect(instance.role).toBe(canonical.role);
    }
  });
});

describe('a variant has to be substitutable, and the catalog says so', () => {
  const reject = (patch: Record<string, unknown>) => () =>
    new WorldModuleRegistry(2, [
      ...DEFAULT_WORLD_MODULES.definitions,
      { ...shifted('region.test-candidate', 0.4), ...patch },
    ]);

  it('refuses a different role', () => {
    expect(reject({ role: 'landmark' })).toThrow(/cannot stand in for/);
  });

  it('refuses a weaker evidence requirement', () => {
    expect(reject({ evidence: 'reconstruction-asset' })).toThrow(/evidence requirement/);
  });

  it('refuses a dropped socket a recipe attaches to', () => {
    expect(reject({ sockets: canonical.sockets.filter((value) => value.key !== 'landmark') }))
      .toThrow(/socket landmark is missing/);
  });

  it('refuses a socket that stops accepting what it used to', () => {
    expect(reject({
      sockets: canonical.sockets.map((value) =>
        value.key === 'content' ? { ...value, accepts: ['landmark'] } : value),
    })).toThrow(/stops accepting/);
  });

  it('refuses an unknown target and a chain of variants', () => {
    expect(() => new WorldModuleRegistry(2, [
      ...DEFAULT_WORLD_MODULES.definitions,
      { ...shifted('region.test-candidate', 0.4), variantOf: 'region.absent' },
    ])).toThrow(/varies unknown module/);
    expect(() => new WorldModuleRegistry(2, [
      ...DEFAULT_WORLD_MODULES.definitions,
      shifted('region.test-first', 0.4),
      { ...shifted('region.test-second', 0.8), variantOf: 'region.test-first' },
    ])).toThrow(/which is itself a variant/);
  });

  /* Naming a variant in a recipe would quietly narrow the slot back to one shape. */
  it('gives a variant no pool of its own', () => {
    const { modules } = withVariants(shifted('region.test-alpha', 0.4));
    expect(modules.variantsOf('region.soft-footprint').map((value) => value.key))
      .toEqual(['region.soft-footprint', 'region.test-alpha']);
    expect(modules.variantsOf('region.test-alpha').map((value) => value.key))
      .toEqual(['region.test-alpha']);
  });

  /*
   * A form is a promise the renderer has to be able to keep, so the catalog refuses one the role
   * has no vocabulary for rather than letting it reach a renderer that would silently ignore it.
   */
  it('refuses a form the role has no vocabulary for', () => {
    const footprint = { ...shifted('region.test-formed', 0.4), form: { kind: 'aero-beacon', parameters: {} } };
    expect(() => new WorldModuleRegistry(3, [...canonicalOnly, footprint as never]))
      .toThrow(/has no registered form vocabulary/);
  });

  it('refuses a form belonging to another role', () => {
    const growth = {
      ...DEFAULT_WORLD_MODULES.get('growth.open-register'),
      key: 'growth.test-wrong',
      variantOf: 'growth.open-register',
      form: { kind: 'aero-beacon', parameters: {} },
    };
    expect(() => new WorldModuleRegistry(3, [...canonicalOnly, growth as never]))
      .toThrow(/is not one of living-buds, survey-stakes/);
  });

  /* No renderer draws a landmark form, so the catalog lets no landmark module declare one. */
  it('refuses any form on a landmark', () => {
    for (const kind of ['aero-beacon', 'survey-strata']) {
      const landmark = {
        ...DEFAULT_WORLD_MODULES.get('landmark.orientation-register'),
        key: 'landmark.test-formed',
        variantOf: 'landmark.orientation-register',
        form: { kind, parameters: {} },
      };
      expect(() => new WorldModuleRegistry(3, [...canonicalOnly, landmark as never]))
        .toThrow(/role landmark has no registered form vocabulary/);
    }
  });

  it('refuses parameters that are not stable names or not real numbers', () => {
    const base = DEFAULT_WORLD_MODULES.get('growth.open-register');
    const bad = (parameters: Record<string, number>) => () => new WorldModuleRegistry(3, [
      ...canonicalOnly,
      { ...base, key: 'growth.test-bad', variantOf: 'growth.open-register',
        form: { kind: 'survey-stakes', parameters } } as never,
    ]);
    expect(bad({ 'not a name': 3 })).toThrow(/is not a stable name/);
    expect(bad({ count: Number.NaN })).toThrow(/finite and non-negative/);
    expect(bad({ count: -1 })).toThrow(/finite and non-negative/);
  });
});
