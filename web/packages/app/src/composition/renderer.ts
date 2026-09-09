/**
 * Mounting the renderer, and reconciling what it actually accepted with what the status bar says.
 *
 * The second half is the point. A scene record can name trained geometry the browser then fails
 * to decode, and a region can hold a reconstruction its own region chose not to draw. So the
 * rungs are recomputed here from `binding.islands` and `binding.trainedScenes`, which is what is
 * on screen, and the status bar is re-rendered from that rather than from the intention.
 *
 * The proof lens is re-applied for the same reason: it is session state, not renderer state, so
 * a world that has just been rebuilt has to be told what the visitor is currently looking
 * through.
 */

import type { RenderingSubstrate } from '@exulanica/graph-client';
import type { GraphSnapshot } from '@exulanica/graph-client';
import type { AtlasScene } from '@exulanica/atlas-core';
import { worldArtProfile } from '@exulanica/presentation';

import { mountAtlas } from '../atlas.js';
import { sourcePresentation } from '../config.js';
import { themeForPreferences } from '../theme.js';
import { el } from '../ui/dom.js';
import type { FirstUseGuidance } from '../ui/first-use-guidance.js';
import type { buildRegionPlan } from '../ui/region-plan.js';
import { reconstructionRungsFor } from './session-and-geometry.js';
import type { AppEnvironment, SessionState } from './session-state.js';
import type { MountedStatusAndInspector } from './status-and-inspector.js';

export interface RendererDependencies {
  readonly env: AppEnvironment;
  readonly state: SessionState;
  readonly snapshot: GraphSnapshot;
  readonly scene: AtlasScene;
  /** The hole the world shows through, and the parent the anchor overlay writes its nodes into. */
  readonly stage: HTMLElement;
  readonly minimap: ReturnType<typeof buildRegionPlan>;
  readonly status: MountedStatusAndInspector;
  readonly firstUse: FirstUseGuidance;
  readonly reflectFirstUse: () => void;
  readonly reflectShell: () => void;
  readonly showTravelStatus: (message: string, kind?: 'progress' | 'failure') => void;
}

export interface MountedRenderer {
  /** The binding this mount produced. Non-null: a failed mount rejects rather than returning. */
  readonly atlas: NonNullable<SessionState['atlas']>;
  /**
   * Report a placement that does not reproduce atlas-core's own transform.
   *
   * Reported rather than trusted, and called from the root at the point the single-file version
   * called it: after the input modes are bound, not before.
   */
  reportPlacementDisagreement(): void;
  dispose(): void;
}

/**
 * Stop the previous mount's renderer completely.
 *
 * Used on the empty-world path, which builds no replacement. It nulls `atlas`, which the
 * pre-mount teardown inside `mountRenderer` deliberately does not: there, the binding is disposed
 * and the field is left holding it across the `await`, because that is what the single-file
 * version did and the previous mount's listeners are still live during that window.
 */
export function disposeRenderer(state: SessionState): void {
  state.atlas?.dispose();
  state.atlas = null;
  state.settingsStylePreviewId = null;
}

