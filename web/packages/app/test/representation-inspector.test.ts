// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';
import { DEFAULT_REPRESENTATION_INTENT, resolveRepresentation, type RepresentationSubject } from '@exulanica/atlas-core';
import { buildRepresentationInspector } from '../src/ui/representation-inspector.js';

const subject: RepresentationSubject = {
  subjectId: 'geometry-1', subjectKind: 'geometry-group', sceneId: null, frameId: 'district-1',
  origin: 'authored', sourceRefs: ['source-1'], availability: 'available',
  rendered: true, points: 'mesh-vertices', compatibleBlend: true, bounds: null,
  label: 'Buildings', dataAvailable: false, unavailableReason: null,
};
function setup() {
  const binding = {
    representationReport: {
      intent: DEFAULT_REPRESENTATION_INTENT,
      subjects: [{ subject, resolved: resolveRepresentation(DEFAULT_REPRESENTATION_INTENT, subject), allocatedPoints: 4096 }],
    },
    setRepresentationIntent: vi.fn((intent) => {
      binding.representationReport = { ...binding.representationReport, intent };
      return binding.representationReport;
    }),
  };
  const view = buildRepresentationInspector(() => binding);
  view.refresh();
  return { binding, view };
}

describe('world representation inspector', () => {
  it('changes only spatial intent and describes sampled geometry honestly', () => {
    const { binding, view } = setup();
    const range = view.root.querySelector<HTMLInputElement>('input')!;
    expect(range.disabled).toBe(false);
    range.value = '65'; range.dispatchEvent(new Event('input'));
    expect(binding.setRepresentationIntent).toHaveBeenCalledWith({ ...DEFAULT_REPRESENTATION_INTENT, pointMix: .65 });
    expect(view.root.textContent).toContain('Sampled mesh points');
    expect(view.root.textContent).toContain('not separately extracted objects');
    expect(view.root.querySelector('pre')!.textContent).toContain('source-1');
    expect(view.root.querySelector('pre')!.textContent).toContain('4096');
    view.dispose();
  });
  it('removes the selected record after source withdrawal', () => {
    const { binding, view } = setup();
    const withdrawn: RepresentationSubject = { ...subject, availability: 'withdrawn' };
    binding.representationReport.subjects = [{ subject: withdrawn,
      resolved: resolveRepresentation(DEFAULT_REPRESENTATION_INTENT, withdrawn), allocatedPoints: 0 }];
    view.refresh();
    expect(view.root.querySelector('pre')!.textContent).toBe('');
    expect(view.root.querySelector('select')!.options.length).toBe(0);
    expect(view.root.querySelector('input')!.disabled).toBe(true);
    view.dispose();
  });
  it('keeps unsupported views disabled instead of offering an inert slider', () => {
    const { binding, view } = setup();
    const surface: RepresentationSubject = { ...subject, points: null, compatibleBlend: false };
    binding.representationReport.subjects = [{ subject: surface,
      resolved: resolveRepresentation(DEFAULT_REPRESENTATION_INTENT, surface), allocatedPoints: 0 }];
    view.refresh();
    expect(view.root.querySelector('input')!.disabled).toBe(true);
    expect(view.root.textContent).toContain('No switchable surface');
    view.dispose();
  });
});
