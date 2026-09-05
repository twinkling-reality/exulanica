// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';
import type { AtlasBinding } from '@exulanica/atlas-react/playcanvas';
import { BrowserValidationRecorder } from '../src/browser-validation.js';

describe('browser validation evidence', () => {
  it('records exact camera segments while refusing to infer visible geometry from an upload or draw', () => {
    const log = vi.spyOn(console, 'info').mockImplementation(() => undefined);
    const events = new Map<string, (value: number) => void>();
    const view = { id: 'scene:camera:a', kind: 'source-camera', position: [1, 2, 3],
      forward: [0, 0, -1], up: [0, 1, 0], fovYDeg: 55, sourceAspect: 1.5, artifactIds: ['a'] };
    const fake = {
      app: { on: (name: string, callback: (value: number) => void) => events.set(name, callback),
        off: (name: string) => events.delete(name), stats: { drawCalls: { total: 3 } } },
      device: { width: 1000, height: 600 }, camera: { camera: { fov: 55 } },
      cameraPose: () => ({ position: { x: 1, y: 2, z: 3 }, forward: { x: 0, y: 0, z: -1 } }),
      inspectionView: view,
      trainedScenes: [], trainedSceneFailures: [],
      islands: [{ pointMap: { map: { header: { pointCount: 123 } } } }],
    };
    const recorder = new BrowserValidationRecorder('?validation-seconds=1&validation-warmup=1');
    recorder.observeBinding(fake as unknown as AtlasBinding, {
      scenes: [], placedPointMapCount: 1, placementMaxErrors: [0],
    });
    events.get('frameend')!(0);
    events.get('frameupdate')!(1000);
    events.get('frameupdate')!(500);
    fake.inspectionView = { ...view, id: 'scene:midpoint:a:b', kind: 'between-cameras' };
    events.get('frameupdate')!(500);
    const output = document.getElementById('exulanica-browser-validation-report')!;
    const record = JSON.parse(output.textContent!);
    expect(record.measurement.time_to_full_detail_ms).toBeNull();
    expect(record.measurement.camera_segments.map((segment: { id: string }) => segment.id))
      .toEqual(['scene:camera:a', 'scene:midpoint:a:b']);
    expect(record.measurement.camera_segments[0].position).toEqual([1, 2, 3]);
    expect(record.measurement.camera_segments[0].frames).toBe(1);
    expect(record.geometry.uploaded_point_count).toBe(123);
    expect(record.geometry.rendered_point_count).toBeUndefined();
    expect(record.renderer.draw_submission_valid).toBe(true);
    expect(record.renderer.render_valid).toBeUndefined();
    output.remove();
    log.mockRestore();
  });
});
