// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';
import { buildStatus, type ReconstructionRungDisclosure } from '../src/ui/status.js';

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

  it('states the measured held-out appearance and accounting beside a trained substrate', () => {
    const quality = { heldoutViews: 7, psnr: 24.1234, ssim: 0.8123, lpips: 0.2104, coverageFraction: 0.931,
      floatersFraction: 0.0213, iterationsCompleted: 30000, durationSeconds: 3312, usdCost: 0.9, gpu: 'NVIDIA L40S' };
    const scene = { sceneId: 'scene-1', recordedRung: 3 as const, displayedRung: 3 as const,
      registeredMemberCount: 51, memberCount: 51, renderingSubstrate: 'gaussian_splats' as const, reasons: [],
      trainingQuality: quality };
    const status = buildStatus({ omittedRegionCount: 0, undrawable: new Map(), reconstructionScenes: [scene] });
    const lines = [...status.querySelectorAll('.reconstruction-rung-quality')].map((p) => p.textContent);
    expect(lines).toHaveLength(2);
    expect(lines[0]).toContain('7 photographs: PSNR 24.12 dB, SSIM 0.812, LPIPS 0.210; coverage 0.931, floater proxy 0.021');
    expect(lines[0]).toContain('appearance only');
    expect(lines[1]).toBe('Trained 30,000 iterations in 55.2 min on NVIDIA L40S for $0.90 at the declared rate.');
    // Falling back to point maps or sources hides numbers that describe geometry not on screen.
    const fallen = buildStatus({ omittedRegionCount: 0, undrawable: new Map(),
      reconstructionScenes: [{ ...scene, renderingSubstrate: 'posed_point_maps' as const }] });
    expect(fallen.querySelector('.reconstruction-rung-quality')).toBeNull();
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

describe('the proof lens in the status panel', () => {
  const base = {
    sceneId: 'scene-proof',
    recordedRung: 3 as const,
    displayedRung: 3 as const,
    registeredMemberCount: 3,
    memberCount: 3,
    reasons: [],
  };

  function tierLine(scene: ReconstructionRungDisclosure): HTMLElement {
    const bar = buildStatus({
      omittedRegionCount: 0,
      undrawable: new Map(),
      reconstructionScenes: [scene],
    });
    const line = bar.querySelector<HTMLElement>('.reconstruction-proof-tier');
    if (line === null) throw new Error('the panel drew no proof tier line');
    return line;
  }

  it('calls a drawn reconstruction reconstructed, and says it is not evidence', () => {
    const line = tierLine({ ...base, renderingSubstrate: 'posed_point_maps' });
    expect(line.dataset.proofTier).toBe('reconstructed');
    expect(line.textContent).toContain('Reconstructed from photographs');
    expect(line.textContent).toContain('not itself evidence');
  });

  it('calls a source-first region photographed', () => {
    const line = tierLine({ ...base, renderingSubstrate: 'source_photographs' });
    expect(line.dataset.proofTier).toBe('photographed');
    expect(line.textContent).toContain('Photographed');
  });

  it('says a scene its region does not draw is showing nothing', () => {
    // Not a shade of reconstructed. A region whose area displays a more complete scene of the
    // same photographs is showing the visitor nothing about the world.
    const line = tierLine({ ...base, renderingSubstrate: 'gaussian_splats', drawn: false });
    expect(line.dataset.proofTier).toBe('unavailable');
    expect(line.textContent).toContain('Not shown');
  });

  it('says generated, and says it carries no rung, whenever a model surface is in view', () => {
    const line = tierLine({
      ...base,
      renderingSubstrate: 'gaussian_splats',
      showingGenerated: true,
    });
    expect(line.dataset.proofTier).toBe('generated');
    expect(line.textContent).toContain('Generated by a model');
    expect(line.textContent).toContain('no reconstruction rung');
  });

  it('defaults to drawn and not generated, so an existing caller keeps its meaning', () => {
    const line = tierLine({ ...base, renderingSubstrate: 'gaussian_splats' });
    expect(line.dataset.proofTier).toBe('reconstructed');
  });
});
