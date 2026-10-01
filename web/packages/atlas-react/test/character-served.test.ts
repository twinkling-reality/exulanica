// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { CHARACTER_CATALOG } from '../src/playcanvas/character/catalog-data.js';
import { canonicalJson, sha256Hex } from '../src/playcanvas/character/digest.js';
import { DESIGNED_LOOKS } from '../src/playcanvas/character/looks-data.js';
import { inhabitantRenderable, PeopleCatalogNotServed } from '../src/playcanvas/character/inhabitant.js';
import { CharacterCatalogs, LAYERED_PROFILE, readServedCatalog, type CatalogPublicationEntry } from '../src/playcanvas/character/served.js';
import { SocietyCrowd } from '../src/playcanvas/society/crowd.js';
import type { OwnedSocietyState } from '../src/playcanvas/society/types.js';
import { SERVED_PEOPLE } from './served-people.js';

const bytesOf = (document: unknown) => new TextEncoder().encode(canonicalJson(document));
const bundle = { profile: LAYERED_PROFILE, catalog: CHARACTER_CATALOG, looks: DESIGNED_LOOKS };

function entry(bytes: Uint8Array, changes: Partial<CatalogPublicationEntry> = {}): CatalogPublicationEntry {
  return {
    catalog_sha256: sha256Hex(bytes),
    catalog_id: CHARACTER_CATALOG.catalogId,
    revision: CHARACTER_CATALOG.revision,
    profile: LAYERED_PROFILE,
    kind: 'layered-people',
    state: 'current',
    ...changes,
  };
}

describe('a served character catalog', () => {
  it('is read from exactly the bytes its digest names', () => {
    const bytes = bytesOf(bundle);
    const served = readServedCatalog(entry(bytes), bytes);
    expect(served.kind).toBe('layered-people');
    expect(served.catalogSha256).toBe(SERVED_PEOPLE.catalogSha256);
    if (served.kind === 'layered-people') expect(served.catalog.families[0]!.familyId).toBe('makehuman-people/v1');
  });

  it('is refused when its bytes, profile, kind or identity disagree with what was asked for', () => {
    const bytes = bytesOf(bundle);
    const altered = bytesOf({ ...bundle, catalog: { ...CHARACTER_CATALOG, revision: 9 } });
    expect(() => readServedCatalog(entry(bytes), altered)).toThrow(/do not hash/);
    expect(() => readServedCatalog(entry(bytes, { kind: 'parametric-body' }), bytes)).toThrow(/no reader/);
    const unknown = bytesOf({ ...bundle, profile: 'exulanica.character-catalog-bundle/v9' });
    expect(() => readServedCatalog(entry(unknown), unknown)).toThrow(/no reader/);
    expect(() => readServedCatalog(entry(bytes, { revision: 3 }), bytes)).toThrow(/another catalog or revision/);
    const broken = bytesOf({ ...bundle, looks: { ...DESIGNED_LOOKS, defaults: { ...DESIGNED_LOOKS.defaults, player: 'nobody' } } });
    expect(() => readServedCatalog(entry(broken), broken)).toThrow(/designed default/);
  });

  it('draws people only once a people catalog is served, and never from a retained one', () => {
    const app = {} as pc.AppBase;
    const catalogs = CharacterCatalogs.forApp(app);
    expect(catalogs.people).toBeNull();
    catalogs.add({ ...SERVED_PEOPLE, state: 'retained' });
    expect(catalogs.people).toBeNull();
    catalogs.add(SERVED_PEOPLE);
    expect(catalogs.people?.catalogSha256).toBe(SERVED_PEOPLE.catalogSha256);
  });
});

describe('a society before its people catalog arrives', () => {
  function setup() {
    const canvas = document.createElement('canvas');
    const device = new pc.NullGraphicsDevice(canvas);
    const app = new pc.AppBase(canvas);
    const options = new pc.AppOptions();
    options.graphicsDevice = device;
    options.componentSystems = [pc.RenderComponentSystem];
    app.init(options);
    const root = new pc.Entity('society', app);
    app.root.addChild(root);
    return { app, device, root };
  }
  const state = (tick: number, x: number): OwnedSocietyState => ({
    profile: 'exulanica-society/v2',
    society_id: 'society',
    branch_id: 'branch',
    tick,
    inhabitants: [{ id: 'person-0', synthetic: true as const, position_mm: [x, 0] }],
  });

  it('draws nobody and refuses an inhabitant by name, then presents the latest snapshot once served', () => {
    const { app, device, root } = setup();
    expect(() => inhabitantRenderable(device, root, { societyId: 's', branchId: 'b', inhabitantId: 'x' }, 'far'))
      .toThrow(PeopleCatalogNotServed);
    const crowd = new SocietyCrowd(device, root);
    expect(crowd.set(state(1, 1000), [0, 0])).toMatchObject({ population: 1, drawn: 0 });
    expect(crowd.set(state(2, 3000), [0, 0])).toMatchObject({ population: 1, drawn: 0 });
    expect(crowd.positionOf('person-0')).toBeNull();
    CharacterCatalogs.forApp(app).add(SERVED_PEOPLE);
    expect(crowd.counts.drawn).toBe(1);
    expect(crowd.positionOf('person-0')).toEqual([3, 0]);
    crowd.destroy();
  });
});
