/**
 * Mounting the renderer. The one file in this package that knows a renderer exists.
 *
 * ADR-0003 resolved to PlayCanvas Engine 2.21.4, and `@exulanica/atlas-react` is the binding.
 * Everything engine-specific lives behind that package, which is what makes a renderer switch a
 * two-package change; nothing here names `playcanvas`, and `.dependency-cruiser.cjs` would fail
 * the build if it did.
 *
 * **Point maps arrive from the caller, and an island without one is anchors only.** A production
 * reconstruction scene may carry several maps with receipt-backed transforms; the preview and
 * older single-frame path may carry one. This file does not decide which regions have geometry.
 *
 * That sentence was false when it was written, and ADR-0009 D10 says so: "the app's own comment
 * claiming that production reads point maps from an API describes an implementation that does not
 * exist". It is true now. `geometry-api.ts` is the production reader, `dev/preview-point-maps.ts`
 * is the preview one, and `main.ts` holds one variable that either of them fills.
 *
 * It is also the thesis under test. Reconstruction quality never participates in the truth
 * guarantee: a region with no geometry at all still resolves every citation to the exact
 * original photograph, and this file is where that stops being a claim in a document.
 *
 * **The placement check runs at startup and its result is reported, not swallowed.** A sign error
 * in a yaw is invisible until somebody walks round the back of a region, and the binding offers
 * a check for exactly that. Running it and discarding the answer would be the same as not
 * running it.
 */

import type { AtlasScene, DistrictInterpretation, IslandId, OwnedDistrict } from '@exulanica/atlas-core';
import type { GeneratedTileMount } from '@exulanica/atlas-react/generated-tile';
import type {
  PresentationTheme,
  WorldArtProfile,
  WorldStyleParameters,
} from '@exulanica/presentation';
import type {
  AuthoredPointMapPlacement,
  AuthoredRegion,
  FrameReport,
  PlacementCheck,
  PointMap,
  PlacedScenePointMap,
  SourceMediaCatalog,
  TrainedSceneGeometry,
  RecoveredSceneCamera,
} from '@exulanica/atlas-react/playcanvas';
import { AtlasBinding, describeWorldKind, type WorldKind } from '@exulanica/atlas-react/playcanvas';

export interface MountedAtlas {
  readonly binding: AtlasBinding;
  /**
   * What kind of world the binding draws: its ground. Decided by the renderer's own
   * `describeWorldKind` over the very options the binding was created from, so a surface that
   * says what this world is cannot disagree with what is drawn.
   */
  readonly worldKind: WorldKind;
  readonly placements: readonly PlacementCheck[];
  dispose(): void;
}

/** What a caller with no reconstructions passes. Empty, rather than a map of empty point maps. */
const NO_POINT_MAPS: ReadonlyMap<IslandId, PointMap> = new Map();

