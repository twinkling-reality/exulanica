/**
 * The conformance fixture, through the Node bake and through the browser preview.
 *
 * Both triangle digests must equal the CHECKED-IN LITERAL below, not merely each other: two
 * builds that agree on a wrong answer agree. The literal is the fixture. It moves only when the
 * fixture, the tessellator version or the digest definition moves, and each of those is a
 * deliberate commit that updates it. The fixture is the city vocabulary lane's version 2 tile,
 * copied byte for byte; `tests/test_bake_determinism.py` holds the copy to its source.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { PreviewUnavailable, previewTile } from '../src/browser/index.js';
import { bakeDocumentFile, nodeSha256 } from '../src/node/index.js';
import { bakeTile } from '../src/core/bake.js';
import { CITY_V2 } from '../src/core/city-v2.js';
import { absoluteSurfaceCoordinates, absoluteVertices, decodeOwd } from '../src/core/owd.js';
import { ringClearance } from '../src/core/ring-clearance.js';
import type { DecodedOwd } from '../src/core/owd.js';
import {
  documentBytes,
  dressedTerrainObject,
  FIXTURE_PATH,
  fixtureBytes,
  fixtureObject,
  recordsOf,
  scratch,
  sortList,
} from './support.js';

/**
 * Over `test/fixtures/tile-conformance.json`, tessellator 18, digest profile v3.
 *
 * THE PAIR IS THE POINT. Cutting the fixture's openings out of its faces moved `render_batch` and
 * left `nav_envelope` byte for byte where it was, which is what the grammar's navigation table says
 * must happen: `city.facade` carries ground `none`, so nothing it draws is support and nothing it
 * draws is ground another record yields to, whichever way that surface faces. An opening change that
 * moved the second of these two lines would be a carve that had escaped the face's own plane.
 */
const GOLDEN = {
  render_batch: '15129ce53e574e684c0faee2fd2c695cfb81696a5d03f3acf874e72c1ced9822',
  nav_envelope: 'dcd548bde8d8ca988c1e3b433c9515fe6531c95d7a5f4085d627e1b54e7eb811',
} as const;

afterEach(() => {
  vi.unstubAllGlobals();
});

const count = (states: string[], state: string): number => states.filter((s) => s === state).length;

type PlanPoint = readonly [number, number];

/**
 * Every region the grammar's navigation table says obstructs a walking capsule, by this test's own
 * reading of that table and of the DRAWN geometry, each as a convex walk in plan.
 *
 * A base ring is the ring the record states. A record whose LOW PARTS obstruct is read out of what
 * it draws: every triangle of its render batch whose three corners all stand below the capsule
 * height its grammar measures above where the record stands. Such a triangle lies inside a low part
 * by construction, so the region it stands for is one this tessellator must keep a capsule out of,
 * and every low part contributes at least the cap it stands on, which is that part's whole
 * footprint. Nothing here reads the carve, or the rule that chose which parts are low: the claim is
 * that what a person is held clear of is what they can see standing in their way.
 */
