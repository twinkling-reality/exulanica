import type * as pc from 'playcanvas';
import { resolveLookRole, type LookFamily, type ResolvedStylePack, type StylePackSurface } from '@exulanica/atlas-core';
import type { SiteDrawing, SiteSlot } from '../generated-site/site-drawing.js';
import type { SiteDresser } from '../generated-site/site-mount.js';
import { attachTileInk } from '../generated-tile/ink.js';
import type { RenderShading } from '../generated-tile/look.js';
import { applyShading } from '../generated-tile/shading.js';
import { dressSlots, type PieceSlot } from './dresser.js';
import { uploadPackPieces, type FetchedPieces } from './pieces.js';
import { swatchMaterial } from './swatch-material.js';

/**
 * A world made from a world kind, dressed in a style pack.
 *
 * The site's drawing names every drawn piece as a slot with a look role, and this dresser resolves
 * each in the pack by the contract's one rule (`resolveLookRole`): the leaf, then the family's
 * `default` leaf, a surface before a piece at each. A slot the engine draws as a primitive takes
 * either; a `none` slot, a hole only a pack fills (a door left open, a whole structure's module),
 * takes a piece alone. A surface's swatch, with its up swatch, becomes the material of the slot's
 * primitive. A piece stands in the slot by its family's fit, baked with every other piece into one
 * mesh per swatch (`dressSlots`), and the slot's primitive is hidden while the piece stands. A slot
 * the pack does not dress keeps the engine's primitive in its fallback colour, drawn in the pack's
 * shading, so a toon site has no surface outside its bands. When the shading draws ink, everything
 * the site draws is outlined.
 *
 * A site holds no texture set's images, so it takes a pack's swatches and pieces only: a leaf the
 * pack dresses with a texture set is resolved as if the pack left it out, so it takes its family's
 * `default`. Nothing here changes a slot, the walk or the seats; the disposer puts back every
 * material, shows every primitive again and frees everything it made, before the slots go.
 */

/** A prepared pack, ready to dress any site. */
export interface SitePackDressing {
  readonly pack: ResolvedStylePack;
  readonly families: ReadonlyMap<string, LookFamily>;
  readonly pieces: FetchedPieces;
  readonly shading: RenderShading;
  /** Told what one site's dressing drew, each time a site is dressed. */
  readonly told?: (summary: SiteDressingSummary) => void;
}

/** What a site's dressing drew, slot by slot. */
export interface SiteDressingSummary {
  /** Slots drawn in one of the pack's surfaces. */
  readonly surfaces: number;
  /** Slots a piece stands in. */
  readonly pieces: number;
  /** Pieces placed: a tiled slot places one per copy. */
  readonly placed: number;
  /** Drawn slots left as the engine's primitive. */
  readonly undressed: number;
  /** Ink segments drawn, when the shading draws ink. */
  readonly inkSegments: number;
}

/**
 * A slot's front in plan (east, north) by its quarter turns, counterclockwise seen from above: a
 * slot facing north turns 0, west 1, south 2 and east 3.
 */
const FRONTS: readonly (readonly [number, number])[] = Object.freeze([[0, 1], [-1, 0], [0, -1], [1, 0]]);

/** The pack as a site may draw it: its surfaces that are swatches, every texture set left out. */
function swatchesOnly(pack: ResolvedStylePack): ResolvedStylePack {
  const surfaces: Record<string, StylePackSurface> = {};
  for (const [role, surface] of Object.entries(pack.surfaces)) {
    if ('swatch' in surface) surfaces[role] = surface;
  }
  return { ...pack, surfaces };
}

function pieceSlot(slot: SiteSlot): PieceSlot {
  return {
    identity: slot.identity,
    lookRole: slot.lookRole,
    positionMm: slot.positionMm,
    front: FRONTS[slot.yawQuarterTurns]!,
    boxMm: slot.boxMm,
  };
}

