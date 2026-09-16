import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';
import { canonicalBytes, canonicalJson } from '../src/canonical-json.js';
import { LIBRARY } from '../src/catalog.js';
import { DATASET_FILE, IMAGE_DIRECTORY, RECORDS_FILE, exportDataset, recordSeed } from '../src/dataset/export.js';
import { outputProblem } from '../src/dataset/output.js';
import {
  DATASET_PROFILE,
  type DatasetPlan,
  RENDERER,
  SAMPLER,
  checkPlan,
  planProblems,
} from '../src/dataset/plan.js';
import { type Light, renderView, sampleLight, sampleView } from '../src/dataset/render.js';
import { frameResolution, pickWide, sampleRecipe } from '../src/dataset/sample.js';
import { sha256Hex } from '../src/digest.js';
import { formatLibrarySource, packageRoot } from '../src/library.js';
import type { Maps } from '../src/maps.js';
import { MAKERS } from '../src/makers/index.js';
import { BAKE_PIPELINE } from '../src/objects.js';
import { recipeProblems } from '../src/recipe.js';
import { parseStrictJsonBytes } from '../src/strict-json.js';

/**
 * The synthetic dataset: its plan, its sampler, its pictures and its manifest.
 *
 * The committed plan is exported once, outside git, and its manifest is committed. This file holds
 * the exporter to its promises on tiny plans (valid recipes only, the same bytes every time, a
 * manifest that names every byte) and holds the committed manifest to the code that would rebuild
 * it: a change to a maker, a published recipe, the sampler, the renderer or the bake that is not
 * followed by a new export fails here.
 */
const PLAN_PATH = join(packageRoot(), 'dataset', 'plans', 'texture-inverse-v1.json');
const MANIFEST_PATH = join(packageRoot(), 'dataset', 'manifests', 'texture-inverse-v1.json');
const EVIDENCE = join(packageRoot(), 'evidence', '2026-09-16-dataset-determinism.log.txt');
const PLAN_TEXT = readFileSync(PLAN_PATH, 'utf8');
const COMMITTED = checkPlan(parseStrictJsonBytes(new TextEncoder().encode(PLAN_TEXT)));

const tiny = (overrides: Partial<DatasetPlan> = {}): DatasetPlan => ({
  ...COMMITTED,
  name: 'tiny',
  sets: ['cc0.brick-running-bond', 'cc0.kerb-stone', 'cc0.storefront-metal'],
  records_per_set: 3,
  bake_size: 32,
  image_size: 16,
  ...overrides,
});

const sourceOf = (setId: string) => LIBRARY.find((source) => source.entry.set_id === setId)!;

function exportInMemory(plan: DatasetPlan): Map<string, Uint8Array> {
  const files = new Map<string, Uint8Array>();
  exportDataset(plan, (path, bytes) => {
    expect(files.has(path), `${path} is written once`).toBe(false);
    files.set(path, bytes);
  });
  return files;
}

describe('a dataset plan', () => {
  it('as committed, is valid and kept in the library layout', () => {
    expect(planProblems(COMMITTED)).toEqual([]);
    expect(formatLibrarySource(JSON.parse(PLAN_TEXT))).toBe(PLAN_TEXT);
  });

  it('names only published sets, and a picture no larger than its bake', () => {
    expect(planProblems({ ...COMMITTED, sets: ['cc0.unknown'] })).toEqual([
      'sets are distinct published set ids, at least one',
    ]);
    expect(planProblems({ ...COMMITTED, sets: [...COMMITTED.sets, COMMITTED.sets[0]] })).toEqual([
      'sets are distinct published set ids, at least one',
    ]);
    expect(planProblems({ ...COMMITTED, image_size: 512 })).toEqual([
      'image_size is a power of two from 8, no larger than bake_size',
    ]);
    expect(planProblems({ ...COMMITTED, bake_size: 300 })).toEqual([
      'bake_size is a power of two from 16 to 1024',
    ]);
    expect(
      planProblems({ ...COMMITTED, lighting: { ...COMMITTED.lighting, elevation_permille: [900, 300] } }),
    ).toHaveLength(1);
    expect(planProblems({ ...COMMITTED, extra: 1 })).toEqual([
      'a dataset plan has exactly profile, name, seed, sets, records_per_set, bake_size, image_size, '
        + 'attempts, variation, lighting',
    ]);
    expect(() => checkPlan({ ...COMMITTED, seed: -1 })).toThrow('seed is an unsigned 32-bit integer');
  });
});

