// @vitest-environment happy-dom
/**
 * What a person reads about a placed depth estimate, and what a client may draw.
 *
 * Two things are held here. The three sentences about truth, scale and coverage are shown exactly
 * as the server wrote them, so a client update cannot quietly soften them. And an estimate in any
 * state but ``available`` contributes nothing to the renderer: no placeholder, no outline, and no
 * box where somebody's kitchen used to be.
 */
import { describe, expect, it, vi } from 'vitest';
import {
  availabilitySentence,
  buildPhotoGeometryInspector,
} from '../src/ui/photo-geometry-inspector.js';
import { drawablePointMaps, type PointMapInstance } from '../src/world-objects-api.js';

const SOURCE = Object.freeze({
  capture_id: '11111111-1111-4111-8111-111111111111',
  source_sha256: 'a'.repeat(64),
  attachment: { attachment_id: '22222222-2222-4222-8222-222222222222', entry_id: 'e' },
  authorization: { authorization_id: 'auth', evidence_sha256: 'b'.repeat(64) },
  screening: { screening_id: 'screen', receipt_sha256: 'c'.repeat(64) },
  right: { right_id: 'right', receipt_sha256: 'd'.repeat(64) },
  model: {
    provider: 'local', role: 'depth', identifier: 'Ruicheng/moge-2-vitl',
    revision: '39c4d5e957afe587e04eec59dc2bcc3be5ecd968', destination: 'local-process',
  },
  artifact: {
    artifact_id: 'artifact', content_sha256: 'e'.repeat(64), byte_size: 4096,
    container: 'opm/2', stage_version: 2, rung: 3, declared_metric: true,
    declared_fov_y_microdegrees: 77_500_000,
  },
});

function instance(overrides: Partial<PointMapInstance> = {}): PointMapInstance {
  return Object.freeze({
    instanceId: 'point-map:kitchen',
    source: SOURCE,
    regionId: 'region:starter',
    transform: {
      coordinateSpace: 'region', coordinateUnit: 'mm',
      xMm: 0, yMm: 1650, zMm: 0, yawMicroradians: 0, scaleMilli: 1000,
    },
    origin: { kind: 'authored', role: 'personal' as const },
    removed: false,
    availability: 'available',
    unavailableReason: null,
    truth: 'Model estimate from one photograph, not measured, shows only what the camera saw, '
      + 'placed here by you.',
    scale: "Approximate size from one photograph; not measured. Shown at 1x the model's own estimate.",
    coverage: 'This shows only the surfaces that one camera saw. Nothing behind or beside them '
      + 'was filled in.',
    ...overrides,
  });
}

const version = (instances: readonly PointMapInstance[]) =>
  ({ pointMapInstances: instances } as never);

describe('the panel for one placed estimate', () => {
  it('leads with what it is, before anything a person would have to open', () => {
    const panel = buildPhotoGeometryInspector({ instance: instance() });
    const visible = panel.cloneNode(true) as HTMLElement;
    visible.querySelectorAll('details').forEach((node) => node.remove());
    const words = visible.textContent ?? '';
    expect(words).toContain('3D estimate from a photo');
    expect(words).toContain('not measured');
    expect(words).toContain('only what the camera saw');
    expect(words).toContain('not measured. Shown at 1x');
    expect(words).toContain('Nothing behind or beside them was filled in');
    expect(words).toContain('Showing in this world.');
  });

  it('shows the three sentences exactly as the server wrote them', () => {
    const given = instance({
      truth: 'A sentence only the server could have written.',
      scale: 'Approximate, and this exact wording.',
      coverage: 'One camera, and nothing else.',
    });
    const words = buildPhotoGeometryInspector({ instance: given }).textContent ?? '';
    for (const sentence of [given.truth, given.scale, given.coverage]) {
      expect(words).toContain(sentence);
    }
  });

  it('names the model, where it ran, and the permission that allowed it', () => {
    const words = buildPhotoGeometryInspector({ instance: instance() }).textContent ?? '';
    expect(words).toContain('Ruicheng/moge-2-vitl@39c4d5e957afe587e04eec59dc2bcc3be5ecd968');
    expect(words).toContain('local-process');
    expect(words).toContain('d'.repeat(64));
    expect(words).toContain('77.5 degrees vertically, estimated, not measured');
  });

  it('calls the metric flag a declaration rather than a fact about the room', () => {
    const words = buildPhotoGeometryInspector({ instance: instance() }).textContent ?? '';
    expect(words).toContain('Scale declared by the model');
    expect(words).not.toMatch(/(^|[^a-z])Metric:/);
  });

  it('offers Undo and Stop, and calls back exactly once each', () => {
    const onUndo = vi.fn();
    const onStop = vi.fn();
    const panel = buildPhotoGeometryInspector({ instance: instance(), onUndo, onStop });
    panel.querySelector<HTMLButtonElement>('.photo-geometry-undo')!.click();
    panel.querySelector<HTMLButtonElement>('.photo-geometry-stop')!.click();
    expect(onUndo).toHaveBeenCalledTimes(1);
    expect(onStop).toHaveBeenCalledTimes(1);
  });
});

describe('what each state tells a person to do', () => {
  it('distinguishes stopping it from every other way it can be absent', () => {
    expect(availabilitySentence(instance({
      availability: 'withdrawn', unavailableReason: 'model_right_withdrawn',
    }))).toContain('you stopped 3D estimates for this photo');
    expect(availabilitySentence(instance({
      availability: 'withdrawn', unavailableReason: 'review_expired',
    }))).toContain('Review it again');
    expect(availabilitySentence(instance({
      availability: 'withdrawn', unavailableReason: 'source_deleted',
    }))).toContain('no longer in your library');
    expect(availabilitySentence(instance({ availability: 'detached' })))
      .toContain('removed from this world');
    expect(availabilitySentence(instance({ availability: 'unavailable_bytes' })))
      .toContain('cannot be read right now');
    expect(availabilitySentence(instance({ removed: true }))).toBe('Removed from this world.');
  });

  it('never tells somebody who stopped it that their review expired', () => {
    const stopped = availabilitySentence(instance({
      availability: 'withdrawn', unavailableReason: 'model_right_withdrawn',
    }));
    expect(stopped).not.toContain('review');
    expect(stopped).not.toContain('library');
  });
});

describe('what the renderer is given', () => {
  it('draws an available estimate and nothing at all for any other state', () => {
    const available = instance({ instanceId: 'point-map:shown' });
    const others = [
      instance({ instanceId: 'point-map:stopped', availability: 'withdrawn', unavailableReason: 'model_right_withdrawn' }),
      instance({ instanceId: 'point-map:detached', availability: 'detached' }),
      instance({ instanceId: 'point-map:gone', availability: 'unavailable_bytes' }),
      instance({ instanceId: 'point-map:drifted', availability: 'binding_drift' }),
      instance({ instanceId: 'point-map:unknown', availability: 'unknown' }),
      instance({ instanceId: 'point-map:removed', removed: true }),
    ];
    const drawable = drawablePointMaps(version([available, ...others]));
    expect(drawable.map((item) => item.instanceId)).toEqual(['point-map:shown']);
  });

  it('draws nothing when a world holds none', () => {
    expect(drawablePointMaps(version([]))).toEqual([]);
    expect(drawablePointMaps({} as never)).toEqual([]);
  });
});
