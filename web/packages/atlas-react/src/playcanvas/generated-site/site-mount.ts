import {attachTerrainDressing, terrainDressingFrameAvailable, createDressingReadiness, type PreparedDressing, type TerrainDressingAttachment} from './terrain-dressing.js';
import { materialOfLeaf, renderCapsFor, unknownSurfaceLeaf, type RenderBudget, type RenderCaps, type RenderForm, type RoofForms, type SiteInteriorCatalog, type SiteSceneryCatalog, type TerrainOccupancyProof, type SurfaceMaterials } from '@exulanica/atlas-core';
import * as pc from 'playcanvas';
import type { GeneratedTileAttachment, GeneratedTileHost, GeneratedTileMount } from '../generated-tile/binding-contract.js';
import type { SiteTextureMetrics } from '../style-pack/site-textures.js';
import type { TileEnvironment } from '../generated-tile/environment.js';
import { applyTileEnvironment } from '../generated-tile/environment.js';
import { TILE_LOOK_V1, type TileLook } from '../generated-tile/look.js';
import { budgetedLook } from '../generated-tile/budgeted-look.js';
import { isTerrainSiteDrawing, type SiteDrawing, type StructuredSiteDrawing, type TerrainSiteDrawing, type SiteSlot } from './site-drawing.js';
import { siteNavigationWorld, siteStart } from './site-navigation.js';
import { drawSiteSlots, type DrawnSiteSlots } from './site-primitives.js';
import { SITE_CEILING, ceilingRests, drawSiteCeiling, lightFromAbove } from './site-interior.js';
import { drawSiteScenery, sceneryOf, type DrawnScenery } from './site-scenery.js';
import { measureSite } from './site-measurements.js';
import { createHeightfieldMesh } from './heightfield-mesh.js';
import { drawnSiteSeats } from './site-seating.js';
import type { SeatGeometry } from './site-seating.js';
import type { FixtureSeat } from '../society/seating.js';

/**
 * A world made from a world kind, ready for the binding: where a person walks, where they open and
 * how its drawing is attached to the scene.
 *
 * It meets the binding through the same seam a generated tile does (`GeneratedTileMount`): the
 * binding stands the person on `navigationWorld`, opens the camera at `start` and hands `attach`
 * the scene, and never reads the drawing. A site is lit by the generated tile's look (its sky,
 * sun, fog and tone mapping), so a site and a town are lit alike.
 *
 * THE GROUND BEYOND A SITE IS THE SITE'S OWN. A look that states a ground beyond the world draws a
 * plane out to its reach in its own colour, which for a town is the lawn its streets end in. A site
 * that is open to the sky stands on its base ground (the one surface its drawing lays over its
 * whole extent), so that plane is drawn in whatever the base ground is drawn in, once it is dressed
 * (the pack's own surface, its leaf's material or the family's default), and lies just under it:
 * the sand of a desert outpost runs to the horizon. It reads the base ground only, never a zone or
 * an area at the site's edge. An indoor site, and a site whose drawing lays no ground over its
 * whole extent, keep the look's own.
 */
export interface GeneratedSiteMount extends GeneratedTileMount {
  readonly dressingReadiness?: ReturnType<typeof createDressingReadiness>;
  /** The kind the world was made from, in its own words, which the About panel says. */
  readonly kindLabel: string;
  readonly drawing: SiteDrawing;
}

/**
 * Dresses a drawn site, such as with a style pack: it runs once the slots are drawn and returns a
 * disposer, which runs before the slots are taken away and puts back everything it changed. It
 * never changes a slot, the walk or the seats; the mount stays the one owner of its entities.
 */
export type SiteUndress = (() => void) & { readonly seatTriangles?: ReadonlyMap<string, SeatGeometry>; readonly textureMetrics?: SiteTextureMetrics; readonly animating?: boolean; readonly dressBeyond?: (instance: pc.MeshInstance, slot: SiteSlot) => void };
export type SiteDresser = (host: GeneratedTileHost, drawn: DrawnSiteSlots, drawing: StructuredSiteDrawing, scenery?: DrawnScenery | null, environment?: TileEnvironment) => SiteUndress;

