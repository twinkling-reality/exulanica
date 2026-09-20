// @vitest-environment happy-dom
import { readFileSync } from 'node:fs';
import { describe, expect, it, vi } from 'vitest';
import {
  DATA_VIEW_STYLE,
  DEFAULT_REPRESENTATION_INTENT,
  districtRepresentationSubjects,
  parseOwnedDistrict,
  resolveRepresentation,
  type RepresentationIntent,
  type RepresentationSubject,
} from '@exulanica/atlas-core';
import { buildRepresentationInspector } from '../src/ui/representation-inspector.js';

const subject: RepresentationSubject = {
  subjectId: 'geometry-1', subjectKind: 'geometry-group', sceneId: null, frameId: 'district-1',
  origin: 'authored', sourceRefs: ['source-1'], availability: 'available',
  rendered: true, points: 'mesh-vertices', compatibleBlend: true, bounds: null,
  label: 'Buildings', dataAvailable: false, unavailableReason: null,
};
const scene: RepresentationSubject = {
  ...subject, subjectId: 'scene-1', subjectKind: 'scene', sceneId: 'scene:1', origin: 'inferred',
  points: 'retained-points', blend: 'overlay', label: null,
  frameId: 'artifact:scene-1', bounds: { frameId: 'artifact:scene-1', units: 'metres', origin: 'inferred',
    basis: 'source-bounds', min: [0, 0, 0], max: [1, 1, 1] },
};

function entries(intent: RepresentationIntent, subjects: readonly RepresentationSubject[]) {
  return subjects.map(item => ({ subject: item, resolved: resolveRepresentation(intent, item),
    allocatedPoints: item.points === null ? 0 : 4096, plannedPoints: item.points === null ? 0 : 5000 }));
}