function obstructionWalks(decoded: DecodedOwd): { kind: string; walk: PlanPoint[] }[] {
  const render = decoded.projections[0]!;
  const vertices = absoluteVertices(render);
  const height = CITY_V2.measures.nav_envelope!.capsule_clearance!.height_mm!;
  const walks: { kind: string; walk: PlanPoint[] }[] = [];
  decoded.header.records.forEach((record, index) => {
    const row = CITY_V2.navigation.find((candidate) => candidate.kind === record.kind)!;
    if (row.obstruction === 'none') return;
    if (row.obstruction === 'base_ring') {
      walks.push({ kind: record.kind, walk: (record.fields as any).tiers[0].ring_mm as PlanPoint[] });
      return;
    }
    const entry = render.header.entries[index]!;
    if (entry.state !== 'drawn') throw new Error(`${record.kind} obstructs with its low parts and draws nothing`);
    const ceiling = (record.fields as any).z_mm + height;
    const partRoles = new Set(((record.fields as any).parts as any[]).map((part) => part.surface_role as string));
    const before = walks.length;
    for (const surface of entry.surfaces!) {
      if (!partRoles.has(surface.role)) continue;
      for (let triangle = surface.first_triangle; triangle < surface.first_triangle + surface.triangle_count; triangle += 1) {
        const corners = [0, 1, 2].map((corner) => render.index[triangle * 3 + corner]!);
        if (corners.some((vertex) => vertices[vertex * 3 + 2]! >= ceiling)) continue;
        const walk = corners.map((vertex) => [vertices[vertex * 3]!, vertices[vertex * 3 + 1]!] as PlanPoint);
        const turning = twice(walk[0]!, walk[1]!, walk[2]!);
        // An underside is drawn counter-clockwise seen from below, so it turns the other way in plan.
        if (turning === 0) continue;
        walks.push({ kind: record.kind, walk: turning > 0 ? walk : [...walk].reverse() });
      }
    }
    if (walks.length === before) throw new Error(`${record.kind} obstructs with its low parts and draws none of them low`);
  });
  return walks;
}

const twice = (a: PlanPoint, b: PlanPoint, c: PlanPoint): number =>
  (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);

/** Whether the interiors of two convex walks share a point, by the separating axis rule. */
function interiorsMeet(first: readonly PlanPoint[], second: readonly PlanPoint[]): boolean {
  const apart = (edges: readonly PlanPoint[], points: readonly PlanPoint[]): boolean => edges.some((from, index) => {
    const to = edges[(index + 1) % edges.length]!;
    return points.every((point) => twice(from, to, point) <= 0);
  });
  const turned = (walk: readonly PlanPoint[]): readonly PlanPoint[] => {
    const area = walk.reduce((total, here, index) => {
      const next = walk[(index + 1) % walk.length]!;
      return total + (here[0] * next[1] - here[1] * next[0]);
    }, 0);
    return area >= 0 ? walk : [...walk].reverse();
  };
  const [a, b] = [turned(first), turned(second)];
  if (apart(a, b)) return false;
  return !apart(b, a);
}

/** The squared distance from a plan point to a closed box given as its four corners, exactly. */
function walkGapSquared(walk: readonly PlanPoint[], x: number, y: number): number {
  let inside = true;
  let nearest = Infinity;
  const turned = walk.reduce((total, here, index) => {
    const next = walk[(index + 1) % walk.length]!;
    return total + (here[0] * next[1] - here[1] * next[0]);
  }, 0) >= 0 ? walk : [...walk].reverse();
  turned.forEach((from, index) => {
    const to = turned[(index + 1) % turned.length]!;
    if (twice(from, to, [x, y]) < 0) inside = false;
    const [dx, dy] = [to[0] - from[0], to[1] - from[1]];
    const span = dx * dx + dy * dy;
    const along = span === 0 ? 0 : Math.min(Math.max(((x - from[0]) * dx + (y - from[1]) * dy) / span, 0), 1);
    const [gx, gy] = [x - (from[0] + along * dx), y - (from[1] + along * dy)];
    nearest = Math.min(nearest, gx * gx + gy * gy);
  });
  return inside ? 0 : nearest;
}

/** The bounding box of plan points. */
function boundsOf(points: readonly PlanPoint[]): { min_x: number; min_y: number; max_x: number; max_y: number } {
  return {
    min_x: Math.min(...points.map((point) => point[0])),
    min_y: Math.min(...points.map((point) => point[1])),
    max_x: Math.max(...points.map((point) => point[0])),
    max_y: Math.max(...points.map((point) => point[1])),
  };
}

