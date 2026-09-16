import { existsSync, mkdirSync, readdirSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { dirname, isAbsolute, join, relative, resolve } from 'node:path';
import {
  ACCEPTED_DECODED_ENVELOPE_BYTES,
  CORRIDOR_SET_COUNT,
  corridorDecodedBytes,
  decodedBytes,
} from './budget.js';
import { CATALOG } from './catalog.js';
import { contactSheet, litPreview } from './inspect/contact-sheet.js';
import { encodePng } from './inspect/png.js';
import { ATTRIBUTES_FILE, BLOB_DIRECTORY, MANIFEST_FILE, publish } from './publish.js';

/**
 * Bake the texture sets.
 *
 *   pnpm texture --out ../assets/textures
 *   pnpm texture --out /tmp/bake-a --inspect /tmp/look
 *
 * `--out` receives the content-addressed sets, the licence blob, `manifest.json` and a
 * `.gitattributes` that keeps checkouts from converting any of them, and nothing else. Every byte
 * written there is a function of each set's seed, id, resolution and version. `--inspect`
 * receives PNG pictures for people; it must lie outside `--out`, because a PNG's bytes depend on
 * the zlib build and nothing in the output directory may.
 *
 * The output directory must be empty or hold only a previous bake. Blobs the new manifest no
 * longer names are removed, so the directory always holds exactly the published sets. A
 * superseded version stays retrievable from history and from any store it was seeded into.
 */

interface Args {
  readonly out: string;
  readonly inspect: string | undefined;
}

const USAGE = 'usage: texture --out DIR [--inspect DIR]\n';
const BLOB_NAME = /^[0-9a-f]{64}\.(ltex|txt)$/;

function parseArgs(argv: readonly string[]): Args {
  let out: string | undefined;
  let inspect: string | undefined;
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '--out') out = argv[++i];
    else if (arg === '--inspect') inspect = argv[++i];
    else if (arg === '--help' || arg === '-h') {
      process.stdout.write(USAGE);
      process.exit(0);
    } else throw new Error(`unknown argument ${String(arg)}\n${USAGE}`);
  }
  if (out === undefined || out === '') throw new Error(`--out is required\n${USAGE}`);
  return { out: resolve(out), inspect: inspect === undefined ? undefined : resolve(inspect) };
}

const within = (parent: string, child: string): boolean => {
  const path = relative(parent, child);
  return path === '' || (!path.startsWith('..') && !isAbsolute(path));
};

/** Refuse a directory that holds anything a bake did not write. */
function checkOutput(out: string): void {
  if (!existsSync(out)) return;
  for (const name of readdirSync(out)) {
    if ((name === MANIFEST_FILE || name === ATTRIBUTES_FILE) && statSync(join(out, name)).isFile()) {
      continue;
    }
    if (name === BLOB_DIRECTORY && statSync(join(out, name)).isDirectory()) {
      for (const blob of readdirSync(join(out, name))) {
        if (!BLOB_NAME.test(blob) || !statSync(join(out, name, blob)).isFile()) {
          throw new Error(`${join(out, name, blob)} is not something a bake writes; refusing`);
        }
      }
      continue;
    }
    throw new Error(`${join(out, name)} is not something a bake writes; refusing`);
  }
}

const mib = (bytes: number): string => `${(bytes / 1048576).toFixed(1)} MiB`;

function main(): void {
  const args = parseArgs(process.argv.slice(2));
  if (args.inspect !== undefined && (within(args.out, args.inspect) || within(args.inspect, args.out))) {
    throw new Error('--inspect must lie outside --out: pictures are never part of a bake');
  }
  checkOutput(args.out);
  const publication = publish(CATALOG);

  mkdirSync(join(args.out, BLOB_DIRECTORY), { recursive: true });
  // Blobs first and the manifest last, so an interrupted bake never names bytes it did not write.
  for (const [path, bytes] of publication.files) {
    if (path !== MANIFEST_FILE) writeFileSync(join(args.out, path), bytes);
  }
  writeFileSync(join(args.out, MANIFEST_FILE), publication.manifest);
  const kept = new Set([...publication.files.keys()].map((path) => path.split('/').pop()));
  for (const blob of readdirSync(join(args.out, BLOB_DIRECTORY))) {
    if (!kept.has(blob)) rmSync(join(args.out, BLOB_DIRECTORY, blob));
  }

  process.stdout.write('set id                      v  texels     extent mm    bytes     sha256\n');
  for (const set of [...publication.sets].sort((a, b) => (a.entry.set_id < b.entry.set_id ? -1 : 1))) {
    const { entry } = set;
    process.stdout.write(
      `${entry.set_id.padEnd(27)} ${String(entry.version).padStart(2)}  `
        + `${`${entry.resolution.width}x${entry.resolution.height}`.padEnd(9)}  `
        + `${`${entry.extent_mm.u}x${entry.extent_mm.v}`.padEnd(11)}  `
        + `${String(entry.byte_size).padStart(8)}  ${entry.content_sha256}\n`,
    );
  }
  const plain = corridorDecodedBytes(CATALOG, false);
  const mipped = corridorDecodedBytes(CATALOG, true);
  process.stdout.write(
    `\nlicence ${publication.licence.sha256}\n`
      + `decoded, the ${CORRIDOR_SET_COUNT} costliest sets as RGBA8: ${plain} bytes (${mib(plain)}), `
      + `${mipped} bytes with mips (${mib(mipped)}); envelope ${ACCEPTED_DECODED_ENVELOPE_BYTES} bytes\n`
      + `decoded, all ${CATALOG.length} sets with mips: `
      + `${CATALOG.reduce((sum, def) => sum + decodedBytes(def, true), 0)} bytes\n`
      + `wrote ${publication.files.size} files to ${args.out}\n`,
  );

  if (args.inspect !== undefined) {
    mkdirSync(args.inspect, { recursive: true });
    const sheet = join(args.inspect, 'contact-sheet.png');
    writeFileSync(sheet, encodePng(contactSheet(publication)));
    for (const set of publication.sets) {
      const path = join(args.inspect, `${set.entry.set_id}.lit.png`);
      mkdirSync(dirname(path), { recursive: true });
      writeFileSync(path, encodePng(litPreview(set.container)));
    }
    process.stdout.write(`wrote inspection pictures to ${args.inspect} (not pinned, not digested)\n`);
  }
}

main();
