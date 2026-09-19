import { createHash } from 'node:crypto';
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { REPOSITORY_ROOT } from './support.js';

const CITY_GRAMMAR_DIR = join(REPOSITORY_ROOT, 'exulanica', 'grammar', 'grammars', 'city');
/** The shape table the fixture builder writes, which is always the version the Python code describes. */
const LIVE_SHAPE_TABLE = join(REPOSITORY_ROOT, 'tests', 'fixtures', 'city-v2', 'record-shapes.json');
const TILE_RECORD_KIND = 'city.tile';

export interface TableSource {
  readonly version: number;
  readonly descriptor: string;
  readonly shapes: string;
}

function readJson(path: string): any {
  return JSON.parse(readFileSync(path, 'utf8'));
}

/**
 * Every city grammar version a table can be built for, with the two files it is built from.
 *
 * THE VERSIONS COME FROM THE DESCRIPTORS ON DISK rather than from a list here, so a version added
 * beside them is picked up instead of silently skipped. A descriptor with no `stages` declares no
 * record kinds and is not a version a tessellator can read, which is what leaves city version 1 out.
 *
 * The shape table for a SUPERSEDED version is the frozen `city-shapes.vN.json` beside its
 * descriptor; for the version the Python code currently describes it is what the fixture builder
 * last wrote, because `describe_shapes` runs over the live shapes and those are one version. That
 * pairing is not assumed: each source's `city.tile` record version is compared against the version
 * that descriptor's own tile stage declares, so a frozen file paired with the wrong descriptor, or
 * the live table read for a version it is not, fails here rather than inside a table nobody can
 * explain afterwards.
 */
export function cityTableSources(): TableSource[] {
  const sources: TableSource[] = [];
  for (const name of readdirSync(CITY_GRAMMAR_DIR).sort()) {
    const match = /^city\.v(\d+)\.json$/.exec(name);
    if (match === null) continue;
    const descriptor = join(CITY_GRAMMAR_DIR, name);
    if (readJson(descriptor).stages === undefined) continue;
    const frozen = join(CITY_GRAMMAR_DIR, `city-shapes.v${match[1]}.json`);
    sources.push({
      version: Number(match[1]),
      descriptor,
      shapes: existsSync(frozen) ? frozen : LIVE_SHAPE_TABLE,
    });
  }
  if (sources.length === 0) throw new Error(`no city descriptor with stages under ${CITY_GRAMMAR_DIR}`);
  for (const source of sources) {
    const declared = readJson(source.descriptor)
      .stages.flatMap((stage: any) => stage.records)
      .find((record: any) => record.kind === TILE_RECORD_KIND);
    const stated = readJson(source.shapes).records.find((shape: any) => shape.kind === TILE_RECORD_KIND);
    if (declared === undefined || stated === undefined) {
      throw new Error(`city v${source.version}: no ${TILE_RECORD_KIND} in ${source.descriptor} or ${source.shapes}`);
    }
    if (declared.version !== stated.version) {
      throw new Error(
        `city v${source.version}: ${source.descriptor} declares ${TILE_RECORD_KIND} version ${declared.version} `
          + `and ${source.shapes} states version ${stated.version}, so those two files are not one grammar version`,
      );
    }
  }
  return sources;
}

/** The grammar table for one city version, as that version's own files state it. */
export function grammarTableFromSources(version: number): unknown {
  const sources = cityTableSources();
  const source = sources.find((candidate) => candidate.version === version);
  if (source === undefined) {
    throw new Error(`no city grammar version ${version}; the tree holds ${JSON.stringify(sources.map((c) => c.version))}`);
  }
  const shapes: unknown = readJson(source.shapes);
  const descriptor = readJson(source.descriptor) as {
    grammar_id: string;
    grammar_version: number;
    frame: unknown;
    projections: { projection: string; resolution_mm: number; preserved: { property: string; measures?: unknown }[] }[];
    navigation: { kind: string; ground: string; cover: string; obstruction: string; reason: string }[];
  };
  // The integer measures each projection's contract states for a preserved property, by projection
  // and property; rows with no measures, and projections with none, are left out.
  const measures: { [projection: string]: { [property: string]: unknown } } = {};
  for (const projection of descriptor.projections) {
    for (const row of projection.preserved) {
      if (row.measures === undefined) continue;
      measures[projection.projection] = { ...measures[projection.projection], [row.property]: row.measures };
    }
  }
  // The resolution every projection's contract states, which a rule that cuts an arc into chords
  // reads instead of choosing a segment count.
  const resolutions: { [projection: string]: number } = {};
  for (const projection of descriptor.projections) resolutions[projection.projection] = projection.resolution_mm;
  return {
    grammar_id: descriptor.grammar_id,
    grammar_version: descriptor.grammar_version,
    // The digest of the descriptor's own bytes, which is what a tile's grammar entry pins. A
    // reader holding this table can then tell whether it is the table a container was baked
    // against, which the grammar version alone cannot say: a descriptor edited within a version
    // moves this and moves nothing else a container carries.
    descriptor_sha256: createHash('sha256').update(readFileSync(source.descriptor)).digest('hex'),
    frame: descriptor.frame,
    measures,
    resolutions,
    // The navigation table's data, row by row; each row's reason is prose and stays in the descriptor.
    navigation: descriptor.navigation.map(({ kind, ground, cover, obstruction }) => ({ kind, ground, cover, obstruction })),
    shapes,
  };
}
