/**
 * An opt-in measurement record for the real authenticated application.
 *
 * The bake-off harness measures a controlled fixture. This recorder answers a different question:
 * what the production application actually fetched, verified, decoded, uploaded, and presented.
 * It activates only for `validation=1`, writes no storage, and emits one credential-free JSON
 * record into the document and console for the external evaluation runner to retain.
 */

import type { AtlasBinding } from '@exulanica/atlas-react/playcanvas';
import type { ReconstructionSceneRecord } from '@exulanica/graph-client';
import type { GeometryIssue, GeometryLoadMeasurement } from './geometry-api.js';

const REPORT_ID = 'exulanica-browser-validation-report';
const REPORT_PREFIX = 'EXULANICA-BROWSER-VALIDATION';

export interface FrameSummary {
  readonly frames: number;
  readonly frameMeanMs: number;
  readonly frameP50Ms: number;
  readonly frameP95Ms: number;
  readonly frameP99Ms: number;
  readonly framesOver16_7Ms: number;
  readonly frameOver16_7Fraction: number;
  readonly fpsP1Low: number;
}

export function summarizeFrameTimes(samples: readonly number[]): FrameSummary {
  const sorted = [...samples].sort((a, b) => a - b);
  const mean = sorted.reduce((total, value) => total + value, 0) / Math.max(1, sorted.length);
  const at = (fraction: number): number => {
    if (sorted.length === 0) return 0;
    const index = Math.min(sorted.length - 1, Math.round((sorted.length - 1) * fraction));
    return sorted[index]!;
  };
  const rounded = (value: number, digits = 2): number => {
    const scale = 10 ** digits;
    return Math.round(value * scale) / scale;
  };
  const framesOver16_7Ms = sorted.filter((value) => value > 16.7).length;
  return Object.freeze({
    frames: sorted.length,
    frameMeanMs: rounded(mean),
    frameP50Ms: rounded(at(0.5)),
    frameP95Ms: rounded(at(0.95)),
    frameP99Ms: rounded(at(0.99)),
    framesOver16_7Ms,
    frameOver16_7Fraction: sorted.length === 0
      ? 0
      : rounded(framesOver16_7Ms / sorted.length, 6),
    fpsP1Low: sorted.length === 0 ? 0 : rounded(1000 / Math.max(at(0.99), 1e-6)),
  });
}

interface BindingContext {
  readonly scenes: readonly ReconstructionSceneRecord[];
  readonly placedPointMapCount: number;
  readonly placementMaxErrors: readonly number[];
}

export class BrowserValidationRecorder {
  readonly #startedAt = performance.now();
  readonly #measureSeconds: number;
  readonly #warmupSeconds: number;
  readonly #geometry: GeometryLoadMeasurement[] = [];
  #geometryIssues: readonly GeometryIssue[] = [];
  #geometryStartedAt: number | null = null;
  #geometryLoadMs: number | null = null;
  #bound = false;

  constructor(search: string) {
    const params = new URLSearchParams(search);
    this.#measureSeconds = boundedSeconds(params.get('validation-seconds'), 10);
    this.#warmupSeconds = boundedSeconds(params.get('validation-warmup'), 2);
  }

  beginGeometryLoad(): void {
    this.#geometryStartedAt ??= performance.now();
  }

  recordGeometry(measurement: GeometryLoadMeasurement): void {
    this.#geometry.push(measurement);
  }

  endGeometryLoad(issues: readonly GeometryIssue[]): void {
    if (this.#geometryStartedAt !== null) {
      this.#geometryLoadMs = performance.now() - this.#geometryStartedAt;
    }
    this.#geometryIssues = issues;
  }

