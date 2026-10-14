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
  { seam: 'Your worlds pictures', file: MAIN, target: '    picture: worldPicture,' },
  {
    seam: 'Your worlds open', file: MAIN, target: `  const open = async (entry: typeof state.savedWorldEntries[number]): Promise<void> => {
    await openWorldEntryContext(state, entry);
    state.worldEntryError = null;
    shell.removeAttribute('data-world-state');
    await mount();
  };`,
  },
  { seam: 'Your worlds front door', file: MAIN, target: '  replaceSurface(shell, [yourWorlds.root]);' },
]);

/** The files the preview edits, relative to the repository root. */
export const SEAM_FILES = Object.freeze([...new Set(SEAMS.map(seam => seam.file))]);

const seam = name => SEAMS.find(one => one.seam === name).target;

/** How often `target` occurs in `code`. */
export const occurrences = (code, target) => code.split(target).length - 1;

/**
 * `code` of the repository-relative `file` as the preview serves it, or null where the preview
 * does not edit that file. `here` is this folder's absolute path, which the workspace imports name.
 * Throws, naming the seam, where a target does not occur exactly once.
 *
 * Your worlds becomes the front door (front-door.ts): its pictures, its Open, which goes to this
 * workspace's world view of the chosen world, and its look. A world opened by its address
 * (`?entry=`) mounts the workspace's world view, or, in a scene preview, only the preview's camera.
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
  return `import { mountContextualWorld } from '/@fs/${here}/contextual-world.ts';
import { mountFrontDoor, frontDoorPicture, openFromFrontDoor } from '/@fs/${here}/front-door.ts';
import { mountScenePreview, scenePreviewPage } from '/@fs/${here}/front-door-preview.ts';
` + code
    .replace(seam('start() deep link'), `    const reviewEntryId = new URLSearchParams(location.search).get('entry');
    if (reviewEntryId) {
      const reviewEntry = state.savedWorldEntries.find(entry => entry.entryId === reviewEntryId);
      if (reviewEntry) { await openWorldEntryContext(state, reviewEntry); state.worldEntryError = null; shell.removeAttribute('data-world-state'); await mount(); return; }
      pendingEntryProblem = 'This saved world is no longer available. Choose a world here.';
    }
` + seam('start() deep link'))
    .replace(seam('begin() await'), 'await environmentSelection.begin();')
    .replace(seam('objects.begin mount'), `await objects.begin(state.activeWorldEntry?.authoredVersionId);
      if (scenePreviewPage()) mountScenePreview({ state, renderer });
      else if (state.activeWorldEntry) await mountContextualWorld({state, renderer, selection: environmentSelection, objects});`)
    .replace(seam('Your worlds pictures'), '    picture: (entry) => frontDoorPicture(entry) ?? worldPicture(entry),')
    .replace(seam('Your worlds open'), '  const open = async (entry: typeof state.savedWorldEntries[number]): Promise<void> => openFromFrontDoor(entry.entryId);')
    .replace(seam('Your worlds front door'), seam('Your worlds front door') + '\n  mountFrontDoor({ root: yourWorlds.root, entries: state.savedWorldEntries });');
}
