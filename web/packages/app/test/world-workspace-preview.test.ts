// The world workspace preview (tools/previews/world-workspace) runs this app and edits main.ts and
// environment-selection.ts as Vite serves them (seams.mjs). Each edit needs its target to occur once
// and the code it inserts to still compile where it lands: a renamed variable or a lost `async`
// would otherwise break the preview with no test noticing. Each patched file is type-checked alone
// against the same file unpatched, and only what the edit introduces counts. The app's production
// build makes the same edits (src/dev/world-workspace-build.ts), so the built bundle carries the workspace;
// the preview's own TypeScript modules are type-checked here, and its own checks (verify-*.mjs) run
// here too, unchanged.
import { mkdtempSync, readdirSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';
import { describe, expect, it } from 'vitest';

const REPOSITORY = new URL('../../../../', import.meta.url);
const WORKSPACE = new URL('tools/previews/world-workspace/', REPOSITORY);

interface Seam { readonly seam: string; readonly file: string; readonly target: string }
interface Seams {
  readonly SEAMS: readonly Seam[];
  readonly SEAM_FILES: readonly string[];
  occurrences(code: string, target: string): number;
  patchSource(file: string, code: string, here: string): string | null;
}

/** A preview module, by a computed path: it is plain JavaScript outside this package. */
const preview = async (name: string): Promise<unknown> => import(/* @vite-ignore */ new URL(name, WORKSPACE).href);
const seams = async (): Promise<Seams> => preview('seams.mjs') as Promise<Seams>;
const source = (file: string): string => readFileSync(new URL(file, REPOSITORY), 'utf8');
const here = fileURLToPath(WORKSPACE).replace(/\/$/, '');

/**
 * What TypeScript says about `text` as `file` alone: imports are left unresolved (their bindings
 * are `any`), so what remains is syntax, names not in scope and grammar such as `await` outside an
 * async function. One string per diagnostic, without its position.
 */
function diagnostics(file: string, text: string): string[] {
  const name = `/check/${file}`;
  const options: ts.CompilerOptions = {
    noResolve: true, noEmit: true, types: [], skipLibCheck: true, strict: false,
    target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext, lib: ['lib.es2022.d.ts', 'lib.dom.d.ts'],
  };
  const host = ts.createCompilerHost(options);
  const read = host.getSourceFile.bind(host);
  host.getSourceFile = (path, language, ...rest) =>
    path === name ? ts.createSourceFile(path, text, language, true) : read(path, language, ...rest);
  const program = ts.createProgram([name], options, host);
  const checked = program.getSourceFile(name)!;
  return [...program.getSyntacticDiagnostics(checked), ...program.getSemanticDiagnostics(checked)]
    .map((one) => `TS${one.code}: ${ts.flattenDiagnosticMessageText(one.messageText, ' ')}`);
}

/**
 * What the edit adds, beyond what the file says unpatched. The workspace imports are `/@fs/` paths
 * Vite serves, never resolvable here, so they are expected to be unresolved, as is the app module a
 * seam imports where it is needed (a baking town's land, asked for while it bakes).
 */
const EXPECTED = [
  /^TS(2307|2792): Cannot find module '\/@fs\/.*\/(contextual-world|front-door|front-door-preview|world-opening|create-world|world-creature)\.ts'/u,
  /^TS(2307|2792): Cannot find module '\.\/composition\/town-land\.js'/u,
  /^TS(2307|2792): Cannot find module '\/@fs\/.*\/opening-steps\.mjs'/u,
];
function introduced(file: string, before: string, after: string): string[] {
  const left = new Map<string, number>();
  for (const one of diagnostics(file, before)) left.set(one, (left.get(one) ?? 0) + 1);
  return diagnostics(file, after).filter((one) => {
    const held = left.get(one) ?? 0;
    if (held > 0) { left.set(one, held - 1); return false; }
    return !EXPECTED.some((expected) => expected.test(one));
  });
}

const APP = fileURLToPath(new URL('web/packages/app/', REPOSITORY));
/** The two hosts written in an untyped style: checked for names, arity and known properties, not for strictness. */
const LOOSE = new Set(['contextual-world.ts', 'build-mode.ts']);
const LOOSER = {
  strict: false, noImplicitAny: false, useUnknownInCatchVariables: false, exactOptionalPropertyTypes: false,
  noUnusedLocals: false, noUnusedParameters: false,
};
const CONTROL = `${here}/type-check-control.ts`;
/** A preview module that is wrong twice: a typed import misused and an untyped parameter, beside an untyped words import. */
const CONTROL_TEXT = [
  "import { cardWords } from './world-ui.ts';",
  "import { buildKeys } from './build-words.mjs';",
  "export const words: number = cardWords({ title: 'A bench' });",
  'export const keys = (state) => [buildKeys(), state];',
].join('\n');

/**
 * What TypeScript says about the preview's modules `names` (and the control's, with `control`), read as one program
 * under this app's compiler options (`looser` relaxes them): imports resolve as Vite serves them (`/src/*` is this
 * app's sources, a package name resolves as it does from them) and each plain JavaScript words module (.mjs) is
 * untyped, its bindings `any`. Only what it says of those modules and the preview's declarations counts, with any
 * diagnostic of no file. One `file:line TScode message` string per diagnostic.
 */
function previewTypeErrors(names: readonly string[], { looser = false, control = false } = {}): string[] {
  const base = ts.readConfigFile(fileURLToPath(new URL('web/tsconfig.base.json', REPOSITORY)), ts.sys.readFile).config.compilerOptions;
  const { options, errors } = ts.convertCompilerOptionsFromJson({
    ...base, composite: false, declaration: false, declarationMap: false, sourceMap: false, noEmit: true,
    module: 'ESNext', moduleResolution: 'Bundler', lib: ['ES2022', 'DOM', 'DOM.Iterable'], types: [],
    allowImportingTsExtensions: true, baseUrl: APP, paths: { '/src/*': [`${APP}src/*`] },
    ...(looser ? LOOSER : {}),
  }, APP);
  expect(errors).toEqual([]);
  const host = ts.createCompilerHost(options);
  const fromApp = `${APP}src/main.ts`;
  host.resolveModuleNameLiterals = (literals, containing, redirected, settings) => literals.map(({ text }) =>
    ts.resolveModuleName(text, /^[./]/u.test(text) ? containing : fromApp, settings, host, undefined, redirected));
  const read = host.getSourceFile.bind(host);
  host.getSourceFile = (path, language, ...rest) =>
    path === CONTROL ? ts.createSourceFile(path, CONTROL_TEXT, language, true) : read(path, language, ...rest);
  const checked = new Set([`${here}/preview-env.d.ts`, ...names.map((name) => `${here}/${name}`), ...(control ? [CONTROL] : [])]);
  const program = ts.createProgram([`${APP}src/vite-env.d.ts`, ...checked], options, host);
  const untypedWords = (one: ts.Diagnostic): boolean => one.code === 7016
    && /module '\.\.?\/[^']*\.mjs'/u.test(ts.flattenDiagnosticMessageText(one.messageText, ' '));
  return ts.getPreEmitDiagnostics(program)
    .filter((one) => !one.file || (checked.has(one.file.fileName) && !untypedWords(one)))
    .map((one) => {
      const message = `TS${one.code} ${ts.flattenDiagnosticMessageText(one.messageText, ' ')}`;
      if (!one.file) return message;
      const at = one.file.getLineAndCharacterOfPosition(one.start ?? 0).line + 1;
      return `${one.file.fileName.slice(here.length + 1)}:${at} ${message}`;
    });
}
const previewModules = (): string[] => readdirSync(here).filter((name) => name.endsWith('.ts') && !name.endsWith('.d.ts')).sort();