export interface SiteMountOptions {
  readonly preparedDressing?: PreparedDressing;
  readonly dressingReadiness?: ReturnType<typeof createDressingReadiness>;
  /** Current authoritative occupancy binding; a source drawing alone cannot establish this. */
  readonly terrainOccupancy?: TerrainOccupancyProof | (() => TerrainOccupancyProof);
  /** The bytes the drawing was served as, which the attachment reports as transferred. */
  readonly servedBytes: number;
  /** Record bounded frame intervals and accounted graphics bytes on the canvas for a review. */
  readonly measure?: boolean;
  /** Publish contact for this attachment; the returned withdrawal runs before geometry is removed. */
  readonly seated?: (seats: readonly FixtureSeat[]) => () => void;
  readonly look?: TileLook;
  readonly dress?: SiteDresser;
  /**
   * The surface material catalog the engine's own colours are read from, leaf by leaf. A dresser
   * carries its own; with no dresser the mount says on the canvas how many slots wear a material
   * and which look roles named none (`data-site-materials`, `data-site-unknown-looks`), as a
   * dresser does.
   */
  readonly materials?: SurfaceMaterials;
  /** The roof form catalog a roof is shaped by, through its material; none draws every roof as served. */
  readonly roofForms?: RoofForms;
  /**
   * The scenery catalog: what stands on the ground beyond the place, by its base ground's material
   * (`site-scenery.ts`). It needs `materials` to name that material; none, or no `materials`, draws
   * the ground beyond bare, and a look with no ground beyond (the tile look) has nothing for it to
   * stand on and draws none. Scenery is drawn beside the site's slots and is none of them.
   */
  readonly scenery?: SiteSceneryCatalog;
  /**
   * The interior catalog: the ceiling and the light an indoor place is drawn with
   * (`site-interior.ts`). None draws an indoor place as a walled floor under the look's sky and sun,
   * as before. The ceiling is drawn beside the site's slots and is none of them.
   */
  readonly interior?: SiteInteriorCatalog;
  /**
   * The render budget (`render-budget.ts` in atlas-core): the look is drawn within the caps of the
   * site's scene form, an open site, an indoor site or a terrain. None draws the look as chosen.
   */
  readonly renderBudget?: RenderBudget;
}

/**
 * The look a site of `form` is drawn in, and the caps its frame is drawn within: the chosen look
 * within the budget's caps for that form. No budget draws the look as chosen, with no caps.
 */
function drawnWithin(options: SiteMountOptions, form: RenderForm): { readonly look: TileLook; readonly caps: RenderCaps | null } {
  const look = options.look ?? TILE_LOOK_V1;
  if (options.renderBudget === undefined) return { look, caps: null };
  const caps = renderCapsFor(options.renderBudget, form);
  return { look: budgetedLook(look, caps), caps };
}

/**
 * How far under a site's ground the ground beyond it lies, in metres: three of the drawing's own
 * layer steps (6 mm each, `LAYER_MM` in the server's drawing), so the two never share a depth where
 * the site's ground ends, and no step shows at its edge from standing height.
 */
export const SITE_BEYOND_DROP_M = 0.018;

/**
 * The slot a site's base ground is drawn by: the ground plane its drawing lays over its whole
 * extent, at the level of the site's origin. Null where the drawing lays none.
 */
export function baseGroundSlot(drawing: StructuredSiteDrawing): SiteSlot | null {
  const { widthMm, depthMm } = drawing.extent;
  return drawing.slots.find((slot) => slot.family === 'ground' && slot.primitive === 'plane'
    && slot.boxMm[0] === widthMm && slot.boxMm[1] === depthMm
    && slot.positionMm[0] * 2 === widthMm && slot.positionMm[1] * 2 === depthMm && slot.positionMm[2] === 0) ?? null;
}

