/**
 * Recompute the visual gate's integrity measurement from containers alone, with no browser.
 *
 *   npx tsx web/scripts/recompute-gate-integrity.ts <container directory> [options]
 *     --record <run.json>   a scored run record: take cull per texture set from it, and print
 *                           every recomputed figure beside the one the run measured
 *     --float64             hold vertices exactly as the container states them, instead of the
 *                           float32 the renderer holds them in
 *     --classify            list every detached component with what it is and what is near it
 *
 * WHY. `componentsDetachedFromSupport` decides `noCutsOrFloatingGeometry`, and on a generated
 * target it decides it alone: the gate hands such a target no obstacle prisms, so two of that key's
 * four inputs cannot be non-zero. Until now the number could only be produced by running the whole
 * harness against a live store, and the twelve examples it carries were all anyone could say about
 * what it counted. This reads the same containers the harness reads and calls the gate's OWN
 * `components`, `classify` and `integrity`, so it is not a second implementation of the rule.
 *
 * WHAT IT IS NOT. It is not the harness. The harness measures what the renderer drew, and two facts
 * about drawing are not in a container:
 *
 *   - CULL. A texture set the look draws double sided makes downward faces count as floor, which
 *     changes which components hold a walking triangle and therefore which can be support roots.
 *     Given `--record` the cull of every set is read from that run's own mesh list; without one,
 *     every textured set is assumed back-face culled and the assumption is printed. Unavailable
 *     surfaces are always double sided, which `unavailable-surface.ts` states outright.
 *   - PRECISION. The harness reads `new Float32Array(...)` from the renderer's vertex buffer, so
 *     the gate measures the container's integers after a single-precision round trip, about
 *     0.03 mm at 300 m. That is the DEFAULT here for the same reason. It matters more than it
 *     sounds: measured on the composed corridor, float64 gives 490 detached and float32 gives 351,
 *     against the page's 322, because the city is dimensioned on a 50 mm module
 *     (`DIMENSION_MODULE_MM`) and the gate tests contact at 50 mm, so a great many gaps in the
 *     world sit exactly on the threshold and are decided by the last bit. Use `--float64` to see
 *     the geometry's own answer, and do not expect it to match a run.
 *
 * So a figure from this tool is the container's answer, not the page's, and the two agree only
 * where nothing sits on the tolerance. `components` and `drawnTriangles` do agree exactly, which is
 * what makes the ones that do not interesting.
 */
import { readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { absoluteVertices, decodeOwd } from '../packages/loom-tess/src/core/index.js';
import {
  composedSupport,
  tileToRenderer,
} from '../packages/atlas-react/src/playcanvas/generated-tile/tile-navigation.js';
import {
  SupportSamples,
  TriangleTable,
  classify,
  componentQueryPoints,
  components,
  integrity,
  pointTriangleDistance,
  type CullMode,
  type DrawnMesh,
} from '../packages/loom-gate/src/index.js';

const UNAVAILABLE = 'generated-tile:unavailable-surfaces#0';
/** The material state a surface carries when no material record dresses it. */
const MATERIAL_NONE = 'none_exists';

interface Options {
  readonly directory: string;
  readonly record: string | null;
  readonly float32: boolean;
  readonly classify: boolean;
}

function options(argv: readonly string[]): Options {
  const rest = argv.slice(2);
  const directory = rest.find((value) => !value.startsWith('--'));
  if (directory === undefined) throw new Error('name the directory holding the .owd containers');
  const at = rest.indexOf('--record');
  return {
    directory: resolve(directory),
    record: at === -1 ? null : rest[at + 1] ?? null,
    float32: !rest.includes('--float64'),
    classify: rest.includes('--classify'),
  };
}

/** The texture set a drawn surface cites, or the unavailable mesh when nothing dresses it. */
function setOfSurface(records: readonly any[], surface: any): string {
  const material = surface.material;
  if (material === undefined || material.state === MATERIAL_NONE) return UNAVAILABLE;
  const cited = records[material.record];
  const setId = cited?.fields?.['texture_set_id'];
  if (typeof setId !== 'string' || cited.version !== 2) return UNAVAILABLE;
  const integers = ['repeat_size_millionths', 'uv_rotation_urad', 'uv_offset_u_mm', 'uv_offset_v_mm'];
  for (const field of integers) {
    const value = cited.fields[field];
    if (typeof value !== 'number' || !Number.isSafeInteger(value)) return UNAVAILABLE;
  }
  if ((cited.fields['repeat_size_millionths'] as number) <= 0) return UNAVAILABLE;
  return `generated-tile:${setId}#0`;
}

const option = options(process.argv);
const run = option.record === null ? null : JSON.parse(readFileSync(option.record, 'utf8'));

/** Cull per texture set: from the run's own mesh list, or the stated assumption. */
const cullOfSet = new Map<string, CullMode>();
if (run !== null) {
  for (const mesh of run.scene.meshes) cullOfSet.set(mesh.id.split('/')[2]!, mesh.cull);
} else {
  cullOfSet.set(UNAVAILABLE, 'none');
}
const assumed: string[] = [];
const cullOf = (set: string): CullMode => {
  const known = cullOfSet.get(set);
  if (known !== undefined) return known;
  assumed.push(set);
  return set === UNAVAILABLE ? 'none' : 'back';
};

const files = readdirSync(option.directory).filter((name) => name.endsWith('.owd')).sort();
if (files.length === 0) throw new Error(`no .owd container in ${option.directory}`);

const meshes: DrawnMesh[] = [];
const navTiles: { tile: string; projection: any }[] = [];
/** Per built triangle, in table order, what record it came from. */
const kindOf: string[] = [];
const tileOf: string[] = [];

for (const file of files) {
  const name = file.replace(/\.owd$/, '');
  const decoded: any = decodeOwd(new Uint8Array(readFileSync(`${option.directory}/${file}`)));
  const render: any = decoded.projections.find((p: any) => p.header.name === 'render_batch');
  const nav: any = decoded.projections.find((p: any) => p.header.name === 'nav_envelope');
  if (render === undefined || nav === undefined) throw new Error(`${name} carries no ${render === undefined ? 'render_batch' : 'nav_envelope'}`);
  navTiles.push({ tile: name, projection: nav });
  const vertices = absoluteVertices(render);
  const records = decoded.header.records;
  const bySet = new Map<string, { triangles: number[]; kinds: string[] }>();
  for (const entry of render.header.entries) {
    // Only what this tile OWNS is drawn. A halo record is the neighbour's own copy and drawing it
    // would put the same building in the world twice.
    if (entry.state !== 'drawn') continue;
    const kind = records[entry.record]!.kind;
    let covered = 0;
    for (const surface of entry.surfaces) {
      const set = setOfSurface(records, surface);
      const bucket = bySet.get(set) ?? { triangles: [], kinds: [] };
      for (let t = surface.first_triangle; t < surface.first_triangle + surface.triangle_count; t += 1) {
        for (let corner = 0; corner < 3; corner += 1) {
          const v = render.index[t * 3 + corner]!;
          const point = tileToRenderer(vertices[v * 3]!, vertices[v * 3 + 1]!, vertices[v * 3 + 2]!);
          for (const value of point) bucket.triangles.push(option.float32 ? Math.fround(value) : value);
        }
        bucket.kinds.push(kind);
      }
      bySet.set(set, bucket);
      covered += surface.triangle_count;
    }
    if (covered !== entry.triangle_count) {
      throw new Error(`${name} record ${entry.record}: its surfaces cover ${covered} of ${entry.triangle_count} triangles`);
    }
  }
  for (const [set, bucket] of bySet) {
    meshes.push({
      id: `geographic-environment/${name}/${set}`,
      triangles: Float64Array.from(bucket.triangles),
      cull: cullOf(set),
      hasUv: true,
      decodedTextureBytes: set === UNAVAILABLE ? 1 : 4096,
    });
    for (const kind of bucket.kinds) { kindOf.push(kind); tileOf.push(name); }
  }
}

console.log(`${files.length} containers, ${meshes.length} meshes, vertices held as ` +
  `${option.float32 ? 'float32, as the renderer holds them' : 'float64, as the container states them'}`);
if (assumed.length > 0) {
  console.log(`ASSUMED back-face culling for ${new Set(assumed).size} texture sets, because no ` +
    `--record was given. A set the look draws double sided is taken for single sided here, which ` +
    `can change which components hold a walking triangle and so which can be support roots.`);
}

const support = composedSupport(navTiles);
const table = new TriangleTable(meshes);
const parts = components(table);
const centroids = table.centroidQueryPoints();
const lowest = componentQueryPoints(parts.list);
const points = new Float64Array(centroids.length + lowest.length);
points.set(centroids);
points.set(lowest, centroids.length);
const heights: (number | null)[] = [];
for (let i = 0; i < points.length; i += 2) {
  // The page's own sampler, in the units `SAMPLE_SUPPORT` hands it: renderer metres.
  const sample = support.surface.sample(points[i]!, points[i + 1]!);
  heights.push(sample === null ? null : sample.height);
}
const samples = new SupportSamples(points, heights);
const classification = classify(table, [], samples);
const result = integrity(table, classification, [], parts, samples);

const figures: [string, number][] = [
  ['drawnTriangles', table.count],
  ['walkingTriangles', classification.walkingTriangles],
  ['components', result.components],
  ['supportComponents', result.supportComponents],
  ['componentsDetachedFromSupport', result.componentsDetachedFromSupport],
  ['detachedTriangles', result.detachedTriangles],
];
const measured = run?.measured;
console.log('\n' + 'field'.padEnd(32) + 'recomputed'.padStart(12) + (measured ? 'the run'.padStart(12) + '  agree' : ''));
for (const [name, value] of figures) {
  const theirs = measured === undefined ? null
    : name in measured ? measured[name]
      : (measured.integrity as Record<string, number>)[name] ?? null;
  const tail = theirs === null ? '' : String(theirs).padStart(12) + '  ' + (theirs === value ? 'yes' : 'NO');
  console.log(name.padEnd(32) + String(value).padStart(12) + tail);
}
console.log(`\ncomposed support: ${support.triangles} envelope triangles over ${support.tiles.length} tiles`);

if (!option.classify) {
  console.log('\nPass --classify to list the detached components and what stands near them.');
} else if (result.detachedExamples.length < result.componentsDetachedFromSupport) {
  console.log(`\nThe measurement lists ${result.detachedExamples.length} of its ` +
    `${result.componentsDetachedFromSupport} detached components, so they cannot all be named from ` +
    `here. Raising that cap in loom-gate is the only way to classify the rest.`);
} else {
  const byLowest = new Map<string, number>();
  parts.list.forEach((component, index) => {
    byLowest.set(component.lowest.map((v) => Math.round(v * 1000)).join(','), index);
  });
  const detached = new Set<number>();
  for (const example of result.detachedExamples) {
    const index = byLowest.get(example.lowestMm.join(','));
    if (index !== undefined) detached.add(index);
  }
  const byKind = new Map<string, { count: number; triangles: number; toReached: number[] }>();
  for (const index of detached) {
    const component = parts.list[index]!;
    let toReached = Infinity;
    for (const v of component.vertices) {
      const reach = Math.min(toReached, 2);
      table.grid.query(v[0] - reach, v[2] - reach, v[0] + reach, v[2] + reach, (t) => {
        const other = parts.of[t]!;
        if (other === index || detached.has(other)) return;
        const d = pointTriangleDistance(v, table.vertex(t, 0), table.vertex(t, 1), table.vertex(t, 2));
        if (d < toReached) toReached = d;
      });
    }
    const kind = kindOf[component.triangles[0]!]!;
    const seen = byKind.get(kind) ?? { count: 0, triangles: 0, toReached: [] };
    seen.count += 1;
    seen.triangles += component.triangles.length;
    seen.toReached.push(Math.round(toReached * 1e6) / 1000);
    byKind.set(kind, seen);
  }
  console.log('\nthe detached components, by the kind of record they came from,');
  console.log('with how far each is from the nearest component the measurement DID reach:\n');
  for (const [kind, seen] of [...byKind].sort((a, b) => b[1].count - a[1].count)) {
    const sorted = [...seen.toReached].sort((a, b) => a - b);
    console.log(`  ${String(seen.count).padStart(5)}  ${kind.padEnd(24)} ${String(seen.triangles).padStart(7)} triangles, ` +
      `nearest reached ${sorted[0]} to ${sorted[sorted.length - 1]} mm`);
  }
}
