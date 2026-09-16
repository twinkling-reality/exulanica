import { canonicalBytes, canonicalJson } from '../canonical-json.js';
import { LIBRARY, definitionOf } from '../catalog.js';
import { sha256Hex } from '../digest.js';
import { stream } from '../hash.js';
import { floorDiv } from '../integer.js';
import { LICENCE_ID } from '../licence.js';
import { bakeMaps } from '../maps.js';
import { BAKE_PIPELINE } from '../objects.js';
import type { Recipe } from '../recipe.js';
import { DATASET_PROFILE, type DatasetPlan, RENDERER, SAMPLER } from './plan.js';
import { type Light, renderView, sampleLight, sampleView } from './render.js';
import { sampleRecipe } from './sample.js';

/**
 * Export a dataset plan: image shards, one line per record, and the manifest that pins them.
 *
 * The directory holds `images/<set id>.rgb` (every record of that set, `image_size` squared
 * pixels of sRGB each, concatenated in record order), `records.jsonl` (one canonical JSON object
 * per line, in record order), and `dataset.json`, the manifest: the plan, the generator versions,
 * the makers and published recipes the records came from, and the length and sha256 of every
 * file. The manifest is written last and is the one file a repository keeps; the bytes stay out
 * of git, and anyone can rebuild them from the plan and check them against it.
 *
 * Records are numbered across the whole dataset, and each record's seed is a stream of the plan's
 * seed and its number, so a record is the same whichever machine, runtime or shard order made it.
 */
export const IMAGE_DIRECTORY = 'images';
export const RECORDS_FILE = 'records.jsonl';
export const DATASET_FILE = 'dataset.json';

export interface DatasetRecord {
  readonly index: number;
  readonly set_id: string;
  /** Position of this record's picture within its set's shard. */
  readonly offset: number;
  readonly recipe: Recipe;
  readonly recipe_sha256: string;
  readonly view: {
    readonly u: number;
    readonly v: number;
    /** Surface under one texel, in micrometres, so a picture's physical scale is known. */
    readonly texel_um: { readonly u: number; readonly v: number };
  };
  readonly light: Light;
  /** Attempts the sampler used, the accepted one included. */
  readonly attempts: number;
}

export interface ShardEntry {
  readonly set_id: string;
  readonly path: string;
  readonly records: number;
  readonly byte_size: number;
  readonly sha256: string;
}

/** Receives each file once, complete, in the order the export finishes them. */
export type Sink = (path: string, bytes: Uint8Array) => void;

export interface DatasetExport {
  readonly manifest: Uint8Array;
  readonly records: number;
  readonly refused: Readonly<Record<string, number>>;
}

/** The seed a record draws everything from: a stream of the plan's seed and the record's number. */
export const recordSeed = (plan: DatasetPlan, index: number): number => stream(plan.seed, index);

export function exportDataset(plan: DatasetPlan, sink: Sink): DatasetExport {
  const pixels = plan.image_size * plan.image_size * 3;
  const lines: string[] = [];
  const shards: ShardEntry[] = [];
  const refused: Record<string, number> = {};
  const makers = new Map<string, { maker_id: string; version: number; object_sha256: string }>();
  const bases: { set_id: string; version: number; recipe_sha256: string }[] = [];
  let index = 0;
  for (const setId of plan.sets) {
    const source = LIBRARY.find((candidate) => candidate.entry.set_id === setId);
    if (source === undefined) throw new Error(`${setId} is not a published set`);
    const { manifest } = source.maker;
    makers.set(`${manifest.maker_id} ${manifest.version}`, {
      maker_id: manifest.maker_id,
      version: manifest.version,
      object_sha256: sha256Hex(canonicalBytes(manifest)),
    });
    bases.push({
      set_id: setId,
      version: source.entry.version,
      recipe_sha256: sha256Hex(canonicalBytes(source.entry.recipe)),
    });
    const images = new Uint8Array(plan.records_per_set * pixels);
    let retries = 0;
    for (let offset = 0; offset < plan.records_per_set; offset += 1, index += 1) {
      const seed = recordSeed(plan, index);
      const { recipe, attempts } = sampleRecipe(plan, source, seed);
      retries += attempts - 1;
      const maps = bakeMaps(definitionOf({ ...source, entry: { ...source.entry, recipe } }));
      const view = sampleView(seed, maps.width, maps.height);
      const light = sampleLight(plan, seed);
      images.set(renderView(maps, view, light, plan.image_size), offset * pixels);
      const record: DatasetRecord = {
        index,
        set_id: setId,
        offset,
        recipe,
        recipe_sha256: sha256Hex(canonicalBytes(recipe)),
        view: {
          u: view.u,
          v: view.v,
          texel_um: {
            u: floorDiv(recipe.extent_mm.u * 1000, maps.width),
            v: floorDiv(recipe.extent_mm.v * 1000, maps.height),
          },
        },
        light,
        attempts,
      };
      lines.push(canonicalJson(record));
    }
    const path = `${IMAGE_DIRECTORY}/${setId}.rgb`;
    sink(path, images);
    shards.push({
      set_id: setId,
      path,
      records: plan.records_per_set,
      byte_size: images.length,
      sha256: sha256Hex(images),
    });
    refused[setId] = retries;
  }
  const records = new TextEncoder().encode(lines.map((line) => `${line}\n`).join(''));
  sink(RECORDS_FILE, records);
  const manifest = canonicalBytes({
    profile: DATASET_PROFILE,
    truth: 'invented',
    licence_id: LICENCE_ID,
    plan,
    plan_sha256: sha256Hex(canonicalBytes(plan)),
    generator: { pipeline: BAKE_PIPELINE, sampler: SAMPLER, renderer: RENDERER },
    makers: [...makers.values()].sort((a, b) =>
      a.maker_id < b.maker_id ? -1 : a.maker_id > b.maker_id ? 1 : a.version - b.version,
    ),
    bases,
    image: {
      width: plan.image_size,
      height: plan.image_size,
      channels: 3,
      layout: 'sRGB bytes, rows top to bottom, one picture after another in record order',
    },
    shards,
    records: {
      path: RECORDS_FILE,
      count: index,
      byte_size: records.length,
      sha256: sha256Hex(records),
    },
    refused_attempts: refused,
  });
  sink(DATASET_FILE, manifest);
  return { manifest, records: index, refused };
}