describe('the sampler', () => {
  it('picks across a wide span exactly, never outside it', () => {
    expect(pickWide(0, -5, 5)).toBe(-5);
    expect(pickWide(4294967295, -5, 5)).toBe(5);
    expect(pickWide(2147483648, 0, 1_000_000)).toBe(500_000);
    for (let h = 0; h < 4294967296; h += 104_729_111) {
      const value = pickWide(h, 16, 80_000);
      expect(value >= 16 && value <= 80_000 && Number.isInteger(value)).toBe(true);
    }
  });

  it('frames a tile at the bake size along its longer side, and square texels where it can', () => {
    expect(frameResolution({ u: 1800, v: 1800 }, 256)).toEqual({ width: 256, height: 256 });
    expect(frameResolution({ u: 1800, v: 450 }, 256)).toEqual({ width: 256, height: 64 });
    expect(frameResolution({ u: 450, v: 1800 }, 256)).toEqual({ width: 64, height: 256 });
    expect(frameResolution({ u: 1000, v: 600 }, 256)).toEqual({ width: 256, height: 128 });
    expect(frameResolution({ u: 100_000, v: 1 }, 256)).toEqual({ width: 256, height: 16 });
  });

  it('gives each record the same valid recipe every time', () => {
    const plan = tiny();
    for (const setId of plan.sets) {
      const source = sourceOf(setId);
      for (let index = 0; index < 6; index += 1) {
        const first = sampleRecipe(plan, source, recordSeed(plan, index));
        const again = sampleRecipe(plan, source, recordSeed(plan, index));
        expect(canonicalJson(again.recipe)).toBe(canonicalJson(first.recipe));
        expect(recipeProblems(first.recipe, source.maker.manifest), setId).toEqual([]);
        expect(first.attempts).toBeGreaterThanOrEqual(1);
      }
    }
  });

  it('varies recipes, and keeps them when told to keep everything', () => {
    const source = sourceOf('cc0.brick-running-bond');
    const plan = tiny();
    const recipes = new Set(
      [0, 1, 2, 3].map((index) =>
        canonicalJson(sampleRecipe(plan, source, recordSeed(plan, index)).recipe.parameters)),
    );
    expect(recipes.size).toBe(4);
    const still = tiny({ variation: { ...plan.variation, keep_permille: 1000, choice_keep_permille: 1000 } });
    const kept = sampleRecipe(still, source, recordSeed(still, 0)).recipe;
    expect(kept.parameters).toEqual(source.entry.recipe.parameters);
    expect(kept.extent_mm).toEqual(source.entry.recipe.extent_mm);
    expect(kept.resolution).toEqual({ width: 32, height: 32 });
  });

  it('refuses a plan whose variation no attempt satisfies, rather than thinning it out', () => {
    const plan = tiny({ attempts: 1 });
    const kerb = sourceOf('cc0.kerb-stone');
    const refusals = [...Array(40).keys()].filter((index) => {
      try {
        sampleRecipe(plan, kerb, recordSeed(plan, index));
        return false;
      } catch (error) {
        expect(String(error)).toContain('cc0.kerb-stone: no attempt of 1 gave a valid recipe');
        return true;
      }
    });
    expect(refusals.length).toBeGreaterThan(0);
  });
});

