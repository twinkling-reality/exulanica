/**
 * The form parts rule: parts and a facing in, integer triangles out.
 *
 * What these tests prove is arithmetic, not appearance. Nothing here draws a bench or a tree, and
 * nothing here has seen one drawn: the rule is not wired into an expander yet. Every expected value
 * below is either worked by hand in the test itself or produced from the rule's own output, never
 * copied from a run.
 */
import { describe, expect, it } from 'vitest';
import {
  type FormObject,
  type FormPart,
  type FormTriangle,
  FormPartsRefusal,
  expandFormParts,
} from '../src/core/form-parts.js';

/** A part with the fields a box needs; each test changes only what it is about. */
const BOX: FormPart = {
  shape: 'box',
  surfaceRole: 'object_primary',
  offsetXMm: 0,
  offsetYMm: 0,
  offsetZMm: 0,
  sizeXMm: 1000,
  sizeYMm: 600,
  sizeZMm: 400,
  topScaleMillionths: 1_000_000,
  segments: 4,
  rings: 1,
};

const OBJECT: FormObject = {
  xMm: 10_000,
  yMm: 20_000,
  zMm: 0,
  facingDxMm: 1,
  facingDyMm: 0,
  parts: [BOX],
};

const object = (over: Partial<FormObject>): FormObject => ({ ...OBJECT, ...over });
const withPart = (over: Partial<FormPart>): FormObject =>
  object({ parts: [{ ...BOX, ...over }] });

function refusalOf(run: () => unknown): string {
  try {
    run();
  } catch (error) {
    if (error instanceof FormPartsRefusal) return error.reason;
    throw error;
  }
  throw new Error('expected a refusal, got triangles');
}

function corners(triangles: readonly FormTriangle[]): Set<string> {
  const out = new Set<string>();
  for (const triangle of triangles) {
    for (const vertex of triangle.vertices) {
      out.add(`${vertex.xMm},${vertex.yMm},${vertex.zMm}`);
    }
  }
  return out;
}

