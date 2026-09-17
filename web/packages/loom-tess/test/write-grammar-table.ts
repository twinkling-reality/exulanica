/**
 * Writes `src/core/city-v2.ts`, the grammar table core reads, from the two files the grammar
 * itself writes: the record shape table (`describe_shapes` over the city's shapes, committed as
 * `tests/fixtures/city-v2/record-shapes.json`) and the descriptor's frame
 * (`exulanica/grammar/grammars/city/city.v2.json`). Nothing in the table is typed by hand.
 *
 *     pnpm exec tsx packages/loom-tess/test/write-grammar-table.ts
 *
 * `test/grammar-table.test.ts` and `tests/test_bake_determinism.py` fail when the committed table
 * and either source differ.
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { PACKAGE_ROOT } from './support.js';
import { grammarTableFromSources } from './grammar-table-sources.js';

const table = grammarTableFromSources();
const source = [
  '/**',
  ' * THE CITY GRAMMAR, VERSION 2, AS DATA. GENERATED: do not edit by hand.',
  ' *',
  ' * Written by `test/write-grammar-table.ts` from `tests/fixtures/city-v2/record-shapes.json`',
  " * (the grammar's own `describe_shapes`) and the frame of",
  ' * `exulanica/grammar/grammars/city/city.v2.json`. `test/grammar-table.test.ts` and',
  ' * `tests/test_bake_determinism.py` hold it equal to both.',
  ' *',
  ' * It is the only file in `src/core` that spells grammar vocabulary: field names, bounds and closed',
  ' * values. `test/vocabulary-emptiness.test.ts` exempts it for that reason and no other.',
  ' */',
  "import type { GrammarTable } from './grammar-table.js';",
  '',
  `export const CITY_V2: GrammarTable = ${JSON.stringify(table, null, 2)};`,
  '',
].join('\n');
writeFileSync(join(PACKAGE_ROOT, 'src', 'core', 'city-v2.ts'), source);
process.stdout.write(`wrote src/core/city-v2.ts, ${readFileSync(join(PACKAGE_ROOT, 'src', 'core', 'city-v2.ts')).length} bytes\n`);