describe('the pictures', () => {
  const flat = (metalness: number, occlusion = 255): Maps => ({
    width: 2,
    height: 1,
    baseColor: new Uint8Array([200, 100, 50, 60, 120, 180]),
    normal: new Uint8Array([128, 128, 255, 128, 128, 255]),
    orm: new Uint8Array([occlusion, 128, metalness, occlusion, 128, metalness]),
    relief: new Uint8Array([128, 128]),
  });
  const light = (intensity: number, ambient: number): Light => ({
    direction_q12: [0, 0, 4096],
    intensity_permille: intensity,
    ambient_permille: ambient,
    gain_permille: [1000, 1000, 1000],
  });
  const total = (bytes: Uint8Array): number => bytes.reduce((sum, byte) => sum + byte, 0);

  it('are lit more by more light, and not at all where the surface is fully occluded', () => {
    const maps = flat(0);
    const dim = renderView(maps, { u: 0, v: 0 }, light(500, 100), 2);
    const bright = renderView(maps, { u: 0, v: 0 }, light(1500, 100), 2);
    expect(total(bright)).toBeGreaterThan(total(dim));
    expect(total(renderView(flat(0, 0), { u: 0, v: 0 }, light(1500, 300), 2))).toBe(0);
    expect(Buffer.from(renderView(maps, { u: 0, v: 0 }, light(900, 200), 2)).equals(
      Buffer.from(renderView(maps, { u: 0, v: 0 }, light(900, 200), 2)),
    )).toBe(true);
  });

  it('show a metal its own colour even with no direct light on it', () => {
    const picture = renderView(flat(255), { u: 0, v: 0 }, light(0, 300), 1);
    expect([...picture].every((channel) => channel > 0)).toBe(true);
    expect(picture[0]!).toBeGreaterThan(picture[2]!);
  });

  it('wrap the window around the tile', () => {
    const maps = flat(0);
    const picture = renderView(maps, { u: 1, v: 0 }, light(1000, 200), 2);
    const shifted = renderView(maps, { u: 0, v: 0 }, light(1000, 200), 2);
    expect([...picture.subarray(0, 3)]).toEqual([...shifted.subarray(3, 6)]);
    expect([...picture.subarray(3, 6)]).toEqual([...shifted.subarray(0, 3)]);
  });

  it('are lit from inside the plan\'s elevation, and seen from anywhere on the tile', () => {
    const plan = tiny();
    const [low, high] = plan.lighting.elevation_permille;
    for (let index = 0; index < 50; index += 1) {
      const { direction_q12: [x, y, z], intensity_permille, gain_permille } = sampleLight(
        plan,
        recordSeed(plan, index),
      );
      const length = Math.sqrt(x * x + y * y + z * z);
      expect(Math.abs(length - 4096)).toBeLessThan(2);
      expect(z).toBeGreaterThanOrEqual(Math.floor((low * 4096) / 1000) - 3);
      expect(z).toBeLessThanOrEqual(Math.ceil((high * 4096) / 1000) + 3);
      expect(intensity_permille).toBeGreaterThanOrEqual(plan.lighting.intensity_permille[0]);
      expect(gain_permille.every((gain) => gain >= 940 && gain <= 1060)).toBe(true);
      const view = sampleView(recordSeed(plan, index), 256, 64);
      expect(view.u >= 0 && view.u < 256 && view.v >= 0 && view.v < 64).toBe(true);
    }
    const overhead = tiny({ lighting: { ...plan.lighting, elevation_permille: [1000, 1000] } });
    expect(() => sampleLight(overhead, recordSeed(overhead, 0))).toThrow('no light direction');
  });
});

describe('an export', () => {
  it('is the same bytes every time, and its manifest names every byte', () => {
    const plan = tiny();
    const first = exportInMemory(plan);
    const second = exportInMemory(plan);
    expect([...first.keys()]).toEqual([
      `${IMAGE_DIRECTORY}/cc0.brick-running-bond.rgb`,
      `${IMAGE_DIRECTORY}/cc0.kerb-stone.rgb`,
      `${IMAGE_DIRECTORY}/cc0.storefront-metal.rgb`,
      RECORDS_FILE,
      DATASET_FILE,
    ]);
    for (const [path, bytes] of first) {
      expect(Buffer.from(bytes).equals(Buffer.from(second.get(path)!)), path).toBe(true);
    }

    const manifestBytes = first.get(DATASET_FILE)!;
    const manifest = parseStrictJsonBytes(manifestBytes) as Record<string, any>;
    expect(canonicalJson(manifest)).toBe(new TextDecoder().decode(manifestBytes));
    expect(manifest.profile).toBe(DATASET_PROFILE);
    expect(manifest.truth).toBe('invented');
    expect(manifest.licence_id).toBe('CC0-1.0');
    expect(manifest.plan).toEqual(plan);
    expect(manifest.plan_sha256).toBe(sha256Hex(canonicalBytes(plan)));
    expect(manifest.generator).toEqual({ pipeline: BAKE_PIPELINE, sampler: SAMPLER, renderer: RENDERER });
    expect(manifest.makers.map((row: any) => row.maker_id)).toEqual(['loom.brick', 'loom.kerb', 'loom.metal']);
    const pixels = plan.image_size * plan.image_size * 3;
    for (const shard of manifest.shards) {
      const bytes = first.get(shard.path)!;
      expect(shard.records).toBe(plan.records_per_set);
      expect(shard.byte_size).toBe(plan.records_per_set * pixels);
      expect(bytes.length).toBe(shard.byte_size);
      expect(sha256Hex(bytes)).toBe(shard.sha256);
    }

    const records = first.get(RECORDS_FILE)!;
    expect(manifest.records).toEqual({
      path: RECORDS_FILE,
      count: 9,
      byte_size: records.length,
      sha256: sha256Hex(records),
    });
    const lines = new TextDecoder().decode(records).split('\n');
    expect(lines.pop()).toBe('');
    lines.forEach((line, index) => {
      const record = parseStrictJsonBytes(new TextEncoder().encode(line)) as Record<string, any>;
      expect(canonicalJson(record)).toBe(line);
      expect(record.index).toBe(index);
      expect(record.set_id).toBe(plan.sets[Math.floor(index / 3)]);
      expect(record.offset).toBe(index % 3);
      const maker = MAKERS.find((candidate) => candidate.manifest.maker_id === record.recipe.maker.id)!;
      expect(recipeProblems(record.recipe, maker.manifest)).toEqual([]);
      expect(record.recipe_sha256).toBe(sha256Hex(canonicalBytes(record.recipe)));
      expect(record.view.texel_um.u).toBe(
        Math.floor((record.recipe.extent_mm.u * 1000) / record.recipe.resolution.width),
      );
    });
  }, 60_000);
});