/** The mount for a checked site drawing. */
export function siteMount(drawing: SiteDrawing, options: SiteMountOptions): GeneratedSiteMount {
  if (isTerrainSiteDrawing(drawing)) return terrainMount(drawing, options);
  const { look, caps } = drawnWithin(options, drawing.extent.enclosure === 'open' ? 'open_site' : 'indoor_site');
  const navigationWorld = siteNavigationWorld(drawing);
  return Object.freeze({
    kindLabel: drawing.kind.label,
    drawing,
    navigationWorld,
    start: siteStart(drawing, navigationWorld),
    attach(host: GeneratedTileHost): GeneratedTileAttachment {
      const environment = applyTileEnvironment(host.app, host.camera, look, caps);
      const materials = options.materials ?? null;
      const slots = drawSiteSlots(host.app.graphicsDevice, drawing, materials, options.roofForms ?? null);
      host.environmentRoot.addChild(slots.root);
      const base = drawing.extent.enclosure === 'open' ? baseGroundSlot(drawing) : null;
      // What stands beyond the place: scenery, beside the site's slots in the same frame and none of
      // them, so nothing that reads or outlines the slots meets it. The dresser is handed it to
      // shade, or to stand its own trees in.
      // It stands on the ground beyond: a look that draws no ground beyond the place draws none.
      const standing = options.scenery === undefined || materials === null || environment.ground === null
        ? null : sceneryOf(drawing, base, options.scenery, materials);
      const scenery = standing === null || standing.pieces.length === 0 ? null : drawSiteScenery(host.app.graphicsDevice, standing, materials);
      if (scenery !== null) host.environmentRoot.addChild(scenery.root);
      const undress = options.dress?.(host, slots, drawing, scenery, environment) ?? null;
      const withdrawSeats = options.seated === undefined ? undefined : options.seated(drawnSiteSeats(drawing, slots, undress?.seatTriangles));
      // An indoor place: a ceiling on the top of the tallest thing it draws, in what that is drawn
      // in once dressed, and the look's sun turned into the light under it.
      const rests = drawing.extent.enclosure === 'indoor' && options.interior !== undefined ? ceilingRests(drawing) : null;
      const ceiling = rests === null ? null : drawSiteCeiling(drawing, rests, options.interior!.indoor);
      if (ceiling !== null) {
        host.environmentRoot.addChild(ceiling.root);
        const dressed = (slots.entities.get(rests!.identity)?.findByName(`${rests!.identity}:shape`) as pc.Entity | null)?.render?.meshInstances[0]?.material ?? null;
        const worn = (ceiling.root.findByName(`${SITE_CEILING}:shape`) as pc.Entity).render!.meshInstances[0]!;
        if (dressed !== null) worn.material = dressed;
        lightFromAbove(environment.sun, options.interior!.indoor);
      }
      // The ground beyond: the look's own plane, drawn in what the dressed base ground is drawn in.
      const beyond = environment.ground?.render?.meshInstances[0] ?? null;
      const baseShape = base === null ? null : (slots.entities.get(base.identity)?.findByName(`${base.identity}:shape`) as pc.Entity | null);
      const worn = baseShape?.render?.meshInstances[0]?.material ?? null;
      const edged = beyond !== null && worn !== null && environment.ground !== null;
      if (edged) {
        beyond.material = worn;
        // A texture needs the beyond plane’s physical UVs, rather than its unit primitive UVs.
        undress?.dressBeyond?.(beyond, base!);
        const at = environment.ground!.getPosition();
        environment.ground!.setPosition(at.x, -SITE_BEYOND_DROP_M, at.z);
      }
      const canvas = host.app.graphicsDevice.canvas as HTMLCanvasElement | undefined;
      if (edged && canvas?.dataset !== undefined) canvas.dataset['siteGroundBeyond'] = base!.lookRole;
      // An indoor place's ceiling, said on the canvas: how high it lies.
      if (ceiling !== null && canvas?.dataset !== undefined) canvas.dataset['siteCeiling'] = String(ceiling.heightMm);
      // What stands beyond, said on the canvas: what, how many, and beyond which ground.
      if (scenery !== null && canvas?.dataset !== undefined) {
        canvas.dataset['siteScenery'] = JSON.stringify({ stands: scenery.stands, beyond: scenery.material, pieces: scenery.pieces.length });
      }
      const said = options.dress === undefined && materials !== null && canvas?.dataset !== undefined;
      if (said) {
        const drawn = drawing.slots.filter((slot) => slots.entities.has(slot.identity));
        canvas.dataset['siteMaterials'] = String(drawn.filter((slot) => slot.leaf !== 'default' && materialOfLeaf(materials, slot.family, slot.leaf) !== null).length);
        canvas.dataset['siteUnknownLooks'] = JSON.stringify([...new Set(drawn.filter((slot) => unknownSurfaceLeaf(materials, slot.lookRole)).map((slot) => slot.lookRole))].sort());
      }
      const stopMeasure = options.measure ? measureSite(host.app, undress?.textureMetrics, environment.residentBytes, () => {
        const position = host.camera.getPosition().clone().sub(host.environmentRoot.getPosition());
        const forward = host.camera.forward;
        return { positionM: [position.x, position.y, position.z], forward: [forward.x, forward.y, forward.z] };
      }) : null;
      let disposed = false;
      return {
        animating: undress?.animating ?? false,
        metrics: Object.freeze({
          tileName: `site:${drawing.worldId}`,
          triangles: slots.triangles,
          drawBatches: slots.drawn,
          transferredBytes: options.servedBytes + (undress?.textureMetrics?.transferredBytes ?? 0),
          decodedTextureBytes: undress?.textureMetrics?.decodedTextureBytes ?? 0,
          unavailableSurfaces: undress?.textureMetrics?.unavailableSurfaces ?? 0,
          neighbours: Object.freeze([]),
          lookId: look.id,
          lookVersion: look.version,
        }),
        dispose(): void {
          if (disposed) return;
          disposed = true;
          withdrawSeats?.();
          stopMeasure?.();
          // The look's plane goes with the environment below; only what the canvas said is taken back here.
          if (edged && canvas?.dataset !== undefined) delete canvas.dataset['siteGroundBeyond'];
          if (said) {
            delete canvas.dataset['siteMaterials'];
            delete canvas.dataset['siteUnknownLooks'];
          }
          if (scenery !== null && canvas?.dataset !== undefined) delete canvas.dataset['siteScenery'];
          if (ceiling !== null && canvas?.dataset !== undefined) delete canvas.dataset['siteCeiling'];
          // The ceiling goes before the dressing is undone: it wears a material the dressing made.
          ceiling?.destroy();
          undress?.();
          scenery?.destroy();
          slots.destroy();
          environment.dispose();
        },
      };
    },
  });
}

