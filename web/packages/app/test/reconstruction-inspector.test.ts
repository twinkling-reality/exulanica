// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';
import { buildReconstructionInspector, sourceCaption } from '../src/ui/reconstruction-inspector.js';
import { buildStatus } from '../src/ui/status.js';

describe('reconstruction camera register', () => {
  it('keeps generated identifiers out of photo captions and return above media', () => {
    expect(sourceCaption('Source 01a07221-f387-7611-8425-41acf0ed73e5', 'Photograph 1')).toBe('Photograph 1');
    expect(sourceCaption('Source 01a0722d 8c7b 791e b304 ee9c31019f1c', 'Photograph 2')).toBe('Photograph 2');
    expect(sourceCaption('Volcanic rock', 'Photograph 1')).toBe('Volcanic rock');
    const panel = buildReconstructionInspector({ onView: () => true, onReturn: vi.fn() });
    expect(panel.root.querySelector('header button')!.textContent).toBe('Return to Atlas');
  });
  it('opens original evidence in source-only fallback without pretending to move a recovered camera', () => {
    const onView = vi.fn(() => false);
    const panel = buildReconstructionInspector({ onView, onReturn: vi.fn() });
    const source = { evidenceRef: 'span', title: 'Original', capturedLabel: '',
      url: 'blob:authorized', available: true, accent: '', alt: 'Original photograph' };
    panel.open('scene', [{ id: 'source:span', kind: 'source-only', label: 'Photograph 1', source }]);
    expect(onView).not.toHaveBeenCalled();
    expect(panel.root.querySelector('h2')!.textContent).toBe('Source photographs');
    expect(panel.root.querySelector('img')!.src).toBe('blob:authorized');
    expect(panel.root.querySelector('details')!.open).toBe(true);
    expect(panel.root.textContent).toContain('No reconstructed surface');
  });
  it('opens on the photograph a visitor pressed E on, not always the first', () => {
    const panel = buildReconstructionInspector({ onView: () => true, onReturn: vi.fn() });
    const source = (n: number) => ({ evidenceRef: `span-${n}`, title: `Original ${n}`, capturedLabel: '',
      url: `blob:authorized-${n}`, available: true, accent: '', alt: 'Original photograph' });
    const choices = [1, 2, 3].map((n) => ({ id: `source:span-${n}`, kind: 'source-only' as const,
      label: `Photograph ${n}`, source: source(n), captureId: `capture-${n}` }));
    panel.open('scene', choices, 1);
    expect(panel.selected?.captureId).toBe('capture-2');
    expect(panel.root.querySelector('img')!.src).toBe('blob:authorized-2');
    panel.open('scene', choices, 9);
    expect(panel.selected?.captureId).toBe('capture-3');
  });
  it('connects stable cameras to authorized originals and labels unobserved midpoints honestly', () => {
    const onView = vi.fn(() => true);
    const onReturn = vi.fn();
    const panel = buildReconstructionInspector({ onView, onReturn });
    document.body.append(panel.root);
    const source = {
      evidenceRef: 'evidence', title: 'Licensed photograph', capturedLabel: '2026',
      url: 'blob:authorized-source', available: true, accent: '#123456', alt: 'Original source',
    };
    expect(panel.open('scene', [
      { id: 'scene:camera:a', kind: 'source-camera', label: 'Source camera 1', source },
      { id: 'scene:midpoint:a:b', kind: 'between-cameras', label: 'Between cameras 1 and 2', source: null },
    ])).toBe(true);
    expect(onView).toHaveBeenLastCalledWith('scene', 'scene:camera:a');
    expect(panel.root.querySelector('img')!.src).toBe(source.url);
    const buttons = panel.root.querySelectorAll('button');
    [...buttons].find((button) => button.textContent === 'Next view')!.click();
    expect(onView).toHaveBeenLastCalledWith('scene', 'scene:midpoint:a:b');
    expect(panel.root.textContent).toContain('unobserved viewpoint');
    expect(panel.root.querySelector('img')).toBeNull();
    panel.root.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(onReturn).toHaveBeenCalledOnce();
    expect(panel.root.hidden).toBe(true);
    panel.root.remove();
  });

  it('makes unavailable cameras actionable without manufacturing source media', () => {
    const panel = buildReconstructionInspector({ onView: () => false, onReturn: vi.fn() });
    expect(panel.open('missing', [])).toBe(false);
    panel.open('scene', [{ id: 'missing', kind: 'source-camera', label: 'Source camera 1', source: null }]);
    expect(panel.root.textContent).toContain('This view is unavailable');
    expect(panel.root.querySelector('img')).toBeNull();
    expect(panel.root.textContent).toContain('Return to Atlas');
  });

  it('offers inspection only when this session loaded reconstruction', () => {
    const onInspectScene = vi.fn();
    const common = {
      sceneId: 'scene', recordedRung: 3 as const, displayedRung: 4 as const,
      registeredMemberCount: 2, memberCount: 3, reasons: ['alignment-unavailable'],
    };
    const missing = buildStatus({ omittedRegionCount: 0, undrawable: new Map(), onInspectScene,
      reconstructionScenes: [{ ...common, renderingSubstrate: 'source_photographs' }] });
    expect(missing.querySelector('button')).toBeNull();
    const available = buildStatus({ omittedRegionCount: 0, undrawable: new Map(), onInspectScene,
      reconstructionScenes: [{ ...common, displayedRung: 3, renderingSubstrate: 'posed_point_maps' }] });
    available.querySelector('button')!.click();
    expect(onInspectScene).toHaveBeenCalledWith('scene');
  });

  it('keeps a live source group inspectable before any reconstruction scene exists', () => {
    const onInspectSources = vi.fn();
    const status = buildStatus({ omittedRegionCount: 0, undrawable: new Map(),
      sourceRegions: [{ regionId: 'photo-group', captureCount: 7 }], onInspectSources });
    expect(status.textContent).toContain('7 grouped photographs');
    expect(status.textContent).not.toContain('Recorded rung');
    status.querySelector('button')!.click();
    expect(onInspectSources).toHaveBeenCalledWith('photo-group');
  });
});