  observeBinding(binding: AtlasBinding, context: BindingContext): void {
    if (this.#bound) return;
    this.#bound = true;
    const frames: number[] = [];
    let warmupMs = 0;
    let measuredMs = 0;
    let firstMeaningfulRenderMs: number | null = null;
    let hiddenDuringRun = document.hidden;
    let peakHeapBytes: number | null = heapBytes();
    let maxDrawCalls = 0;
    const cameraSegments: {
      id: string;
      kind: string;
      position: readonly number[];
      forward: readonly number[];
      up: readonly number[] | null;
      fovYDeg: number;
      sourceAspect: number | null;
      artifactIds: readonly string[];
      samples: number[];
    }[] = [];

    const onVisibility = (): void => {
      if (document.hidden) hiddenDuringRun = true;
    };
    document.addEventListener('visibilitychange', onVisibility);

    const onFrameEnd = (): void => {
      firstMeaningfulRenderMs ??= performance.now() - this.#startedAt;
      maxDrawCalls = Math.max(maxDrawCalls, binding.app.stats.drawCalls.total);
    };
    const onFrame = (frameMs: number): void => {
      const heap = heapBytes();
      if (heap !== null) peakHeapBytes = Math.max(peakHeapBytes ?? 0, heap);
      if (firstMeaningfulRenderMs === null) return;
      if (warmupMs < this.#warmupSeconds * 1000) {
        warmupMs += frameMs;
        return;
      }
      if (measuredMs >= this.#measureSeconds * 1000) return;
      measuredMs += frameMs;
      frames.push(frameMs);
      const inspection = binding.inspectionView;
      const id = inspection?.id ?? 'atlas-navigation';
      let segment = cameraSegments.at(-1);
      if (segment?.id !== id) {
        const pose = binding.cameraPose();
        segment = {
          id, kind: inspection?.kind ?? 'atlas-navigation',
          position: inspection?.position ?? [pose.position.x, pose.position.y, pose.position.z],
          forward: inspection?.forward ?? [pose.forward.x, pose.forward.y, pose.forward.z],
          up: inspection?.up ?? null,
          fovYDeg: binding.camera.camera?.fov ?? 70,
          sourceAspect: inspection?.sourceAspect ?? null,
          artifactIds: inspection?.artifactIds ?? [], samples: [],
        };
        cameraSegments.push(segment);
      }
      segment.samples.push(frameMs);
      if (measuredMs >= this.#measureSeconds * 1000) finish();
    };

    const finish = (): void => {
      binding.app.off('frameend', onFrameEnd);
      binding.app.off('frameupdate', onFrame);
      document.removeEventListener('visibilitychange', onVisibility);
      const gl = (binding.device as unknown as { gl?: WebGL2RenderingContext }).gl;
      const gpuError = gl?.getError() ?? null;
      const resources = performance.getEntriesByType('resource') as PerformanceResourceTiming[];
      const resourceBytes = resources.reduce((total, entry) => total + entry.transferSize, 0);
      const decodedResourceBytes = resources.reduce(
        (total, entry) => total + entry.decodedBodySize,
        0,
      );
      const scene = context.scenes[0] ?? null;
      const geometryBytes = this.#geometry.reduce(
        (total, item) => total + (item.reused ? 0 : item.receivedBytes),
        0,
      );
      const record = Object.freeze({
        profile: 'exulanica.browser-reconstruction-validation/v1',
        measured_at: new Date().toISOString(),
        measurement: {
          driver: 'requestAnimationFrame',
          warmup_seconds: this.#warmupSeconds,
          duration_seconds: this.#measureSeconds,
          first_meaningful_render_ms: rounded(firstMeaningfulRenderMs),
          // A frame and a draw call do not prove every point survived the shaders or appeared.
          time_to_full_detail_ms: null,
          geometry_load_ms: rounded(this.#geometryLoadMs),
          ...summarizeFrameTimes(frames),
          hidden_during_run: hiddenDuringRun,
          camera_segments: cameraSegments.map(({ samples, ...camera }) => ({
            ...camera, ...summarizeFrameTimes(samples),
          })),
        },
        runtime: {
          browser_user_agent: navigator.userAgent,
          platform: navigator.platform || null,
          logical_cpu_count: navigator.hardwareConcurrency || null,
          device_memory_gb: deviceMemory(),
          gpu: gpuName(gl),
          engine: document.querySelector('canvas')?.getAttribute('data-engine') ?? null,
          viewport_css_px: [window.innerWidth, window.innerHeight],
          canvas_px: [binding.device.width, binding.device.height],
          device_pixel_ratio: window.devicePixelRatio,
          peak_js_heap_mb: peakHeapBytes === null
            ? null
            : rounded(peakHeapBytes / (1024 * 1024)),
        },
        scene: scene === null ? null : {
          scene_id: scene.sceneId,
          member_count: scene.memberCount,
          registered_member_count: scene.registeredMemberCount,
          excluded_member_count: scene.memberCount - scene.registeredMemberCount,
          recorded_rung: scene.recordedRung,
          displayed_rung: scene.displayedRung,
          rendering_substrate: scene.renderingSubstrate,
          withholding_reasons: scene.displayReasons,
          pose_receipt_sha256: scene.poseReceiptSha256,
          placement_receipt_sha256: scene.placementReceiptSha256,
        },
        geometry: {
          placed_point_map_count: context.placedPointMapCount,
          uploaded_point_map_count: binding.islands.length,
          uploaded_point_count: binding.islands.reduce(
            (total, visual) => total + visual.pointMap.map.header.pointCount,
            0,
          ),
          loaded_trained_scene_count: binding.trainedScenes.length,
          loaded_gaussian_count: binding.trainedScenes.reduce((total, scene) => total + scene.geometry.pointCount, 0),
          trained_scene_failures: binding.trainedSceneFailures,
          authenticated_network_bytes: geometryBytes,
          artifact_sizes: this.#geometry.map((item) => item.expectedBytes),
          loads: this.#geometry,
          issues: this.#geometryIssues,
          placement_max_errors: context.placementMaxErrors,
        },
        network: {
          transfer_bytes: resourceBytes,
          decoded_body_bytes: decodedResourceBytes,
          resource_count: resources.length,
        },
        renderer: {
          max_draw_calls: maxDrawCalls,
          gpu_error: gpuError,
          draw_submission_valid: binding.islands.length === context.placedPointMapCount
            && (binding.islands.length > 0 || binding.trainedScenes.length > 0)
            && maxDrawCalls > 0
            && (gpuError === null || gpuError === gl?.NO_ERROR),
        },
        limitations: [
          'This local browser measurement is not representative of the eventual production host.',
          'Peak JavaScript heap is null when the browser does not expose performance.memory.',
          'Resource transfer bytes follow the browser Resource Timing accounting convention.',
          'Uploaded point counts and draw submissions are not evidence of visible pixels or reconstruction quality.',
          'Time to full detail is unmeasured; the first presented frame may contain authored world geometry only.',
          'Inspection preserves source vertical field of view; horizontal coverage follows the recorded canvas aspect ratio.',
        ],
      });
      const output = document.createElement('script');
      output.id = REPORT_ID;
      output.type = 'application/json';
      output.textContent = JSON.stringify(record);
      document.getElementById(REPORT_ID)?.remove();
      document.body.append(output);
      console.info(`${REPORT_PREFIX} ${JSON.stringify(record)}`);
    };

    binding.app.on('frameend', onFrameEnd);
    binding.app.on('frameupdate', onFrame);
  }
}

export function browserValidation(search: string): BrowserValidationRecorder | null {
  return new URLSearchParams(search).get('validation') === '1'
    ? new BrowserValidationRecorder(search)
    : null;
}

function boundedSeconds(raw: string | null, fallback: number): number {
  const value = raw === null ? fallback : Number(raw);
  return Number.isFinite(value) ? Math.max(1, Math.min(60, value)) : fallback;
}

function rounded(value: number | null): number | null {
  return value === null ? null : Math.round(value * 100) / 100;
}

function heapBytes(): number | null {
  const memory = (performance as unknown as { memory?: { usedJSHeapSize: number } }).memory;
  return memory?.usedJSHeapSize ?? null;
}

function deviceMemory(): number | null {
  return (navigator as Navigator & { deviceMemory?: number }).deviceMemory ?? null;
}

function gpuName(gl: WebGL2RenderingContext | undefined): string | null {
  if (gl === undefined) return null;
  const extension = gl.getExtension('WEBGL_debug_renderer_info');
  if (extension !== null) return String(gl.getParameter(extension.UNMASKED_RENDERER_WEBGL));
  return String(gl.getParameter(gl.RENDERER));
}
