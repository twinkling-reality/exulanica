// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';
import {
  DEFAULT_REPRESENTATION_INTENT,
  resolveRepresentation,
  type RepresentationIntent,
  type RepresentationSubject,
} from '@exulanica/atlas-core';
import {
  representationAvailabilityLines,
  representationAvailabilitySentence,
  starterGroundAvailabilityLines,
} from '../src/ui/representation-availability.js';
import { placedCatalogObjectSubject } from '@exulanica/atlas-react/playcanvas';
import { buildRepresentationInspector } from '../src/ui/representation-inspector.js';

const subject: RepresentationSubject = {
  subjectId: 'geometry-1', subjectKind: 'geometry-group', sceneId: null, frameId: 'district-1',
  origin: 'authored', sourceRefs: ['source-1'], availability: 'available',
  rendered: true, points: 'mesh-vertices', compatibleBlend: true, bounds: null,
  label: 'Buildings', dataAvailable: false, unavailableReason: null,
};

function entries(intent: RepresentationIntent, subjects: readonly RepresentationSubject[]) {
  return subjects.map(item => ({ subject: item, resolved: resolveRepresentation(intent, item),
    allocatedPoints: item.points === null ? 0 : 4096, plannedPoints: item.points === null ? 0 : 5000 }));
}

function setup(
  subjects: readonly RepresentationSubject[] = [subject],
  initialSelection: string | null = subjects[0]?.subjectId ?? null,
  starterGround: (() => { readonly renderedInView: boolean } | null) | undefined = undefined,
) {
  const binding = {
    representationReport: {
      intent: DEFAULT_REPRESENTATION_INTENT,
      subjects: entries(DEFAULT_REPRESENTATION_INTENT, subjects),
      allocatedPoints: 4096, pointBudget: 1_048_576, pendingSubjects: 0,
      selection: initialSelection,
      style: { id: 'exulanica.data-view', version: 2 },
    },
    setRepresentationIntent: vi.fn((intent: RepresentationIntent) => {
      binding.representationReport = { ...binding.representationReport, intent,
        subjects: entries(intent, binding.representationReport.subjects.map(item => item.subject)) };
      return binding.representationReport;
    }),
    setRepresentationSelection: vi.fn((id: string | null) => {
      binding.representationReport = { ...binding.representationReport, selection: id };
      return binding.representationReport;
    }),
  };
  const view = buildRepresentationInspector(() => binding, starterGround === undefined
    ? {}
    : { starterGround });
  view.refresh();
  return { binding, view };
}

function availabilityStates(root: HTMLElement): Record<string, string> {
  return Object.fromEntries([...root.querySelectorAll<HTMLLIElement>('.representation-availability li')]
    .map(item => [item.dataset['kind'] ?? '', item.dataset['state'] ?? '']));
}

describe('representation availability lines', () => {
  it('marks rendered and point available, and semantic provenance artifact honestly for a surface subject', () => {
    const lines = representationAvailabilityLines(subject);
    expect(Object.fromEntries(lines.map(item => [item.kind, item.state]))).toEqual({
      rendered: 'available',
      point: 'available',
      semantic: 'unavailable',
      provenance: 'available',
      artifact: 'unavailable',
    });
    expect(representationAvailabilitySentence(lines.find(item => item.kind === 'point')!))
      .toContain('Sampled mesh points are available.');
    expect(representationAvailabilitySentence(lines.find(item => item.kind === 'artifact')!))
      .toContain('unavailable');
  });

  it('reports a placed catalog object as a display record and a reviewed-asset identity only', () => {
    // Built by the renderer's own registration for an object placed from the reviewed catalog.
    const placed = placedCatalogObjectSubject({
      objectId: 'object-1-1',
      islandId: 'region:starter' as never,
      asset: {
        assetKey: 'cc0.marker-cube', mediaType: 'model/gltf-binary',
        contentSha256: 'b'.repeat(64), byteSize: 784,
      },
      transform: { xMm: 0, yMm: 0, zMm: -3500, yawMicroradians: 0, scaleMilli: 1000 },
      behaviour: null,
    }, { min: [-0.25, 0, -0.25], max: [0.25, 0.5, 0.25] });
    const lines = representationAvailabilityLines(placed);
    expect(Object.fromEntries(lines.map(item => [item.kind, item.state]))).toEqual({
      rendered: 'available',
      point: 'available',
      semantic: 'unavailable',
      provenance: 'available',
      artifact: 'unavailable',
    });
    const semantic = lines.find(item => item.kind === 'semantic')!.detail;
    expect(semantic).toContain('display record only');
    expect(semantic).not.toContain('Structured source records are available');
    const provenance = lines.find(item => item.kind === 'provenance')!.detail;
    expect(provenance).toContain('Reviewed catalog asset cc0.marker-cube');
    expect(provenance).toContain('bbbbbbbbbbbb');
    expect(provenance).not.toContain('source reference');
  });

  it('keeps point semantic provenance and artifact unavailable for empty starter ground with rendered view', () => {
    const lines = starterGroundAvailabilityLines(true);
    expect(Object.fromEntries(lines.map(item => [item.kind, item.state]))).toEqual({
      rendered: 'available',
      point: 'unavailable',
      semantic: 'unavailable',
      provenance: 'unavailable',
      artifact: 'unavailable',
    });
    expect(lines.find(item => item.kind === 'rendered')!.detail)
      .toContain('Authored starter ground is drawn');
    expect(starterGroundAvailabilityLines(false).find(item => item.kind === 'rendered')!.state)
      .toBe('unavailable');
  });

  it('lists availability for the selected subject in the inspector', () => {
    const { view } = setup();
    expect(availabilityStates(view.root)).toEqual({
      rendered: 'available',
      point: 'available',
      semantic: 'unavailable',
      provenance: 'available',
      artifact: 'unavailable',
    });
    expect(view.root.querySelector('.representation-availability li[data-kind="semantic"]')!.textContent)
      .toContain('unavailable');
    view.dispose();
  });

  it('lists starter ground availability when that is the current subject and nothing is selected', () => {
    const { view } = setup([], null, () => ({ renderedInView: true }));
    expect(availabilityStates(view.root)).toEqual({
      rendered: 'available',
      point: 'unavailable',
      semantic: 'unavailable',
      provenance: 'unavailable',
      artifact: 'unavailable',
    });
    expect(view.root.querySelector('.representation-availability li[data-kind="point"]')!.textContent)
      .toContain('no point representation');
    view.dispose();
  });

  it('does not invent starter availability when the world is not an authored starter', () => {
    const { view } = setup([], null, () => null);
    expect(view.root.querySelector<HTMLElement>('.representation-availability')!.hidden).toBe(true);
    expect(view.root.querySelectorAll('.representation-availability li')).toHaveLength(0);
    view.dispose();
  });
});
