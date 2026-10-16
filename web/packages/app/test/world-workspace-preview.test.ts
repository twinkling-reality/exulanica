// The world workspace preview (tools/previews/world-workspace) runs this app and edits main.ts and
// environment-selection.ts as Vite serves them (seams.mjs). Each edit needs its target to occur once
// and the code it inserts to still compile where it lands: a renamed variable or a lost `async`
// would otherwise break the preview with no test noticing. Each patched file is type-checked alone
// against the same file unpatched, and only what the edit introduces counts. The preview's own
// checks (verify-*.mjs) run here too, unchanged.
import { readFileSync } from 'node:fs';
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
 * Vite serves, never resolvable here, so they are expected to be unresolved.
 */
const EXPECTED = [/^TS(2307|2792): Cannot find module '\/@fs\/.*\/(contextual-world|front-door|front-door-preview|world-opening|create-world)\.ts'/u];
function introduced(file: string, before: string, after: string): string[] {
  const left = new Map<string, number>();
  for (const one of diagnostics(file, before)) left.set(one, (left.get(one) ?? 0) + 1);
  return diagnostics(file, after).filter((one) => {
    const held = left.get(one) ?? 0;
    if (held > 0) { left.set(one, held - 1); return false; }
    return !EXPECTED.some((expected) => expected.test(one));
  });
}

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

describe('the world workspace preview\'s own checks', () => {
  // Each script asserts at its top level; importing it runs it, and a failed assertion fails here.
  it.each(['verify-discovery.mjs', 'verify-observer-requests.mjs', 'verify-decision-words.mjs', 'verify-compare-words.mjs', 'verify-personality-words.mjs', 'verify-read-backoff.mjs', 'verify-entity-activity.mjs', 'verify-front-door.mjs', 'verify-build-words.mjs', 'verify-world-ui.mjs', 'verify-world-corners.mjs', 'verify-character-words.mjs', 'verify-character-view.mjs', 'verify-run-words.mjs', 'verify-entity-run.mjs', 'verify-entity-assignment.mjs', 'verify-world-opening.mjs', 'verify-history.mjs', 'verify-world-screen.mjs', 'verify-create-words.mjs', 'verify-create-steps.mjs', 'verify-talk-words.mjs', 'verify-talk-pops.mjs', 'verify-talk-scene.mjs'])('%s passes', async (script) => {
    await expect(preview(script)).resolves.toBeDefined();
  });
});