/** Whether any triangle of a projection holds a plan point, its edges included. */
function supports(projection: DecodedOwd['projections'][number], vertices: ArrayLike<number>, x: number, y: number): boolean {
  const point: PlanPoint = [x, y];
  for (let triangle = 0; triangle < projection.header.triangle_count; triangle += 1) {
    const corner = (at: number): PlanPoint => {
      const vertex = projection.index[triangle * 3 + at]!;
      return [vertices[vertex * 3]!, vertices[vertex * 3 + 1]!];
    };
    const [a, b, c] = [corner(0), corner(1), corner(2)];
    const sides = [twice(a, b, point), twice(b, c, point), twice(c, a, point)];
    if (sides.every((side) => side >= 0)) return true;
    if (sides.every((side) => side <= 0)) return true;
  }
  return false;
}

async function decodedFixture(bytes: Uint8Array = fixtureBytes()): Promise<DecodedOwd> {
  return decodeOwd((await bakeTile(bytes, nodeSha256)).container);
}

describe('the triangle digest of the conformance fixture', () => {
  it('is the golden literal through the Node bake and through the browser preview', async () => {
    const out = join(scratch('conformance'), 'fixture.owd');
    const node = await bakeDocumentFile(FIXTURE_PATH, out);
    const browser = await previewTile(fixtureBytes());

    expect(node.triangle_digests).toEqual(GOLDEN);
    expect(Object.fromEntries(browser.triangleDigests)).toEqual(GOLDEN);
    // Same container too, though the browser never writes or serves it.
    expect(browser.containerSha256).toBe(node.container_sha256);
    expect(await nodeSha256(new Uint8Array(readFileSync(out)))).toBe(node.container_sha256);
    expect(browser.tileInputsDigest).toBe(node.tile_inputs_digest);
    // Two bakes of a tile whose navigation is carved: the default five seconds is not enough.
  }, 30_000);

  it('draws the terrain patch undressed round the streets, the segments dressed, and states why nothing else draws', async () => {
    const { header, projections } = await decodedFixture();
    const [renderBatch, navEnvelope] = projections;
    expect(renderBatch!.header.name).toBe('render_batch');
    expect(navEnvelope!.header.name).toBe('nav_envelope');
    const grammar = fixtureObject().grammars[0];
    expect(header.records).toHaveLength(grammar.owned.length + grammar.halo.length);
    expect(header.grammars[0]).toMatchObject({
      subject_identity: grammar.subject_identity,
      frame: { name: 'city_local', units: 'mm', axes: 'x_east_y_north_z_up', metric_class: 'metric_authored' },
    });
    const terrain = header.records.findIndex((record) => record.kind === 'city.terrain');

    // The terrain patch is drawn less the carriageways and gutters the three segments draw and less
    // the ground the building stands on, and says no material dresses it: the grammar admits none.
    // Every other surface waits on a rule.
    const render = renderBatch!.header.entries.map((entry) => entry.state);
    expect(count(render, 'drawn')).toBe(46);
    // Six of them are the interior backings, one plane per face, standing behind the upper glazing
    // so a person looking in sees a room rather than the far side of the building.
    const backings = renderBatch!.header.entries.filter((_entry, index) => header.records[index]!.kind === 'city.interior_backing');
    expect(backings).toHaveLength(6);
    for (const entry of backings) {
      expect(entry).toMatchObject({ state: 'drawn', vertex_count: 4, triangle_count: 2 });
      if (entry.state !== 'drawn') throw new Error('a backing is not drawn');
      expect(entry.surfaces!.map((surface) => [surface.role, surface.orientation])).toEqual([['wall', 'vertical']]);
    }
    expect(count(render, 'halo')).toBe(grammar.halo.length);
    const drawnTerrain = renderBatch!.header.entries[terrain]!;
    expect(drawnTerrain).toMatchObject({
      state: 'drawn',
      first_vertex: 6961,
      vertex_count: 478,
      triangle_count: 495,
      surfaces: [{ role: 'terrain', orientation: 'horizontal', material: { state: 'none-exists' }, triangle_count: 495 }],
    });
    // The building draws, so the ground it stands on is the building's and not the terrain's: its
    // base ring is cut out of the patch by the same yield rule the segments' surfaces are.
    const building = renderBatch!.header.entries[header.records.findIndex((record) => record.kind === 'city.massing')]!;
    expect(building).toMatchObject({ state: 'drawn', vertex_count: 89, triangle_count: 47 });
    if (building.state !== 'drawn') throw new Error('the building is not drawn');
    // Its own wall keeps only what no face covers. A facade covers the run it states and the
    // storeys it states, so where a run stops short of its edge the building's wall stands there,
    // and the building drew 65 triangles before its nine faces took their part of it.
    expect(building.surfaces!.map((surface) => [surface.role, surface.orientation, surface.material.state])).toEqual([
      ['wall', 'vertical', 'record'],
      ['roof', 'horizontal', 'record'],
      ['parapet', 'vertical', 'record'],
    ]);
    // Nine faces draw, one per tier edge, each its wall and ground band with that band's panels.
    const faces = renderBatch!.header.entries.filter((_entry, index) => header.records[index]!.kind === 'city.facade');
    expect(faces).toHaveLength(9);
    expect(faces.every((entry) => entry.state === 'drawn')).toBe(true);
    const roles = new Set(faces.flatMap((entry) => entry.state === 'drawn' ? entry.surfaces!.map((surface) => surface.role) : []));
    expect([...roles].sort()).toEqual(['door', 'fascia', 'glazing', 'ground_band', 'party_wall_scar', 'stall_riser', 'trim', 'wall']);
    for (const surface of building.surfaces!) {
      if (surface.material.state !== 'record') throw new Error('a building surface cites no record');
      expect(header.records[surface.material.record]!.fields.role).toBe(surface.role);
    }
    // Yielding takes more from the grid than it adds by cutting: the streets, their corners and the
    // lots cover whole cells, so terrain draws FEWER triangles than the grid's own 16 by 16 pairs,
    // and the cells it keeps are cut rather than whole, which is why it is not a multiple of two.
    expect(drawnTerrain.state === 'drawn' && drawnTerrain.triangle_count).toBeLessThan(16 * 16 * 2);
    expect(drawnTerrain.state === 'drawn' && drawnTerrain.triangle_count % 2).toBe(1);
    // Each segment draws a carriageway and a gutter, each dressed by its own material record.
    const segments = renderBatch!.header.entries.filter((_entry, index) => header.records[index]!.kind === 'city.street_segment');
    expect(segments).toHaveLength(3);
    for (const entry of segments) {
      if (entry.state !== 'drawn') throw new Error('a segment is not drawn');
      expect(entry.surfaces!.map((surface) => [surface.role, surface.orientation, surface.material.state])).toEqual([
        ['carriageway', 'horizontal', 'record'],
        ['gutter', 'horizontal', 'record'],
      ]);
      for (const surface of entry.surfaces!) {
        if (surface.material.state !== 'record') throw new Error('a segment surface cites no record');
        expect(header.records[surface.material.record]!.fields.role).toBe(surface.role);
      }
    }
    expect(renderBatch!.surfaceMm).toHaveLength(renderBatch!.header.vertex_count * 2);
    for (const entry of renderBatch!.header.entries) {
      if (entry.state === 'unavailable') expect(entry.needs.length).toBeGreaterThan(0);
    }

    // Navigation draws what a person may stand on: the same ground partition, and the segments'
    // own carriageways and gutters, each carved clear of what the navigation table says obstructs.
    const nav = navEnvelope!.header.entries.map((entry) => entry.state);
    expect(count(nav, 'drawn')).toBe(11);
    expect(count(nav, 'halo')).toBe(grammar.halo.length);
    // Fewer triangles than render's terrain, and far fewer than when terrain drew under the ground
    // a carve had cleared: the segments cover what they stand on whether or not a capsule fits.
    expect(navEnvelope!.header.entries[terrain]).toMatchObject({ state: 'drawn', vertex_count: 394, triangle_count: 576 });
    expect(navEnvelope!.surfaceMm).toBeUndefined();

    // Halo is exactly what the document lists as halo.
    header.records.forEach((record, index) => {
      expect(renderBatch!.header.entries[index]!.state === 'halo').toBe(record.membership === 'halo');
    });
  });

  it('draws no triangle of no area, which has no normal and reaches a renderer as a value that is not finite', async () => {
    const decoded = await decodedFixture();
    for (const projection of decoded.projections) {
      const vertices = absoluteVertices(projection);
      const corner = (triangle: number, at: number): [number, number, number] => {
        const vertex = projection.index[triangle * 3 + at]!;
        return [vertices[vertex * 3]!, vertices[vertex * 3 + 1]!, vertices[vertex * 3 + 2]!];
      };
      const flat: string[] = [];
      for (let triangle = 0; triangle < projection.header.triangle_count; triangle += 1) {
        const [a, b, c] = [corner(triangle, 0), corner(triangle, 1), corner(triangle, 2)];
        const edge = (from: readonly number[], to: readonly number[]): number[] =>
          [to[0]! - from[0]!, to[1]! - from[1]!, to[2]! - from[2]!];
        const [u, v] = [edge(a, b), edge(a, c)];
        const normal = [u[1]! * v[2]! - u[2]! * v[1]!, u[2]! * v[0]! - u[0]! * v[2]!, u[0]! * v[1]! - u[1]! * v[0]!];
        if (normal.every((value) => value === 0)) flat.push(`${String(triangle)} at ${JSON.stringify(a)}`);
      }
      // The scan must have something to look at, or an empty projection would pass it silently.
      expect(projection.header.triangle_count).toBeGreaterThan(0);
      expect(flat, `${projection.header.name} draws triangles of no area: ${flat.slice(0, 6).join('; ')}`).toEqual([]);
    }
  });

  it('returns the wall into an opening on exactly the faces whose own record states a grid', async () => {
    const { header, projections } = await decodedFixture();
    const faces = header.records
      .map((record, index) => ({ record, entry: projections[0]!.header.entries[index]! }))
      .filter((row) => row.record.kind === 'city.facade');
    // Read from the fixture's own records, so a fixture that gained or lost a grid moves this too.
    const gridded = faces.map((row) => (row.record.fields.openings as readonly unknown[]).length > 0);
    const returned = faces.map((row) => row.entry.state === 'drawn'
      && row.entry.surfaces!.some((surface) => surface.role === 'trim'));
    // Both halves matter: a fixture where no face states a grid would make the comparison vacuous,
    // and one where every face did would make it blind to a rule that returns unconditionally.
    expect(gridded.filter(Boolean).length).toBeGreaterThan(0);
    expect(gridded.filter((has) => !has).length).toBeGreaterThan(0);
    expect(returned).toEqual(gridded);
  });

  it('supports nothing a capsule could not stand on, over what the navigation table says obstructs', async () => {
    const decoded = await decodedFixture();
    const nav = decoded.projections[1]!;
    const vertices = absoluteVertices(nav);
    const radius = CITY_V2.measures.nav_envelope!.capsule_clearance!.radius_mm!;
    const walks = obstructionWalks(decoded);
    // One building by its base ring, and the low drawn geometry of seven pieces of furniture and a
    // tree: the posts they stand on and what hangs off them below head height, never their canopies.
    expect(new Set(walks.map((row) => row.kind))).toEqual(new Set(['city.massing', 'city.street_furniture', 'city.street_tree']));
    expect(walks.filter((row) => row.kind === 'city.massing')).toHaveLength(1);
    expect(walks.filter((row) => row.kind !== 'city.massing').length).toBeGreaterThan(0);

    // No support meets a clearance piece. Those pieces cover everywhere within the radius of the
    // walk, which `ring-clearance.test.ts` holds them to, so no support is within the radius of it.
    const pieces = walks.flatMap((row) => ringClearance(row.walk, radius, 'the conformance tile'));
    for (let triangle = 0; triangle < nav.header.triangle_count; triangle += 1) {
      const walk = [0, 1, 2].map((corner) => {
        const vertex = nav.index[triangle * 3 + corner]!;
        return [vertices[vertex * 3]!, vertices[vertex * 3 + 1]!] as [number, number];
      });
      for (const piece of pieces) {
        expect(interiorsMeet(walk, piece), `triangle ${triangle} at ${JSON.stringify(walk[0])} meets a clearance`).toBe(false);
      }
    }

    // And measured against the radius itself, not against those pieces: over a lattice round the
    // street tree, no point within the radius of its TRUNK is supported, and points past it are,
    // which is the whole of the change: the tree's canopy is 6 m across and its pit is walkable.
    const trunk = walks.filter((row) => row.kind === 'city.street_tree').map((row) => row.walk);
    const box = boundsOf(trunk.flat());
    // 300 mm of trunk, where the canopy the record states is 6,000 mm across and the pit 1,200.
    expect(box.max_x - box.min_x).toBe(300);
    expect(box.max_y - box.min_y).toBe(300);
    let within = 0;
    let beyond = 0;
    for (let y = box.min_y - radius - 200; y <= box.max_y + radius + 200; y += 20) {
      for (let x = box.min_x - radius - 200; x <= box.max_x + radius + 200; x += 20) {
        const gap = Math.min(...trunk.map((walk) => walkGapSquared(walk, x, y)));
        const held = supports(nav, vertices, x, y);
        if (gap < radius * radius) {
          within += 1;
          expect(held, `(${x}, ${y}) is within the radius of the trunk and supported`).toBe(false);
        }
        if (gap > (radius + 10) * (radius + 10) && held) beyond += 1;
      }
    }
    expect(within).toBeGreaterThan(0);
    expect(beyond).toBeGreaterThan(0);
  });

  it('samples support height on the surface the support came from', async () => {
    const decoded = await decodedFixture();
    const nav = decoded.projections[1]!;
    const vertices = absoluteVertices(nav);
    const terrain = recordsOf(fixtureObject(), 'city.terrain')[0].fields;
    const entry = nav.header.entries[decoded.header.records.findIndex((record) => record.kind === 'city.terrain')]!;
    if (entry.state !== 'drawn') throw new Error('the terrain supports nobody');
    const cell = terrain.cell_mm as number;
    const side = terrain.samples_per_side as number;
    const heights = terrain.height_mm as number[];
    let atSamples = 0;
    for (let step = 0; step < entry.vertex_count; step += 1) {
      const vertex = entry.first_vertex + step;
      const [x, y, z] = [vertices[vertex * 3]!, vertices[vertex * 3 + 1]!, vertices[vertex * 3 + 2]!];
      if (x % cell === 0 && y % cell === 0 && x >= 0 && y >= 0) {
        expect(z, `the sample at ${x}, ${y}`).toBe(heights[(y / cell) * side + x / cell]);
        atSamples += 1;
        continue;
      }
      // A carved corner is on its cell's own plane, floored, so it lies between that cell's
      // samples. A corner the carve kept a millimetre past its cell extrapolates by under one.
      const column = Math.min(Math.max(Math.floor(x / cell), 0), side - 2);
      const row = Math.min(Math.max(Math.floor(y / cell), 0), side - 2);
      const corners = [0, 1].flatMap((up) => [0, 1].map((east) => heights[(row + up) * side + column + east]!));
      expect(z, `the carved corner at ${x}, ${y}`).toBeGreaterThanOrEqual(Math.min(...corners) - 1);
      expect(z, `the carved corner at ${x}, ${y}`).toBeLessThanOrEqual(Math.max(...corners) + 1);
    }
    expect(atSamples).toBeGreaterThan(0);
    expect(nav.header.contract.admissible_uses).toEqual(['sampling support height']);
  });

  it('gives undressed terrain plan surface coordinates, s = x and t = y', async () => {
    const decoded = await decodedFixture();
    const renderBatch = decoded.projections[0]!;
    const vertices = absoluteVertices(renderBatch);
    const surface = absoluteSurfaceCoordinates(renderBatch)!;
    const terrain = renderBatch.header.entries.find((_entry, index) => decoded.header.records[index]!.kind === 'city.terrain')!;
    if (terrain.state !== 'drawn') throw new Error('the terrain is not drawn');
    for (let step = 0; step < terrain.vertex_count; step += 1) {
      const vertex = terrain.first_vertex + step;
      expect(surface[vertex * 2]).toBe(vertices[vertex * 3]);
      expect(surface[vertex * 2 + 1]).toBe(vertices[vertex * 3 + 1]);
    }
  });

  it('draws dressed terrain citing its material record', async () => {
    const decoded = await decodedFixture(documentBytes(dressedTerrainObject()));
    const renderBatch = decoded.projections[0]!;
    const entry = renderBatch.header.entries.find((_candidate, index) => decoded.header.records[index]!.kind === 'city.terrain')!;
    if (entry.state !== 'drawn') throw new Error('unreachable');
    const [surface] = entry.surfaces!;
    expect(surface).toMatchObject({ role: 'terrain', orientation: 'horizontal' });
    if (surface!.material.state !== 'record') throw new Error('the dressed terrain cites no record');
    const material = decoded.header.records[surface!.material.record]!;
    expect(material.kind).toBe('city.surface_material');
    expect(material.fields.surface_identity).toBe(decoded.header.records[entry.record]!.identity);
    expect(decoded.projections[0]!.header.triangle_digest).not.toBe(GOLDEN.render_batch);
  });

  it('moves when one integer of the fixture moves, in both builds alike', async () => {
    const document = fixtureObject();
    const terrain = recordsOf(document, 'city.terrain')[0].fields;
    terrain.height_mm[0] = 10;
    terrain.extent.max_z_mm = 10;
    const perturbed = documentBytes(document);
    const node = await bakeTile(perturbed, nodeSha256);
    const browser = await previewTile(perturbed);
    expect(node.triangleDigests.get('render_batch')).not.toBe(GOLDEN.render_batch);
    expect(node.triangleDigests.get('nav_envelope')).not.toBe(GOLDEN.nav_envelope);
    expect(Object.fromEntries(browser.triangleDigests)).toEqual(Object.fromEntries(node.triangleDigests));
    // A bake carves navigation exactly, which is most of its work, and this test bakes twice.
  }, 120_000);

  it('moves when a record that draws nothing changes, because its entry is digested too', async () => {
    const document = fixtureObject();
    recordsOf(document, 'city.parcel')[0].fields.address_number += 1;
    const node = await bakeTile(documentBytes(document), nodeSha256);
    expect(node.triangleDigests.get('render_batch')).not.toBe(GOLDEN.render_batch);
    expect(node.triangleDigests.get('nav_envelope')).not.toBe(GOLDEN.nav_envelope);
  });

  it('moves when an owned record becomes halo, because halo is never drawn', async () => {
    const document = fixtureObject();
    const grammar = document.grammars[0];
    const index = grammar.owned.findIndex((record: any) => record.kind === 'city.premises');
    grammar.halo.push(...grammar.owned.splice(index, 1));
    sortList(grammar.halo);
    const node = await bakeTile(documentBytes(document), nodeSha256);
    expect(node.triangleDigests.get('render_batch')).not.toBe(GOLDEN.render_batch);
    expect(node.triangleDigests.get('nav_envelope')).not.toBe(GOLDEN.nav_envelope);
  });
});

describe('the browser preview', () => {
  it('refuses outright where crypto.subtle is missing', async () => {
    vi.stubGlobal('crypto', undefined);
    await expect(previewTile(fixtureBytes())).rejects.toBeInstanceOf(PreviewUnavailable);
  });

  it('refuses where crypto has no subtle member', async () => {
    vi.stubGlobal('crypto', {});
    await expect(previewTile(fixtureBytes())).rejects.toBeInstanceOf(PreviewUnavailable);
  });
});
