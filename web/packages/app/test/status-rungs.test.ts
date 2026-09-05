// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';
import { buildStatus } from '../src/ui/status.js';

describe('reconstruction rung disclosure', () => {
  it('makes a source-only review obvious and opens the exact inspector collection', () => {
    const inspect = vi.fn();
    const status = buildStatus({ omittedRegionCount: 0, undrawable: new Map(),
      sourceRegions: [{ regionId: 'region-1', captureCount: 40 }],
      reconstructionFocus: { collections: [{ sceneId: 'region-1', sourceCount: 51 }] },
      onInspectSources: inspect,
    });
    const notice = status.querySelector('.reconstruction-availability')!;
    expect(notice.textContent).toContain('No 3D reconstruction is loaded');
    expect(notice.textContent).toContain('51 original photographs');
    expect(notice.textContent).toContain('landscape is authored');
    notice.querySelector('button')!.click();
    expect(inspect).toHaveBeenCalledWith('region-1');
  });

  it('uses the displayed substrate after load failure, preserving the recorded rung', () => {
    const scene = { sceneId: 'scene-1', recordedRung: 3 as const, displayedRung: 4 as const,
      registeredMemberCount: 3, memberCount: 3, renderingSubstrate: 'source_photographs' as const,
      reasons: ['The trained asset could not load.'] };
    const input = { omittedRegionCount: 0, undrawable: new Map(), reconstructionScenes: [scene],
      reconstructionFocus: { collections: [{ sceneId: scene.sceneId, sourceCount: 3 }] } };
    expect(buildStatus(input).querySelector('.reconstruction-availability')).not.toBeNull();
    expect(buildStatus({ ...input, reconstructionScenes: [{ ...scene,
      renderingSubstrate: 'gaussian_splats' }] }).querySelector('.reconstruction-availability')).toBeNull();
    expect(scene.recordedRung).toBe(3);
  });

  it('leaves ordinary world presentation unchanged and never invents missing originals', () => {
    const base = { omittedRegionCount: 0, undrawable: new Map() };
    expect(buildStatus(base).querySelector('.reconstruction-availability')).toBeNull();
    const status = buildStatus({ ...base, reconstructionFocus: { collections: [] } });
    expect(status.textContent).toContain('No source photographs are available');
    expect(status.querySelector('button')).toBeNull();
  });

  it('keeps the recorded gate result separate from the substrate this browser displays', () => {
    const status = buildStatus({
      omittedRegionCount: 0,
      undrawable: new Map(),
      reconstructionScenes: [{
        sceneId: 'scene-1',
        recordedRung: 3,
        displayedRung: 4,
        registeredMemberCount: 2,
        memberCount: 3,
        renderingSubstrate: 'source_photographs',
        reasons: [
          'Rung 2 withheld: no measured corridor receipt is available.',
          'This browser could not load a verified posed map.',
        ],
      }],
    });

    expect(status.querySelector('summary')?.textContent).toBe(
      'Recorded rung 3; showing rung 4 from source photographs.',
    );
    expect(status.querySelector('.reconstruction-rung-copy')?.textContent).toBe(
      'Source first. The photographs are arranged by time and by what they share. No geometry was recovered.',
    );
    expect(status.querySelector('.reconstruction-rung-registration')?.textContent).toBe(
      '2 of 3 photographs registered.',
    );
    expect([...status.querySelectorAll('li')].map((item) => item.textContent)).toEqual([
      'Rung 2 withheld: no measured corridor receipt is available.',
      'This browser could not load a verified posed map.',
    ]);
  });
});