/** Draw the original admitted triangles; scene dressing never supplies navigation authority. */
function terrainMount(drawing: TerrainSiteDrawing, options: SiteMountOptions): GeneratedSiteMount {
  const { look, caps } = drawnWithin(options, 'terrain');
  const dressed = drawing.profile === 'exulanica.site-drawing/v4';
  const prepared = options.preparedDressing;
  if (dressed && (prepared === undefined || prepared.dressing !== drawing.dressing)) throw new TypeError('The exact terrain dressing must be prepared before mounting.');
  const readiness = options.dressingReadiness ?? createDressingReadiness();
  const proof = (): TerrainOccupancyProof => typeof options.terrainOccupancy === 'function' ? options.terrainOccupancy() : options.terrainOccupancy ?? {status: 'unavailable'};
  const navigationWorld = siteNavigationWorld(drawing, () => dressed && !readiness.read() ? {status: 'unavailable'} : proof());
  return Object.freeze({drawing, dressingReadiness: readiness, kindLabel: 'Terrain', navigationWorld, start: siteStart(drawing, navigationWorld),
    attach(host: GeneratedTileHost): GeneratedTileAttachment {
      const environment = applyTileEnvironment(host.app, host.camera, look, caps);
      // An infinite presentation floor would obscure the bounded admitted surface.
      if (environment.ground !== null) environment.ground.enabled = false;
      const mesh = createHeightfieldMesh(host.app.graphicsDevice, drawing.terrain.geometry);
      const material = new pc.StandardMaterial();
      material.name = 'admitted-terrain'; material.diffuse.set(0.36, 0.43, 0.28); material.gloss = 0.15; material.update();
      const entity = new pc.Entity(`terrain:${drawing.terrain.geometry.data.component_id}`);
      entity.addComponent('render', {meshInstances: [new pc.MeshInstance(mesh, material)], castShadows: true, receiveShadows: true});
      host.environmentRoot.addChild(entity);
      const canvas = host.app.graphicsDevice.canvas as HTMLCanvasElement | undefined;
      if (canvas?.dataset !== undefined) {
        canvas.dataset['terrainGeometry'] = drawing.terrain.geometry.sha256;
        canvas.dataset['terrainContact'] = drawing.terrain.sha256;
      }
      let disposed = false;
      const frameCurrent = (): boolean => !disposed && terrainDressingFrameAvailable(host.environmentRoot) && proof().status === 'verified';
      let dressing: TerrainDressingAttachment | null = null;
      const generation = dressed ? readiness.begin(() => frameCurrent() && dressing?.current() === true) : null;
      if (dressed) {
        entity.enabled = false;
        dressing = attachTerrainDressing(host.app, host.environmentRoot, prepared!, () => frameCurrent() && generation!.current());
        void dressing.ready.then(() => {if (!disposed && generation!.current() && proof().status === 'verified') {generation!.ready(); entity.enabled = true;}}).catch(() => {generation!.dispose();});
      }
      const update = (): void => {
        if (!dressed) return;
        if (!frameCurrent() || !generation!.current() || dressing?.current() !== true) {generation!.dispose(); dressing?.dispose(); entity.enabled = false;}
        if (canvas?.dataset !== undefined) canvas.dataset['terrainDressing'] = readiness.read() ? 'ready' : 'unavailable';
      };
      host.app.on('update', update);
      const stopMeasure = options.measure ? measureSite(host.app, undefined, environment.residentBytes) : null;
      return {get metrics() {return Object.freeze({tileName: `terrain:${drawing.worldId}`,
        triangles: (drawing.terrain.geometry.data.east_mm.length - 1) * (drawing.terrain.geometry.data.south_mm.length - 1) * 2 + (prepared?.triangles ?? 0),
        drawBatches: 1 + (prepared?.draws ?? 0), transferredBytes: options.servedBytes + (prepared?.transferredBytes ?? 0), decodedTextureBytes: dressing?.decodedTextureBytes ?? 0, unavailableSurfaces: dressed && !readiness.read() ? (prepared?.draws ?? 0) : 0,
        neighbours: Object.freeze([]), lookId: look.id, lookVersion: look.version});},
        sourceCurrent() {return dressed && !disposed && readiness.read() && generation?.current() === true;},
        pickSource(origin: readonly [number, number, number], direction: readonly [number, number, number]) {
          if (!dressed || disposed || !readiness.read() || !generation?.current()) return null;
          return dressing?.pick(origin, direction) ?? null;
        },
        dispose() { if (disposed) return; disposed = true; generation?.dispose(); dressing?.dispose(); host.app.off('update', update); stopMeasure?.(); entity.destroy(); mesh.destroy(); material.destroy(); environment.dispose();
          if (canvas?.dataset !== undefined) {delete canvas.dataset['terrainGeometry']; delete canvas.dataset['terrainContact']; delete canvas.dataset['terrainDressing'];}
        }};
    }});
}