function setup(
  subjects: readonly RepresentationSubject[] = [subject],
  initialSelection: string | null = subjects[0]?.subjectId ?? null,
) {
  const binding = {
    representationReport: {
      intent: DEFAULT_REPRESENTATION_INTENT,
      subjects: entries(DEFAULT_REPRESENTATION_INTENT, subjects),
      allocatedPoints: 4096, pointBudget: 1_048_576, pendingSubjects: 0,
      selection: initialSelection,
      style: { id: DATA_VIEW_STYLE.id, version: DATA_VIEW_STYLE.version },
    },
    representationOverlayPlan: { refusals: [{ subjectId: 'geometry-1', overlay: 'box', reason: 'No bounds of its own.' }] },
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
  const view = buildRepresentationInspector(() => binding);
  view.refresh();
  return { binding, view };
}

const toggles = (root: HTMLElement) => [...root.querySelectorAll<HTMLInputElement>('.representation-toggle input')];
const search = (root: HTMLElement, query: string) => {
  const input = root.querySelector<HTMLInputElement>('input[type=search]')!;
  input.value = query;
  input.dispatchEvent(new Event('input'));
  return input;
};

describe('world representation inspector', () => {
  it('changes only spatial intent and describes sampled geometry honestly', () => {
    const { binding, view } = setup();
    const range = view.root.querySelector<HTMLInputElement>('input[type=range]')!;
    expect(range.disabled).toBe(false);
    range.value = '65'; range.dispatchEvent(new Event('input'));
    expect(binding.setRepresentationIntent).toHaveBeenCalledWith({ ...DEFAULT_REPRESENTATION_INTENT, pointMix: .65 });
    expect(view.root.textContent).toContain('Sampled mesh points');
    expect(view.root.textContent).toContain('not separately extracted objects');
    expect(view.root.textContent).toContain('4,096 points prepared of a 1,048,576 point budget.');
    expect(view.root.querySelector('pre')!.textContent).toContain('source-1');
    expect(view.root.querySelector('pre')!.textContent).toContain('4096');
    view.dispose();
  });

  it('turns boxes, ids, labels, colour and the visualization look on and off through intent alone', () => {
    const { binding, view } = setup();
    const [boxes, ids, labels, visualization] = toggles(view.root);
    for (const input of [boxes!, ids!, labels!, visualization!]) expect(input.disabled).toBe(false);
    boxes!.checked = true; boxes!.dispatchEvent(new Event('change'));
    ids!.checked = true; ids!.dispatchEvent(new Event('change'));
    labels!.checked = true; labels!.dispatchEvent(new Event('change'));
    visualization!.checked = true; visualization!.dispatchEvent(new Event('change'));
    const colour = view.root.querySelector<HTMLSelectElement>('select[aria-label="Colour points by"]')!;
    colour.value = 'kind'; colour.dispatchEvent(new Event('change'));
    expect(binding.setRepresentationIntent).toHaveBeenLastCalledWith({
      ...DEFAULT_REPRESENTATION_INTENT, boxes: true, ids: true, labels: true, binary: 'visualization', colour: 'kind',
    });
    const record = JSON.parse(view.root.querySelector('pre')!.textContent!);
    expect(record.look).toMatchObject({ style: 'exulanica.data-view@2', colour_by: 'kind',
      colour_key: 'geometry-group', treatment: 'visualization' });
    expect(record.look.presentation).toContain('encode no artifact bytes');
    expect(record.visualization).toMatchObject({ label: 'Generated binary visualization, not artifact bytes' });
    expect(record.overlays).toEqual({ box: false, id_tag: false, label_tag: false });
    expect(view.root.querySelector('.representation-description')!.textContent)
      .toContain('No box: No bounds of its own.');
    ids!.checked = false; ids!.dispatchEvent(new Event('change'));
    expect(binding.representationReport.intent.ids).toBe(false);
    view.dispose();
  });

  it('shows the style version and a legend of only the colour keys present', () => {
    const { binding, view } = setup([subject, scene]);
    expect(view.root.querySelector('.representation-style')!.textContent)
      .toContain('Look exulanica.data-view, version 2.');
    const legend = () => [...view.root.querySelectorAll('.representation-legend li')].map(item => item.textContent);
    expect(legend()).toEqual(['Authored', 'Inferred']);
    binding.setRepresentationIntent({ ...DEFAULT_REPRESENTATION_INTENT, colour: 'kind' });
    view.refresh();
    expect(legend()).toEqual(['Grouped geometry', 'Scene']);
    view.dispose();
  });

  it('names a city record kind in plain words in the legend', () => {
    const street: RepresentationSubject = { ...subject, subjectId: 'generated:city.street_segment:3afeee23-e3b3-5cbb-8654-ed114473327c',
      subjectKind: 'object', origin: 'generated',
      record: { kind: 'city.street_segment', version: 2, identity: '3afeee23-e3b3-5cbb-8654-ed114473327c', key: '' } };
    const { binding, view } = setup([street]);
    binding.setRepresentationIntent({ ...DEFAULT_REPRESENTATION_INTENT, colour: 'kind' });
    view.refresh();
    expect([...view.root.querySelectorAll('.representation-legend li')].map(item => item.textContent)).toEqual(['Street segment']);
    view.dispose();
  });

  it('leaves a subject hidden by residency out of the legend', () => {
    const { binding, view } = setup([subject, scene]);
    const legend = () => [...view.root.querySelectorAll('.representation-legend li')].map(item => item.textContent);
    binding.representationReport = { ...binding.representationReport, subjects: binding.representationReport.subjects
      .map(item => item.subject.subjectId === 'scene-1'
        ? { ...item, resolved: resolveRepresentation(DEFAULT_REPRESENTATION_INTENT, item.subject, false) } : item) };
    view.refresh();
    expect(legend()).toEqual(['Authored']);
    view.dispose();
  });

  it('selects only on an explicit list choice and preserves that selection when the panel closes', () => {
    const { binding, view } = setup([subject, scene], null);
    view.root.open = true;
    view.root.dispatchEvent(new Event('toggle'));
    expect(binding.setRepresentationSelection).not.toHaveBeenCalled();
    const list = view.root.querySelector<HTMLSelectElement>('select[aria-label="Inspect a displayed geometry group"]')!;
    expect(list.value).toBe('');
    expect(list.options[0]!.textContent).toBe('No subject selected');
    list.value = 'geometry-1'; list.dispatchEvent(new Event('change'));
    expect(binding.setRepresentationSelection).toHaveBeenLastCalledWith('geometry-1');
    list.value = 'scene-1'; list.dispatchEvent(new Event('change'));
    expect(binding.setRepresentationSelection).toHaveBeenLastCalledWith('scene-1');
    expect(JSON.parse(view.root.querySelector('pre')!.textContent!).blend).toBe('overlay');
    expect(view.root.querySelector('.representation-description')!.textContent)
      .toContain('Points appear over its own look');
    view.root.open = false;
    view.root.dispatchEvent(new Event('toggle'));
    expect(binding.representationReport.selection).toBe('scene-1');
    expect(binding.setRepresentationSelection).not.toHaveBeenCalledWith(null);
    view.dispose();
  });

  it('reflects a scene selection without treating it as a new explicit list choice', () => {
    const { binding, view } = setup([subject, scene]);
    binding.setRepresentationSelection('scene-1');
    view.refresh();
    const list = view.root.querySelector<HTMLSelectElement>('select[aria-label="Inspect a displayed geometry group"]')!;
    expect(list.value).toBe('scene-1');
    view.dispose();
  });

  it('searches the full retained district by name, identity, kind and origin without selecting', () => {
    const district = parseOwnedDistrict(JSON.parse(readFileSync(
      `${process.cwd()}/../assets/owned-world/flatiron/flatiron-owned-district.json`, 'utf8',
    )));
    const retained = districtRepresentationSubjects(district);
    expect(retained).toHaveLength(400);
    const { binding, view } = setup(retained, null);
    const list = view.root.querySelector<HTMLSelectElement>('select[aria-label="Inspect a displayed geometry group"]')!;

    const input = search(view.root, 'Flatiron Building');
    expect(input.closest('label')?.textContent).toContain('Search displayed subjects');
    expect(view.root.querySelector('.representation-search-status')!.textContent)
      .toBe('1 of 400 subjects match “Flatiron Building”.');
    expect([...list.options].map(option => option.textContent))
      .toEqual(['No subject selected', 'Flatiron Building']);
    expect(binding.setRepresentationSelection).not.toHaveBeenCalled();

    search(view.root, 'doitt_id:507159');
    expect(list.options[1]!.value).toBe('doitt_id:507159');
    expect(binding.setRepresentationSelection).not.toHaveBeenCalled();

    search(view.root, 'external object');
    expect(view.root.querySelector('.representation-search-status')!.textContent)
      .toBe('400 of 400 subjects match “external object”.');
    expect(list.options).toHaveLength(401);
    view.dispose();
  });

  it('keeps an existing selection inspectable outside matches and never searches source references', () => {
    const { binding, view } = setup([subject, scene], 'scene-1');
    const list = view.root.querySelector<HTMLSelectElement>('select[aria-label="Inspect a displayed geometry group"]')!;
    const before = binding.setRepresentationSelection.mock.calls.length;

    search(view.root, 'Buildings');
    expect(binding.setRepresentationSelection).toHaveBeenCalledTimes(before);
    expect(binding.representationReport.selection).toBe('scene-1');
    expect(list.value).toBe('scene-1');
    expect(list.options[1]!.textContent).toBe('scene-1 (selected, outside search)');
    expect(view.root.querySelector('.representation-search-status')!.textContent)
      .toContain('1 of 2 subjects match “Buildings”. The selected subject remains inspectable outside this filter');
    expect(JSON.parse(view.root.querySelector('pre')!.textContent!).id).toBe('scene-1');

    search(view.root, 'source-1');
    expect(view.root.querySelector('.representation-search-status')!.textContent)
      .toContain('No subjects match “source-1”. The selected subject remains inspectable outside this filter');
    expect(binding.representationReport.selection).toBe('scene-1');

    search(view.root, '');
    view.root.open = true; view.root.dispatchEvent(new Event('toggle'));
    view.root.open = false; view.root.dispatchEvent(new Event('toggle'));
    expect(binding.setRepresentationSelection).toHaveBeenCalledTimes(before);
    expect(binding.representationReport.selection).toBe('scene-1');
    view.dispose();
  });

  it('does not resurrect a withdrawn selection while a filter is active', () => {
    const { binding, view } = setup([subject, scene], 'geometry-1');
    search(view.root, 'Buildings');
    const before = binding.setRepresentationSelection.mock.calls.length;
    const withdrawn = { ...subject, availability: 'withdrawn' as const };
    binding.representationReport = {
      ...binding.representationReport,
      selection: null,
      subjects: [
        { subject: withdrawn, resolved: resolveRepresentation(DEFAULT_REPRESENTATION_INTENT, withdrawn),
          allocatedPoints: 0, plannedPoints: 0 },
        binding.representationReport.subjects[1]!,
      ],
    };
    view.refresh();

    const list = view.root.querySelector<HTMLSelectElement>('select[aria-label="Inspect a displayed geometry group"]')!;
    expect(binding.setRepresentationSelection).toHaveBeenCalledTimes(before);
    expect(binding.representationReport.selection).toBeNull();
    expect(list.value).toBe('');
    expect(list.options[1]!.textContent).toBe('Buildings (unavailable)');
    expect(list.options[1]!.disabled).toBe(true);
    expect(view.root.querySelector('pre')!.textContent).toBe('');

    search(view.root, '');
    view.root.open = true; view.root.dispatchEvent(new Event('toggle'));
    expect(binding.representationReport.selection).toBeNull();
    expect(binding.setRepresentationSelection).toHaveBeenCalledTimes(before);
    view.dispose();
  });

  it('removes the selected record after source withdrawal', () => {
    const { binding, view } = setup();
    const withdrawn: RepresentationSubject = { ...subject, availability: 'withdrawn' };
    binding.representationReport.subjects = [{ subject: withdrawn,
      resolved: resolveRepresentation(DEFAULT_REPRESENTATION_INTENT, withdrawn), allocatedPoints: 0, plannedPoints: 0 }];
    view.refresh();
    expect(view.root.querySelector('pre')!.textContent).toBe('');
    const list = view.root.querySelector<HTMLSelectElement>('select[aria-label="Inspect a displayed geometry group"]')!;
    expect(list.options).toHaveLength(2);
    expect(list.options[1]!.textContent).toBe('Buildings (unavailable)');
    expect(list.options[1]!.disabled).toBe(true);
    expect(view.root.querySelector<HTMLInputElement>('input[type=range]')!.disabled).toBe(true);
    for (const input of toggles(view.root)) expect(input.disabled).toBe(true);
    expect(view.root.querySelectorAll('.representation-legend li')).toHaveLength(0);
    view.dispose();
  });

  it('refuses a stale list choice without throwing and clears the previous selection', () => {
    const { binding, view } = setup([subject, scene], 'scene-1');
    const list = view.root.querySelector<HTMLSelectElement>('select[aria-label="Inspect a displayed geometry group"]')!;
    const withdrawn = { ...subject, availability: 'withdrawn' as const };
    binding.representationReport.subjects = [
      { subject: withdrawn, resolved: resolveRepresentation(DEFAULT_REPRESENTATION_INTENT, withdrawn),
        allocatedPoints: 0, plannedPoints: 0 },
      binding.representationReport.subjects[1]!,
    ];
    binding.setRepresentationSelection.mockImplementation((id: string | null) => {
      const selected = binding.representationReport.subjects
        .find(item => item.subject.subjectId === id)?.subject;
      if (selected !== undefined && selected.availability !== 'available') {
        throw new TypeError(`Unavailable representation subject ${id}`);
      }
      binding.representationReport = { ...binding.representationReport, selection: id };
      return binding.representationReport;
    });

    // The inventory changed between refreshes, so the still-enabled option is a real UI race.
    list.value = 'geometry-1';
    expect(() => list.dispatchEvent(new Event('change'))).not.toThrow();

    expect(binding.setRepresentationSelection).toHaveBeenNthCalledWith(1, 'geometry-1');
    expect(binding.setRepresentationSelection).toHaveBeenNthCalledWith(2, null);
    expect(binding.representationReport.selection).toBeNull();
    expect(list.value).toBe('');
    expect(list.options[1]!.textContent).toBe('Buildings (unavailable)');
    expect(list.options[1]!.disabled).toBe(true);
    expect(view.root.querySelector('[role=status]')!.textContent)
      .toContain('That subject is no longer available. No subject is selected.');
    view.dispose();
  });

  it('keeps unsupported views disabled instead of offering an inert slider', () => {
    const { binding, view } = setup();
    const surface: RepresentationSubject = { ...subject, points: null, compatibleBlend: false };
    binding.representationReport.subjects = [{ subject: surface,
      resolved: resolveRepresentation(DEFAULT_REPRESENTATION_INTENT, surface), allocatedPoints: 0, plannedPoints: 0 }];
    view.refresh();
    expect(view.root.querySelector<HTMLInputElement>('input[type=range]')!.disabled).toBe(true);
    expect(view.root.textContent).toContain('No switchable surface');
    expect(view.root.querySelector('.representation-description')!.textContent)
      .toContain('Surface only');
    view.dispose();
  });

  it('states the missing isolated point form even at the rendered endpoint', () => {
    const metadata: RepresentationSubject = {
      ...subject, subjectId: 'doitt_id:2327', subjectKind: 'object', origin: 'external',
      points: null, compatibleBlend: false,
      bounds: { frameId: 'district-1', units: 'metres', origin: 'external', basis: 'source-bounds',
        min: [0, 0, 0], max: [1, 2, 3] },
      label: 'Source building',
      unavailableReason: 'Building geometry shares an aggregate district draw; no per-feature point buffer.',
    };
    const { binding, view } = setup([metadata]);
    binding.setRepresentationSelection(metadata.subjectId);
    view.refresh();
    expect(view.root.querySelector('.representation-description')!.textContent)
      .toContain('no per-feature point buffer');
    expect(JSON.parse(view.root.querySelector('pre')!.textContent!).displayed_points).toBe(0);
    view.dispose();
  });
});
