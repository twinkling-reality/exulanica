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
  };
  return {
    grammar_id: descriptor.grammar_id,
    grammar_version: descriptor.grammar_version,
    frame: descriptor.frame,
    shapes,
  };
}
