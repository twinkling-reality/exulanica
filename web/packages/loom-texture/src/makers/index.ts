import type { Maker } from '../maker.js';
import { manifestProblems } from '../recipe.js';
import { ashlarMaker } from './ashlar.js';
import { asphaltMaker } from './asphalt.js';
import { brickMaker } from './brick.js';
import { concreteMaker } from './concrete.js';
import { foliageMaker } from './foliage.js';
import { glazingMaker } from './glazing.js';
import { kerbMaker } from './kerb.js';
import { metalMaker } from './metal.js';
import { pavingMaker } from './paving.js';
import { renderMaker } from './render.js';

/**
 * Every maker this package has, sorted by id. A recipe names a maker by id and version, and this
 * is the only place that name resolves to code.
 */
export const MAKERS: readonly Maker[] = Object.freeze(
  [
    ashlarMaker,
    asphaltMaker,
    brickMaker,
    concreteMaker,
    kerbMaker,
    metalMaker,
    pavingMaker,
    renderMaker,
  ].sort((a, b) => (a.manifest.maker_id < b.manifest.maker_id ? -1 : 1)),
);

/**
 * Makers written and tested but not yet published, sorted by id. Each joins `MAKERS` in the commit
 * that publishes its first set, pins that set in a migration, and moves the set's entry from
 * `library-drafts/` to `library/`. Until then no published recipe can name one: `readLibrary`
 * resolves the library against `MAKERS` alone, and only this package's tests and inspection read
 * the drafts.
 */
export const DRAFT_MAKERS: readonly Maker[] = Object.freeze(
  [foliageMaker, glazingMaker].sort((a, b) => (a.manifest.maker_id < b.manifest.maker_id ? -1 : 1)),
);

for (const maker of [...MAKERS, ...DRAFT_MAKERS]) {
  const problems = manifestProblems(maker.manifest);
  if (problems.length > 0) {
    throw new Error(`${maker.manifest.maker_id} has a malformed manifest: ${problems.join('; ')}`);
  }
}

/** The maker a recipe names, or a refusal: there is no nearest version and no default maker. */
export function makerFor(id: string, version: number): Maker {
  const maker = MAKERS.find(
    (candidate) => candidate.manifest.maker_id === id && candidate.manifest.version === version,
  );
  if (maker === undefined) throw new Error(`no maker ${id} version ${version}`);
  return maker;
}