describe('the world workspace preview\'s edits to this app', () => {
  it('finds each seam exactly once in the sources', async () => {
    const { SEAMS, occurrences } = await seams();
    expect(SEAMS.map((one) => one.seam)).toEqual([
      'picker hook', 'start() deep link', 'begin() await', 'objects.begin mount',
      'Your worlds pictures', 'Your worlds open', 'Your worlds front door', 'Your worlds create', 'land drawn', 'opening first',
    ]);
    for (const one of SEAMS) expect(occurrences(source(one.file), one.target), `${one.seam} in ${one.file}`).toBe(1);
  });

  it('applies to each file without adding a missing name, a misplaced await or a syntax error', async () => {
    const { SEAM_FILES, patchSource } = await seams();
    for (const file of SEAM_FILES) {
      const code = source(file);
      const patched = patchSource(file, code, here);
      expect(patched, file).not.toBeNull();
      expect(patched, file).not.toBe(code);
      expect(introduced(file, code, patched!), file).toEqual([]);
    }
  }, 60_000);

  it("draws a moment's kept preview its next society afresh, as when the world opened, so nobody walks there", async () => {
    const { patchSource } = await seams();
    const selection = 'web/packages/app/src/composition/environment-selection.ts';
    const patched = patchSource(selection, source(selection), here)!;
    const again = patched.split('\n').find((line) => line.includes('atlas.__workspaceDrawSocietyAgain = '));
    expect(again).toBeDefined();
    // Read first: a read whose digest is the last one drawn draws nothing new, and a moment's read keeps the served
    // digest. Then the snapshot drawn is forgotten and the crowd cleared, and the view just read is drawn as a first
    // one: everyone placed where it puts them, rather than walked there from the last moment.
    const at = (text: string) => again!.indexOf(text);
    expect(at('await liveSociety?.refresh()')).toBeGreaterThan(-1);
    expect(at('renderedSnapshot = null')).toBeGreaterThan(at('await liveSociety?.refresh()'));
    expect(at('atlas.authoredSociety?.clearSociety()')).toBeGreaterThan(at('await liveSociety?.refresh()'));
    expect(at('reflectSavedWorldSociety(live.view)')).toBeGreaterThan(at('renderedSnapshot = null'));
    expect(at('reflectSavedWorldSociety(live.view)')).toBeGreaterThan(at('atlas.authoredSociety?.clearSociety()'));
  });

  it('keeps a town still baking under its opening and opens it in place once baked, with no second page load (B1)', async () => {
    const { patchSource, BAKE_POLL_MS, BAKE_READS } = await seams() as Seams & { BAKE_POLL_MS: number; BAKE_READS: number };
    const main = 'web/packages/app/src/main.ts';
    const patched = patchSource(main, source(main), here)!;
    const opened = patched.slice(patched.indexOf('const reviewEntryId'));
    const waits = opened.indexOf("if (reviewEntry && reviewEntry.generatedGround?.tiles.some((tile) => tile.state === 'baking')) {");
    const reloads = opened.indexOf('location.reload();');
    const taken = opened.indexOf('reviewEntry = again;');
    const mounts = opened.indexOf('await mount(); return;');
    // While a tile bakes the address waits, reading the entry again; nothing is mounted until it reads baked.
    expect(waits).toBeGreaterThan(-1);
    expect(reloads).toBeGreaterThan(waits);
    const waiting = opened.slice(waits, reloads);
    expect(waiting).toContain('await state.worldEntries?.entry(reviewEntry.entryId)');
    expect(waiting).toContain(`setTimeout(done, ${BAKE_POLL_MS})`);
    expect(waiting).toContain(`read < ${BAKE_READS}`);
    expect(waiting).not.toContain('mount(');
    // A tile that failed, or one still baking after every read, opens the page again, which says so.
    expect(waiting).toMatch(/if \(!again \|\| again\.generatedGround\?\.tiles\.some\(\(tile\) => tile\.state === 'baking' \|\| tile\.state === 'failed'\)\) \{\n\s*$/u);
    // Baked: the fresh entry takes the saved one's place and opens through the same lines as a baked town opened from
    // its address, with no second page load.
    expect(taken).toBeGreaterThan(reloads);
    expect(mounts).toBeGreaterThan(taken);
    expect(opened.slice(reloads, taken)).toContain('candidate.entryId === again.entryId ? again : candidate');
    expect(opened.slice(taken, mounts)).toMatch(/^reviewEntry = again;\n\s*\}\n\s*if \(reviewEntry\) \{ await openWorldEntryContext\(state, reviewEntry\);/u);
    expect(opened.slice(taken, mounts)).not.toContain('location.reload');
    // The opening names the bake (C3): its share is shown before the first wait and after each read, from the
    // tiles the entry serves, and the bake's own report ends it before the fresh entry opens.
    const first = waiting.indexOf('bakeShown(reviewEntry);');
    expect(first).toBeGreaterThan(-1);
    expect(first).toBeLessThan(waiting.indexOf('await new Promise((done) => setTimeout(done'));
    expect(waiting).toContain('detail: { baking: bakeShare(entry.generatedGround?.tiles) }');
    expect(waiting.indexOf('if (again) bakeShown(again);')).toBeGreaterThan(waiting.indexOf('await state.worldEntries?.entry(reviewEntry.entryId)'));
    const made = opened.indexOf("detail: { report: 'land-made' }");
    expect(made).toBeGreaterThan(reloads);
    expect(made).toBeLessThan(taken);
    expect(patched).toContain(`import { bakeShare } from '/@fs/${here}/opening-steps.mjs';`);
    // Its land is asked for before the first wait, and nothing waits on the ask.
    const asks = waiting.indexOf("void import('./composition/town-land.js').then((land) => land.askForTownLand(asking, reviewEntry)");
    expect(asks).toBeGreaterThan(-1);
    expect(asks).toBeLessThan(waiting.indexOf('await new Promise((done) => setTimeout(done'));
    // Bounded: five minutes of reads at most before it opens again.
    expect(BAKE_POLL_MS * BAKE_READS).toBe(300_000);
  });

  it('sends a town with a tile that could not be baked to Your worlds, saying which and why, never mounting it', async () => {
    const { patchSource } = await seams();
    const { fill, say } = await import('../src/ui/copy.js');
    const main = 'web/packages/app/src/main.ts';
    const patched = patchSource(main, source(main), here)!;
    const opened = patched.slice(patched.indexOf('const reviewEntryId'));
    const fails = opened.indexOf("if (reviewEntry && reviewEntry.generatedGround?.tiles.some((tile) => tile.state === 'failed')) {");
    const waits = opened.indexOf("tile.state === 'baking'");
    // Read before the bake's wait, so a bake that fails while it is waited for ends here after its reload.
    expect(fails).toBeGreaterThan(-1);
    expect(fails).toBeLessThan(waits);
    const failing = opened.slice(fails, waits);
    expect(failing).toContain("failed: fill('world.opening.didNotOpen', { title: reviewEntry.title }) + ' ' + say('world.generated.failed') + ' ' + say('world.generated.openTriesAgain')");
    expect(failing).toMatch(/await mountNoWorld\(\{ retry: \(\) => start\(token, csrfToken\), failed: [^\n]*\}\);\n\s*return;/u);
    expect(failing).not.toMatch(/\bmount\(\)|setTimeout|location\.reload/u);
    // What Your worlds says, in the words a world that did not open is said with.
    expect(fill('world.opening.didNotOpen', { title: 'A small town' }) + ' ' + say('world.generated.failed') + ' ' + say('world.generated.openTriesAgain'))
      .toBe('A small town did not open. Part of this world could not be made, so it cannot be drawn. Open tries to make it again.');
  });

  it("asks for a failed world's bakes again on a person's Open, never as its address opens", async () => {
    const { patchSource } = await seams();
    const main = 'web/packages/app/src/main.ts';
    const patched = patchSource(main, source(main), here)!;
    const opening = patched.slice(patched.indexOf('const open = async (entry'));
    const open = opening.slice(0, opening.indexOf('\n  };') + 5);
    const asks = open.indexOf("if (entry.generatedGround?.tiles.some((tile) => tile.state === 'failed')) await state.worldEntries?.askForBakesAgain(entry).catch(() => 0);");
    // Asked, and waited for, before the world opens; a refused ask opens it all the same.
    expect(asks).toBeGreaterThan(-1);
    expect(asks).toBeLessThan(open.indexOf('return openFromFrontDoor(entry.entryId);'));
    // The address opens on what the server says, and asks for nothing: a fault every bake meets is not asked for in a loop.
    const address = patched.slice(patched.indexOf('const reviewEntryId'), patched.indexOf("pendingEntryProblem = 'This saved world is no longer available."));
    expect(address).not.toContain('askForBakesAgain');
  });

  it('notices a seam whose code no longer fits: a positive control', async () => {
    const { patchSource, occurrences } = await seams();
    const file = 'web/packages/app/src/composition/environment-selection.ts';
    // As if a change renamed the variable the picker hook reads.
    const renamed = source(file).replaceAll('pickedAlong', 'pickedOnTheWay');
    const found = introduced(file, renamed, patchSource(file, renamed, here)!);
    expect(found).toHaveLength(1);
    expect(found[0]).toMatch(/^TS(2304|2552): Cannot find name 'pickedAlong'\./u);
    // And a target that no longer occurs once is refused by name.
    const main = 'web/packages/app/src/main.ts';
    const doubled = `${source(main)}\nvoid environmentSelection.begin();\n`;
    expect(occurrences(doubled, 'void environmentSelection.begin();')).toBe(2);
    expect(() => patchSource(main, doubled, here)).toThrow(/"begin\(\) await" occurs 2 times/u);
  }, 60_000);
});

describe('the world workspace preview\'s modules', () => {
  it('notices a misused import and an untyped parameter in a preview module: a positive control', () => {
    const found = previewTypeErrors([], { control: true });
    expect(found.map((one) => one.replace(/ TS(\d+) .*/u, ' TS$1'))).toEqual([
      'type-check-control.ts:3 TS2322', 'type-check-control.ts:4 TS7006',
    ]);
    expect(found[0]).toMatch(/'DocumentFragment' is not assignable to type 'number'/u);
  }, 60_000);

  it('type-check under this app\'s compiler options, the two untyped-style hosts under looser ones', () => {
    const modules = previewModules();
    expect(modules).toEqual(expect.arrayContaining([...LOOSE]));
    expect(previewTypeErrors(modules.filter((name) => !LOOSE.has(name)))).toEqual([]);
    expect(previewTypeErrors([...LOOSE], { looser: true })).toEqual([]);
  }, 60_000);
});

describe('the world workspace preview\'s own checks', () => {
  // Each script asserts at its top level; importing it runs it, and a failed assertion fails here.
  it.each(['verify-discovery.mjs', 'verify-observer-requests.mjs', 'verify-decision-words.mjs', 'verify-compare-words.mjs', 'verify-personality-words.mjs', 'verify-read-backoff.mjs', 'verify-entity-activity.mjs', 'verify-front-door.mjs', 'verify-build-words.mjs', 'verify-world-ui.mjs', 'verify-world-corners.mjs', 'verify-character-words.mjs', 'verify-character-view.mjs', 'verify-run-words.mjs', 'verify-entity-run.mjs', 'verify-entity-assignment.mjs', 'verify-world-opening.mjs', 'verify-history.mjs', 'verify-world-screen.mjs', 'verify-create-words.mjs', 'verify-create-steps.mjs', 'verify-talk-words.mjs', 'verify-talk-pops.mjs', 'verify-talk-scene.mjs', 'verify-moment-framing.mjs', 'verify-character-group.mjs', 'verify-day-rows.mjs', 'verify-decision-flow.mjs', 'verify-compare-line.mjs'])('%s passes', async (script) => {
    await expect(preview(script)).resolves.toBeDefined();
  });
});

describe('the app\'s production build', () => {
  /** A sentence only the workspace says (build mode's refusal in a world with nowhere to place a thing). */
  const WORKSPACE_WORDS = 'Nothing can be placed in this world.';

  it('carries none of the workspace\'s words in the app\'s own sources: a positive control', () => {
    const sources = (directory: URL): string[] => readdirSync(directory, { withFileTypes: true }).flatMap((one) =>
      one.isDirectory() ? sources(new URL(one.name + '/', directory)) : one.name.endsWith('.ts') ? [readFileSync(new URL(one.name, directory), 'utf8')] : []);
    expect(sources(new URL('web/packages/app/src/', REPOSITORY)).some((text) => text.includes(WORKSPACE_WORDS))).toBe(false);
  });

  it('carries the world workspace, reading through the app\'s own /api, with no development path in it', async () => {
    const { build } = await import('vite');
    const out = mkdtempSync(join(tmpdir(), 'workspace-build-'));
    try {
      await build({
        configFile: fileURLToPath(new URL('web/packages/app/vite.config.ts', REPOSITORY)),
        root: fileURLToPath(new URL('web/packages/app/', REPOSITORY)),
        logLevel: 'silent',
        build: { outDir: out, emptyOutDir: true },
      });
      const assets = join(out, 'assets');
      const bundle = readdirSync(assets).filter((name) => name.endsWith('.js')).map((name) => readFileSync(join(assets, name), 'utf8')).join('\n');
      expect(bundle).toContain(WORKSPACE_WORDS);
      expect(bundle).not.toContain('/review-api');
      expect(bundle).not.toContain(fileURLToPath(REPOSITORY).replace(/\/$/u, ''));
    } finally {
      rmSync(out, { recursive: true, force: true });
    }
  }, 120_000);
});
