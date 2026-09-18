/**
 * The facade rule, held to what the records state by arithmetic of this test's own:
 *
 *   - THE FACE IS THE RUN BY ITS STOREYS: everything the rule draws for one face, added up in the
 *     face's plane, is its run length times the height of the storeys it covers. Nothing is left
 *     out and nothing is drawn twice.
 *   - AN OPENING IS MISSING WALL, NOT DRAWN WALL: the wall's area is the rectangle less every
 *     opening the grid states, one per bay per storey, and the return into each is its perimeter by
 *     its reveal depth. The two together are checked against the same total as everything else here.
 *   - A RETURN FACES INTO ITS OPENING: every one of its quads points at the hole rather than away
 *     from it, so a person in the street sees the wall's thickness and not its back.
 *   - THE BAND BELONGS TO THE BAYS: every ground panel is drawn, at its own recess and in the
 *     surface role the grammar gives its panel role, and the part of the band no bay covers takes
 *     the ground band role.
 *   - A PARTY WALL SCARS ABOVE THE NEIGHBOUR: the region above `neighbour_top_mm` is the scar's and
 *     the rest is the wall's.
 *   - THE BUILDING GIVES UP WHAT THE FACE COVERS: the massing rule draws no wall where a facade
 *     draws, so the two together cover a tier edge exactly once.
 *   - THE BACKING IS ONE PLANE, BEHIND THE GLASS AND FACING OUT: its area is its width by its
 *     height, it stands at the depth it states back from the face, its heights are above the
 *     BUILDING's base rather than the face's, and it faces the way the face does, so a person in
 *     the street sees it through the window rather than seeing its back from inside the room.
 */
import { describe, expect, it } from 'vitest';
import { backingPieces, facadePieces, faceCover, panelSurfaceRole } from '../src/core/facades.js';
import type { BackingFields, FacadeFields, FaceFrame, GroundBayFields } from '../src/core/facades.js';
import { panelSteps } from '../src/core/openings.js';
import type { OpeningGridFields, PanelStepFields } from '../src/core/openings.js';
import { massingPieces } from '../src/core/massing.js';
import type { MassingFields } from '../src/core/massing.js';
import type { Plan } from '../src/core/integer-math.js';
import type { Piece } from '../src/core/pieces.js';

const RING: Plan[] = [[0, 0], [12000, 0], [12000, 9000], [0, 9000]];

function block(): MassingFields {
  return {
    base_elevation_mm: 100,
    ground_storey_height_mm: 4500,
    upper_storey_height_mm: 3000,
    storeys: 3,
    tiers: [{ first_storey: 0, last_storey: 2, ring_mm: RING, light_wells_mm: [], parapet_height_mm: 0 }],
    roof_form: 'flat',
    ridge_mm: [],
    roof_rise_mm: 0,
  };
}

function face(over: Partial<FacadeFields> = {}): FacadeFields {
  return {
    identity: 'face',
    building_identity: 'building',
    tier_ordinal: 0,
    edge_ordinal: 0,
    exposure: 'frontage',
    run_length_mm: 12000,
    first_storey: 0,
    last_storey: 2,
    band_top_mm: 4200,
    neighbour_top_mm: 0,
    bays: { count: 0, pitch_mm: 0, margin_start_mm: 0 },
    openings: [],
    ...over,
  };
}

/** One opening grid, in the shape the grammar states it, over what a case wants to change. */
function grid(over: Partial<OpeningGridFields> = {}): OpeningGridFields {
  return {
    storeys: [1],
    u_offset_mm: 600,
    width_mm: 1200,
    height_mm: 1600,
    sill_height_mm: 900,
    reveal_depth_mm: 180,
    head_rise_mm: 0,
    ...over,
  };
}

/** The resolution the city's projections state, which is how far a chord may sit from its circle. */
const RESOLUTION_MM = 1;

/** The frame the expander builds for a face on the first edge of the block's only tier. */
function frameOf(massing: MassingFields, facade: FacadeFields): FaceFrame {
  const base = massing.base_elevation_mm;
  const top = base + massing.ground_storey_height_mm + (facade.last_storey) * massing.upper_storey_height_mm;
  return { from: RING[0]!, to: RING[1]!, run: 12000, datum: base, base, top };
}