describe('a box, where the arithmetic can be done by hand', () => {
  it('puts its eight corners exactly where its sizes and its offset say', () => {
    // Facing +x is the identity turn, so local millimetres are world millimetres: the box spans
    // 1000 by 600 by 400 about (10000, 20000, 0), and its offset places its bottom centre.
    const triangles = expandFormParts(OBJECT);
    expect(corners(triangles)).toEqual(
      new Set([
        '10500,19700,0', '10500,20300,0', '9500,20300,0', '9500,19700,0',
        '10500,19700,400', '10500,20300,400', '9500,20300,400', '9500,19700,400',
      ]),
    );
  });

  it('makes twelve triangles: two for each of six faces', () => {
    expect(expandFormParts(OBJECT)).toHaveLength(12);
  });

  it('turns by the facing vector exactly when the facing is a Pythagorean one', () => {
    // A 3, 4, 5 facing has an exact unit vector, (600000, 800000) at the measure's scale, so a
    // point 500 mm along the part's local +x lands 300 east and 400 north of the object with no
    // rounding at all. The box's front face centre is at local (500, 0).
    const triangles = expandFormParts(object({ facingDxMm: 3, facingDyMm: 4 }));
    const places = corners(triangles);
    // Local (500, -300) turns to (10000 + 300 + 240, 20000 + 400 - 180) = (10540, 20220).
    expect(places.has('10540,20220,0')).toBe(true);
    // Local (-500, 300), the opposite corner, turns to (9460, 19780).
    expect(places.has('9460,19780,0')).toBe(true);
  });

  it('gives the same triangles for a facing of any length, since a direction is not a magnitude', () => {
    const once = expandFormParts(object({ facingDxMm: 3, facingDyMm: 4 }));
    const scaled = expandFormParts(object({ facingDxMm: 300, facingDyMm: 400 }));
    expect(scaled).toEqual(once);
  });

  it('measures s round the part from its local +x and t down from the object base', () => {
    const triangles = expandFormParts(OBJECT);
    const sides = triangles.filter((triangle) => triangle.orientation === 'vertical');
    expect(sides).toHaveLength(8);
    const walk = new Set(sides.flatMap((side) => side.vertices.map((vertex) => vertex.sMm)));
    // The four corners sit at 0, 600, 1600 and 2200 round a 1000 by 600 box, and the walk closes
    // at its perimeter, 3200.
    expect([...walk].sort((a, b) => a - b)).toEqual([0, 600, 1600, 2200, 3200]);
    for (const side of sides) {
      for (const vertex of side.vertices) {
        // t = base - z, the grammar's own form, which points down from the object's own z_mm.
        expect(vertex.tMm).toBe(OBJECT.zMm - vertex.zMm);
      }
    }
  });

  it('gives the top s = +x and t = +y, and the underside s = +x and t = -y', () => {
    // The grammar's invariant is that t is always to the left of s, seen from the side the face is
    // seen from. Under a part, left of +x is -y, so an underside's t is the negated plan y; the
    // same pair as the top would read mirrored there.
    const flat = expandFormParts(OBJECT).filter((t) => t.orientation === 'horizontal');
    expect(flat).toHaveLength(4);
    const tops = flat.filter((triangle) => triangle.vertices.every((v) => v.zMm === 400));
    const undersides = flat.filter((triangle) => triangle.vertices.every((v) => v.zMm === 0));
    expect(tops).toHaveLength(2);
    expect(undersides).toHaveLength(2);
    for (const triangle of tops) {
      for (const vertex of triangle.vertices) {
        expect(vertex.sMm).toBe(vertex.xMm);
        expect(vertex.tMm).toBe(vertex.yMm);
      }
    }
    for (const triangle of undersides) {
      for (const vertex of triangle.vertices) {
        expect(vertex.sMm).toBe(vertex.xMm);
        expect(vertex.tMm).toBe(-vertex.yMm);
      }
    }
  });

  it('emits an underside at all, which a part lifted clear of the ground shows', () => {
    const undersides = expandFormParts(withPart({ offsetZMm: 900 })).filter(
      (triangle) => triangle.orientation === 'horizontal'
        && triangle.vertices.every((vertex) => vertex.zMm === 900),
    );
    expect(undersides).toHaveLength(2);
    for (const vertex of undersides[0]!.vertices) expect(vertex.tMm).toBe(-vertex.yMm);
  });
});

describe('the circle, built by chord bisection so that no sine is taken', () => {
  it('puts a four sided prism\'s first vertex on local +x', () => {
    const triangles = expandFormParts(
      withPart({ shape: 'prism', sizeXMm: 1000, sizeYMm: 1000, segments: 4 }),
    );
    // The polygon is inscribed in the 1000 by 1000 ellipse, so its vertices are 500 from the
    // centre on each axis, and the first is on +x, which the identity facing sends east.
    expect(corners(triangles).has('10500,20000,0')).toBe(true);
    expect(corners(triangles).has('10000,20500,0')).toBe(true);
  });

  it('bisects to the 45 degree point the measure gives, and not to a rounded one', () => {
    // isqrt(2 * S^2 * S^2) = 1414213562373 with S = 10^6, so the unit point is
    // floor(10^18 / 1414213562373) = 707106, and a 2000 wide ellipse puts the vertex at
    // floor(2000 * 707106 / 10^6) = 1414 half millimetres, which is 707 mm from the centre.
    const triangles = expandFormParts(
      withPart({ shape: 'prism', sizeXMm: 2000, sizeYMm: 2000, segments: 8 }),
    );
    expect(corners(triangles).has('10707,20707,0')).toBe(true);
  });

  it('counts a prism\'s triangles as two a side plus two fans, and a cone\'s as one a side', () => {
    const prism = expandFormParts(withPart({ shape: 'prism', segments: 8 }));
    expect(prism).toHaveLength(2 * 8 + 6 + 6);
    const cone = expandFormParts(
      withPart({ shape: 'prism', segments: 8, topScaleMillionths: 0 }),
    );
    // A cone has no top face, and each of its sides is a single triangle to the apex.
    expect(cone).toHaveLength(8 + 6);
  });

  it('tapers a prism by its top scale, in millionths', () => {
    const half = expandFormParts(
      withPart({ shape: 'prism', sizeXMm: 1000, sizeYMm: 1000, segments: 4, topScaleMillionths: 500_000 }),
    );
    const top = [...corners(half)].filter((place) => place.endsWith(',400'));
    expect(top).toContain('10250,20000,400');
  });
});

