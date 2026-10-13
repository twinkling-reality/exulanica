// The places the world workspace preview edits the app's own sources as Vite serves them, and the
// edit itself. serve.mjs applies it; web/packages/app/test/world-workspace-preview.test.ts checks
// it against the real sources, so a change to one of these lines fails a test instead of the
// preview's start-up.

const MAIN = 'web/packages/app/src/main.ts';
const SELECTION = 'web/packages/app/src/composition/environment-selection.ts';

/** Each target must occur exactly once in its file; `seam` names it in a refusal. */
export const SEAMS = Object.freeze([
  { seam: 'picker hook', file: SELECTION, target: '    const pickAlong = (' },
  { seam: 'start() deep link', file: MAIN, target: '    await mountNoWorld({ retry: () => start(token, csrfToken) });' },
  { seam: 'begin() await', file: MAIN, target: 'void environmentSelection.begin();' },
  { seam: 'objects.begin mount', file: MAIN, target: 'void objects.begin(state.activeWorldEntry?.authoredVersionId);' },
]);

/** The files the preview edits, relative to the repository root. */
export const SEAM_FILES = Object.freeze([...new Set(SEAMS.map(seam => seam.file))]);

const seam = name => SEAMS.find(one => one.seam === name).target;

/** How often `target` occurs in `code`. */
export const occurrences = (code, target) => code.split(target).length - 1;

/**
 * `code` of the repository-relative `file` as the preview serves it, or null where the preview
 * does not edit that file. `here` is this folder's absolute path, which the workspace import names.
 * Throws, naming the seam, where a target does not occur exactly once.
 */
export function patchSource(file, code, here) {
  if (!SEAM_FILES.includes(file)) return null;
  for (const one of SEAMS.filter(each => each.file === file)) {
    const found = occurrences(code, one.target);
    if (found !== 1) throw Error(`World workspace seam "${one.seam}" occurs ${found} times in ${file}; it must occur exactly once.`);
  }
  if (file === SELECTION) {
    return code.replace(seam('picker hook'), '    atlas.__workspacePick = pickedAlong;\n' + seam('picker hook'));
  }
  return `import { mountContextualWorld } from '/@fs/${here}/contextual-world.ts';\n` + code
    .replace(seam('start() deep link'), `    const reviewEntryId = new URLSearchParams(location.search).get('entry');
    if (reviewEntryId) {
      const reviewEntry = state.savedWorldEntries.find(entry => entry.entryId === reviewEntryId);
      if (reviewEntry) { await openWorldEntryContext(state, reviewEntry); state.worldEntryError = null; shell.removeAttribute('data-world-state'); await mount(); return; }
      pendingEntryProblem = 'This saved world is no longer available. Choose a world here.';
    }
` + seam('start() deep link'))
    .replace(seam('begin() await'), 'await environmentSelection.begin();')
    .replace(seam('objects.begin mount'), `await objects.begin(state.activeWorldEntry?.authoredVersionId);
      if (state.activeWorldEntry) await mountContextualWorld({state, renderer, selection: environmentSelection, objects});`);
}
