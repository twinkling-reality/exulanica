// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { adaptSnapshot } from '@exulanica/graph-client';
import { admittedSourceChoices, mountStatusAndInspector } from '../src/composition/status-and-inspector.js';
import { buildReconstructionInspector } from '../src/ui/reconstruction-inspector.js';
import { buildStatus } from '../src/ui/status.js';
import { createSessionState, type AppEnvironment } from '../src/composition/session-state.js';

afterEach(() => vi.unstubAllGlobals());

const snapshot = adaptSnapshot({ state_version: 1, entities: [], occurrences: [], proposals: [],
  scene_groups: [], reconstruction_scenes: [], never_same: [], deleted_entity_ids: [],
  review_sources: [{ kind: 'admitted_capture', capture_id: 'actual-capture', evidence_span_id: 'actual-span',
    captured_at: null, media_type: 'image/jpeg', state: 'available', reason: null,
    evidence_path: '/evidence/actual-span/masked', content_sha256: 'a'.repeat(64),
    person_review_state: 'screened', person_regions: [{ region_id: 'actual-region', state: 'unknown',
      silhouette_ppm: [[0, 0], [100, 0], [0, 100]], display_name: null, subject_id: null }],
  }] });

describe('review without scene or island', () => {
  it('opens the actual capture and person regions from the admitted source action', () => {
    const media = new Map([['actual-span', { evidenceRef: 'actual-span', title: 'Photograph', capturedLabel: '',
      available: true, url: 'blob:authorized', accent: '', alt: 'Authorized photograph' }]]);
    const onView = vi.fn();
    const onViewShown = vi.fn();
    const panel = buildReconstructionInspector({ onView, onViewShown, onReturn: vi.fn() });
    const choices = admittedSourceChoices(snapshot, media);
    const status = buildStatus({ omittedRegionCount: 0, undrawable: new Map(),
      reconstructionScenes: [], sourceRegions: [], reconstructionFocus: { collections: [] },
      admittedSourceCount: snapshot.reviewSources!.length,
      onInspectAdmittedSources: () => { panel.open('admitted-captures', choices); },
    });
    status.querySelector('button')!.click();
    expect(panel.root.hidden).toBe(false);
    expect(panel.root.querySelector('img')?.src).toBe('blob:authorized');
    expect(onView).not.toHaveBeenCalled();
    expect(onViewShown).toHaveBeenCalledWith('admitted-captures', expect.objectContaining({
      captureId: 'actual-capture', personReviewState: 'screened', personRegions: [{
        regionId: 'actual-region', state: 'unknown', silhouettePpm: [[0, 0], [100, 0], [0, 100]],
        displayName: null, subjectId: null,
      }],
    }));
    expect(panel.root.dataset.sceneId).toBeUndefined();
    expect(panel.root.dataset.captureId).toBe('actual-capture');
    expect(status.textContent).not.toContain('No source photographs are available');
    expect(status.textContent).not.toContain('Recorded rung');
  });
  it('keeps review identity when viewer bytes are missing and has no source fallback for old payloads', () => {
    const choices = admittedSourceChoices(snapshot, new Map());
    expect(choices[0]).toMatchObject({ source: null, captureId: 'actual-capture' });
    const { reviewSources: _sources, ...oldSnapshot } = snapshot;
    expect(admittedSourceChoices(oldSnapshot, new Map())).toEqual([]);
  });
});

describe('mounted admitted capture review', () => {
  it('loads current person review for the actual capture and ignores a response after disposal', async () => {
    let complete!: (response: Response) => void;
    const fetch = vi.fn(() => new Promise<Response>((resolve) => { complete = resolve; }));
    vi.stubGlobal('fetch', fetch);
    const state = createSessionState();
    state.credentials = { baseUrl: 'https://review.test', token: 'current-session' };
    state.previewSourceMedia = new Map([['actual-span', { evidenceRef: 'actual-span',
      captureIds: ['actual-capture'], title: 'Photograph', capturedLabel: '',
      available: true, url: 'blob:authorized', accent: '', alt: 'Authorized photograph' }]]);
    const env: AppEnvironment = {
      shell: document.createElement('div'), canvas: document.createElement('canvas'),
      systemAppearance: window.matchMedia('(prefers-color-scheme: dark)'),
      systemReducedMotion: window.matchMedia('(prefers-reduced-motion: reduce)'),
      browserMeasurement: null, preview: false, previewArtProfile: undefined,
    };
    const mounted = mountStatusAndInspector({ env, state, snapshot,
      built: { omitted: [], undrawable: new Map() }, showWorld: vi.fn(), showTravelStatus: vi.fn() });
    mounted.statusElement.querySelector('button')!.click();
    expect(state.reviewCaptureId).toBe('actual-capture');
    expect(fetch).toHaveBeenCalledWith('https://review.test/person-regions/actual-capture',
      expect.objectContaining({ headers: expect.objectContaining({ authorization: 'Bearer current-session' }) }));
    mounted.dispose();
    complete(new Response(JSON.stringify({ capture_id: 'actual-capture', review_state: 'screened', regions: [] }),
      { headers: { 'content-type': 'application/json' } }));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(state.reviewCaptureId).toBeNull();
    expect(mounted.inspectorRoot.hidden).toBe(true);
    expect(mounted.inspectorRoot.querySelector('.reconstruction-review')!.childElementCount).toBe(0);
  });
});
