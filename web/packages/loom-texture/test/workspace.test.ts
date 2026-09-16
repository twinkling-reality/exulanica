import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync, cpSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterAll, describe, expect, it } from 'vitest';
import { canonicalBytes } from '../src/canonical-json.js';
import { LIBRARY, definitionOf } from '../src/catalog.js';
import { decodeContainer } from '../src/container.js';
import { sha256Hex } from '../src/digest.js';
import { libraryEntryProblems, packageRoot } from '../src/library.js';
import { planProblems } from '../src/dataset/plan.js';
import { publishSet } from '../src/publish.js';
import type { Recipe } from '../src/recipe.js';
import { bakeWorkspaceRequest, RequestRefused } from '../src/workspace/bake.js';
import { WORKSPACE_LICENCE_ID, workspaceLicence } from '../src/workspace/licence.js';
import {
  BAKE_REQUEST_PROFILE,
  BAKE_RESULT_PROFILE,
  bakeRequestProblems,
} from '../src/workspace/request.js';
import { packageSourceDigest, sourceFiles } from '../src/workspace/source.js';
import { REPOSITORY } from './support.js';

/**
 * A workspace's own bake: the request the backend writes, the command it runs, and the licence
 * that keeps the bytes in the workspace. The backend's half (`exulanica/world/material_bakes.py`)
 * trusts none of what the command prints; `tests/test_material_recipes.py` runs this command and
 * checks it again.
 */
const LICENCE = workspaceLicence();
const BRICK = LIBRARY.find((source) => source.entry.set_id === 'cc0.brick-running-bond')!;
const SET_ID = `ws.${'0123456789abcdef'.repeat(2)}`;

function recipe(): Recipe {
  return { ...structuredClone(BRICK.entry.recipe), resolution: { width: 16, height: 16 } } as Recipe;
}

function request(): Record<string, unknown> {
  const body = recipe();
  return {
    profile: BAKE_REQUEST_PROFILE,
    set_id: SET_ID,
    version: 1,
    title: 'Workspace variant of loom.brick version 1',
    summary: `Baked in one workspace from recipe ${sha256Hex(canonicalBytes(body))}.`,
    licence: { id: WORKSPACE_LICENCE_ID, sha256: LICENCE.sha256 },
    maker_sha256: sha256Hex(canonicalBytes(BRICK.maker.manifest)),
    recipe: body,
  };
}

const scratch: string[] = [];
afterAll(() => {
  for (const directory of scratch) rmSync(directory, { recursive: true, force: true });
});
function temporary(): string {
  const directory = mkdtempSync(join(tmpdir(), 'loom-workspace-'));
  scratch.push(directory);
  return directory;
}

describe('the workspace licence', () => {
  it('is the committed text, and the backend pins the same digest', () => {
    const python = readFileSync(join(REPOSITORY, 'exulanica/materials/workspace.py'), 'utf8');
    const pinned = python.match(/WORKSPACE_LICENCE_SHA256: Final = "([0-9a-f]{64})"/);
    expect(pinned?.[1]).toBe(LICENCE.sha256);
    expect(python).toContain(`WORKSPACE_LICENCE_ID: Final = "${WORKSPACE_LICENCE_ID}"`);
    expect(LICENCE.bytes.every((byte) => byte === 0x0a || (byte >= 0x20 && byte < 0x7f))).toBe(true);
  });
});

describe('a bake request', () => {
  it('is accepted whole, and baked into a container that says whose it is', () => {
    expect(bakeRequestProblems(request(), LICENCE.sha256)).toEqual([]);
    const container = bakeWorkspaceRequest(request(), LICENCE.sha256);
    const { header } = decodeContainer(container);
    expect(header.set_id).toBe(SET_ID);
    expect(header.licence).toEqual({ id: WORKSPACE_LICENCE_ID, sha256: LICENCE.sha256 });
    expect(header.title).toBe('Workspace variant of loom.brick version 1');
    expect(header.resolution).toEqual({ width: 16, height: 16 });
    expect(bakeWorkspaceRequest(request(), LICENCE.sha256)).toEqual(container);
  });

  const broken: readonly [string, (candidate: Record<string, unknown>) => void, string][] = [
    ['an extra field', (c) => { c.note = 1; }, 'exactly'],
    ['another profile', (c) => { c.profile = 'exulanica.texture-bake-request/v2'; }, 'profile'],
    ['a published id', (c) => { c.set_id = 'cc0.brick-running-bond'; }, 'ws. and 32'],
    ['a short id', (c) => { c.set_id = 'ws.0123'; }, 'ws. and 32'],
    ['version 2', (c) => { c.version = 2; }, 'version is 1'],
    ['an empty title', (c) => { c.title = ''; }, 'title and summary'],
    ['a padded summary', (c) => { c.summary = ' padded'; }, 'title and summary'],
    ['a non-ASCII title', (c) => { c.title = 'café'; }, 'title and summary'],
    ['the published licence', (c) => { c.licence = { id: 'CC0-1.0', sha256: LICENCE.sha256 }; }, 'licence'],
    ['another text', (c) => { c.licence = { id: WORKSPACE_LICENCE_ID, sha256: '0'.repeat(64) }; }, 'licence'],
    ['another manifest', (c) => { c.maker_sha256 = '0'.repeat(64); }, 'not the manifest'],
    ['an unknown maker', (c) => { (c.recipe as { maker: object }).maker = { id: 'loom.none', version: 1 }; }, 'maker id and version'],
    ['a recipe the maker refuses', (c) => { (c.recipe as Recipe as { parameters: Record<string, unknown> }).parameters.courses = 25; }, 'recipe: '],
  ];
  for (const [name, change, message] of broken) {
    it(`is refused with ${name}`, () => {
      const candidate = request();
      change(candidate);
      const problems = bakeRequestProblems(candidate, LICENCE.sha256);
      expect(problems.join('; ')).toContain(message);
      expect(() => bakeWorkspaceRequest(candidate, LICENCE.sha256)).toThrow(RequestRefused);
    });
  }
});

