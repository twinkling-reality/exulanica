import { readFileSync, writeFileSync } from 'node:fs';
import { canonicalBytes, canonicalJson } from '../canonical-json.js';
import { sha256Hex } from '../digest.js';
import { StrictJsonError, parseStrictJsonBytes } from '../strict-json.js';
import { RequestRefused, bakeWorkspaceRequest } from './bake.js';
import { workspaceLicence } from './licence.js';
import { BAKE_RESULT_PROFILE, type BakeResult } from './request.js';
import { packageSourceDigest } from './source.js';

/**
 * Bake one workspace recipe for the backend's bake worker.
 *
 *   node --import tsx packages/loom-texture/src/workspace/cli.ts --request REQUEST --out CONTAINER
 *
 * Reads a bake request, which must be canonical JSON, checks it (`request.ts`), bakes it, writes
 * the container to `--out`, which must not exist yet, and prints the result as canonical JSON on
 * stdout: the container's digest and length, the Node version, and the digest of this package's
 * source. It opens no socket and writes no other file. The worker runs it in a process of its own,
 * with a wall-clock timeout and a memory ceiling, and trusts nothing it prints without checking.
 *
 * Exit 0: baked. Exit 2: the request was refused, every reason on stderr. Exit 1: anything else.
 */
const USAGE = 'usage: bake-workspace --request FILE --out FILE\n';
const REFUSED = 2;

function parseArgs(argv: readonly string[]): { request: string; out: string } {
  let request: string | undefined;
  let out: string | undefined;
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '--request') request = argv[++i];
    else if (arg === '--out') out = argv[++i];
    else throw new Error(`unknown argument ${String(arg)}\n${USAGE}`);
  }
  if (!request || !out) throw new Error(`--request and --out are required\n${USAGE}`);
  return { request, out };
}

function refuse(problems: readonly string[]): never {
  process.stderr.write(`${problems.join('\n')}\n`);
  process.exit(REFUSED);
}

function main(): void {
  const args = parseArgs(process.argv.slice(2));
  const raw = new Uint8Array(readFileSync(args.request));
  let candidate: unknown;
  try {
    candidate = parseStrictJsonBytes(raw);
  } catch (error) {
    if (error instanceof StrictJsonError) refuse([`request: ${error.message}`]);
    throw error;
  }
  if (Buffer.compare(Buffer.from(canonicalBytes(candidate as object)), Buffer.from(raw)) !== 0) {
    refuse(['request: a bake request is canonical JSON, byte for byte']);
  }
  const licence = workspaceLicence();
  let container: Uint8Array;
  try {
    container = bakeWorkspaceRequest(candidate, licence.sha256);
  } catch (error) {
    if (error instanceof RequestRefused) refuse(error.problems);
    throw error;
  }
  writeFileSync(args.out, container, { flag: 'wx' });
  const result: BakeResult = {
    profile: BAKE_RESULT_PROFILE,
    content_sha256: sha256Hex(container),
    byte_size: container.length,
    runtime: { node: process.version, package_sha256: packageSourceDigest() },
  };
  process.stdout.write(canonicalJson(result));
}

main();
