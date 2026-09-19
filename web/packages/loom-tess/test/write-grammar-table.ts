/**
 * Writes `src/core/city-v<N>.ts`, one per city grammar version core reads, from the two files the
 * grammar itself writes for that version: its record shape table and the frame, contract measures
 * and navigation table of its descriptor. Nothing in a table is typed by hand.
 *
 *     pnpm exec tsx packages/loom-tess/test/write-grammar-table.ts
 *
 * `test/grammar-table.test.ts` and `tests/test_bake_determinism.py` fail when a committed table and
 * either of its sources differ. Which versions exist, and which two files each is built from, is
 * decided in `grammar-table-sources.ts` by reading the grammar directory rather than by a list.
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { basename, join, relative } from 'node:path';
import { PACKAGE_ROOT, REPOSITORY_ROOT } from './support.js';
import { cityTableSources, grammarTableFromSources } from './grammar-table-sources.js';

for (const source of cityTableSources()) {
  const table = grammarTableFromSources(source.version);
  const name = `city-v${source.version}.ts`;
  const relativeShapes = relative(REPOSITORY_ROOT, source.shapes);
  const text = [
    '/**',
    ` * THE CITY GRAMMAR, VERSION ${source.version}, AS DATA. GENERATED: do not edit by hand.`,
    ' *',
    " * Written by `test/write-grammar-table.ts` from the grammar's own record shape table",
    ` * (\`${relativeShapes}\`) and the frame, contract measures and navigation table of`,
    ` * \`exulanica/grammar/grammars/city/${basename(source.descriptor)}\`.`,
    ' * `test/grammar-table.test.ts` and `tests/test_bake_determinism.py` hold it equal to both.',
    ' *',
    ' * It is one of the files in `src/core` that spells grammar vocabulary: field names, bounds and',
    ' * closed values. `test/vocabulary-emptiness.test.ts` exempts it for that reason and no other.',
    ' */',
    "import type { GrammarTable } from './grammar-table.js';",
    '',
    `export const CITY_V${source.version}: GrammarTable = ${JSON.stringify(table, null, 2)};`,
    '',
  ].join('\n');
  const path = join(PACKAGE_ROOT, 'src', 'core', name);
  writeFileSync(path, text);
  process.stdout.write(`wrote src/core/${name}, ${readFileSync(path).length} bytes, from ${relativeShapes}\n`);
}
