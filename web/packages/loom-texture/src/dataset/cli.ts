import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { sha256Hex } from '../digest.js';
import { packageRoot } from '../library.js';
import { parseStrictJsonBytes } from '../strict-json.js';
import { DATASET_FILE, exportDataset } from './export.js';
import { outputProblem } from './output.js';
import { checkPlan } from './plan.js';

/**
 * Export a synthetic texture dataset.
 *
 *   npx tsx packages/loom-texture/src/dataset/cli.ts \
 *     --plan packages/loom-texture/dataset/plans/texture-inverse-v1.json \
 *     --out ../.exulanica/datasets/texture/texture-inverse-v1 \
 *     --record packages/loom-texture/dataset/manifests/texture-inverse-v1.json
 *
 * `--out` must be empty or absent, and must lie outside the repository or inside its ignored
 * `.exulanica/` directory: dataset bytes never enter git. `--record` writes a copy of the
 * manifest, which is the one file a repository keeps, wherever it is asked to. CPU only.
 */

interface Args {
  readonly plan: string;
  readonly out: string;
  readonly record: string | undefined;
}

const USAGE = 'usage: texture-dataset --plan FILE --out DIR [--record FILE]\n';

function parseArgs(argv: readonly string[]): Args {
  let plan: string | undefined;
  let out: string | undefined;
  let record: string | undefined;
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '--plan') plan = argv[++i];
    else if (arg === '--out') out = argv[++i];
    else if (arg === '--record') record = argv[++i];
    else if (arg === '--help' || arg === '-h') {
      process.stdout.write(USAGE);
      process.exit(0);
    } else throw new Error(`unknown argument ${String(arg)}\n${USAGE}`);
  }
  if (plan === undefined || out === undefined) throw new Error(`--plan and --out are required\n${USAGE}`);
  return {
    plan: resolve(plan),
    out: resolve(out),
    record: record === undefined ? undefined : resolve(record),
  };
}

function main(): void {
  const args = parseArgs(process.argv.slice(2));
  const plan = checkPlan(parseStrictJsonBytes(new Uint8Array(readFileSync(args.plan))));
  const root = resolve(packageRoot(), '..', '..', '..');
  const problem = outputProblem(root, args.out);
  if (problem !== null) throw new Error(problem);
  process.stdout.write(
    `exporting ${plan.name}: ${plan.sets.length} sets x ${plan.records_per_set} records, `
      + `bake ${plan.bake_size}, pictures ${plan.image_size}\n`,
  );
  const result = exportDataset(plan, (path, bytes) => {
    const target = join(args.out, path);
    mkdirSync(dirname(target), { recursive: true });
    writeFileSync(target, bytes);
    process.stdout.write(`  wrote ${path}: ${bytes.length} bytes, sha256 ${sha256Hex(bytes)}\n`);
  });
  if (args.record !== undefined) {
    mkdirSync(dirname(args.record), { recursive: true });
    writeFileSync(args.record, result.manifest);
  }
  process.stdout.write(
    `${result.records} records; refused attempts ${JSON.stringify(result.refused)}\n`
      + `manifest ${join(args.out, DATASET_FILE)} sha256 ${sha256Hex(result.manifest)}\n`,
  );
}

main();