export async function mountRenderer(deps: RendererDependencies): Promise<MountedRenderer> {
  const { env, state } = deps;
  const current = deps.snapshot;

  state.atlas?.dispose();
  state.settingsStylePreviewId = null;
  const activeTheme = themeForPreferences(state.preferences, env.systemAppearance.matches);
  let lastMoving: boolean | null = null;
  let lastAnchorFocus: boolean | null = null;
  const rendererLoading = el('p', { class: 'reconstruction-loading', role: 'status',
    text: 'Opening the Atlas and decoding its available reconstruction…' });
  env.shell.append(rendererLoading);
  env.shell.setAttribute('aria-busy', 'true');
  try {
    state.atlas = await mountAtlas(env.canvas, deps.stage, deps.scene, (report) => {
      if (lastMoving !== report.moving) {
        lastMoving = report.moving;
        env.shell.setAttribute('data-moving', report.moving ? 'true' : 'false');
      }
      if (report.moving && deps.firstUse.observeMovement()) deps.reflectFirstUse();
      if (!deps.minimap.root.hidden) {
        const camera = state.atlas?.binding.controls.state;
        deps.minimap.setViewer(
          camera === undefined ? null : { x: camera.x, z: camera.z, yaw: camera.yaw },
        );
      }
      const anchorFocused = report.mode === 'traverse' && report.focusedIndex !== null;
      if (lastAnchorFocus !== anchorFocused) {
        lastAnchorFocus = anchorFocused;
        env.shell.toggleAttribute('data-anchor-focus', anchorFocused);
      }
      env.shell.setAttribute('data-spatial', report.spatial.phase);
      if (report.recoveryReason !== null) {
        deps.showTravelStatus(
          report.recoveryReason === 'outside-field'
            ? 'Returned to the nearest safe place; the resident field ended here.'
            : report.recoveryReason === 'no-surface'
              ? 'Returned to the nearest safe place; there is no walkable surface here.'
              : 'Returned to the nearest safe place; the surface ahead is too steep or discontinuous.',
          'failure',
        );
      }
    }, {
      theme: activeTheme,
      fieldOfView: state.preferences.fieldOfView,
      mouseSensitivity: state.preferences.mouseSensitivity,
      artProfile: env.previewArtProfile ?? worldArtProfile(
        state.preferences.worldArtProfile,
        state.preferences.worldArtProfileVersion,
        state.preferences.worldStyleParameters,
      ),
      ...(env.previewArtProfile === undefined
        ? { artProfileParameters: state.preferences.worldStyleParameters }
        : {}),
      ...(state.previewSourceMedia === undefined ? {} : { sourceMedia: state.previewSourceMedia }),
      ...(state.pointMaps === undefined ? {} : { pointMaps: state.pointMaps }),
      ...(state.placedPointMaps === undefined ? {} : { placedPointMaps: state.placedPointMaps }),
      trainedGeometry: state.trainedGeometry,
      sourcePresentation: sourcePresentation(),
      recoveredCameras: state.recoveredCameras,
      reducedMotion: env.systemReducedMotion.matches,
    }, env.browserMeasurement === null ? undefined : (binding) => {
      env.browserMeasurement!.observeBinding(binding, {
        scenes: current.reconstructionScenes ?? [],
        placedPointMapCount: state.placedPointMaps?.length ?? 0,
        placementMaxErrors: binding.verifyPlacements().map((check) => check.maxErrorMetres),
      });
    });
  } finally { rendererLoading.remove(); env.shell.removeAttribute('aria-busy'); }
  const atlas = state.atlas;
  // Only renderer-accepted legacy preview maps suppress the source-only region notice.
  if (env.preview) {
    for (const visual of atlas.binding.islands) {
      if (state.pointMaps?.has(visual.island.islandId)) {
        deps.status.noteRenderedPreviewRegion(visual.island.islandId);
      }
    }
  }
  const actualRendering = new Map<string, RenderingSubstrate>();
  for (const visual of atlas.binding.islands) actualRendering.set(visual.pointMap.sceneId, 'posed_point_maps');
  for (const visual of atlas.binding.trainedScenes) actualRendering.set(visual.geometry.sceneId, 'gaussian_splats');
  state.reconstructionRungs = reconstructionRungsFor(
    current.reconstructionScenes ?? [], actualRendering, state.notDrawnScenes, state.displayFrames,
  );
  state.geometryNotices = Object.freeze([...state.geometryNotices, ...atlas.binding.trainedSceneFailures
    .map((failure) => `Trained reconstruction unavailable: ${failure.reason}`)]);
  deps.status.refreshStatus();
  // The lens survives a remount. It is session state, not renderer state, so a world that has just
  // been rebuilt has to be told what the visitor is currently looking through.
  deps.status.applyProofLens();
  env.canvas.dataset.companionRenderer = 'svg';
  deps.reflectShell();

  return {
    atlas,
    // Reported rather than trusted. A placement that does not reproduce atlas-core's own transform
    // is a region turned the wrong way, which is invisible until somebody walks behind it.
    reportPlacementDisagreement: () => {
      const worst = Math.max(0, ...atlas.placements.map((check) => check.maxErrorMetres));
      if (worst > 1e-3) {
        console.warn(`atlas placement disagrees with atlas-core by ${worst} atlas units`);
      }
    },
    dispose: () => disposeRenderer(state),
  };
}
