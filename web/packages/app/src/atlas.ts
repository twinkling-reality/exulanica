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

import type { AtlasScene, IslandId } from '@exulanica/atlas-core';
import type {
  PresentationTheme,
  WorldArtProfile,
  WorldStyleParameters,
} from '@exulanica/presentation';
import type {
  FrameReport,
  PlacementCheck,
  PointMap,
  PlacedScenePointMap,
  SourceMediaCatalog,
} from '@exulanica/atlas-react/playcanvas';
import { AtlasBinding } from '@exulanica/atlas-react/playcanvas';

export interface MountedAtlas {
  readonly binding: AtlasBinding;
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
  },
  beforeStart?: (binding: AtlasBinding) => void,
): Promise<MountedAtlas> {
  const binding = await AtlasBinding.create({
    canvas,
    overlayParent,
    scene,
    pointMaps: presentation?.pointMaps ?? NO_POINT_MAPS,
    ...(presentation?.placedPointMaps === undefined
      ? {}
      : { placedPointMaps: presentation.placedPointMaps }),
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
  });
  canvas.dataset.worldProfile = binding.composedWorld.profileId;
  canvas.dataset.worldTopology = binding.topology.topologyDigest;
  canvas.dataset.worldModules = String(binding.topology.instances.length);

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
    placements: binding.verifyPlacements(),
    dispose: () => {
      window.removeEventListener('resize', onResize);
      delete canvas.dataset.worldProfile;
      delete canvas.dataset.worldTopology;
      delete canvas.dataset.worldModules;
      binding.destroy();
    },
  };
}
