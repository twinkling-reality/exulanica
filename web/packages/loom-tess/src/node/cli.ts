#!/usr/bin/env tsx
/**
 * The tessellator's command line.
 *
 *   pnpm tess bake <tile-document.json> <out.owd>   bake, write, print the digests
 *   pnpm tess verify <file.owd>                     decode and rebake; print the digests again
 *   pnpm tess params                                the bake stage parameters this build states
 *   pnpm tess shapes                                the record shapes this build reads
 *
 * Output is deterministic: the same document gives the same container bytes, on any machine and
 * any Node version, the promise `scene-synth`'s CLI makes for its fixtures. Every line printed is
 * canonical JSON, so the Python bake stage can compare it byte for byte.
 */
import { BAKE_PARAMETERS } from '../core/bake.js';
import { canonicalJson } from '../core/canonical-json.js';
import type { CanonicalValue } from '../core/canonical-json.js';
import {
  HEX64_PATTERN,
  IDENTITY_PATTERN,
  KEY_PATTERN,
  MATERIAL_RECORD_KIND,
  PLANE,
  PROJECTIONS,
  RECORD_SHAPES,
  TEXTURE_SET_ID_PATTERN,
  TILE_SHAPE,
} from '../core/record-shapes.js';
import { bakeDocumentFile, verifyFile } from './index.js';

const USAGE = [
  'usage: tess bake <tile-document.json> <out.owd>',
  '       tess verify <file.owd>',
  '       tess params',
  '       tess shapes',
  '',
].join('\n');

function print(value: unknown): void {
  process.stdout.write(`${canonicalJson(value as CanonicalValue)}\n`);
}

async function main(argv: readonly string[]): Promise<void> {
  const [command, ...rest] = argv;
  if (command === 'bake' && rest.length === 2) {
    print(await bakeDocumentFile(rest[0]!, rest[1]!));
    return;
  }
  if (command === 'verify' && rest.length === 1) {
    const decoded = await verifyFile(rest[0]!);
    print({
      tile_inputs_digest: decoded.header.tile_inputs_digest,
      triangle_digests: Object.fromEntries(
        decoded.header.projections.map((projection) => [projection.name, projection.triangle_digest]),
      ),
    });
    return;
  }
  if (command === 'params' && rest.length === 0) {
    print(BAKE_PARAMETERS);
    return;
  }
  if (command === 'shapes' && rest.length === 0) {
    print({
      patterns: {
        hex64: HEX64_PATTERN.source,
        identity: IDENTITY_PATTERN.source,
        key: KEY_PATTERN.source,
        texture_set_id: TEXTURE_SET_ID_PATTERN.source,
      },
      plane: PLANE,
      projections: [...PROJECTIONS],
      material_record_kind: MATERIAL_RECORD_KIND,
      tile: TILE_SHAPE,
      records: RECORD_SHAPES,
    });
    return;
  }
  process.stderr.write(USAGE);
  process.exitCode = 2;
}

main(process.argv.slice(2)).catch((error: unknown) => {
  process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
  process.exitCode = 1;
});
