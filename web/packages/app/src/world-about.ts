/**
 * What the About panel says the open world is.
 *
 * The sentence is chosen by the kind of world the renderer draws (`WorldKind`, decided once by
 * `describeWorldKind` from the options the binding was created with), never by a world's name, so
 * a starter world is not described as a district and a new world is not described as an old one.
 * The words live in `ui/copy.ts` with every other sentence in the product; this file only says
 * which sentence belongs to which ground.
 */

import type { WorldGround, WorldKind } from '@exulanica/atlas-react/playcanvas';
import { fill, say } from './ui/copy.js';

/**
 * The copy for each ground a world can stand on. `memoryShown` and `memoryHidden` replace the
 * sentence while the memory layer is composed over, or kept apart from, a ground whose view has
 * its own layer to compose; a ground without them keeps its sentence, because hiding a layer does
 * not change what the world is.
 *
 * Keyed by every ground form, so a form the renderer adds fails the typecheck here until it has a
 * sentence rather than borrowing another form's.
 */
const GROUND_COPY: Readonly<Record<WorldGround['form'], {
  readonly about: string;
  readonly memoryShown?: string;
  readonly memoryHidden?: string;
}>> = Object.freeze({
  'authored-endless': { about: 'world.about.authored-endless' },
  'authored-flat': { about: 'world.about.authored-flat' },
  'scene-regions': { about: 'world.about.scene-regions' },
  'owned-district': {
    about: 'world.about.owned-district',
    memoryShown: 'world.about.district-memory-shown',
    memoryHidden: 'world.about.district-memory-hidden',
  },
  'generated-tile': { about: 'world.about.generated-tile' },
});

const MILLIMETRES_PER_METRE = 1000;

/** A length in whole metres when it is one, else to the tenth a person reads a ground at. */
function metres(millimetres: number): string {
  const value = millimetres / MILLIMETRES_PER_METRE;
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

/** The values a ground's sentence is filled with: a bounded starter states its own size. */
function groundValues(ground: WorldGround): Readonly<Record<string, string>> {
  if (ground.form !== 'authored-flat' || ground.region.ground.kind !== 'flat') return {};
  return {
    width: metres(2 * ground.region.ground.halfWidthMm),
    depth: metres(2 * ground.region.ground.halfDepthMm),
  };
}

/** What this world is, said the same way wherever it is said. */
export function aboutWorld(kind: WorldKind): string {
  return fill(GROUND_COPY[kind.ground.form].about, groundValues(kind.ground));
}

/**
 * What this world is while its memory layer is shown or hidden. Only a ground that states a layer
 * of its own to compose changes its sentence with the layer.
 */
export function aboutWorldLayers(kind: WorldKind, memoryLayerVisible: boolean): string {
  const copy = GROUND_COPY[kind.ground.form];
  const layered = memoryLayerVisible ? copy.memoryShown : copy.memoryHidden;
  return layered === undefined ? aboutWorld(kind) : say(layered);
}