/** The area of every piece by role, in the face's own plane, and each role's least depth off it. */
function measure(pieces: readonly Piece[]): { area: Map<string, number>; depth: Map<string, number> } {
  const area = new Map<string, number>();
  const depth = new Map<string, number>();
  for (const piece of pieces) {
    const surface = piece.surface!;
    for (let triangle = 0; triangle + 2 < piece.triangles.length; triangle += 3) {
      const corners = [0, 1, 2].map((corner) => {
        const vertex = piece.triangles[triangle + corner]!;
        return [piece.vertices[vertex * 3]!, piece.vertices[vertex * 3 + 1]!, piece.vertices[vertex * 3 + 2]!];
      }) as [number[], number[], number[]];
      const edge = (from: number[], to: number[]): number[] => [to[0]! - from[0]!, to[1]! - from[1]!, to[2]! - from[2]!];
      const [u, v] = [edge(corners[0], corners[1]), edge(corners[0], corners[2])];
      const cross = [u[1]! * v[2]! - u[2]! * v[1]!, u[2]! * v[0]! - u[0]! * v[2]!, u[0]! * v[1]! - u[1]! * v[0]!];
      area.set(surface.role, (area.get(surface.role) ?? 0) + Math.hypot(...cross) / 2);
      for (const corner of corners) {
        // The face runs along +x from the origin, so the depth into the building is +y.
        const into = corner[1]!;
        const least = depth.get(surface.role);
        depth.set(surface.role, least === undefined ? into : Math.min(least, into));
      }
    }
  }
  return { area, depth };
}

/** The outward normal of a piece's first triangle, which is which way its surface faces. */
function normalOf(piece: Piece): [number, number, number] {
  const corner = (at: number): number[] => {
    const vertex = piece.triangles[at]!;
    return [piece.vertices[vertex * 3]!, piece.vertices[vertex * 3 + 1]!, piece.vertices[vertex * 3 + 2]!];
  };
  const [a, b, c] = [corner(0), corner(1), corner(2)];
  const edge = (from: number[], to: number[]): number[] => [to[0]! - from[0]!, to[1]! - from[1]!, to[2]! - from[2]!];
  const [u, v] = [edge(a, b), edge(a, c)];
  return [u[1]! * v[2]! - u[2]! * v[1]!, u[2]! * v[0]! - u[0]! * v[2]!, u[0]! * v[1]! - u[1]! * v[0]!];
}