/** The dresser that draws any site in `dressing`'s pack. */
export function packSiteDresser(dressing: SitePackDressing): SiteDresser {
  const pack = swatchesOnly(dressing.pack);
  const { families, shading } = dressing;
  return (host, drawn, drawing: SiteDrawing) => {
    const device = host.app.graphicsDevice;
    const made: pc.StandardMaterial[] = [];
    const replaced: (readonly [pc.MeshInstance, pc.Material])[] = [];
    const hidden: (readonly [pc.Entity, boolean])[] = [];
    const surfaceMaterials = new Map<string, pc.StandardMaterial>();
    const shadedFallbacks = new Map<pc.Material, pc.StandardMaterial | null>();
    const wear = (entity: pc.Entity, identity: string, material: (current: pc.Material) => pc.Material): void => {
      const shape = entity.findByName(`${identity}:shape`) as pc.Entity | null;
      for (const instance of shape?.render?.meshInstances ?? []) {
        const next = material(instance.material);
        if (next === instance.material) continue;
        replaced.push([instance, instance.material]);
        instance.material = next;
      }
    };
    /** The engine's fallback colour in the pack's shading, or the material itself where the shading changes nothing. */
    const shaded = (fallback: pc.Material): pc.Material => {
      if (!shadedFallbacks.has(fallback)) {
        const copy = (fallback as pc.StandardMaterial).clone();
        copy.name = `style-pack:shaded:${fallback.name}`;
        if (applyShading(copy, shading)) {
          made.push(copy);
          shadedFallbacks.set(fallback, copy);
        } else {
          copy.destroy();
          shadedFallbacks.set(fallback, null);
        }
      }
      return shadedFallbacks.get(fallback) ?? fallback;
    };

    let surfaces = 0;
    let undressed = 0;
    const modules: PieceSlot[] = [];
    const leftAsDrawn: SiteSlot[] = [];
    for (const slot of drawing.slots) {
      const entity = drawn.entities.get(slot.identity);
      const resolved = resolveLookRole(pack, slot, families, entity === undefined ? 'module' : 'either');
      if (resolved?.kind === 'module') {
        modules.push(pieceSlot(slot));
      } else if (resolved?.kind === 'surface' && resolved.swatch !== null && entity !== undefined) {
        let material = surfaceMaterials.get(resolved.role);
        if (material === undefined) {
          material = swatchMaterial(resolved.swatch, resolved.up, shading, `style-pack:surface:${resolved.role}`);
          made.push(material);
          surfaceMaterials.set(resolved.role, material);
        }
        const worn = material;
        wear(entity, slot.identity, () => worn);
        surfaces += 1;
      } else if (entity !== undefined) {
        leftAsDrawn.push(slot);
      }
    }

    const pieces = uploadPackPieces(device, dressing.pieces);
    const placed = dressSlots(drawn.root, modules, pack, families, pieces, shading);
    const standing = new Set(modules.map((slot) => slot.identity));
    for (const identity of placed.undressed) standing.delete(identity);
    for (const identity of standing) {
      const entity = drawn.entities.get(identity);
      if (entity === undefined) continue;
      hidden.push([entity, entity.enabled]);
      entity.enabled = false;
    }
    // A drawn slot no piece could stand in after all keeps its primitive, as one the pack left out.
    for (const identity of placed.undressed) {
      const slot = drawing.slots.find((one) => one.identity === identity);
      if (slot !== undefined && drawn.entities.has(identity)) leftAsDrawn.push(slot);
    }
    for (const slot of leftAsDrawn) {
      wear(drawn.entities.get(slot.identity)!, slot.identity, shaded);
      undressed += 1;
    }

    const ink = shading.ink === null ? null : attachTileInk(device, drawn.root, shading.ink, undefined, ['']);
    dressing.told?.({
      surfaces,
      pieces: standing.size,
      placed: placed.placed,
      undressed,
      inkSegments: ink?.segments ?? 0,
    });

    let undone = false;
    return () => {
      if (undone) return;
      undone = true;
      ink?.dispose();
      placed.dispose();
      for (const [entity, enabled] of hidden.splice(0).reverse()) entity.enabled = enabled;
      for (const [instance, material] of replaced.splice(0).reverse()) instance.material = material;
      for (const material of made.splice(0)) material.destroy();
      pieces.dispose();
    };
  };
}
