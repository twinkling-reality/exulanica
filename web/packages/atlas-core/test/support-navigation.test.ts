import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { describe, expect, it } from 'vitest';
import { canonicalJson, readSupportNavigation, SupportNavigationError, atlasVec3, resolveGroundMovement, type NavigationWorld, type SupportNetworkDocument } from '../src/index.js';
const fixture = JSON.parse(readFileSync('packages/atlas-react/test/fixtures/site-support.v2.json', 'utf8'));
const raw = fixture.drawing.support.network;
const hash = (bytes: Uint8Array) => createHash('sha256').update(bytes).digest('hex');
const read = (document = raw) => readSupportNavigation(document, raw.source.world_id, 'base-ground', hash);
const seal = (doc: SupportNetworkDocument) => { const { document_sha256: _, ...unsigned } = doc; return { ...unsigned, document_sha256: hash(new TextEncoder().encode(canonicalJson(unsigned))) }; };
const world = (support = read()): NavigationWorld => ({ support, surface: { sample: () => null }, eyeHeight: 1.6, cameraRadius: .34, centre: atlasVec3(48, 0, -64), fieldRadius: 80, recoveryRadius: 82, maximumSlopeDegrees: 12, maximumStepHeight: .18, surfaceSampleSpacing: .05, regions: [], obstacles: [], traces: [] });
describe('canonical support query parity', () => {
  for (const query of fixture.queries)
    it(`${query.operation} ${query.position_mm}`, () => {
      const nav = read();
      let result;
      const run = () => query.operation === 'support_at' ? { surface_id: query.surface_id, support_z_mm: nav.supportAt(query.surface_id, query.position_mm) } : (() => { const v = nav.connectionAt(query.connection_id, query.from_surface_id, query.position_mm); return { surface_id: v.surfaceId, support_z_mm: v.heightMm }; })();
      if (query.expected.code) {
        try {
          run();
          throw Error('query should refuse');
        }
        catch (error) {
          expect(error).toBeInstanceOf(SupportNavigationError);
          expect(error).toMatchObject(query.expected);
        }
      }
      else {
        result = run();
        expect(result).toEqual(query.expected);
      }
    });
  it('holds immutable source/digest and rejects edited bytes or another world', () => {
    const nav = read();
    expect(Object.isFrozen(nav.document.surfaces[0])).toBe(true);
    expect(() => read({ ...raw, network_id: 'different' })).toThrow('document_sha256');
    expect(() => readSupportNavigation(raw, 'another-world', 'base-ground', hash)).toThrow('source');
  });
});
describe('movement carries explicit support identity', () => {
  it('ascends and descends only through its declared portal, retaining straddling state', () => {
    const nav = read(), before = JSON.stringify(nav.entry);
    const edge = nav.move(nav.entry, [51000, -3340], [51000, -4390]);
    expect(edge.state).toMatchObject({ surfaceId: 'deck', connectionId: 'step' });
    expect(edge.heightMm).toBe(150);
    const atop = nav.move(edge.state, [51000, -4390], [51000, -5340]);
    expect(atop.state).toMatchObject({ surfaceId: 'deck', connectionId: null });
    const down = nav.move(atop.state, [51000, -5340], [51000, -3340]);
    expect(down.state).toEqual(nav.entry);
    expect(down.heightMm).toBe(0);
    expect(JSON.stringify(nav.entry)).toBe(before);
  });
  it('blocks the deck from outside its portal without mutating the original state', () => {
    const nav = read(), state = nav.entry;
    expect(() => nav.move(state, [51900, -3340], [51900, -5340])).toThrow();
    expect(state).toEqual(nav.entry);
    expect(() => nav.supportAt('base-ground', [51000, -5340])).toThrow('headroom');
  });
  it('does not join stacked plan overlap or infer the highest level', () => {
    const doc = structuredClone(raw);
    doc.surfaces.find((s: any) => s.surface_id === 'deck').support_z_mm = 3000;
    doc.connections = doc.connections.filter((c: any) => c.kind !== 'step');
    const nav = read(seal(doc));
    expect(nav.move(nav.entry, [51000, -3340], [51000, -5340])).toMatchObject({ heightMm: 0, state: { surfaceId: 'base-ground' } });
    expect(() => nav.at({ ...nav.entry, networkSha256: 'f'.repeat(64) }, [51000, -3340])).toThrow('exact network');
  });
  it('re-resolves a collision-clipped speculative step from the original surface', () => {
    const nav = read(), w = { ...world(nav), obstacles: [{ id: 'placed-prop', centre: atlasVec3(51, 0, -4.1), radius: .1 }] };
    const current = atlasVec3(51, 1.6, -3.34);
    const result = resolveGroundMovement(w, { current, desired: atlasVec3(51, 1.6, -5.34), lastSafe: current, supportState: nav.entry, lastSafeSupport: nav.entry });
    expect(result.collided).toBe(true);
    expect(result.supportState?.surfaceId).toBe('base-ground');
    expect(result.position.y).toBe(1.6);
    expect(result.position.z).toBeGreaterThan(-4);
  });
  it('recovers to the saved surface and height rather than the lower overlapping floor', () => {
    const nav = read(), state = nav.move(nav.entry, [51000, -3340], [51000, -5340]).state, safe = atlasVec3(51, 1.75, -5.34);
    const result = resolveGroundMovement(world(nav), { current: safe, desired: atlasVec3(500, 1.75, -5.34), lastSafe: safe, supportState: state, lastSafeSupport: state });
    expect(result.recovered).toBe(true);
    expect(result.position).toEqual(safe);
    expect(result.supportState).toEqual(state);
  });
});

it('blocks a valid network’s off-route overhead solid for the whole actor', () => {
  const doc=structuredClone(raw);
  doc.solids.push({solid_id:'zz-overhead',box_mm:[55000,-3500,1600,56000,-2500,2100]});
  const nav=read(seal(doc));
  expect(()=>nav.move(nav.entry,[54000,-3000],[55500,-3000])).toThrow();
  expect(nav.at(nav.entry,[54000,-3000])).toBe(0);
});
