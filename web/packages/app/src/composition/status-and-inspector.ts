/**
 * The status bar, the reconstruction inspector, the proof lens, click-to-evidence, and the
 * review of who is in a photograph.
 *
 * These are one surface because they are one claim. The status bar says what the world is
 * showing and at what rung; the inspector is how a visitor checks that claim against the
 * photographs it was made from; the lens colours the claim; a click resolves it to the recorded
 * observations behind one point; the review is the consent state of the people in that same
 * photograph. Every one of them needs the graph, the theme and the renderer binding at once, and
 * before the split this whole region was already textually its own for that reason.
 *
 * Nothing here writes the graph. The review panel writes receipts through its own authorized
 * route, which is a different gate with a different contract, and the proof lens writes four
 * floats per region and nothing else.
 */

import {
  canvasToSourcePixel,
  islandId as toIslandId,
  observationSentence,
  pickObservedPoint,
  type IslandId,
  type PickCamera,
} from '@exulanica/atlas-core';
import type { GraphSnapshot } from '@exulanica/graph-client';

import { sourcePresentation } from '../config.js';
import {
  ObservationsClient,
  ObservationsUnavailable,
  consentSentence,
} from '../observations-api.js';
import { PersonReviewApi, ReviewUnavailable } from '../person-review-api.js';
import type { SceneBuild } from '../scene.js';
import { themeForPreferences } from '../theme.js';
import { el } from '../ui/dom.js';
import { buildPersonReview } from '../ui/person-review.js';
import { PersonRegionDrafts } from '../ui/person-region-editor.js';
import { proofLensIslandColors } from '../ui/proof-lens.js';
import { buildReconstructionInspector } from '../ui/reconstruction-inspector.js';
import { buildStatus } from '../ui/status.js';
import type { AppEnvironment, SessionState } from './session-state.js';

export interface StatusAndInspectorDependencies {
  readonly env: AppEnvironment;
  readonly state: SessionState;
  /** The snapshot this mount is drawn from. */
  readonly snapshot: GraphSnapshot;
  /** What the scene builder omitted or could not draw, for the status bar's own count. */
  readonly built: Pick<SceneBuild, 'omitted' | 'undrawable'>;
  /** Bring the world forward. Opening an inspector is a world gesture, not a panel one. */
  readonly showWorld: () => void;
  readonly showTravelStatus: (message: string, kind?: 'progress' | 'failure') => void;
}

export interface MountedStatusAndInspector {
  readonly inspectorRoot: HTMLElement;
  /** The status bar currently in the document. Replaced in place by `refreshStatus`. */
  readonly statusElement: HTMLElement;
  /** Re-render the status bar from what the renderer actually accepted, and swap it in place. */
  refreshStatus(): void;
  /** Push the lens state at the renderer, and push nothing else. */
  applyProofLens(): void;
  hideInspector(): void;
  /** A legacy preview map the renderer accepted, so the source-only notice stops claiming it. */
  noteRenderedPreviewRegion(islandId: string): void;
  inspectReconstruction(sceneId: string): void;
  inspectSceneSources(sceneId: string): void;
  /** One click on the world canvas, resolved against the recorded observation graph. */
  resolveEvidenceAt(clientX: number, clientY: number): void;
  /** Who is in this photograph, or nothing when the view stands on no single photograph. */
  loadPersonReview(captureId: string | null): void;
  dispose(): void;
}

/**
 * How far from the cursor, in screen pixels, a recorded point may be and still count as clicked.
 *
 * Expressed in screen pixels and converted to the photograph's own pixels per click, because the
 * two are not the same scale: the inspector fits a 4080-pixel-tall original into a canvas around
 * 700 pixels tall, so eight screen pixels is about forty-five source pixels. A tolerance typed
 * in source pixels would be a different gesture on every display.
 */
const PICK_TOLERANCE_CANVAS_PX = 8;
const PICK_OCCLUSION_BAND_CANVAS_PX = 2;