describe('the facade rule', () => {
  it('draws the run by its storeys exactly once, as a band below and a wall above', () => {
    const massing = block();
    const facade = face();
    const frame = frameOf(massing, facade);
    const { area } = measure(facadePieces(facade, massing, frame, [], RESOLUTION_MM, 'case'));
    const height = frame.top - frame.base;
    expect(area.get('ground_band')).toBeCloseTo(12000 * 4200, 6);
    expect(area.get('wall')).toBeCloseTo(12000 * (height - 4200), 6);
    expect([...area.values()].reduce((total, value) => total + value, 0)).toBeCloseTo(12000 * height, 6);
  });

  it('cuts one opening per bay per storey out of the wall and returns the wall into each', () => {
    const massing = block();
    // Four bays of 3 m over the whole run, one storey listed, so four openings and not one.
    const facade = face({
      bays: { count: 4, pitch_mm: 3000, margin_start_mm: 0 },
      openings: [grid({ storeys: [1] })],
    });
    const frame = frameOf(massing, facade);
    const { area } = measure(facadePieces(facade, massing, frame, [], RESOLUTION_MM, 'case'));
    const height = frame.top - frame.base;
    const wallHeight = height - 4200;
    const openings = 4 * 1200 * 1600;
    expect(area.get('wall')).toBeCloseTo(12000 * wallHeight - openings, 6);
    // The return is the opening's perimeter by its reveal depth, four times over.
    expect(area.get('trim')).toBeCloseTo(4 * 2 * (1200 + 1600) * 180, 6);
    expect(area.get('ground_band')).toBeCloseTo(12000 * 4200, 6);
    // The face still accounts for its whole rectangle: what is drawn plus what is missing.
    const drawn = [...area.values()].reduce((total, value) => total + value, 0);
    expect(drawn - area.get('trim')! + openings).toBeCloseTo(12000 * height, 6);
  });

  it('cuts an opening in every storey the grid lists, and none where it lists none', () => {
    const massing = block();
    const frame = frameOf(massing, face());
    const areaOf = (storeys: number[]): number => {
      const facade = face({
        bays: { count: 4, pitch_mm: 3000, margin_start_mm: 0 },
        openings: [grid({ storeys })],
      });
      return measure(facadePieces(facade, massing, frame, [], RESOLUTION_MM, 'case')).area.get('wall')!;
    };
    const whole = measure(facadePieces(face(), massing, frame, [], RESOLUTION_MM, 'case')).area.get('wall')!;
    expect(whole - areaOf([1])).toBeCloseTo(4 * 1200 * 1600, 6);
    expect(whole - areaOf([1, 2])).toBeCloseTo(8 * 1200 * 1600, 6);
  });

  it('returns the wall into its opening rather than out of it', () => {
    const massing = block();
    const facade = face({
      bays: { count: 1, pitch_mm: 12000, margin_start_mm: 0 },
      openings: [grid({ storeys: [1], u_offset_mm: 6000 })],
    });
    const frame = frameOf(massing, facade);
    const pieces = facadePieces(facade, massing, frame, [], RESOLUTION_MM, 'case');
    const reveal = pieces.find((piece) => piece.surface!.role === 'trim')!;
    expect(reveal.surface!.orientation).toBe('vertical');
    // The opening runs 6000 to 7200 along a face on +x, its sill at 5500 and its head at 7100, so
    // its middle is (6600, 0, 6300). Every quad of the return faces that point.
    const middle = [6600, 0, 6300];
    for (let triangle = 0; triangle + 2 < reveal.triangles.length; triangle += 3) {
      const corner = (at: number): number[] => {
        const vertex = reveal.triangles[triangle + at]!;
        return [reveal.vertices[vertex * 3]!, reveal.vertices[vertex * 3 + 1]!, reveal.vertices[vertex * 3 + 2]!];
      };
      const [a, b, c] = [corner(0), corner(1), corner(2)];
      const edge = (from: number[], to: number[]): number[] => [to[0]! - from[0]!, to[1]! - from[1]!, to[2]! - from[2]!];
      const [u, v] = [edge(a, b), edge(a, c)];
      const normal = [u[1]! * v[2]! - u[2]! * v[1]!, u[2]! * v[0]! - u[0]! * v[2]!, u[0]! * v[1]! - u[1]! * v[0]!];
      const toward = edge(a, middle);
      const along = normal[0]! * toward[0]! + normal[1]! * toward[1]! + normal[2]! * toward[2]!;
      expect(along).toBeGreaterThan(0);
    }
  });

  it('refuses an opening that falls outside the wall its face draws', () => {
    const massing = block();
    const frame = frameOf(massing, face());
    const cut = (over: Partial<OpeningGridFields>): void => {
      const facade = face({ bays: { count: 4, pitch_mm: 3000, margin_start_mm: 0 }, openings: [grid(over)] });
      facadePieces(facade, massing, frame, [], RESOLUTION_MM, 'case');
    };
    // The wall starts at 4300 and the storey's floor is 4600, so a sill 301 mm below it is outside.
    expect(() => cut({ sill_height_mm: 0 })).not.toThrow();
    expect(() => cut({ storeys: [0] })).toThrow(/below the 4300 mm its face's wall starts at/);
    // The wall ends at 10600, and storey 2's floor is 7600.
    expect(() => cut({ storeys: [2], sill_height_mm: 900, height_mm: 2100 })).not.toThrow();
    expect(() => cut({ storeys: [2], sill_height_mm: 900, height_mm: 2101 })).toThrow(/above the 10600 mm its face's wall ends at/);
    // The last bay starts at 9000, so 2400 of offset and 600 of width just fits the 12000 run.
    expect(() => cut({ u_offset_mm: 2400, width_mm: 600 })).not.toThrow();
    expect(() => cut({ u_offset_mm: 2400, width_mm: 601 })).toThrow(/past the face's 12000 mm run/);
  });

  it('gives the band to its bays, each panel in its own role and at its own recess', () => {
    const massing = block();
    const facade = face();
    const frame = frameOf(massing, facade);
    const bay: GroundBayFields = {
      facade_identity: 'face',
      u_start_mm: 1000,
      width_mm: 6000,
      panels: [
        { role: 'stall_riser', u_start_mm: 1000, u_end_mm: 7000, z_bottom_mm: 0, z_top_mm: 600, recess_mm: 20 },
        { role: 'glazing', u_start_mm: 1000, u_end_mm: 7000, z_bottom_mm: 600, z_top_mm: 3000, recess_mm: 140 },
        { role: 'transom', u_start_mm: 1000, u_end_mm: 7000, z_bottom_mm: 3000, z_top_mm: 3400, recess_mm: 140 },
        { role: 'fascia', u_start_mm: 1000, u_end_mm: 7000, z_bottom_mm: 3400, z_top_mm: 4200, recess_mm: 0 },
      ],
    };
    const { area, depth } = measure(facadePieces(facade, massing, frame, [bay], RESOLUTION_MM, 'case'));
    // The two panes are one surface, since the grammar dresses a transom as glazing.
    expect(panelSurfaceRole('transom', 'case')).toBe('glazing');
    expect(area.get('glazing')).toBeCloseTo(6000 * (2400 + 400), 6);
    expect(area.get('stall_riser')).toBeCloseTo(6000 * 600, 6);
    expect(area.get('fascia')).toBeCloseTo(6000 * 800, 6);
    // The band's own role keeps what no bay covers: 1 m at the start and 5 m past the bay's end.
    expect(area.get('ground_band')).toBeCloseTo((1000 + 5000) * 4200, 6);
    // Each recess is into the building, and the deepest is the glazing's.
    expect(depth.get('stall_riser')).toBeCloseTo(20, 6);
    expect(depth.get('glazing')).toBeCloseTo(140, 6);
    expect(depth.get('fascia')).toBeCloseTo(0, 6);
    // Where the panels step in depth the wall between them is drawn, in the trim role: the riser to
    // the glazing is 120 mm over the bay's 6 m, and the transom to the fascia is 140 mm over it.
    // Without these a shopfront's glass floats behind its own frame.
    expect(area.get('trim')).toBeCloseTo(6000 * 120 + 6000 * 140, 6);
    // Still exactly the run by its storeys, counting every surface once. The returns are drawn
    // ACROSS the face rather than on it, so they are not part of that rectangle.
    const height = frame.top - frame.base;
    const drawn = [...area.values()].reduce((total, value) => total + value, 0);
    expect(drawn - area.get('trim')!).toBeCloseTo(12000 * height, 6);
  });

  it('finds a step where a bay\'s panels share an edge at different depths, and nowhere else', () => {
    const panel = (u: [number, number], z: [number, number], recess: number): PanelStepFields =>
      ({ u_start_mm: u[0], u_end_mm: u[1], z_bottom_mm: z[0], z_top_mm: z[1], recess_mm: recess });
    // Side by side, the deep panel on the right: the step runs DOWN the shared line.
    expect(panelSteps([panel([0, 100], [0, 100], 0), panel([100, 200], [0, 100], 500)], 'case'))
      .toEqual([{ from: [100, 100], to: [100, 0], shallow: 0, deep: 500 }]);
    // Side by side, the deep panel on the left: the same line, run the other way.
    expect(panelSteps([panel([0, 100], [0, 100], 500), panel([100, 200], [0, 100], 0)], 'case'))
      .toEqual([{ from: [100, 0], to: [100, 100], shallow: 0, deep: 500 }]);
    // Stacked, the deep panel above: the line runs right, so the return faces up into the recess.
    expect(panelSteps([panel([0, 100], [0, 100], 0), panel([0, 100], [100, 200], 500)], 'case'))
      .toEqual([{ from: [0, 100], to: [100, 100], shallow: 0, deep: 500 }]);
    // Stacked, the deep panel below: the line runs left, so the return faces down into it.
    expect(panelSteps([panel([0, 100], [0, 100], 500), panel([0, 100], [100, 200], 0)], 'case'))
      .toEqual([{ from: [100, 100], to: [0, 100], shallow: 0, deep: 500 }]);
    // No step at all: the same recess, and panels meeting at a corner rather than along an edge.
    expect(panelSteps([panel([0, 100], [0, 100], 7), panel([100, 200], [0, 100], 7)], 'case')).toEqual([]);
    expect(panelSteps([panel([0, 100], [0, 100], 0), panel([100, 200], [100, 200], 500)], 'case')).toEqual([]);
    // And a step is found only over the part of the line the two panels share.
    expect(panelSteps([panel([0, 100], [0, 100], 0), panel([100, 200], [40, 60], 500)], 'case'))
      .toEqual([{ from: [100, 60], to: [100, 40], shallow: 0, deep: 500 }]);
  });

  it('returns the face across a bay\'s depth steps, facing into the recess', () => {
    const massing = block();
    const facade = face();
    const frame = frameOf(massing, facade);
    // A shopfront: a flush riser and fascia with the glass and its transom set back 140 mm.
    const bay: GroundBayFields = {
      facade_identity: 'face',
      u_start_mm: 1000,
      width_mm: 6000,
      panels: [
        { role: 'stall_riser', u_start_mm: 1000, u_end_mm: 7000, z_bottom_mm: 0, z_top_mm: 600, recess_mm: 0 },
        { role: 'glazing', u_start_mm: 1000, u_end_mm: 7000, z_bottom_mm: 600, z_top_mm: 3400, recess_mm: 140 },
        { role: 'fascia', u_start_mm: 1000, u_end_mm: 7000, z_bottom_mm: 3400, z_top_mm: 4200, recess_mm: 0 },
      ],
    };
    const pieces = facadePieces(facade, massing, frame, [bay], RESOLUTION_MM, 'case');
    const reveal = pieces.find((piece) => piece.surface!.role === 'trim')!;
    // Two steps, the riser to the glass and the glass to the fascia, each 6 m by 140 mm.
    expect(measure([reveal]).area.get('trim')).toBeCloseTo(2 * 6000 * 140, 6);
    // The lower step faces UP into the recess above it and the upper one faces DOWN into it. The
    // face runs along +x, so the two normals must have opposite z and no other component.
    const normals: number[][] = [];
    for (let triangle = 0; triangle + 2 < reveal.triangles.length; triangle += 3) {
      const corner = (at: number): number[] => {
        const vertex = reveal.triangles[triangle + at]!;
        return [reveal.vertices[vertex * 3]!, reveal.vertices[vertex * 3 + 1]!, reveal.vertices[vertex * 3 + 2]!];
      };
      const [a, b, c] = [corner(0), corner(1), corner(2)];
      const edge = (from: number[], to: number[]): number[] => [to[0]! - from[0]!, to[1]! - from[1]!, to[2]! - from[2]!];
      const [u, v] = [edge(a, b), edge(a, c)];
      normals.push([u[1]! * v[2]! - u[2]! * v[1]!, u[2]! * v[0]! - u[0]! * v[2]!, u[0]! * v[1]! - u[1]! * v[0]!]);
    }
    expect(normals).toHaveLength(4);
    for (const normal of normals) {
      expect(normal[0]).toBe(0);
      expect(normal[1]).toBe(0);
    }
    // Two up and two down, since each step is a quad of two triangles.
    expect(normals.filter((normal) => normal[2]! > 0)).toHaveLength(2);
    expect(normals.filter((normal) => normal[2]! < 0)).toHaveLength(2);
  });

  it('scars a party wall above the neighbour and walls it below', () => {
    const massing = block();
    const facade = face({ exposure: 'party_wall', neighbour_top_mm: 7000, band_top_mm: 4200 });
    const frame = frameOf(massing, facade);
    const { area } = measure(facadePieces(facade, massing, frame, [], RESOLUTION_MM, 'case'));
    const top = frame.top - frame.datum;
    expect(area.get('party_wall_scar')).toBeCloseTo(12000 * (top - 7000), 6);
    expect(area.get('wall')).toBeCloseTo(12000 * (7000 - 4200), 6);
    expect(area.get('ground_band')).toBeCloseTo(12000 * 4200, 6);
  });

  it('stands one plane behind the glass, facing out, at the depth and heights it states', () => {
    const massing = block();
    const facade = face();
    const frame = frameOf(massing, facade);
    const backing: BackingFields = {
      identity: 'backing',
      facade_identity: 'face',
      building_identity: 'building',
      u_start_mm: 1000,
      width_mm: 6000,
      sill_mm: 5000,
      height_mm: 4000,
      depth_mm: 700,
    };
    const pieces = backingPieces(backing, facade, frame, 'case');
    const { area, depth } = measure(pieces);
    // One surface, one rectangle, in the role the grammar's material table gives a backing.
    expect(pieces.map((piece) => [piece.surface!.role, piece.surface!.orientation])).toEqual([['wall', 'vertical']]);
    expect([...area.keys()]).toEqual(['wall']);
    expect(area.get('wall')).toBeCloseTo(6000 * 4000, 6);
    // The plane stands its whole depth into the building, not a millimetre of it outside.
    expect(depth.get('wall')).toBeCloseTo(700, 6);
    // Heights are above the BUILDING's base: 100 + 5000, not the face's base plus 5000.
    const heights = pieces.flatMap((piece) => [...Array(piece.vertices.length / 3).keys()].map((vertex) => piece.vertices[vertex * 3 + 2]!));
    expect(Math.min(...heights)).toBe(massing.base_elevation_mm + 5000);
    expect(Math.max(...heights)).toBe(massing.base_elevation_mm + 9000);
    // And it faces the way the face does. The face runs along +x, so out of the building is -y.
    expect(normalOf(pieces[0]!)[1]).toBeLessThan(0);
    expect(normalOf(massingPieces(block(), [], 'case')[0]!)[1]).toBeLessThan(0);
  });

  it('refuses a backing that reaches past the run of the face it is laid out on', () => {
    const facade = face({ run_length_mm: 5000 });
    const frame = frameOf(block(), facade);
    const over = (width: number): BackingFields => ({
      identity: 'backing',
      facade_identity: 'face',
      building_identity: 'building',
      u_start_mm: 1000,
      width_mm: width,
      sill_mm: 5000,
      height_mm: 4000,
      depth_mm: 700,
    });
    expect(() => backingPieces(over(4000), facade, frame, 'case')).not.toThrow();
    expect(() => backingPieces(over(4001), facade, frame, 'case')).toThrow(/reaches 5001 mm along a face whose run is 5000 mm/);
  });

  it('takes its part of the tier edge away from the building\'s own wall', () => {
    const massing = block();
    const facade = face();
    const cover = faceCover(facade, massing, 'case');
    const bare = measure(massingPieces(massing, [], 'case')).area.get('wall')!;
    const left = measure(massingPieces(massing, [cover], 'case')).area.get('wall')!;
    const frame = frameOf(massing, facade);
    // The whole first edge is the face's, so the building keeps the other three.
    expect(bare - left).toBeCloseTo(12000 * (frame.top - frame.base), 6);
    expect(left).toBeCloseTo((12000 + 9000 + 9000) * (frame.top - frame.base), 6);
  });

  it('keeps the building\'s wall where a face covers only part of an edge', () => {
    const massing = block();
    // A short face over the upper storeys only: the building keeps the rest of that edge.
    const facade = face({ run_length_mm: 5000, first_storey: 1, last_storey: 2 });
    const cover = faceCover(facade, massing, 'case');
    const { area } = measure(massingPieces(massing, [cover], 'case'));
    const height = 4500 + 2 * 3000;
    const perimeter = 12000 + 9000 + 12000 + 9000;
    // The face takes 5 m of the first edge over the two upper storeys, and nothing else.
    expect(area.get('wall')).toBeCloseTo(perimeter * height - 5000 * (2 * 3000), 6);
  });
});