export async function mountAtlas(
  canvas: HTMLCanvasElement,
  overlayParent: HTMLElement,
  scene: AtlasScene,
  onFrame?: (report: FrameReport) => void,
  presentation?: {
    readonly theme: PresentationTheme;
    readonly fieldOfView: number;
    readonly mouseSensitivity: number;
    readonly artProfile?: WorldArtProfile;
    readonly artProfileParameters?: WorldStyleParameters;
    readonly sourceMedia?: SourceMediaCatalog;
    readonly reducedMotion?: boolean;
    readonly pointMaps?: ReadonlyMap<IslandId, PointMap>;
    readonly placedPointMaps?: readonly PlacedScenePointMap[];
    readonly trainedGeometry?: readonly TrainedSceneGeometry[];
    readonly recoveredCameras?: readonly RecoveredSceneCamera[];
    readonly ownedDistrict?: {
      readonly document: OwnedDistrict;
      readonly residentBytes: number;
      readonly interpretation?: DistrictInterpretation;
    };
    /** Development evaluation only; see `composition/generated-tile.ts`. */
    readonly generatedTile?: GeneratedTileMount;
    readonly authoredRegion?: AuthoredRegion;
    /** Placed depth estimates for that region; ignored without one, because they have no root. */
    readonly authoredPointMaps?: readonly AuthoredPointMapPlacement[];
  },
  beforeStart?: (binding: AtlasBinding) => void,
): Promise<MountedAtlas> {
  const options: Parameters<typeof AtlasBinding.create>[0] = {
    canvas,
    overlayParent,
    scene,
    pointMaps: presentation?.pointMaps ?? NO_POINT_MAPS,
    recoveredCameras: presentation?.recoveredCameras ?? [],
    ...(presentation?.trainedGeometry === undefined ? {} : { trainedGeometry: presentation.trainedGeometry }),
    ...(presentation?.placedPointMaps === undefined
      ? {}
      : { placedPointMaps: presentation.placedPointMaps }),
    ...(presentation?.ownedDistrict === undefined
      ? {}
      : { ownedDistrict: presentation.ownedDistrict }),
    ...(presentation?.generatedTile === undefined
      ? {}
      : { generatedTile: presentation.generatedTile }),
    ...(presentation?.authoredRegion === undefined
      ? {}
      : { authoredRegion: presentation.authoredRegion }),
    ...(presentation?.authoredPointMaps === undefined
      ? {}
      : { authoredPointMaps: presentation.authoredPointMaps }),
    ...(presentation === undefined
      ? {}
      : {
          theme: presentation.theme,
          fov: presentation.fieldOfView,
          sensitivityMultiplier: presentation.mouseSensitivity,
          ...(presentation.artProfile === undefined ? {} : { artProfile: presentation.artProfile }),
          ...(presentation.artProfileParameters === undefined
            ? {}
            : { artProfileParameters: presentation.artProfileParameters }),
          ...(presentation.sourceMedia === undefined ? {} : { sourceMedia: presentation.sourceMedia }),
          ...(presentation.reducedMotion === undefined
            ? {}
            : { reducedMotion: presentation.reducedMotion }),
        }),
  };
  const worldKind = describeWorldKind(options);
  const binding = await AtlasBinding.create(options);
  canvas.dataset.worldProfile = binding.composedWorld.profileId;
  canvas.dataset.worldTopology = binding.topology.topologyDigest;
  canvas.dataset.worldModules = String(binding.topology.instances.length);
  if (binding.ownedDistrict !== null) {
    canvas.dataset.ownedDistrict = binding.ownedDistrict.district.district_id;
    canvas.dataset.ownedBuildings = String(binding.ownedDistrict.metrics.logicalBuildings);
    canvas.dataset.ownedDrawCalls = String(binding.ownedDistrict.metrics.drawCalls);
    canvas.dataset.ownedResidentBytes = String(binding.ownedDistrict.metrics.residentBytes);
  }

  if (onFrame !== undefined) binding.onFrame = onFrame;
  // The engine drives the clock. The binding's own update runs before the render, which is the
  // order the interaction model describes: move, decide density, decide attention, then draw.
  /*
   * The engine drives the clock; the binding decides whether the frame is worth drawing.
   *
   * `autoRender = false` stops the renderer, not the update loop: input, focus, residency and the
   * DOM overlay all keep running every tick, so nothing that reads world state goes stale. Only
   * the GPU work is skipped, and only when the binding says the screen would come out identical.
   */
  binding.app.autoRender = false;
  // A resize changes the picture without moving the camera, so it has to announce itself.
  const onResize = (): void => binding.invalidate();
  window.addEventListener('resize', onResize);
  binding.app.on('update', (dt: number) => {
    const nowMs = performance.now();
    binding.update(dt, nowMs);
    const draw = binding.wantsFrame(nowMs);
    binding.app.renderNextFrame = draw;
    if (draw) binding.markRendered(nowMs);
  });
  beforeStart?.(binding);
  binding.app.start();

  return {
    binding,
    worldKind,
    placements: binding.verifyPlacements(),
    dispose: () => {
      window.removeEventListener('resize', onResize);
      delete canvas.dataset.worldProfile;
      delete canvas.dataset.worldTopology;
      delete canvas.dataset.worldModules;
      delete canvas.dataset.ownedDistrict;
      delete canvas.dataset.ownedBuildings;
      delete canvas.dataset.ownedDrawCalls;
      delete canvas.dataset.ownedResidentBytes;
      delete canvas.dataset.ownedFrameMs;
      binding.destroy();
    },
  };
}