describe('the output directory', () => {
  let scratch: string | undefined;

  afterEach(() => {
    if (scratch !== undefined) rmSync(scratch, { recursive: true, force: true });
    scratch = undefined;
  });

  it('is never where git could take the bytes, and never shared with another export', () => {
    const root = resolve(packageRoot(), '..', '..', '..');
    expect(outputProblem(root, join(root, 'datasets', 'x'))).toContain('inside the repository');
    expect(outputProblem(root, root)).toContain('inside the repository');
    expect(outputProblem(root, join(root, '.exulanica', 'datasets', 'fresh-export-name'))).toBeNull();
    scratch = mkdtempSync(join(tmpdir(), 'loom-dataset-'));
    expect(outputProblem(root, join(scratch, 'new'))).toBeNull();
    mkdirSync(join(scratch, 'used'));
    writeFileSync(join(scratch, 'used', 'dataset.json'), '{}');
    expect(outputProblem(root, join(scratch, 'used'))).toContain('is not empty');
  });
});

describe('the committed manifest', () => {
  it('is what exporting the committed plan with this code would write', () => {
    expect(existsSync(MANIFEST_PATH), `${MANIFEST_PATH} is committed`).toBe(true);
    const bytes = new Uint8Array(readFileSync(MANIFEST_PATH));
    const manifest = parseStrictJsonBytes(bytes) as Record<string, any>;
    expect(canonicalJson(manifest)).toBe(new TextDecoder().decode(bytes));
    expect(manifest.profile).toBe(DATASET_PROFILE);
    expect(manifest.plan).toEqual(COMMITTED);
    expect(manifest.plan_sha256).toBe(sha256Hex(canonicalBytes(COMMITTED)));
    expect(manifest.generator).toEqual({ pipeline: BAKE_PIPELINE, sampler: SAMPLER, renderer: RENDERER });
    const used = COMMITTED.sets.map(sourceOf);
    expect(manifest.bases).toEqual(used.map((source) => ({
      set_id: source.entry.set_id,
      version: source.entry.version,
      recipe_sha256: sha256Hex(canonicalBytes(source.entry.recipe)),
    })));
    expect(manifest.makers).toEqual(
      MAKERS.filter((maker) => used.some((source) => source.maker === maker)).map((maker) => ({
        maker_id: maker.manifest.maker_id,
        version: maker.manifest.version,
        object_sha256: sha256Hex(canonicalBytes(maker.manifest)),
      })),
    );
    const pixels = COMMITTED.image_size * COMMITTED.image_size * 3;
    expect(manifest.shards.map((shard: any) => [shard.set_id, shard.byte_size])).toEqual(
      COMMITTED.sets.map((setId) => [setId, COMMITTED.records_per_set * pixels]),
    );
    expect(manifest.records.count).toBe(COMMITTED.sets.length * COMMITTED.records_per_set);
  });
});

describe('the dataset determinism record', () => {
  it('is of the committed manifest, on three runtimes across two architectures', () => {
    const record = readFileSync(EVIDENCE, 'utf8');
    const manifestBytes = new Uint8Array(readFileSync(MANIFEST_PATH));
    const manifest = parseStrictJsonBytes(manifestBytes) as Record<string, any>;
    const expected = new Map<string, string>([
      ...manifest.shards.map((shard: any): [string, string] => [`./${shard.path}`, shard.sha256]),
      [`./${manifest.records.path}`, manifest.records.sha256],
      [`./${DATASET_FILE}`, sha256Hex(manifestBytes)],
    ]);
    expect(record).toContain(
      'working tree changes under web/packages/loom-texture and assets/textures: 0',
    );
    for (const run of ['node24-arm64', 'node26-arm64', 'node20-x86_64-rosetta']) {
      const section = record.split(`== run ${run}\n`)[1]!.split('\n== ')[0]!;
      expect(section, run).toContain('exit: 0');
      const listed = new Map(
        [...section.matchAll(/^([0-9a-f]{64}) {2}(\.\/\S+)$/gm)].map((match) => [match[2]!, match[1]!]),
      );
      expect(listed, run).toEqual(expected);
    }
    for (const run of ['node26-arm64', 'node20-x86_64-rosetta']) {
      expect(record).toContain(`${run}: 0 of ${expected.size} files differ; ${expected.size} files present`);
    }
    expect(record).toContain("committed manifest: identical to node24-arm64's");
    expect(record).toContain(`committed manifest sha256 ${sha256Hex(manifestBytes)}`);
  });
});
