/**
 * The data view's GPU pixel checks. See `pixel-scenes.ts` for how a page runs them.
 *
 * `runDataViewPixelChecks` answers three questions with exact bytes:
 *
 * 1. At the rendered end with every overlay off, does registering the data view change a pixel?
 *    The baseline scenes are also run on a checkout of main and compared digest for digest.
 * 2. Does the personal point-map look at its existing settings still draw what main draws?
 *    Same comparison, on the committed `python-writer.opm` fixture.
 * 3. Does a withdrawn subject draw nothing at any slider position, with every overlay on? A scene
 *    holding a withdrawn box is compared with the same scene without that box, at 0, 0.5 and 1,
 *    for the world canvas and for the tag canvas, and its overlay plan must hold no mark for it.
 */
import {
  DATA_VIEW_STYLE,
  DEFAULT_REPRESENTATION_INTENT,
  type RepresentationIntent,
  type RepresentationSubject,
} from '@exulanica/atlas-core';
import { DataViewOverlay } from '../../src/playcanvas/data-view/overlay.js';
import { representationWorldBounds } from '../../src/playcanvas/representation-binding.js';
import { RepresentationRuntime } from '../../src/playcanvas/representation-runtime.js';
import {
  BOXES,
  addBoxes,
  boxSubject,
  createStage,
  digestStage,
  registerBoxes,
  renderBaselineScenes,
  sha256,
  type PixelDigest,
} from './pixel-scenes.js';

const WITHDRAWN = 'pixel:box-b';

export interface OverlayDigest extends PixelDigest {
  readonly tagsSha256: string;
  readonly marksForWithdrawn: number;
  readonly allocatedPoints: number;
}

async function overlayScene(
  scene: string, box: 'available' | 'withdrawn' | 'absent', intent: RepresentationIntent,
): Promise<OverlayDigest> {
  const stage = await createStage();
  const specs = box === 'absent' ? BOXES.filter(spec => spec.id !== WITHDRAWN) : BOXES;
  const instances = addBoxes(stage, specs);
  const runtime = new RepresentationRuntime();
  const subjects = new Map(specs.map(spec => [spec.id, (): RepresentationSubject => boxSubject(spec,
    spec.id === WITHDRAWN && box === 'withdrawn'
      ? { availability: 'withdrawn', unavailableReason: 'Withdrawn for this check.' } : {},
  )] as const));
  registerBoxes(stage, runtime, instances, subjects);
  const overlay = new DataViewOverlay({
    device: stage.device,
    app: stage.app,
    camera: stage.camera,
    report: () => runtime.report,
    worldBounds: subject => {
      const instance = instances.get(subject.subjectId);
      return instance === undefined || subject.bounds === null
        ? null : representationWorldBounds(subject.bounds, instance.node);
    },
    reducedMotion: () => true,
    invalidate: () => {},
  }, DATA_VIEW_STYLE);
  let report = runtime.setIntent(intent);
  for (let i = 0; i < 64 && report.pendingSubjects > 0; i += 1) report = runtime.update();
  const digest = await digestStage(stage, scene);
  const plan = overlay.plan;
  const marksForWithdrawn = plan === null ? -1 : [
    ...plan.boxes, ...plan.tags,
  ].filter(mark => mark.subjectId === WITHDRAWN).length
    + plan.links.filter(link => link.from === WITHDRAWN || link.to === WITHDRAWN).length;
  const tags = document.querySelector<HTMLCanvasElement>('canvas.data-view-tags');
  const tagBytes = tags === null
    ? new Uint8Array(0)
    : new Uint8Array(tags.getContext('2d')!.getImageData(0, 0, tags.width, tags.height).data.buffer);
  const result = {
    ...digest,
    tagsSha256: await sha256(tagBytes),
    marksForWithdrawn,
    allocatedPoints: report.allocatedPoints,
  };
  runtime.destroy();
  overlay.destroy();
  stage.destroy();
  return result;
}

export interface DataViewPixelResult {
  readonly baseline: readonly PixelDigest[];
  readonly renderedEndWithOverlay: OverlayDigest;
  readonly withdrawn: readonly {
    readonly pointMix: number;
    readonly withWithdrawn: OverlayDigest;
    readonly without: OverlayDigest;
    readonly worldIdentical: boolean;
    readonly tagsIdentical: boolean;
  }[];
}

export async function runDataViewPixelChecks(opmUrl: string): Promise<DataViewPixelResult> {
  const baseline = await renderBaselineScenes(opmUrl);
  // The rendered end with the overlay attached: must equal the registered scene without one.
  const renderedEndWithOverlay = await overlayScene('rendered-end-with-overlay', 'available', DEFAULT_REPRESENTATION_INTENT);
  const withdrawn = [];
  for (const pointMix of [0, 0.5, 1]) {
    const intent: RepresentationIntent = {
      ...DEFAULT_REPRESENTATION_INTENT, pointMix, boxes: true, ids: true, labels: true,
      binary: 'visualization', colour: 'kind',
    };
    const withWithdrawn = await overlayScene(`withdrawn-present-${pointMix}`, 'withdrawn', intent);
    const without = await overlayScene(`withdrawn-absent-${pointMix}`, 'absent', intent);
    withdrawn.push({
      pointMix, withWithdrawn, without,
      worldIdentical: withWithdrawn.sha256 === without.sha256,
      tagsIdentical: withWithdrawn.tagsSha256 === without.tagsSha256,
    });
  }
  return { baseline, renderedEndWithOverlay, withdrawn };
}
