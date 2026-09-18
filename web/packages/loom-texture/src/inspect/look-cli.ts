import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { MANIFEST_FILE } from '../publish.js';
import { encodePng } from './png.js';
import { publishedLook, publishedSets } from './published-look.js';

/**
 * Pictures of the sets a published directory holds, from its committed bytes.
 *
 *   pnpm texture-look --textures ../assets/textures --out /tmp/look
 *   pnpm texture-look --textures ../assets/textures --out /tmp/look --set cc0.road-paint-white
 *
 * Nothing is baked: each container is read from `blobs/` by the digest its manifest pins, so what
 * is drawn is what a reader reads. That is the difference from `--inspect` on the bake command,
 * which can only picture the bake it just did. Use this to look at a set that is already published,
 * including one whose maker has moved since, and to look at a class the contact sheet lays out in a
 * single row.
 *
 * The pictures are not pinned, not digested and not part of any bake: they depend on the zlib build
 * that wrote the PNGs, so they never belong in a published directory.
 */
const USAGE = 'usage: texture-look --textures DIR --out DIR [--set ID] [--tiles N]\n';

interface Args {
  readonly textures: string;
  readonly out: string;
  readonly set: string | undefined;
  readonly tiles: number;
}

function parseArgs(argv: readonly string[]): Args {
  const values = new Map<string, string>();
  for (let index = 0; index < argv.length; index += 2) {
    const flag = argv[index];
    const value = argv[index + 1];
    if (flag === undefined || value === undefined || !flag.startsWith('--')) throw new Error(USAGE);
    values.set(flag.slice(2), value);
  }
  const textures = values.get('textures');
  const out = values.get('out');
  if (textures === undefined || out === undefined) throw new Error(USAGE);
  const tiles = values.has('tiles') ? Number(values.get('tiles')) : 3;
  if (!Number.isInteger(tiles) || tiles < 1 || tiles > 8) {
    throw new Error('--tiles is a whole number of tiles from 1 to 8\n');
  }
  for (const flag of values.keys()) {
    if (!['textures', 'out', 'set', 'tiles'].includes(flag)) throw new Error(USAGE);
  }
  return { textures, out, set: values.get('set'), tiles };
}

function main(): void {
  const args = parseArgs(process.argv.slice(2));
  const manifest = new Uint8Array(readFileSync(join(args.textures, MANIFEST_FILE)));
  const sets = publishedSets(manifest);
  if (args.set !== undefined && !sets.has(args.set)) {
    const known = [...sets.keys()].join(', ');
    throw new Error(`${args.set} is not a set this directory publishes; it holds ${known}\n`);
  }
  const wanted = args.set === undefined ? [...sets.keys()] : [args.set];
  mkdirSync(args.out, { recursive: true });
  for (const setId of wanted) {
    const entry = sets.get(setId)!;
    const container = new Uint8Array(
      readFileSync(join(args.textures, 'blobs', `${entry.contentSha256}.ltex`)),
    );
    const directory = join(args.out, setId);
    mkdirSync(directory, { recursive: true });
    const pictures = publishedLook(container, args.tiles);
    for (const [name, image] of pictures) {
      writeFileSync(join(directory, `${name}.png`), encodePng(image));
    }
    process.stdout.write(
      `${setId.padEnd(27)} ${entry.materialClass.padEnd(8)} `
        + `${`${entry.width}x${entry.height}`.padEnd(9)} ${pictures.size} pictures\n`,
    );
  }
  process.stdout.write(`wrote pictures for ${wanted.length} sets to ${args.out}\n`);
}

main();
