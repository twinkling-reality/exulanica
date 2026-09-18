import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { REPOSITORY_ROOT } from './support.js';

export const SHAPE_TABLE_PATH = join(REPOSITORY_ROOT, 'tests', 'fixtures', 'city-v2', 'record-shapes.json');
export const CITY_DESCRIPTOR_PATH = join(REPOSITORY_ROOT, 'exulanica', 'grammar', 'grammars', 'city', 'city.v2.json');

/** The grammar table as the grammar's own files state it. */
export function grammarTableFromSources(): unknown {
  const shapes: unknown = JSON.parse(readFileSync(SHAPE_TABLE_PATH, 'utf8'));
  const descriptor = JSON.parse(readFileSync(CITY_DESCRIPTOR_PATH, 'utf8')) as {
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
    frame: descriptor.frame,
    measures,
    resolutions,
    // The navigation table's data, row by row; each row's reason is prose and stays in the descriptor.
    navigation: descriptor.navigation.map(({ kind, ground, cover, obstruction }) => ({ kind, ground, cover, obstruction })),
    shapes,
  };
}