describe('an ellipsoid, whose surface the grammar\'s two frames do not cover', () => {
  const canopy: Partial<FormPart> = {
    shape: 'ellipsoid',
    surfaceRole: 'canopy',
    sizeXMm: 2000,
    sizeYMm: 2000,
    sizeZMm: 2000,
    segments: 8,
    rings: 4,
  };

  it('collapses its poles to one triangle a meridian rather than a zero area quad', () => {
    const triangles = expandFormParts(withPart(canopy));
    // Two polar bands of 8 triangles and two middle bands of 16.
    expect(triangles).toHaveLength(2 * 8 * (4 - 1));
    for (const triangle of triangles) {
      const [a, b, c] = triangle.vertices;
      const area = Math.abs(
        (b.xMm - a.xMm) * (c.yMm - a.yMm) - (b.yMm - a.yMm) * (c.xMm - a.xMm),
      ) + Math.abs(
        (b.xMm - a.xMm) * (c.zMm - a.zMm) - (b.zMm - a.zMm) * (c.xMm - a.xMm),
      );
      expect(area).toBeGreaterThan(0);
    }
  });

  it('fills its sizes: its poles sit at the bottom and the top of size_z', () => {
    const triangles = expandFormParts(withPart(canopy));
    const heights = [...new Set(triangles.flatMap((t) => t.vertices.map((v) => v.zMm)))];
    expect(Math.min(...heights)).toBe(0);
    expect(Math.max(...heights)).toBe(2000);
  });

  it('gives a downward leaning triangle the underside frame, not the top\'s', () => {
    // The lower cap of a canopy is seen from below, so its t is negated there too, by the same
    // left-of-s invariant that settles a part's underside.
    const triangles = expandFormParts(withPart(canopy));
    const low = triangles.filter(
      (triangle) => triangle.orientation === 'horizontal'
        && triangle.vertices.every((vertex) => vertex.zMm < 1000),
    );
    expect(low.length).toBeGreaterThan(0);
    for (const triangle of low) {
      for (const vertex of triangle.vertices) expect(vertex.tMm).toBe(-vertex.yMm);
    }
  });

  it('gives each triangle the frame its own normal leans towards', () => {
    const triangles = expandFormParts(withPart(canopy));
    const flat = triangles.filter((triangle) => triangle.orientation === 'horizontal');
    const upright = triangles.filter((triangle) => triangle.orientation === 'vertical');
    // The polar bands lean towards horizontal and the two middle bands towards vertical; this
    // asserts both frames are reached, not a particular count, because the count follows from the
    // ring count and would say nothing extra.
    expect(flat.length).toBeGreaterThan(0);
    expect(upright.length).toBeGreaterThan(0);
    expect(flat.length + upright.length).toBe(triangles.length);
  });

  it('keeps one walk round the widest band, so a meridian holds its s from pole to pole', () => {
    const triangles = expandFormParts(withPart(canopy)).filter((t) => t.orientation === 'vertical');
    const walks = new Set(triangles.flatMap((t) => t.vertices.map((v) => v.sMm)));
    // Nine values: eight meridians and the closing of the walk. A per band walk would give more.
    expect(walks.size).toBe(9);
  });
});

