// The places the world workspace preview edits the app's own sources as Vite serves them, and the
// edit itself. serve.mjs applies it; web/packages/app/test/world-workspace-preview.test.ts checks
// it against the real sources, so a change to one of these lines fails a test instead of the
// preview's start-up.

import { OPENING_EVENT, OPENING_STAGES } from './opening-steps.mjs';

const MAIN = 'web/packages/app/src/main.ts';
const SELECTION = 'web/packages/app/src/composition/environment-selection.ts';
const BOOTSTRAP = 'web/packages/app/src/bootstrap.ts';

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
  { seam: 'Your worlds create', file: MAIN, target: '        creating = showWorldCreation(closeCreate);' },
  { seam: 'land drawn', file: MAIN, target: '  const geographicDistrict = renderer.atlas.binding.ownedDistrict !== null;' },
  { seam: 'opening first', file: BOOTSTRAP, target: "void import('./main.js')" },
]);

/** How often a town's page reads its entry again while its tiles bake, and how many times at most. */
export const BAKE_POLL_MS = 1000;
export const BAKE_READS = 300;

/** How a seam tells the opening (world-opening.ts) that a loading stage ended (opening-steps.mjs). */
const report = (index, title = '') => `window.dispatchEvent(new CustomEvent('${OPENING_EVENT}', { detail: { report: '${OPENING_STAGES[index].report}'${title ? `, title: ${title}` : ''} } }));`;

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
 * A world's page shows its opening (world-opening.ts) from the app's first script, beside the app's
 * own start (its small module loads while the app's large one does), and the app reports each
 * loading stage to it as the stage ends: the world read, the land drawn, the people in.
 * Create a world on the front door is the workspace's own (create-world.ts, frames 20 to 22), in
 * place of the app's old dialog.
 * A town whose tiles are still baking when its address opens keeps its opening up and is opened only
 * once they are baked, as a reload opens it: mounted while they bake, its world view would stand on an
 * empty scene far from the town, over a mount that could not open it.
 */
export function patchSource(file, code, here) {
  if (!SEAM_FILES.includes(file)) return null;
  for (const one of SEAMS.filter(each => each.file === file)) {
    const found = occurrences(code, one.target);
    if (found !== 1) throw Error(`World workspace seam "${one.seam}" occurs ${found} times in ${file}; it must occur exactly once.`);
  }
  if (file === BOOTSTRAP) {
    return code.replace(seam('opening first'), `void import('/@fs/${here}/world-opening.ts').then((opening) => opening.mountOpening(), () => {});\n` + seam('opening first'));
  }
  if (file === SELECTION) {
    // Build mode mounts the placed things' layer itself where nothing is placed yet, as a society does:
    // its tray reads the library and draws through that layer.
    return code.replace(seam('picker hook'), '    atlas.__workspacePick = pickedAlong;\n    atlas.__workspaceThings = () => things;\n'
      + '    atlas.__workspaceMountThings = () => drawPlacedThings(atlas, regionId, true).then(() => things);\n' + seam('picker hook'));
  }
  return `import { mountContextualWorld } from '/@fs/${here}/contextual-world.ts';
import { mountFrontDoor, frontDoorPicture, openFromFrontDoor } from '/@fs/${here}/front-door.ts';
import { mountScenePreview, scenePreviewPage } from '/@fs/${here}/front-door-preview.ts';
import { mountCreateWorld } from '/@fs/${here}/create-world.ts';
import { creatureMakerFor } from '/@fs/${here}/world-creature.ts';
` + code
    .replace(seam('start() deep link'), `    const reviewEntryId = new URLSearchParams(location.search).get('entry');
    if (reviewEntryId) {
      const reviewEntry = state.savedWorldEntries.find(entry => entry.entryId === reviewEntryId);
      if (reviewEntry && reviewEntry.generatedGround?.tiles.some((tile) => tile.state === 'baking')) {
        // Read again every ${BAKE_POLL_MS} ms for up to ${BAKE_READS} reads; then the page opens again with whatever it reads.
        for (let read = 0, baking = true; baking && read < ${BAKE_READS}; read += 1) {
          await new Promise((done) => setTimeout(done, ${BAKE_POLL_MS}));
          const again = await state.worldEntries?.entry(reviewEntry.entryId).catch(() => null);
          baking = again?.generatedGround?.tiles.some((tile) => tile.state === 'baking') ?? true;
        }
        location.reload();
        return;
      }
      if (reviewEntry) { await openWorldEntryContext(state, reviewEntry); ${report(0, 'reviewEntry.title')} state.worldEntryError = null; shell.removeAttribute('data-world-state'); await mount(); return; }
      pendingEntryProblem = 'This saved world is no longer available. Choose a world here.';
    }
` + seam('start() deep link'))
    .replace(seam('begin() await'), `await environmentSelection.begin();\n  ${report(2)}`)
    .replace(seam('land drawn'), `  ${report(1)}\n` + seam('land drawn'))
    // Build mode's "Make a creature" tile opens the maker in the world (unit 9), where the page can ask.
    .replace(seam('objects.begin mount'), `await objects.begin(state.activeWorldEntry?.authoredVersionId);
      if (scenePreviewPage()) mountScenePreview({ state, renderer });
      else if (state.activeWorldEntry) await mountContextualWorld({state, renderer, selection: environmentSelection, objects, send: sendPlanned, binding: activeEntryWriteBinding, makeCreature: creatureMakerFor(state)});`)
    .replace(seam('Your worlds pictures'), '    picture: (entry) => frontDoorPicture(entry) ?? worldPicture(entry),')
    .replace(seam('Your worlds open'), '  const open = async (entry: typeof state.savedWorldEntries[number]): Promise<void> => openFromFrontDoor(entry.entryId);')
    .replace(seam('Your worlds front door'), seam('Your worlds front door') + '\n  mountFrontDoor({ root: yourWorlds.root, entries: state.savedWorldEntries });')
    .replace(seam('Your worlds create'), '        creating = mountCreateWorld({ root: yourWorlds.root, credentials: state.credentials, entries: state.worldEntries, onClose: closeCreate });');
}
