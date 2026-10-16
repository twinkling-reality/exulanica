import type * as pc from 'playcanvas';
import {
  PIECE_DRAWING_DEFAULTS, materialOfLeaf, planBorders, resolveLookRole, resolveSurfaceLookRole, unknownSurfaceLeaf,
  type GroundBorders, type GroundPlane, type LookFamily, type ResolvedStylePack, type SurfaceMaterials,
  type LandWater, type StyleSlot, type StylePackSurface, type SurfacePattern, type SurfacePatterns,
  type LandSurfaces,
} from '@exulanica/atlas-core';
import { growLandCover } from './land-cover.js';
import type { StructuredSiteDrawing, SiteSlot } from '../generated-site/site-drawing.js';
import { baseGroundSlot, type SiteDresser } from '../generated-site/site-mount.js';
import { linearRgb } from './preset-look.js';
import { SCENERY_STONES, SCENERY_TREES } from '../generated-site/site-scenery.js';
import { attachTileInk } from '../generated-tile/ink.js';
import type { RenderShading } from '../generated-tile/look.js';
import { applyShading } from '../generated-tile/shading.js';
import { applyBorder, bordersRun, clearPlaneBorder, setPlaneBorder } from './border-material.js';
import { applyGroundFinish, applySeaFinish, applyWaterFinish, finishRuns, setFinishWaters, waterRectOf, type SurfaceFinish, type WaterRect } from './ground-finish.js';
import { PlanarReflection } from './planar-reflection.js';
import { dressSlots, placementMatrix, type PieceSlot } from './dresser.js';
import { applyFallFinish } from './fall-finish.js';
import { applyPattern } from './pattern-material.js';
import { uploadPackPieces, type FetchedPieces } from './pieces.js';
import { swatchMaterial } from './swatch-material.js';
import { SiteTextures, packTextureSetId } from './site-textures.js';
import { WaterRipples } from './water-material.js';
import { coverMatrix, growCover, slotRectMm, type CoverSlot } from './ground-cover.js';
import { CLIMB_STANDOFF_M, growClimbers, type ClimbSlot } from './climbers.js';
import { growTrailers, trailMatrix } from './trailers.js';
import { drawInstancedPieces, type InstancePlacement } from './instanced-pieces.js';
import { PlantWind, windRuns } from './wind.js';
import { applyFacadeFinish, clearFacadeWall, facadeApplied, facadeFronts, facadeRuns, facadeWears, litShareOf, setFacadeWall, type FacadeFront } from './facade-finish.js';
import type { PreparedTextureSet } from '../generated-tile/texture-materials.js';
import { FALLING_WATER_DEFAULTS, TILE_LOOK_V1, isRenderLook, type TileLook } from '../generated-tile/look.js';
import { seatGeometry, type SeatGeometry } from '../generated-site/site-seating.js';

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
 * A LEAF THE PACK DOES NOT STATE IS READ BY ITS MATERIAL before it takes the family's `default`,
 * where the dressing carries the surface material catalog (`resolveSurfaceLookRole`): `ground.sand`
 * is sand and `wall.adobe` adobe, in the pack's own surface for that material where it states one
 * and otherwise in the catalog's colour, drawn in the pack's shading like any swatch. A leaf whose
 * words name no material takes the default as before and is counted: the canvas says how many
 * slots wear a catalog material and which look roles were thrown away (`data-site-materials`,
 * `data-site-unknown-looks`), so the next catalog is written from the words that were written.
 *
 * A SURFACE WHOSE LEAF NAMES A MATERIAL IS NOT ONE FLAT COLOUR, where the dressing carries the
 * surface pattern catalog: the material's pattern (courses, boards, strokes, seams, ripples or a
 * grain) is drawn in its colour, whichever swatch that colour is (the catalog's, or the pack's own
 * surface for it, a lawn's included), toward the pack's ink where it draws ink
 * (`pattern-material.ts`). A pack's surface that colours its upward faces apart keeps that instead.
 * The canvas says how many slots are patterned (`data-site-patterned`).
 *
 * Texture surfaces reuse the tile's pinned texture uploads and material classes, with physical UVs
 * on copies of the primitive meshes. A refused set draws the unavailable pattern, never a swatch
 * substitute. Glass requests the environment's scene-colour copy only when it is drawn. Nothing
 * here changes slots, walking or seats; disposal restores meshes and materials before freeing uploads.
 */

/** A prepared pack, ready to dress any site. */

/** The set a surface is drawn in: a library set by its id, a pack's own texture by its key, or none for a swatch. */
function textureSetOf(surface: StylePackSurface): string | null {
  if ('texture_set' in surface) return surface.texture_set;
  return 'texture' in surface ? packTextureSetId(surface.texture) : null;
}

export interface SitePackDressing {
  readonly pack: ResolvedStylePack;
  readonly families: ReadonlyMap<string, LookFamily>;
  readonly pieces: FetchedPieces;
  readonly shading: RenderShading;
  readonly textures?: ReadonlyMap<string, PreparedTextureSet>;
  readonly look?: TileLook;
  /** The surface material catalog a leaf is read by before it takes its family's default; none reads no leaf. */
  readonly materials?: SurfaceMaterials;
  /** The surface pattern catalog a material's colour is patterned by; none, or no `materials`, draws every surface flat. */
  readonly patterns?: SurfacePatterns;
  /**
   * The ground border catalog the edges of a site's grounds are broken by, where two meet and at the
   * site's outer edge (`border-material.ts`); none, or no `materials`, draws every ground to its ruled
   * rectangle as before.
   */
  readonly borders?: GroundBorders;
  /**
   * The finish a site's grounds, paths and water are drawn with over their colours (`ground-finish.ts`):
   * a varied tone, wet ground near water, water lighter at its edge and darker in its middle with
   * drifting light, and a real reflection where it states a strength. None draws them flat as before.
   */
  readonly finish?: SurfaceFinish;
  /** The land's surface catalog the land is drawn in, so land cover grows by the role drawn at each point; none, every point is the land's own ground. */
  readonly landSurfaces?: LandSurfaces;
  /** Told what one site's dressing drew, each time a site is dressed. */
  readonly told?: (summary: SiteDressingSummary) => void;
}

/** What a site's dressing drew, slot by slot. */
export interface SiteDressingSummary {
  /** Slots drawn in one of the pack's surfaces. */
  readonly surfaces: number;
  /** Slots drawn in a catalog material's own colour, because the pack states none for it. */
  readonly materials: number;
  /** The look roles thrown away: each names no material the catalog knows, and its slots took the family default. Sorted. */
  readonly unknownLooks: readonly string[];
  /** Slots whose colour carries their material's pattern. */
  readonly patterned: number;
  /** Slots a piece stands in. */
  readonly pieces: number;
  /** Pieces placed: a tiled slot places one per copy. */
  readonly placed: number;
  /** Drawn slots left as the engine's primitive. */
  readonly undressed: number;
  /** Ink segments drawn, when the shading draws ink. */
  readonly inkSegments: number;
  /** Pieces of the pack standing as scenery beyond the place (its own tree at each tree); 0 where it has none. */
  readonly sceneryPieces: number;
  /** Ground planes drawn with a broken border, their own or a neighbour's over them. */
  readonly bordered: number;
  /** Neighbours left out of a plane's working because it has more than the working carries. */
  readonly borderNeighboursLeftOut: number;
  /**
   * What the pack's cover grew, where it states any: its pieces, the slots growing them, the pieces
   * the guard left out, and the points the bound on tries never tried.
   */
  readonly cover?: { readonly pieces: number; readonly slots: number; readonly leftOut: number; readonly untried: number };
  /** The building walls drawn with windows, where the pack states any facade, and the materials they wear. */
  readonly facade?: { readonly walls: number; readonly materials: number };
  /** What climbs the buildings' walls, where the pack states any: its plants, the buildings growing them, the plants the guard left out. */
  readonly climb?: { readonly pieces: number; readonly buildings: number; readonly leftOut: number };
  /**
   * What hangs over the terraces' edges, where the pack states trail and the site stands on land: its
   * plants, the grounds growing any, the plants hung over a wall, the plants the guard left out, and the
   * stations the bound on stations never read.
   */
  readonly trail?: { readonly pieces: number; readonly terraces: number; readonly walled: number; readonly leftOut: number; readonly untried: number };
  /** What grows on the land, where the pack states land cover: its pieces, by surface role, the pieces the guard left out and the points never tried. */
  readonly landCover?: { readonly pieces: number; readonly byRole: Readonly<Record<string, number>>; readonly leftOut: number; readonly untried: number };
  /** How many of the pieces' materials sway, where the look states a wind and the device runs it. */
  readonly swaying?: number;
}

/**
 * A slot's front in plan (east, north) by its quarter turns, counterclockwise seen from above: a
 * slot facing north turns 0, west 1, south 2 and east 3.
 */
const FRONTS: readonly (readonly [number, number])[] = Object.freeze([[0, 1], [-1, 0], [0, -1], [1, 0]]);

/** The look role a tree of the scenery beyond a place is dressed by: the pack's plant, whatever its leaf. */
const SCENERY_TREE_ROLE = 'plant.tree';

/** The families of a building's own envelope, which a piece dressing the whole building replaces. */
const BUILDING_ENVELOPE: ReadonlySet<string> = new Set(['wall', 'door', 'window', 'roof']);

function pieceSlot(slot: SiteSlot): PieceSlot {
  return {
    identity: slot.identity,
    lookRole: slot.lookRole,
    positionMm: slot.positionMm,
    front: FRONTS[slot.yawQuarterTurns]!,
    boxMm: slot.boxMm,
    ...(slot.drape === true ? { drape: true as const } : {}),
    ...(slot.storeyHeightMm === undefined ? {} : { storeyHeightMm: slot.storeyHeightMm }),
    ...(slot.arcadeBays === undefined ? {} : { arcadeBays: slot.arcadeBays }),
  };
}

/**
 * How far apart in height a site's waters may lie and still be reflected as one level, in metres:
 * the drawing lays its planes 6 mm apart, so waters drawn at one level differ by a few layers at
 * most; waters further apart than this are not one mirror, and none is reflected.
 */
const LEVEL_TOLERANCE_M = 0.05;

/** The dresser that draws any site in `dressing`'s pack. */
export function packSiteDresser(dressing: SitePackDressing): SiteDresser {
  const pack = dressing.pack;
  const { families, shading } = dressing;
  const catalog = dressing.materials ?? null;
  const patterns = catalog === null ? null : dressing.patterns ?? null;
  const borders = catalog === null ? null : dressing.borders ?? null;
  /** The pattern of the material a slot's leaf names, where the catalogs state one. */
  const patternOf = (slot: SiteSlot): SurfacePattern | null => {
    if (catalog === null || patterns === null) return null;
    const material = materialOfLeaf(catalog, slot.family, slot.leaf);
    return material === null ? null : patterns.byMaterial.get(material.key) ?? null;
  };
  return (host, drawn, drawing: StructuredSiteDrawing, scenery = null, environment, land) => {
    const device = host.app.graphicsDevice;
    const textures = new SiteTextures(device, dressing.look ?? TILE_LOOK_V1, dressing.textures);
    const water = new WaterRipples(host.app, host.camera);
    // A look's water finish, when it states one; otherwise water keeps its ripples alone.
    const waterFinish = dressing.look !== undefined && isRenderLook(dressing.look) ? dressing.look.water ?? null : null;
    // A water whose look states how it meets solids takes its foam by the look role it asks for, so two
    // waters drawn in one surface but asking for different roles keep a material each.
    const waterRoleKey = (slot: SiteSlot): string => slot.family === 'water' && waterFinish?.contact !== undefined ? `@${slot.lookRole}` : '';
    const fallingWater = (dressing.look !== undefined && isRenderLook(dressing.look) ? dressing.look.fallingWater : undefined) ?? FALLING_WATER_DEFAULTS;
    // The surface finish, on the device it is written for; the materials it was set into, by kind.
    const finish = dressing.finish !== undefined && finishRuns(device) ? dressing.finish : null;
    const finishedGrounds = new Set<pc.StandardMaterial>();
    const finishedWaters = new Set<pc.StandardMaterial>();
    /** `byDepth`: the look's water finish owns this water's colour, so the surface finish leaves it. */
    const finished = (slot: SiteSlot, material: pc.StandardMaterial, byDepth: boolean): void => {
      if (finish === null) return;
      if (slot.family === 'water') {
        if (byDepth) return;
        applyWaterFinish(device, material, finish);
        water.animate(material);
        finishedWaters.add(material);
      } else if (slot.family === 'ground' || slot.family === 'path') {
        applyGroundFinish(device, material, finish);
        finishedGrounds.add(material);
      }
    };
    // The pack's windows, where it states a facade for a wall's look role or the role its surface is
    // drawn in, on the device they are written for: on the walls that face out of a building
    // (`facadeFronts`), each stating its building and its rule on its own instances, lit by the
    // light's own share or the rule's by the look's sun. Materials stay shared: a wall that states
    // none, a boundary wall among them, draws its plain colour; glazing draws none.
    const facades = Object.keys(pack.facade).length > 0 && facadeRuns(device) ? pack.facade : null;
    const fronts = facades === null ? new Map<string, FacadeFront>() : facadeFronts(drawing.slots);
    const facadeLook = dressing.look ?? TILE_LOOK_V1;
    const litStated = isRenderLook(facadeLook) ? facadeLook.litWindows ?? null : null;
    const facaded = new Set<pc.StandardMaterial>();
    const facadeWalls: string[] = [];
    const facing: pc.MeshInstance[] = [];
    /** The facade rule a wall facing out of its building takes: its own role's, else that of the role it is drawn in. */
    const facadeRuleOf = (slot: SiteSlot, drawnAs: string | null) => facades === null || !fronts.has(slot.identity)
      ? null : facades[slot.lookRole] ?? (drawnAs === null ? null : facades[drawnAs] ?? null);
    /** Set the facade into what a facade wall wears, its own, and state its building and rule on each of its instances. */
    const faceOut = (entity: pc.Entity, slot: SiteSlot, drawnAs: string | null): void => {
      const rule = facadeRuleOf(slot, drawnAs);
      if (rule === null) return;
      const litShare = litShareOf(rule, facadeLook.sun.elevationDeg, litStated);
      const shape = entity.findByName(`${slot.identity}:shape`) as pc.Entity | null;
      let stated = false;
      for (const instance of shape?.render?.meshInstances ?? []) {
        const material = instance.material;
        if (!facadeWears(material) || !setFacadeWall(instance, drawn.root, fronts.get(slot.identity)!, rule, litShare)) continue;
        if (!facadeApplied(material)) applyFacadeFinish(device, material);
        facaded.add(material);
        facing.push(instance);
        stated = true;
      }
      if (stated) facadeWalls.push(slot.identity);
    };
    const texturedSlots = new Set<string>();
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
    let materials = 0;
    let patterned = 0;
    let undressed = 0;
    const unknownLooks = new Set<string>();
    const modules: PieceSlot[] = [];
    const leftAsDrawn: SiteSlot[] = [];
    const resolve = (slot: SiteSlot) => {
      const accepts = drawn.entities.has(slot.identity) ? 'either' : 'module';
      return catalog === null
        ? resolveLookRole(pack, slot, families, accepts)
        : resolveSurfaceLookRole(pack, slot, families, accepts, catalog);
    };
    // The buildings the pack dresses with one piece each: their own walls, doors, windows and roof
    // give way to it once it stands; their rooms' floors and fixtures stay.
    const owners = new Set(drawing.slots.flatMap((slot) => (slot.structure === undefined ? [] : [slot.structure])));
    const dressedBuildings = new Set(drawing.slots
      .filter((slot) => owners.has(slot.identity) && resolve(slot)?.kind === 'module')
      .map((slot) => slot.identity));
    const envelopeOf = (slot: SiteSlot): string | null =>
      slot.structure !== undefined && dressedBuildings.has(slot.structure) && BUILDING_ENVELOPE.has(slot.family) ? slot.structure : null;
    for (const slot of drawing.slots) {
      const entity = drawn.entities.get(slot.identity);
      const resolved = resolve(slot);
      // A drawn slot whose leaf names nothing known is drawn as its family's default: counted, by its words.
      if (catalog !== null && entity !== undefined && resolved?.role !== slot.lookRole && unknownSurfaceLeaf(catalog, slot.lookRole)) {
        unknownLooks.add(slot.lookRole);
      }
      if (resolved?.kind === 'module') {
        // A dressed building's own door: the building's piece has its doors, so none is baked in.
        if (envelopeOf(slot) === null) modules.push(pieceSlot(slot));
      } else if (resolved?.kind === 'material' && entity !== undefined) {
        const pattern = patternOf(slot);
        const key = resolved.role + waterRoleKey(slot);
        let material = surfaceMaterials.get(key);
        if (material === undefined) {
          material = swatchMaterial(resolved.material.swatch, null, shading, `style-pack:material:${resolved.role}`);
          const byDepth = slot.family === 'water' && shading.model === 'pbr' && water.add(material, waterFinish, { role: slot.lookRole });
          if (pattern !== null) applyPattern(material, pattern, shading.ink);
          finished(slot, material, byDepth);
          made.push(material);
          surfaceMaterials.set(key, material);
        }
        const worn = material;
        wear(entity, slot.identity, () => worn);
        faceOut(entity, slot, resolved.role);
        materials += 1;
        if (pattern !== null) patterned += 1;
       } else if (resolved?.kind === 'surface' && textureSetOf(resolved.surface) !== null && entity !== undefined) {
        const shape = entity.findByName(`${slot.identity}:shape`) as pc.Entity | null;
        const unavailable = textures.metrics().unavailableSurfaces;
        for (const instance of shape?.render?.meshInstances ?? []) {
          if (textures.wear(instance, slot, textureSetOf(resolved.surface)!, resolved.up, drawn.root)) environment?.requestSceneColor();
        }
        // A wall whose texture could not be read shows that, and no windows over it.
        if (textures.metrics().unavailableSurfaces === unavailable) faceOut(entity, slot, resolved.role);
        texturedSlots.add(slot.identity);
        surfaces += 1;
      } else if (resolved?.kind === 'surface' && resolved.swatch !== null && entity !== undefined) {
        // The pack's own surface takes its material's pattern too, unless it colours its upward faces apart.
        const pattern = resolved.up === null ? patternOf(slot) : null;
        const key = pattern === null ? resolved.role : `${resolved.role}:${pattern.key}`;
        let material = surfaceMaterials.get(key + waterRoleKey(slot));
        if (material === undefined) {
          material = swatchMaterial(resolved.swatch, resolved.up, shading, `style-pack:surface:${key}`);
          const byDepth = slot.family === 'water' && shading.model === 'pbr' && water.add(material, waterFinish, { role: slot.lookRole });
          if (pattern !== null) applyPattern(material, pattern, shading.ink);
          finished(slot, material, byDepth);
          made.push(material);
          surfaceMaterials.set(key + waterRoleKey(slot), material);
        }
        const worn = material;
        wear(entity, slot.identity, () => worn);
        faceOut(entity, slot, resolved.role);
        surfaces += 1;
        if (pattern !== null) patterned += 1;
      } else if (entity !== undefined) {
        leftAsDrawn.push(slot);
      }
    }

    const pieces = uploadPackPieces(device, dressing.pieces, shading);
    // Textured pieces choose their level of detail by where the person looks from.
    const view = { app: host.app, camera: host.camera };
    const seatTriangles = new Map<string, SeatGeometry>();
    const placed = dressSlots(drawn.root, modules, pack, families, pieces, shading, {
      identities: new Set(drawing.seats.map(seat => seat.identity)),
      // Bound retained contact copies across the whole site; oversized seats remain unavailable.
      maximumVertices: 100_000,
      triangles: (identity, positions, normals) => seatTriangles.set(identity, seatGeometry(positions, normals)),
    }, land?.groundM, view);
    const standing = new Set(modules.map((slot) => slot.identity));
    for (const identity of placed.undressed) standing.delete(identity);
    for (const identity of standing) {
      const entity = drawn.entities.get(identity);
      if (entity === undefined) continue;
      hidden.push([entity, entity.enabled]);
      entity.enabled = false;
    }
    // A building whose piece stands: its own box gives way to it. One whose piece could not stand
    // keeps its walls and roof as drawn, and its doors open, as a pack with no door leaves them.
    for (const slot of drawing.slots) {
      const building = envelopeOf(slot);
      if (building === null || !standing.has(building)) continue;
      const entity = drawn.entities.get(slot.identity);
      if (entity === undefined || !entity.enabled) continue;
      hidden.push([entity, entity.enabled]);
      entity.enabled = false;
    }
    // What grows on the grounds, where the pack states cover for their look roles: its textured plant
    // pieces, instanced in cells like any textured piece, on the slots drawn as surfaces and nowhere
    // anything stands on them or lies over them. A piece the library holds untextured grows nowhere.
    const grown = Object.keys(pack.cover).length === 0 ? null : growCover(drawing.slots as readonly CoverSlot[], pack.cover, {
      land: land === undefined ? null : { groundMm: land.groundMm, waters: land.section.water },
      grows: (slot) => {
        const entity = drawn.entities.get(slot.identity);
        return entity !== undefined && entity.enabled && (slot.primitive === 'plane' || slot.primitive === 'box');
      },
      // The role its surface resolved to: a leaf the pack states takes its own rule alone, so a paving
      // drawn in its own surface never grows its family default's grass.
      drawnAs: (slot) => {
        const resolved = resolve(slot as SiteSlot);
        return resolved === null || resolved.kind === 'module' ? null : resolved.role;
      },
    });
    const coverPlacements: InstancePlacement[] = [];
    for (const point of grown?.points ?? []) {
      const module = pack.modules[point.piece];
      const variant = module?.variants[Math.floor(point.pick * module.variants.length)];
      const file = variant === undefined ? undefined : module!.files.get(variant.file);
      const piece = file === undefined ? undefined : pieces.get(module!, file);
      if (piece?.textured === undefined) continue;
      coverPlacements.push({
        key: `cover:${String(module!.stated)}:${file!.sha256}`,
        lod0: piece.textured.lod0,
        lod1: piece.textured.lod1,
        matrix: coverMatrix(point, point.upM),
        heightM: piece.bounds[4] * point.scale,
      });
    }
    const cover = coverPlacements.length === 0 ? null : drawInstancedPieces(drawn.root, coverPlacements, view);
    // What climbs the buildings, where the pack states climb for their look roles: its textured plant
    // pieces at the foot of the faces each rule lists, each scaled whole to the height it reaches and
    // set just proud of its face, instanced in cells like cover. A piece held untextured grows nowhere.
    const variantOf = (role: string, pick: number) => {
      const module = pack.modules[role];
      return module === undefined || module.variants.length === 0 ? null : { module, variant: module.variants[Math.floor(pick * module.variants.length)]! };
    };
    const climbing = Object.keys(pack.climb).length === 0 ? null : growClimbers(drawing.slots as readonly ClimbSlot[], pack.climb, {
      sizeOf: (role, pick) => variantOf(role, pick)?.variant.size_mm ?? null,
      sunAzimuthDeg: dressing.look?.sun.azimuthDeg ?? null,
    });
    const climbPlacements: InstancePlacement[] = [];
    for (const point of climbing?.points ?? []) {
      const chosen = variantOf(point.piece, point.pick);
      const file = chosen === null ? undefined : chosen.module.files.get(chosen.variant.file);
      const piece = file === undefined ? undefined : pieces.get(chosen!.module, file);
      if (piece?.textured === undefined || !(piece.bounds[4] > 0)) continue;
      const scale = point.heightM / piece.bounds[4];
      // The piece's back (its least z) stands its standoff in front of the face.
      const out = CLIMB_STANDOFF_M - piece.bounds[2] * scale;
      const [east, north, up] = point.footM;
      climbPlacements.push({
        key: `climb:${String(chosen!.module.stated)}:${file!.sha256}`,
        lod0: piece.textured.lod0,
        lod1: piece.textured.lod1,
        matrix: placementMatrix(point.outward, [east + point.outward[0] * out, north + point.outward[1] * out, up], [scale, scale, scale], 0),
        heightM: point.heightM,
      });
    }
    // A climbing plant's shadow lies on the wall a few centimetres behind it: climbers cast within the
    // drawing's own reach for them (by default none), not the trees' reach.
    const climbView = { ...view, drawing: { ...PIECE_DRAWING_DEFAULTS, shadowReachM: PIECE_DRAWING_DEFAULTS.climbShadowReachM } };
    const climbers = climbPlacements.length === 0 ? null : drawInstancedPieces(drawn.root, climbPlacements, climbView);
    // What hangs over the terraces' edges of a site on land, where the pack states trail for a ground's
    // look role, or else for the role its surface is drawn in (as cover's): its textured plant pieces
    // along each side of the ground's plane where the land falls away past it, each scaled whole to the
    // share of the face it hangs and laid down the face just proud of it, instanced in cells as the
    // climbers are and casting within their reach. The base ground is the land itself and grows none.
    const baseSlot = baseGroundSlot(drawing);
    const trailing = land === undefined || Object.keys(pack.trail).length === 0 ? null : growTrailers(drawing.slots.flatMap((slot) => {
      if (slot.identity === baseSlot?.identity || slot.family !== 'ground' || slot.primitive !== 'plane') return [];
      const entity = drawn.entities.get(slot.identity);
      if (entity === undefined || !entity.enabled) return [];
      const resolved = resolve(slot);
      const drawnAs = resolved === null || resolved.kind === 'module' ? null : resolved.role;
      const rule = pack.trail[slot.lookRole] ?? (drawnAs === null ? null : pack.trail[drawnAs] ?? null);
      return rule === null ? [] : [{ slot, rule }];
    }), land, drawing.slots, {
      sizeOf: (role, pick) => variantOf(role, pick)?.variant.size_mm ?? null,
      sunAzimuthDeg: dressing.look?.sun.azimuthDeg ?? null,
    });
    const trailPlacements: InstancePlacement[] = [];
    for (const point of trailing?.points ?? []) {
      const chosen = variantOf(point.piece, point.pick);
      const file = chosen === null ? undefined : chosen.module.files.get(chosen.variant.file);
      const piece = file === undefined ? undefined : pieces.get(chosen!.module, file);
      if (piece?.textured === undefined || !(piece.bounds[4] > 0)) continue;
      trailPlacements.push({
        key: `trail:${String(chosen!.module.stated)}:${file!.sha256}`,
        lod0: piece.textured.lod0,
        lod1: piece.textured.lod1,
        matrix: trailMatrix(point, piece.bounds),
        heightM: point.hangM,
      });
    }
    // A trailing plant lies on its face as a climbing one on its wall: it takes the climbers' shadow reach.
    const trailers = trailPlacements.length === 0 ? null : drawInstancedPieces(drawn.root, trailPlacements, climbView);
    // What grows on the land itself, where the pack states land cover: its textured pieces over the
    // near land by the surface role the land is drawn in at each point, kept off the place's own slots
    // (the land under the place, its base ground, grows), instanced in cells like cover.
    const landGrown = land === undefined || Object.keys(pack.land_cover).length === 0 ? null : growLandCover(pack.land_cover, {
      chunks: land.chunks, groundMm: land.groundMm, dryAt: land.dryAt, waters: land.section.water, surfaces: dressing.landSurfaces ?? null,
    }, {
      placeMm: [0, 0, drawing.extent.widthMm, drawing.extent.depthMm],
      keepOutMm: drawing.slots.filter((slot) => slot.identity !== baseSlot?.identity).map((slot) => slotRectMm(slot as CoverSlot)),
    });
    const landPlacements: InstancePlacement[] = [];
    for (const point of landGrown?.points ?? []) {
      const chosen = variantOf(point.piece, point.pick);
      const file = chosen === null ? undefined : chosen.module.files.get(chosen.variant.file);
      const piece = file === undefined ? undefined : pieces.get(chosen!.module, file);
      if (piece?.textured === undefined) continue;
      landPlacements.push({
        key: `land-cover:${String(chosen!.module.stated)}:${file!.sha256}`,
        lod0: piece.textured.lod0,
        lod1: piece.textured.lod1,
        matrix: coverMatrix(point, point.upM),
        heightM: piece.bounds[4] * point.scale,
      });
    }
    const landCover = landPlacements.length === 0 ? null : drawInstancedPieces(drawn.root, landPlacements, view);
    // The look's wind sways every textured piece of the families it names, the cover's and the slots'.
    const lookWind = dressing.look !== undefined && isRenderLook(dressing.look) ? dressing.look.wind ?? null : null;
    const wind = lookWind === null || !windRuns(device) ? null : new PlantWind(host.app, lookWind);
    if (wind !== null && lookWind !== null) {
      const swaying = new Set(lookWind.swayFamilies);
      for (const [role, module] of Object.entries(pack.modules)) {
        if (!swaying.has(role.split('.')[0]!)) continue;
        for (const variant of module.variants) {
          const file = module.files.get(variant.file);
          const piece = file === undefined ? undefined : pieces.get(module, file);
          if (piece?.textured === undefined) continue;
          // Its own share of the wind; a cut-out material (its leaves) flutters, an opaque one (its trunk) bends whole.
          const share = (variant.sway_permille ?? 1000) / 1000;
          for (const primitive of [...piece.textured.lod0, ...(piece.textured.lod1 ?? [])]) wind.add(primitive.material, piece.bounds[4], { share });
        }
      }
    }

    // A drawn slot no piece could stand in after all keeps its primitive, as one the pack left out.
    for (const identity of placed.undressed) {
      const slot = drawing.slots.find((one) => one.identity === identity);
      if (slot !== undefined && drawn.entities.has(identity)) leftAsDrawn.push(slot);
    }
    // A facade wall left as drawn wears its own copy of the fallback, so the engine's is never changed.
    const facadeFallbacks = new Map<pc.Material, pc.Material>();
    const facadeFallback = (fallback: pc.Material): pc.Material => {
      let copy = facadeFallbacks.get(fallback);
      if (copy === undefined) {
        const own = (shaded(fallback) as pc.StandardMaterial).clone();
        own.name = `style-pack:facade:${fallback.name}`;
        made.push(own);
        facadeFallbacks.set(fallback, own);
        copy = own;
      }
      return copy;
    };
    for (const slot of leftAsDrawn) {
      const entity = drawn.entities.get(slot.identity)!;
      const front = facadeRuleOf(slot, null) !== null;
      wear(entity, slot.identity, front ? facadeFallback : shaded);
      if (front) faceOut(entity, slot, null);
      undressed += 1;
    }

    // A site on land's sea, lakes and cascades, in the pack's water as its ponds are, with the look's
    // water over it: the look's own depth water where it states one, else the finish with the land's
    // own depth; a fall, the look's falling water. Made here, with everything else the dresser makes,
    // so their time is kept from the start.
    // The rock a landscape's volumes are drawn in: the look's ground.rock, as its catalog material or
    // the pack's own surface, its upward faces in the look's ground for the volume's top look
    // (ground.grass for grass) where that is not rock; made once for each top look and only when
    // asked. As every surface that colours its upward faces apart, rock with a top drops its pattern.
    const groundSwatch = (leaf: string) => {
      const role: StyleSlot = { identity: 'site-volumes', lookRole: `ground.${leaf}`, positionMm: [0, 0, 0], yawQuarterTurns: 0, boxMm: [0, 0, 0] };
      const resolved = catalog === null ? resolveLookRole(pack, role, families, 'surface') : resolveSurfaceLookRole(pack, role, families, 'surface', catalog);
      return resolved?.kind === 'material' ? { swatch: resolved.material.swatch, up: null, key: resolved.material.key as string | null }
        : resolved?.kind === 'surface' && resolved.swatch !== null ? { swatch: resolved.swatch, up: resolved.up, key: null } : null;
    };
    const volumeRocks = new Map<string, pc.Material | null>();
    const volumeLook = (topLook: string | null): pc.Material | null => {
      const asked = topLook === null || topLook === 'rock' ? null : topLook;
      const known = volumeRocks.get(asked ?? 'rock');
      if (known !== undefined) return known;
      const rock = groundSwatch('rock');
      const topSwatch = asked === null ? null : groundSwatch(asked)?.swatch ?? null;
      // A top the look has no ground for is the rock throughout.
      if (asked !== null && topSwatch === null) {
        const plain = volumeLook(null);
        volumeRocks.set(asked, plain);
        return plain;
      }
      const top = topSwatch === null ? null : asked;
      const up = topSwatch ?? rock?.up ?? null;
      let material: pc.Material | null = null;
      if (rock !== null) {
        const dressed = swatchMaterial(rock.swatch, up, shading, `style-pack:volumes:rock${top === null ? '' : `:${top}`}`);
        const pattern = up !== null || rock.key === null || patterns === null ? null : patterns.byMaterial.get(rock.key) ?? null;
        if (pattern !== null) applyPattern(dressed, pattern, shading.ink);
        made.push(dressed);
        material = dressed;
      }
      volumeRocks.set(asked ?? 'rock', material);
      return material;
    };
    const landWaters = new Map<string, pc.StandardMaterial>();
    const resolveWater = (identity: string, lookRole: string) => {
      const role: StyleSlot = { identity, lookRole, positionMm: [0, 0, 0], yawQuarterTurns: 0, boxMm: [0, 0, 0] };
      return catalog === null ? resolveLookRole(pack, role, families, 'surface') : resolveSurfaceLookRole(pack, role, families, 'surface', catalog);
    };
    for (const body of land?.section.water ?? []) {
      if (body.kind === 'pond') continue;
      const identity = `site-land:water:${body.id}`;
      // A cascade's pool and fall are the lake's water where the look states none of their own.
      const own = resolveWater(identity, `water.${body.kind}`);
      const resolved = (body.kind === 'pool' || body.kind === 'fall') && own?.role !== `water.${body.kind}`
        ? resolveWater(identity, 'water.lake') : own;
      const swatch = resolved?.kind === 'material' ? { swatch: resolved.material.swatch, up: null }
        : resolved?.kind === 'surface' && resolved.swatch !== null ? { swatch: resolved.swatch, up: resolved.up } : null;
      if (swatch === null) continue;
      const material = swatchMaterial(swatch.swatch, swatch.up, shading, `style-pack:land-water:${body.kind}:${body.id}`);
      made.push(material);
      landWaters.set(body.id, material);
      if (body.kind === 'fall') {
        // A sheet standing upright: streaks down it and foam where it lands, no depth and no ripples.
        const place = { bottomM: body.bottomMm / 1000, acrossEast: body.side === 'north' || body.side === 'south' };
        if (applyFallFinish(device, material, fallingWater, place)) water.animate(material);
        continue;
      }
      // No ripple normals on a lake or the sea, under the look's depth finish or the surface finish:
      // each is seen from afar, where ripples read as glints, and the finish's drift and sheen move
      // its colour. A pool lies within the site, near, and keeps the noise ripple a pond has.
      const byDepth = shading.model === 'pbr' && waterFinish !== null && water.add(material, waterFinish, { ripples: body.kind === 'pool', role: `water.${body.kind}` });
      if (!byDepth && finish !== null && applySeaFinish(device, material, finish)) water.animate(material);
    }
    // The colour the pack states for the ground a site on land's near land wears, which its backdrop
    // is coloured over (`landGround`): its up swatch where it states one, which faces the sky as the
    // land does. A texture states no colour, and the backdrop keeps the one it was drawn over.
    const baseDressing = land === undefined || baseSlot === null ? null : resolve(baseSlot);
    const landGround = baseDressing?.kind === 'material' ? baseDressing.material.swatch.srgb8
      : baseDressing?.kind === 'surface' && baseDressing.swatch !== null ? (baseDressing.up ?? baseDressing.swatch).srgb8 : null;

    // Where the site's waters are, from the engine's bounds of their planes as drawn (before any border
    // grows them), for the wet ground beside them and their own shallow edges; and the reflection in
    // them, where the finish states one and every water lies at one level.
    let reflection: PlanarReflection | null = null;
    if (finish !== null && (finishedGrounds.size > 0 || finishedWaters.size > 0)) {
      const waterRects: WaterRect[] = [];
      const levels: number[] = [];
      for (const slot of drawing.slots) {
        if (slot.family !== 'water' || slot.primitive !== 'plane') continue;
        const instance = (drawn.entities.get(slot.identity)?.findByName(`${slot.identity}:shape`) as pc.Entity | null | undefined)?.render?.meshInstances[0];
        if (instance === undefined) continue;
        waterRects.push(waterRectOf(instance));
        levels.push(instance.aabb.center.y);
      }
      for (const material of [...finishedGrounds, ...finishedWaters]) {
        setFinishWaters(material, waterRects);
        material.update();
      }
      const level = levels.length === 0 ? null : levels.reduce((sum, one) => sum + one, 0) / levels.length;
      if (finish.reflectionStrength > 0 && finishedWaters.size > 0 && level !== null && levels.every((one) => Math.abs(one - level) <= LEVEL_TOLERANCE_M)) {
        reflection = new PlanarReflection(host.app, host.camera, level, finish.reflectionSizePx, finish.reflectionStrength);
        for (const material of finishedWaters) reflection.add(material);
      }
    }

    // The borders between the site's grounds: each ground plane is given what lies over it and its
    // own edge, in whatever it now wears (the pack's own surface, a material's colour or a plain
    // one), and drawn larger by as far as any edge may reach. The base ground's outer edge breaks
    // only where a ground beyond is drawn for it to break over. On a device the working is not
    // written for, no ground is touched: each keeps its ruled rectangle.
    const bordered: (readonly [pc.MeshInstance, pc.Entity, number, number])[] = [];
    let borderNeighboursLeftOut = 0;
    if (catalog !== null && borders !== null && bordersRun(device)) {
      const drawnPlanes = new Map<string, { readonly instance: pc.MeshInstance; readonly shape: pc.Entity; readonly plane: GroundPlane }>();
      for (const slot of drawing.slots) {
        // A plane laid on land is a mesh that bends with it: it is not grown, and keeps its ruled edge.
        if (slot.primitive !== 'plane' || texturedSlots.has(slot.identity) || slot.supportSurfaceId !== undefined || slot.drape === true) continue;
        const shape = drawn.entities.get(slot.identity)?.findByName(`${slot.identity}:shape`) as pc.Entity | null | undefined;
        const instance = shape?.render?.meshInstances[0];
        if (shape == null || instance === undefined) continue;
        const turned = slot.yawQuarterTurns % 2 !== 0;
        const east = (turned ? slot.boxMm[1] : slot.boxMm[0]) / 2, north = (turned ? slot.boxMm[0] : slot.boxMm[1]) / 2;
        const [x, y] = slot.positionMm;
        const material = slot.leaf === 'default' ? null : materialOfLeaf(catalog, slot.family, slot.leaf);
        drawnPlanes.set(slot.identity, {
          instance, shape,
          plane: {
            identity: slot.identity, rectMm: [x - east, y - north, x + east, y + north], layerMm: slot.positionMm[2],
            border: material === null ? null : borders.byMaterial.get(material.key) ?? null,
          },
        });
      }
      // The ground laid over the whole extent breaks at the place's outer edge only out of doors and
      // only where a ground beyond is drawn: indoors its edge is at the walls, with nothing under it.
      const base = baseGroundSlot(drawing);
      const beyond = drawing.extent.enclosure === 'open' && host.app.root.findByName('generated-tile:edge-ground') !== null;
      const plan = planBorders([...drawnPlanes.values()].map((one) => one.plane), base?.identity ?? null, beyond, borders.greatestReachMm);
      const grow = 2 * borders.greatestReachMm / 1000;
      const origin = drawn.root.getPosition();
      for (const [identity, planeBorder] of plan) {
        const { instance, shape, plane } = drawnPlanes.get(identity)!;
        // The working goes into a material this dressing made: a ground still in a material that is
        // not its own (the engine's plain one, where the shading changes nothing) wears a copy of it.
        if (!made.includes(instance.material as pc.StandardMaterial)) {
          const copy = (instance.material as pc.StandardMaterial).clone();
          copy.name = `style-pack:bordered:${instance.material.name}`;
          made.push(copy);
          replaced.push([instance, instance.material]);
          instance.material = copy;
        }
        applyBorder(device, instance.material as pc.StandardMaterial);
        setPlaneBorder(instance, plane.rectMm, planeBorder, [origin.x, origin.z]);
        const scale = shape.getLocalScale();
        bordered.push([instance, shape, scale.x, scale.z]);
        shape.setLocalScale(scale.x + grow, scale.y, scale.z + grow);
        borderNeighboursLeftOut += planeBorder.overLeftOut;
      }
    }


    // Scenery beyond the place: the pack's own tree stands at each tree where the pack has one, in
    // its own mesh beside the site's (it is none of the site's slots, and far trees are not inked);
    // plain trees the pack cannot stand in, and stones, keep their plain shapes in the pack's shading.
    let sceneryPieces: ReturnType<typeof dressSlots> | null = null;
    if (scenery !== null) {
      const trees = scenery.root.findByName(SCENERY_TREES) as pc.Entity | null;
      const stones = scenery.root.findByName(SCENERY_STONES) as pc.Entity | null;
      if (trees !== null && scenery.root.parent !== null) {
        const standingTrees = scenery.pieces.map((piece): PieceSlot => ({
          identity: `site-scenery:${piece.identity}`,
          lookRole: SCENERY_TREE_ROLE,
          positionMm: [piece.xMm, piece.yMm, scenery.groundMm === null ? 0 : scenery.groundMm(piece.xMm, piece.yMm)],
          front: FRONTS[piece.quarterTurns]!,
          boxMm: [piece.widthMm, piece.widthMm, piece.heightMm],
        }));
        const stood = dressSlots(scenery.root.parent as pc.Entity, standingTrees, pack, families, pieces, shading, undefined, undefined, view);
        if (stood.undressed.length === 0 && stood.placed > 0) {
          sceneryPieces = stood;
          hidden.push([trees, trees.enabled]);
          trees.enabled = false;
        } else {
          stood.dispose();
          wear(trees, SCENERY_TREES, shaded);
        }
      }
      if (stones !== null) wear(stones, SCENERY_STONES, shaded);
    }

    // A ground with a broken border is left out of the ink: its mesh's edge is not the edge drawn.
    const brokenGrounds = new Set(bordered.map(([instance]) => instance));
    const ink = shading.ink === null ? null : attachTileInk(device, drawn.root, shading.ink, undefined, [''], (instance) => brokenGrounds.has(instance));
    const unknown = [...unknownLooks].sort();
    const canvas = device.canvas as HTMLCanvasElement | undefined;
    if (catalog !== null && canvas?.dataset !== undefined) {
      canvas.dataset['siteMaterials'] = String(materials);
      canvas.dataset['siteUnknownLooks'] = JSON.stringify(unknown);
      canvas.dataset['sitePatterned'] = String(patterned);
    }
    // How many of the scenery's pieces are the pack's own, said beside what the mount says of it.
    if (sceneryPieces !== null && canvas?.dataset !== undefined) canvas.dataset['siteSceneryPieces'] = String(sceneryPieces.placed);
    // How many grounds are drawn with a broken border.
    if (bordered.length > 0 && canvas?.dataset !== undefined) canvas.dataset['siteBorders'] = String(bordered.length);
    // How many textured pieces stand instanced, in how many cells, the site's, the scenery's, the cover's, the climbers' and the trailers'.
    const instancedParts = [placed.instanced, sceneryPieces?.instanced ?? null, cover, climbers, trailers, landCover].filter((one) => one !== null);
    if (instancedParts.length > 0 && canvas?.dataset !== undefined) {
      canvas.dataset['sitePieceInstances'] = JSON.stringify({
        instances: instancedParts.reduce((sum, one) => sum + one.instances, 0),
        cells: instancedParts.reduce((sum, one) => sum + one.cells, 0),
      });
    }
    // What the cover grew, and how many materials sway.
    const coverSaid = grown === null ? null : { pieces: coverPlacements.length, slots: grown.slots, leftOut: grown.leftOut, untried: grown.untried };
    if (coverSaid !== null && canvas?.dataset !== undefined) canvas.dataset['siteCover'] = JSON.stringify(coverSaid);
    // What climbs the walls.
    const climbSaid = climbing === null ? null : { pieces: climbPlacements.length, buildings: climbing.buildings, leftOut: climbing.leftOut };
    if (climbSaid !== null && canvas?.dataset !== undefined) canvas.dataset['siteClimb'] = JSON.stringify(climbSaid);
    // What hangs over the terraces' edges, counted as it was drawn.
    const trailSaid = trailing === null ? null : {
      pieces: trailPlacements.length, terraces: trailing.terraces, walled: trailing.walled, leftOut: trailing.leftOut, untried: trailing.untried,
    };
    if (trailSaid !== null && canvas?.dataset !== undefined) canvas.dataset['siteTrail'] = JSON.stringify(trailSaid);
    // What grows on the land.
    const landCoverSaid = landGrown === null ? null : { pieces: landPlacements.length, byRole: landGrown.byRole, leftOut: landGrown.leftOut, untried: landGrown.untried };
    if (landCoverSaid !== null && canvas?.dataset !== undefined) canvas.dataset['siteLandCover'] = JSON.stringify(landCoverSaid);
    if (wind !== null && canvas?.dataset !== undefined) canvas.dataset['siteWind'] = String(wind.materials);
    // How many building walls show windows (a dressed building's hidden walls not among them), and in how many materials.
    const facadeSaid = facades === null ? null : {
      walls: facadeWalls.filter((identity) => drawn.entities.get(identity)?.enabled === true).length,
      materials: facaded.size,
    };
    if (facadeSaid !== null && canvas?.dataset !== undefined) canvas.dataset['siteFacade'] = JSON.stringify(facadeSaid);
    // How many of the site's materials wear the surface finish, and whether its water reflects.
    if (finish !== null && canvas?.dataset !== undefined) {
      canvas.dataset['siteFinish'] = JSON.stringify({ grounds: finishedGrounds.size, waters: finishedWaters.size, reflection: reflection !== null });
    }
    dressing.told?.({
      surfaces,
      materials,
      unknownLooks: unknown,
      patterned,
      pieces: standing.size,
      placed: placed.placed,
      undressed,
      inkSegments: ink?.segments ?? 0,
      sceneryPieces: sceneryPieces?.placed ?? 0,
      bordered: bordered.length,
      borderNeighboursLeftOut,
      ...(coverSaid === null ? {} : { cover: coverSaid }),
      ...(climbSaid === null ? {} : { climb: climbSaid }),
      ...(trailSaid === null ? {} : { trail: trailSaid }),
      ...(landCoverSaid === null ? {} : { landCover: landCoverSaid }),
      ...(wind === null ? {} : { swaying: wind.materials }),
      ...(facadeSaid === null ? {} : { facade: facadeSaid }),
    });

    let undone = false;
    const dispose = () => {
      if (undone) return;
      undone = true;
      if (catalog !== null && canvas?.dataset !== undefined) {
        delete canvas.dataset['siteMaterials'];
        delete canvas.dataset['siteUnknownLooks'];
        delete canvas.dataset['sitePatterned'];
      }
      if (sceneryPieces !== null && canvas?.dataset !== undefined) delete canvas.dataset['siteSceneryPieces'];
      if (bordered.length > 0 && canvas?.dataset !== undefined) delete canvas.dataset['siteBorders'];
      if (instancedParts.length > 0 && canvas?.dataset !== undefined) delete canvas.dataset['sitePieceInstances'];
      if (finish !== null && canvas?.dataset !== undefined) delete canvas.dataset['siteFinish'];
      if (coverSaid !== null && canvas?.dataset !== undefined) delete canvas.dataset['siteCover'];
      if (climbSaid !== null && canvas?.dataset !== undefined) delete canvas.dataset['siteClimb'];
      if (trailSaid !== null && canvas?.dataset !== undefined) delete canvas.dataset['siteTrail'];
      if (landCoverSaid !== null && canvas?.dataset !== undefined) delete canvas.dataset['siteLandCover'];
      if (wind !== null && canvas?.dataset !== undefined) delete canvas.dataset['siteWind'];
      if (facadeSaid !== null && canvas?.dataset !== undefined) delete canvas.dataset['siteFacade'];
      for (const instance of facing.splice(0)) clearFacadeWall(instance);
      reflection?.dispose();
      // Every bordered ground is its full rectangle again, with nothing stated on it.
      for (const [instance, shape, x, z] of bordered.splice(0)) {
        clearPlaneBorder(instance);
        shape.setLocalScale(x, shape.getLocalScale().y, z);
      }
      ink?.dispose();
      sceneryPieces?.dispose();
      cover?.dispose();
      climbers?.dispose();
      trailers?.dispose();
      landCover?.dispose();
      wind?.dispose();
      placed.dispose();
      for (const [entity, enabled] of hidden.splice(0).reverse()) entity.enabled = enabled;
      for (const [instance, material] of replaced.splice(0).reverse()) instance.material = material;
      for (const material of made.splice(0)) material.destroy();
      pieces.dispose();
      water.dispose();
      textures.dispose();
    };
    return Object.defineProperty(Object.assign(dispose, {
      seatTriangles,
      animating: water.animating || (wind?.animating ?? false),
      landWater: (body: LandWater): pc.Material | null => landWaters.get(body.id) ?? null,
      ...(landGround === null ? {} : { landGround: linearRgb(landGround) }),
      volumeLook,
      dressBeyond(instance: pc.MeshInstance, slot: SiteSlot): void {
        const resolved = catalog === null
          ? resolveLookRole(pack, slot, families, 'either')
          : resolveSurfaceLookRole(pack, slot, families, 'either', catalog);
        const set = resolved?.kind === 'surface' ? textureSetOf(resolved.surface) : null;
        if (resolved?.kind === 'surface' && set !== null) {
          if (textures.wear(instance, slot, set, resolved.up, host.environmentRoot)) {
            environment?.requestSceneColor();
          }
        }
      },
    }), 'textureMetrics', {
      // The pieces' pictures are textures the site holds too.
      get: () => {
        const metrics = textures.metrics();
        return { ...metrics, decodedTextureBytes: metrics.decodedTextureBytes + pieces.decodedTextureBytes };
      },
    });
  };
}