describe('the two things a mutation of the rule proved these tests could not see', () => {
  // Both of these were written after breaking the rule on purpose: winding was reversed and the
  // ellipse's two plan sizes were swapped, and every test above still passed. A docstring claim no
  // test holds is the failure this project spent a day naming, so here are the tests.

  /** Twice the triangle's normal, from its own two edges. */
  function normal(triangle: FormTriangle): readonly [number, number, number] {
    const [a, b, c] = triangle.vertices;
    const u = [b.xMm - a.xMm, b.yMm - a.yMm, b.zMm - a.zMm] as const;
    const v = [c.xMm - a.xMm, c.yMm - a.yMm, c.zMm - a.zMm] as const;
    return [
      u[1] * v[2] - u[2] * v[1],
      u[2] * v[0] - u[0] * v[2],
      u[0] * v[1] - u[1] * v[0],
    ];
  }

  it('winds every triangle of a solid so its normal points away from the inside', () => {
    // Each of these parts is convex, so the mean of its vertices lies inside it, and a triangle
    // wound counter-clockwise seen from outside has a normal pointing away from that point. A
    // solid wound inside out fails here and nowhere else.
    for (const part of [
      { shape: 'box' } as const,
      { shape: 'prism', segments: 8 } as const,
      { shape: 'prism', segments: 8, topScaleMillionths: 0 } as const,
      { shape: 'ellipsoid', segments: 8, rings: 4, sizeXMm: 900, sizeYMm: 700, sizeZMm: 500 } as const,
    ]) {
      const triangles = expandFormParts(withPart(part));
      const vertices = triangles.flatMap((triangle) => triangle.vertices);
      const inside = [0, 1, 2].map((axis) =>
        vertices.reduce((total, vertex) => total + [vertex.xMm, vertex.yMm, vertex.zMm][axis]!, 0)
        / vertices.length);
      for (const triangle of triangles) {
        const face = normal(triangle);
        const outward = [0, 1, 2].map((axis) => {
          const corner = triangle.vertices[0]!;
          return [corner.xMm, corner.yMm, corner.zMm][axis]! - inside[axis]!;
        });
        const dot = face[0] * outward[0]! + face[1] * outward[1]! + face[2] * outward[2]!;
        expect(dot, `${part.shape} ${JSON.stringify(triangle.vertices)}`).toBeGreaterThan(0);
      }
    }
  });

  it('inscribes a prism in the ellipse its two sizes state, which a square footprint hides', () => {
    // 2000 by 1000 with four segments: the vertex on +x is 1000 from the centre and the one on +y
    // is 500. Swapping the two sizes passes every test that uses a square part.
    const triangles = expandFormParts(
      withPart({ shape: 'prism', sizeXMm: 2000, sizeYMm: 1000, segments: 4 }),
    );
    expect(corners(triangles).has('11000,20000,0')).toBe(true);
    expect(corners(triangles).has('10000,20500,0')).toBe(true);
    expect(corners(triangles).has('9000,20000,0')).toBe(true);
    expect(corners(triangles).has('10000,19500,0')).toBe(true);
  });
});

describe('what the rule refuses by name rather than guessing', () => {
  it('refuses a facing of zero, which is not a direction', () => {
    expect(refusalOf(() => expandFormParts(object({ facingDxMm: 0, facingDyMm: 0 })))).toBe('facing');
  });

  it('refuses a facing component past the grammar\'s direction limit', () => {
    expect(refusalOf(() => expandFormParts(object({ facingDxMm: 1_000_001, facingDyMm: 0 })))).toBe(
      'facing',
    );
  });

  it('refuses an object with no parts', () => {
    expect(refusalOf(() => expandFormParts(object({ parts: [] })))).toBe('parts');
  });

  it('refuses a shape it does not know', () => {
    const part = { ...BOX, shape: 'wedge' } as unknown as FormPart;
    expect(refusalOf(() => expandFormParts(object({ parts: [part] })))).toBe('shape');
  });

  it('refuses a surface role outside the grammar\'s part roles', () => {
    expect(refusalOf(() => expandFormParts(withPart({ surfaceRole: 'fascia' })))).toBe('role');
  });

  it('refuses a size of zero, which would be a solid with no thickness', () => {
    expect(refusalOf(() => expandFormParts(withPart({ sizeZMm: 0 })))).toBe('size');
  });

  it('refuses the counts each shape does not allow', () => {
    expect(refusalOf(() => expandFormParts(withPart({ segments: 8 })))).toBe('counts');
    expect(refusalOf(() => expandFormParts(withPart({ shape: 'prism', segments: 5 })))).toBe('counts');
    expect(refusalOf(() => expandFormParts(withPart({ shape: 'prism', segments: 8, rings: 2 })))).toBe(
      'counts',
    );
    expect(
      refusalOf(() => expandFormParts(withPart({ shape: 'ellipsoid', segments: 8, rings: 3 }))),
    ).toBe('counts');
  });

  it('refuses a taper where the shape does not take one', () => {
    expect(refusalOf(() => expandFormParts(withPart({ topScaleMillionths: 500_000 })))).toBe('taper');
    expect(
      refusalOf(() =>
        expandFormParts(
          withPart({ shape: 'ellipsoid', segments: 8, rings: 4, topScaleMillionths: 500_000 }),
        ),
      ),
    ).toBe('taper');
    expect(refusalOf(() => expandFormParts(withPart({ topScaleMillionths: 1_000_001 })))).toBe('taper');
  });

  it('refuses a value that is not a whole number of millimetres', () => {
    expect(refusalOf(() => expandFormParts(withPart({ offsetXMm: 12.5 })))).toBe('offset');
    expect(refusalOf(() => expandFormParts(object({ xMm: 0.5 })))).toBe('offset');
  });

  it('refuses a part so large that a vertex would leave what a double holds exactly', () => {
    expect(refusalOf(() => expandFormParts(withPart({ sizeXMm: 9_007_199_254_740_990 })))).toBe(
      'range',
    );
  });
});