describe('the publishing paths', () => {
  it('will not publish a set under the workspace licence or a ws. id', () => {
    const source = definitionOf(BRICK);
    const small = { ...source, width: 16, height: 16 };
    expect(() => publishSet({ ...small, licenceId: WORKSPACE_LICENCE_ID }, LICENCE.sha256)).toThrow(
      /published set is under CC0-1.0/,
    );
    expect(() => publishSet({ ...small, setId: 'ws.brick' }, LICENCE.sha256)).toThrow(/ws\./);
    expect(publishSet(small, LICENCE.sha256).entry.licence_id).toBe('CC0-1.0');
  });

  it('will not list a library entry under the workspace licence or a ws. id', () => {
    const entry = structuredClone(BRICK.entry) as unknown as Record<string, unknown>;
    expect(libraryEntryProblems({ ...entry, licence_id: WORKSPACE_LICENCE_ID })).toContain(
      'licence_id is CC0-1.0',
    );
    expect(libraryEntryProblems({ ...entry, set_id: 'ws.brick' }).join('; ')).toContain('ws.');
  });

  it('will not put a workspace set in a training dataset', () => {
    const plan = JSON.parse(
      readFileSync(join(packageRoot(), 'dataset', 'plans', 'texture-inverse-v1.json'), 'utf8'),
    ) as Record<string, unknown>;
    expect(planProblems(plan)).toEqual([]);
    expect(planProblems({ ...plan, sets: [SET_ID] })).toContain(
      'sets are distinct published set ids, at least one',
    );
  });
});

describe('the package source digest', () => {
  it('names every file the bake can read and nothing else', () => {
    const files = sourceFiles().map((file) => file.path);
    expect(files).toContain('package.json');
    expect(files).toContain('src/workspace/cli.ts');
    expect(files).toContain('licences/workspace-private.txt');
    expect(files.some((path) => path.startsWith('library/'))).toBe(true);
    expect(files.some((path) => path.startsWith('test/') || path.includes('/.'))).toBe(false);
    expect([...files].sort()).toEqual(files);
    expect(packageSourceDigest()).toBe(packageSourceDigest());
  });

  it('moves with a changed file and refuses a link', () => {
    const copy = join(temporary(), 'package');
    for (const part of ['package.json', 'src', 'library', 'licences']) {
      cpSync(join(packageRoot(), part), join(copy, part), { recursive: true });
    }
    const before = packageSourceDigest(copy);
    expect(before).toBe(packageSourceDigest());
    writeFileSync(join(copy, 'src', 'extra.ts'), 'export {};\n');
    expect(packageSourceDigest(copy)).not.toBe(before);
    writeFileSync(join(copy, 'src', '.DS_Store'), 'editor state');
    symlinkSync(join(copy, 'src', 'extra.ts'), join(copy, 'library', 'linked.json'));
    expect(() => packageSourceDigest(copy)).toThrow(/is a link/);
  });
});

describe('the command', () => {
  const command = (args: readonly string[]) =>
    spawnSync(
      process.execPath,
      ['--import', 'tsx', join(packageRoot(), 'src', 'workspace', 'cli.ts'), ...args],
      { cwd: join(packageRoot(), '..', '..'), encoding: 'buffer' },
    );

  it('bakes a request into a new file and prints what it wrote', () => {
    const directory = temporary();
    const requestPath = join(directory, 'request.json');
    const out = join(directory, 'container.ltex');
    writeFileSync(requestPath, canonicalBytes(request()));
    const run = command(['--request', requestPath, '--out', out]);
    expect(run.status, run.stderr.toString()).toBe(0);
    const result = JSON.parse(run.stdout.toString()) as Record<string, unknown>;
    const written = new Uint8Array(readFileSync(out));
    expect(result).toEqual({
      byte_size: written.length,
      content_sha256: sha256Hex(written),
      profile: BAKE_RESULT_PROFILE,
      runtime: { node: process.version, package_sha256: packageSourceDigest() },
    });
    expect(run.stdout.toString()).toBe(new TextDecoder().decode(canonicalBytes(result)));
    expect(written).toEqual(bakeWorkspaceRequest(request(), LICENCE.sha256));

    const again = command(['--request', requestPath, '--out', out]);
    expect(again.status).toBe(1);
    expect(again.stderr.toString()).toContain('EEXIST');
  });

  it('refuses a request it will not run, or one that is not canonical, with exit 2', () => {
    const directory = temporary();
    const refused = join(directory, 'refused.json');
    writeFileSync(refused, canonicalBytes({ ...request(), version: 2 }));
    const run = command(['--request', refused, '--out', join(directory, 'a.ltex')]);
    expect(run.status).toBe(2);
    expect(run.stderr.toString()).toContain('version is 1');

    const spaced = join(directory, 'spaced.json');
    writeFileSync(spaced, JSON.stringify(request(), null, 2));
    const loose = command(['--request', spaced, '--out', join(directory, 'b.ltex')]);
    expect(loose.status).toBe(2);
    expect(loose.stderr.toString()).toContain('canonical');
  });
});