export function mountStatusAndInspector(
  deps: StatusAndInspectorDependencies,
): MountedStatusAndInspector {
  const { env, state } = deps;
  const current = deps.snapshot;

  /** Which region draws which scene, as the regions themselves already decided. */
  const islandOfScene = (sceneId: string): IslandId | undefined => {
    const region = current.islands.find((island) => island.reconstructionSceneId === sceneId);
    return region === undefined ? undefined : toIslandId(region.islandId);
  };

  /**
   * Push the lens state at the renderer, and push nothing else.
   *
   * Every argument is read fresh: the disclosures the status panel is already showing, the region
   * each scene resolved to, and the current theme. Nothing is stored, no scene is rebuilt, and the
   * one call this makes writes four floats per region.
   */
  const applyProofLens = (): void => {
    state.atlas?.binding.setProofLens(
      state.proofLensEnabled
        ? proofLensIslandColors(
            state.reconstructionRungs,
            islandOfScene,
            themeForPreferences(state.preferences, env.systemAppearance.matches),
          )
        : null,
    );
  };

  /** The raw recovered camera for one capture: the frame the observation graph is recorded in. */
  const pickCameraFor = (sceneId: string, captureId: string): PickCamera | null => {
    const record = current.reconstructionScenes?.find((scene) => scene.sceneId === sceneId);
    const camera = record?.members.find((member) => member.captureId === captureId)?.recoveredCamera;
    if (camera == null) return null;
    /*
     * THE RAW TRANSFORM, NOT THE DISPLAYED ONE, and the difference is the whole correctness of
     * this gesture. `geometry-api.ts` composes each scene's display frame into the cameras it
     * hands the renderer, so the scene stands upright and at walking scale; the observation
     * graph's world coordinates are the recovered COLMAP frame and are not composed with
     * anything. Projecting one through the other would be a silent, plausible-looking error.
     *
     * Either pair would in fact agree, because a similarity applied to both a camera and a point
     * cancels in the projection. Using the recorded pair is still the right choice: it is the one
     * that stays correct if the display frame ever stops being a similarity, and it is the pair
     * whose agreement was measured. Against this scene on 2026-09-06, reprojecting every retained
     * observation of the first photograph through this transform reproduced COLMAP's own recorded
     * pixel to a median of 2.8 px and a maximum of 9.9 px on a 3060x4080 original, which is the
     * SIMPLE_RADIAL distortion that `pinhole-approximation` says it is dropping.
     */
    return {
      sceneFromCameraRowMajor: camera.sceneFromCameraRowMajor,
      calibration: camera.calibration,
      projection: camera.projection,
    };
  };

  /**
   * Load the scene's recorded observation graph once, when the inspector opens on it.
   *
   * Started on open rather than on the first click so the answer is ready when a visitor asks:
   * the real bowl scene's graph is about 53 MB of JSON. Cached by scene id for the session,
   * because an accepted pose receipt is immutable and re-reading it could not say anything new.
   */
  const loadObservations = (sceneId: string): void => {
    if (state.observationGraphSceneId === sceneId
      && (state.observationGraph !== null || state.observationLoad !== null)) return;
    const where = state.credentials;
    if (where === null) {
      reconstructionInspector.showEvidence({
        kind: 'failed', reason: 'This session has no credentials to read the observation graph with.',
      });
      return;
    }
    state.observationGraphSceneId = sceneId;
    state.observationGraph = null;
    reconstructionInspector.showEvidence({ kind: 'loading' });
    state.observationLoad = new ObservationsClient(where).load(sceneId).then((graph) => {
      if (state.observationGraphSceneId !== sceneId) return;
      state.observationGraph = graph;
      reconstructionInspector.showEvidence({
        kind: 'ready', pointCount: graph.points.length, retainedPerImage: graph.retainedPerImage,
      });
    }).catch((error: unknown) => {
      if (state.observationGraphSceneId !== sceneId) return;
      reconstructionInspector.showEvidence({
        kind: 'failed',
        reason: error instanceof ObservationsUnavailable
          ? error.message
          : 'The recorded observation graph could not be read.',
      });
    }).finally(() => {
      if (state.observationGraphSceneId === sceneId) state.observationLoad = null;
    });
  };

  /**
   * Load who is in the photograph this view stands on, and let a reviewer answer.
   *
   * Called on every view change, including with null, because the panel is about ONE photograph
   * and leaving the previous one on screen would offer buttons that write receipts against a
   * capture the visitor has already left. `state.reviewCaptureId` is the guard: a slow answer for
   * the previous photograph is dropped rather than rendered.
   *
   * Every action refetches instead of patching the panel in place. One receipt can move more than
   * the row it was written against, because a subject can be bound to several regions and the
   * resolved state is a fold over all of that subject's receipts; a client that edited one row
   * would be a second implementation of a rule the server already owns.
   */
  const manualDrafts = new PersonRegionDrafts();
  let reviewGeneration = 0;
  const loadPersonReview = (captureId: string | null): void => {
    const generation = ++reviewGeneration;
    reconstructionInspector.showReview(null);
    state.reviewCaptureId = captureId;
    if (captureId === null) {
      reconstructionInspector.showReview(null);
      return;
    }
    const where = state.credentials;
    if (where === null) {
      reconstructionInspector.showReview(
        el('p', { text: 'This session has no credentials to read who is in this photograph.' }),
      );
      return;
    }
    const api = new PersonReviewApi(where);
    const act = (run: () => Promise<unknown>): void => {
      void run()
        .then(() => { if (state.reviewCaptureId === captureId && generation === reviewGeneration) loadPersonReview(captureId); })
        .catch((error: unknown) => {
          if (state.reviewCaptureId !== captureId || generation !== reviewGeneration) return;
          reconstructionInspector.showReview(el('p', {
            class: 'person-review-failed',
            text: error instanceof ReviewUnavailable
              ? error.message
              : 'That review edit was not recorded.',
          }));
        });
    };
    void api.load(captureId).then((review) => {
      // Dropped rather than drawn: the visitor has moved to another photograph since this asked.
      if (state.reviewCaptureId !== captureId || generation !== reviewGeneration) return;
      reconstructionInspector.showReview(buildPersonReview({
        captureId: review.captureId,
        reviewState: review.reviewState,
        regions: review.regions,
        onReload: () => loadPersonReview(captureId),
        editor: {
          captureId, source: sourceForCapture(captureId), drafts: manualDrafts,
          isCurrent: () => state.reviewCaptureId === captureId && generation === reviewGeneration
            && reconstructionInspector.selected?.captureId === captureId,
          onAdd: async (region) => {
            // Reconcile an uncertain previous response before writing another receipt.
            const latest = await api.load(captureId);
            if (!latest.regions.some((item) => item.regionKey === region.region_key)) {
              await api.add(captureId, region);
            }
          },
        },
        onConfirm: (regionKey) => act(() =>
          api.edit(captureId, { region_key: regionKey, action: 'confirm' })),
        onDelete: (regionKey) => act(() =>
          api.edit(captureId, { region_key: regionKey, action: 'delete' })),
        onConsent: (regionKey, scope, decision) => {
          const region = review.regions.find((item) => item.regionKey === regionKey);
          if (region === undefined) return;
          act(() => api.consent(captureId, region, scope, decision));
        },
      }));
    }).catch((error: unknown) => {
      if (state.reviewCaptureId !== captureId || generation !== reviewGeneration) return;
      reconstructionInspector.showReview(el('p', {
        class: 'person-review-failed',
        text: error instanceof ReviewUnavailable
          ? error.message
          : 'Who is in this photograph could not be read.',
      }));
    });
  };

  /** What one capture's original looks like in this session, through its own evidence handles. */
  const sourceForCapture = (captureId: string) =>
    [...(state.previewSourceMedia?.values() ?? [])].find((descriptor) =>
      descriptor.captureIds?.includes(captureId))
    ?? current.occurrences
      .filter((occurrence) => occurrence.captureId === captureId)
      .flatMap((occurrence) => occurrence.evidence)
      .map((handle) => state.previewSourceMedia?.get(handle))
      .find((descriptor) => descriptor !== undefined) ?? null;

  /**
   * One click in the inspector, resolved to the photographs that observed that piece of the world.
   *
   * The answer is recorded provenance and nothing else: the point is one COLMAP actually stored,
   * and the photographs listed are the ones whose observations of it were retained. Nothing here
   * reprojects the point into other cameras to ask which of them could have seen it, because that
   * is a geometric guess about visibility rather than a record of an observation.
   */
  const resolveEvidenceAt = (clientX: number, clientY: number): void => {
    const view = state.atlas?.binding.inspectionView ?? null;
    if (view === null) return;
    const captureId = view.captureIds[0];
    if (view.kind !== 'source-camera' || view.calibration === null || captureId === undefined) {
      reconstructionInspector.showEvidence({
        kind: 'unsupported',
        reason: view.kind === 'between-cameras'
          ? 'This is a midpoint between two photographs, not a photograph. No camera stood here, '
            + 'so there is no calibrated projection to invert. Choose either adjacent source camera.'
          : 'This view has no accepted calibration, so a click cannot be inverted exactly.',
      });
      return;
    }
    const graph = state.observationGraph;
    if (graph === null) {
      if (state.observationLoad === null) loadObservations(view.sceneId);
      return;
    }
    const camera = pickCameraFor(view.sceneId, captureId);
    if (camera === null) {
      reconstructionInspector.showEvidence({
        kind: 'unsupported',
        reason: 'This session holds no recovered camera for that photograph.',
      });
      return;
    }
    const rect = env.canvas.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return;
    const cursor = canvasToSourcePixel(
      camera.calibration,
      { width: rect.width, height: rect.height },
      { x: clientX - rect.left, y: clientY - rect.top },
    );
    const sourcePxPerCanvasPx = camera.calibration.height / rect.height;
    const tolerancePx = PICK_TOLERANCE_CANVAS_PX * sourcePxPerCanvasPx;
    const result = pickObservedPoint(camera, graph.points, cursor, {
      tolerancePx,
      occlusionBandPx: PICK_OCCLUSION_BAND_CANVAS_PX * sourcePxPerCanvasPx,
    });
    if (result === null) {
      reconstructionInspector.showEvidence({
        kind: 'miss', toleranceSourcePx: tolerancePx, canvasPx: PICK_TOLERANCE_CANVAS_PX,
      });
      return;
    }
    const observedBy = graph.observedBy.get(result.point.pointId) ?? [];
    reconstructionInspector.showEvidence({
      kind: 'hit',
      // Verbatim from atlas-core. It is the sentence that must state both the full track length
      // and the retained count whenever they differ, and rewording it here is how they diverge.
      sentence: observationSentence(result),
      pointId: result.point.pointId,
      pixelDistance: result.pixelDistance,
      // The POINT's mean residual over its whole track, which is what the receipt records: the
      // pose stage copies `points3D.txt` field 7 onto every row of a track, so all of these are
      // the same number and it belongs to the point, not to any one photograph.
      meanReprojectionErrorPx: observedBy[0]?.reprojectionErrorPx ?? 0,
      projection: result.projection,
      photographs: observedBy.map((observation, index) => {
        const source = sourceForCapture(observation.captureId);
        return {
          captureId: observation.captureId,
          title: source?.title ?? null,
          label: `Photograph ${String(index + 1)}`,
          url: source?.url ?? null,
          alt: source?.alt ?? 'An authorized original photograph.',
          available: source?.available === true && source.url !== null,
          x: observation.x,
          y: observation.y,
          consentSentence: consentSentence(observation.consent),
        };
      }),
    });
  };

  const reconstructionInspector = buildReconstructionInspector({
    onView: (sceneId, viewId) => state.atlas?.binding.inspectSceneView(sceneId, viewId) ?? false,
    onReturn: () => { loadPersonReview(null); state.atlas?.binding.endSceneInspection(); },
    // The world canvas is aria-hidden, so the click has to have a real button beside it or the
    // gesture exists only for sighted mouse users.
    onResolveCentre: () => {
      const rect = env.canvas.getBoundingClientRect();
      resolveEvidenceAt(rect.left + rect.width / 2, rect.top + rect.height / 2);
    },
    onViewShown: (sceneId, view) => {
      // A new view is a new projection, so the previous pick no longer describes what is on
      // screen. The panel goes back to saying what a click could resolve rather than keeping an
      // answer about a camera the visitor has left.
      // The review is about a photograph, so it follows the view that stands on one and is
      // cleared by every view that does not. Called before the early return below for exactly
      // that reason: a midpoint between two cameras must not keep the previous photograph's
      // people on screen with buttons that write receipts against it.
      loadPersonReview(view.captureId ?? null);
      if (view.kind !== 'source-camera' || view.projection === 'opm-estimate') {
        reconstructionInspector.showEvidence({
          kind: 'unsupported',
          reason: view.kind === 'between-cameras'
            ? 'This is a midpoint between two photographs. No camera stood here, so there is no '
              + 'calibrated projection to invert. Choose either adjacent source camera.'
            : 'This view has no accepted calibration, so a click cannot be inverted exactly.',
        });
        return;
      }
      loadObservations(sceneId);
      const graph = state.observationGraph;
      if (graph !== null && state.observationGraphSceneId === sceneId) {
        reconstructionInspector.showEvidence({
          kind: 'ready', pointCount: graph.points.length, retainedPerImage: graph.retainedPerImage,
        });
      }
    },
  });

  const inspectReconstruction = (sceneId: string): void => {
    deps.showWorld();
    const record = current.reconstructionScenes?.find((scene) => scene.sceneId === sceneId);
    const views = state.atlas?.binding.inspectionViews(sceneId) ?? [];
    let cameraNumber = 0;
    const choices = views.map((view) => {
      const member = view.kind === 'source-camera'
        ? record?.members.find((candidate) => candidate.captureId === view.captureIds[0]
          || (view.captureIds.length === 0 && candidate.placement?.artifactId === view.artifactIds[0]))
        : undefined;
      if (view.kind === 'source-camera') cameraNumber += 1;
      // World source IDs name topology slots, not captures. Join through the actual evidence
      // handles of this capture; matching a generated source ID to a capture ID loses every source.
      const source = member === undefined ? null :
        [...(state.previewSourceMedia?.values() ?? [])].find((descriptor) =>
          descriptor.captureIds?.includes(member.captureId))
        ?? current.occurrences
          .filter((occurrence) => occurrence.captureId === member.captureId)
          .flatMap((occurrence) => occurrence.evidence)
          .map((handle) => state.previewSourceMedia?.get(handle))
          .find((descriptor) => descriptor !== undefined) ?? null;
      return {
        id: view.id, kind: view.kind, projection: view.projection,
        label: view.kind === 'source-camera'
          ? `Source camera ${cameraNumber}` : `Between cameras ${cameraNumber} and ${cameraNumber + 1}`,
        source,
        // Taken from the member already resolved above rather than from `view.captureIds`, which
        // names topology slots on a source-only view. Null for a midpoint, where no single
        // photograph is being looked at and so no review is about anything.
        captureId: member?.captureId ?? null,
      };
    });
    if (!reconstructionInspector.open(sceneId, choices)) {
      deps.showTravelStatus('No verified reconstruction cameras are available. The original sources remain in Index.', 'failure');
    }
  };

  // Both the availability panel and inspector count the same authorized, deduplicated set.
  const sourcesForScene = (sceneId: string) => {
    const record = current.reconstructionScenes?.find((scene) => scene.sceneId === sceneId);
    const region = current.islands.find((island) => island.islandId === (record?.islandId ?? sceneId));
    const captures = new Set(record?.members.map((member) => member.captureId) ?? region?.captureIds ?? []);
    const regionId = record?.islandId ?? region?.islandId;
    const seen = new Set<string>();
    return [...(state.previewSourceMedia?.values() ?? [])].filter((source) => {
      if (seen.has(source.evidenceRef)) return false;
      if ((regionId === undefined || source.regionId !== regionId)
        && !source.captureIds?.some((id) => captures.has(id))) return false;
      seen.add(source.evidenceRef);
      return true;
    });
  };

  const inspectSceneSources = (sceneId: string): void => {
    state.atlas?.binding.endSceneInspection();
    deps.showWorld();
    const sources = sourcesForScene(sceneId);
    const choices = sources.map((source, index) => ({
      id: `source:${source.evidenceRef}`, kind: 'source-only' as const,
      label: `Photograph ${index + 1}`, source,
      captureId: source.captureIds?.length === 1 ? source.captureIds[0] ?? null : null,
    }));
    if (!reconstructionInspector.open(sceneId, choices)) {
      deps.showTravelStatus('No authorized source photographs are available in this session.', 'failure');
    }
  };

  const renderedPreviewRegions = new Set<string>();
  const renderReconstructionStatus = (): HTMLElement => buildStatus({
    omittedRegionCount: deps.built.omitted.length, undrawable: deps.built.undrawable,
    notices: [...state.sourceMediaNotices, ...state.geometryNotices],
    reconstructionScenes: state.reconstructionRungs,
    sourceRegions: current.islands
      .filter((island) => !renderedPreviewRegions.has(island.islandId)
        && !current.reconstructionScenes?.some((scene) => scene.islandId === island.islandId))
      .map((island) => ({ regionId: island.islandId, captureCount: island.captureIds.length })),
    onInspectScene: inspectReconstruction, onInspectSources: inspectSceneSources,
    // The lens switch, last in the input as it is last in the panel. Toggling it calls
    // `applyProofLens` and nothing else: no scene is rebuilt and this panel is not re-rendered,
    // which is what makes "toggling the lens changes no scene, no rung and no receipt" checkable
    // rather than merely asserted.
    proofLens: {
      enabled: state.proofLensEnabled,
      theme: themeForPreferences(state.preferences, env.systemAppearance.matches),
      onToggle: (enabled) => {
        state.proofLensEnabled = enabled;
        applyProofLens();
      },
    },
    ...(sourcePresentation() === 'inspection' ? {
      reconstructionFocus: {
        collections: current.islands.map((island) => {
          const sceneId = current.reconstructionScenes?.find((scene) => scene.islandId === island.islandId)?.sceneId
            ?? island.islandId;
          return { sceneId, sourceCount: sourcesForScene(sceneId).length };
        }),
      },
    } : {}),
  });

  let statusElement = renderReconstructionStatus();

  return {
    inspectorRoot: reconstructionInspector.root,
    get statusElement() { return statusElement; },
    refreshStatus: () => {
      const refreshed = renderReconstructionStatus();
      statusElement.replaceWith(refreshed);
      statusElement = refreshed;
    },
    applyProofLens,
    hideInspector: () => reconstructionInspector.hide(),
    noteRenderedPreviewRegion: (islandId) => renderedPreviewRegions.add(islandId),
    inspectReconstruction,
    inspectSceneSources,
    resolveEvidenceAt,
    loadPersonReview,
    dispose: () => undefined,
  };
}