describe('the properties the tessellator will rely on', () => {
  const tree: FormObject = object({
    facingDxMm: 7,
    facingDyMm: -3,
    parts: [
      { ...BOX, shape: 'prism', surfaceRole: 'trunk', sizeXMm: 300, sizeYMm: 300, sizeZMm: 3000, segments: 8 },
      {
        ...BOX,
        shape: 'ellipsoid',
        surfaceRole: 'canopy',
        offsetZMm: 2600,
        sizeXMm: 4000,
        sizeYMm: 4000,
        sizeZMm: 3000,
        segments: 16,
        rings: 8,
      },
    ],
  });

  it('gives every vertex as a whole number of millimetres', () => {
    for (const triangle of expandFormParts(tree)) {
      for (const vertex of triangle.vertices) {
        for (const value of [vertex.xMm, vertex.yMm, vertex.zMm, vertex.sMm, vertex.tMm]) {
          expect(Number.isSafeInteger(value)).toBe(true);
        }
      }
    }
  });

  it('gives the same triangles twice, from the same records', () => {
    expect(expandFormParts(tree)).toEqual(expandFormParts(tree));
  });

  it('carries each part\'s surface role through to its own triangles', () => {
    const roles = new Set(expandFormParts(tree).map((triangle) => triangle.surfaceRole));
    expect([...roles].sort()).toEqual(['canopy', 'trunk']);
  });

  it('keeps every vertex inside the extent the part states, however the object is turned', () => {
    // A part reaches at most the diagonal of its own plan sizes from the object, whichever way it
    // is turned, and in height it spans its offset to its offset plus its size. The tile document
    // refuses a vertex outside a record's extent, so this is the property that matters there.
    for (const triangle of expandFormParts(tree)) {
      for (const vertex of triangle.vertices) {
        const reach = Math.hypot(vertex.xMm - tree.xMm, vertex.yMm - tree.yMm);
        expect(reach).toBeLessThanOrEqual(Math.hypot(4000, 4000) / 2 + 1);
        expect(vertex.zMm).toBeGreaterThanOrEqual(0);
        expect(vertex.zMm).toBeLessThanOrEqual(2600 + 3000);
      }
    }
  });

  it('holds no floating point arithmetic in the rule itself', async () => {
    const source = await import('node:fs/promises').then((fs) =>
      fs.readFile(new URL('../src/core/form-parts.ts', import.meta.url), 'utf8'),
    );
    for (const banned of ['Math.sin', 'Math.cos', 'Math.sqrt', 'Math.atan', 'Math.PI']) {
      expect(source.includes(banned), banned).toBe(false);
    }
  });
});
