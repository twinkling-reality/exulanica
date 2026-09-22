import {
  DATA_VIEW_STYLE,
  dataViewKindColour,
  representationBinaryVisualization,
  type RepresentationIntent,
  type RepresentationResolution,
  type RepresentationSubject,
} from '@exulanica/atlas-core';
import { el } from './dom.js';
import {
  representationAvailabilityLines,
  representationAvailabilitySentence,
  starterGroundAvailabilityLines,
  type RepresentationAvailabilityLine,
} from './representation-availability.js';
import './representation-inspector.css';

interface Entry {
  readonly subject: RepresentationSubject;
  readonly resolved: RepresentationResolution;
  readonly allocatedPoints?: number;
  readonly plannedPoints?: number;
}
interface Report {
  readonly intent: RepresentationIntent;
  readonly subjects: readonly Entry[];
  readonly allocatedPoints?: number;
  readonly pointBudget?: number;
  readonly pendingSubjects?: number;
  readonly selection?: string | null;
  readonly style?: { readonly id: string; readonly version: number };
}
interface Refusal { readonly subjectId: string; readonly overlay: string; readonly reason: string }
interface Binding {
  readonly representationReport: Report;
  setRepresentationIntent(intent: RepresentationIntent): Report;
  setRepresentationSelection?(subjectId: string | null): Report;
  readonly representationOverlayPlan?: { readonly refusals: readonly Refusal[] } | null;
}

/** Optional starter-ground facts when no data-view subject is selected. */
export interface RepresentationInspectorOptions {
  /**
   * When the authored starter is the current subject, report whether its ground is already drawn.
   * Return null when the active world is not that starter.
   */
  readonly starterGround?: () => { readonly renderedInView: boolean } | null;
}

const ORIGIN_WORDS: Readonly<Record<string, string>> = {
  inferred: 'Inferred',
  authored: 'Authored',
  generated: 'Generated',
  external: 'External source',
};
const KIND_WORDS: Readonly<Record<string, string>> = {
  'scene': 'Scene',
  'object': 'Object',
  'geometry-group': 'Grouped geometry',
};
const BLEND_WORDS: Readonly<Record<RepresentationResolution['blend'], string>> = {
  crossfade: 'Surface dissolves as its points appear',
  overlay: 'Points appear over its own look, which leaves at the points end',
  endpoint: 'Switches at the points end only',
  none: 'One form only',
};
const PRESENTATION = 'Glow, dashes, the moving band, colour and the dark ground are presentation. '
  + 'They add no geometry and encode no artifact bytes.';

function swatchColour(colourBy: RepresentationIntent['colour'], key: string): string | null {
  const palette = DATA_VIEW_STYLE.palette;
  if (colourBy === 'origin') return palette.origin[key as keyof typeof palette.origin] ?? null;
  return dataViewKindColour(DATA_VIEW_STYLE, key) ?? null;
}

function keyWords(colourBy: RepresentationIntent['colour'], key: string): string {
  if (colourBy === 'origin') return ORIGIN_WORDS[key] ?? key;
  // A city record kind in plain words, from the kind itself: city.street_segment is "Street segment".
  const city = /^city\.([a-z][a-z0-9_]*)$/.exec(key)?.[1];
  const words = city?.replaceAll('_', ' ');
  return KIND_WORDS[key] ?? (words === undefined ? key : words.charAt(0).toUpperCase() + words.slice(1));
}

function checkbox(label: string): { readonly root: HTMLLabelElement; readonly input: HTMLInputElement } {
  const input = el('input', { type: 'checkbox', disabled: true });
  return { root: el('label', { class: 'representation-toggle' }, [input, el('span', { text: label })]), input };
}

function subjectMatches(entry: Entry, query: string): boolean {
  const words = query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  if (words.length === 0) return true;
  const { subject } = entry;
  const searchable = [
    subject.label,
    subject.subjectId,
    subject.subjectKind,
    subject.origin,
    subject.record?.kind,
  ].filter((value): value is string => value !== null && value !== undefined)
    .join(' ').toLocaleLowerCase();
  return words.every(word => searchable.includes(word));
}

function availabilityItems(lines: readonly RepresentationAvailabilityLine[]): HTMLLIElement[] {
  return lines.map(item => el('li', {
    'data-kind': item.kind,
    'data-state': item.state,
    text: representationAvailabilitySentence(item),
  }));
}

/** A read-only lens on actual renderer capabilities. It never requests or changes source data. */
export function buildRepresentationInspector(
  getBinding: () => Binding | null,
  options: RepresentationInspectorOptions = {},
) {
  const root = el('details', { class: 'representation-inspector' });
  const slider = el('input', { type: 'range', min: '0', max: '100', step: '1', value: '0',
    'aria-label': 'Rendered world to points', disabled: true });
  const value = el('output', { text: 'Rendered' });
  const status = el('p', { class: 'representation-status', role: 'status', text: 'Open to inspect the current view.' });
  const boxes = checkbox('Boxes');
  const ids = checkbox('Ids');
  const labels = checkbox('Labels');
  const colour = el('select', { 'aria-label': 'Colour points by', disabled: true }, [
    el('option', { value: 'origin', text: 'Where it came from' }),
    el('option', { value: 'kind', text: 'What it is' }),
  ]);
  const visualization = checkbox('Visualization look (dashes)');
  const legend = el('ul', { class: 'representation-legend', 'aria-label': 'Point colours in this view' });
  const styleLine = el('p', { class: 'representation-style' });
  const search = el('input', {
    type: 'search',
    placeholder: 'Name, identity, kind or origin',
    autocomplete: 'off',
    disabled: true,
  });
  const searchStatus = el('p', { class: 'representation-search-status', role: 'status' });
  const subjects = el('select', { 'aria-label': 'Inspect a displayed geometry group', disabled: true });
  const availabilityHeading = el('p', {
    class: 'representation-availability-heading',
    text: 'Representation availability',
  });
  const availability = el('ul', {
    class: 'representation-availability',
    'aria-label': 'Representation availability',
  });
  const description = el('p', { class: 'representation-description' });
  const record = el('pre', { class: 'representation-record' });
  const data = el('details', {}, [el('summary', { text: 'Display record' }), record]);
  root.append(
    el('summary', { text: 'World → data' }),
    el('p', { text: 'Reveal the points behind the surfaces. Your position stays the same.' }),
    el('div', { class: 'representation-range-head' }, [el('span', { text: 'Rendered' }), value, el('span', { text: 'Points' })]),
    slider, status,
    el('fieldset', { class: 'representation-controls' }, [
      el('legend', { text: 'Show on the world' }), boxes.root, ids.root, labels.root,
    ]),
    el('fieldset', { class: 'representation-controls' }, [
      el('legend', { text: 'Look' }),
      el('label', {}, [el('span', { text: 'Colour by' }), colour]),
      visualization.root, legend, styleLine,
    ]),
    el('label', {}, [el('span', { text: 'Search displayed subjects' }), search]),
    searchStatus,
    el('label', {}, [el('span', { text: 'Inspect geometry' }), subjects]),
    availabilityHeading, availability, description, data,
  );
  let current: Report | null = null;
  let inventoryKey = '';
  let legendKey = '';
  let timer: ReturnType<typeof setInterval> | null = null;
  let selectionRefusal: string | null = null;

  function selectedEntry(): Entry | undefined {
    return current?.subjects.find(item => item.subject.subjectId === current?.selection
      && item.subject.availability === 'available');
  }
  function showAvailability() {
    const entry = selectedEntry();
    if (entry !== undefined) {
      availabilityHeading.hidden = false;
      availability.hidden = false;
      availability.replaceChildren(...availabilityItems(representationAvailabilityLines(entry.subject)));
      return;
    }
    const starter = options.starterGround?.() ?? null;
    if (starter !== null && (current?.selection === null || current?.selection === undefined)) {
      availabilityHeading.hidden = false;
      availability.hidden = false;
      availability.replaceChildren(...availabilityItems(starterGroundAvailabilityLines(starter.renderedInView)));
      return;
    }
    availabilityHeading.hidden = true;
    availability.hidden = true;
    availability.replaceChildren();
  }
  function showRecord() {
    showAvailability();
    const entry = selectedEntry();
    data.hidden = entry === undefined;
    if (entry === undefined) { description.textContent = ''; record.textContent = ''; return; }
    const { subject, resolved } = entry;
    const intent = current!.intent;
    const refusals = (getBinding()?.representationOverlayPlan?.refusals ?? [])
      .filter(item => item.subjectId === subject.subjectId);
    const reasons = [...resolved.reasons];
    if (subject.points === null && subject.unavailableReason !== null
      && !reasons.includes(subject.unavailableReason)) reasons.push(subject.unavailableReason);
    description.textContent = [
      resolved.pointLabel ?? 'Surface only',
      ORIGIN_WORDS[subject.origin] ?? subject.origin,
      subject.subjectKind === 'geometry-group' ? 'Grouped geometry, not separately extracted objects'
        : subject.record?.kind ?? subject.subjectKind,
      BLEND_WORDS[resolved.blend],
      ...reasons,
      ...refusals.map(item => `No ${item.overlay === 'id' ? 'id tag' : item.overlay === 'label' ? 'label tag' : item.overlay}: ${item.reason}`),
    ].join(' · ');
    const style = current!.style ?? { id: DATA_VIEW_STYLE.id, version: DATA_VIEW_STYLE.version };
    // The display descriptor is already resident and authorized. This is not original artifact bytes.
    record.textContent = JSON.stringify({
      id: subject.subjectId, kind: subject.subjectKind,
      record: subject.record ?? null,
      scene: subject.sceneId, frame: subject.frameId,
      origin: subject.origin, point_basis: subject.points, point_label: resolved.pointLabel,
      blend: resolved.blend,
      weights: { rendered: resolved.renderedWeight, points: resolved.pointWeight },
      displayed_points: entry.allocatedPoints ?? 0,
      planned_points: entry.plannedPoints ?? 0,
      bounds: subject.bounds, source_references: subject.sourceRefs,
      overlays: { box: resolved.boxes, id_tag: resolved.ids, label_tag: resolved.labels },
      look: {
        style: `${style.id}@${style.version}`,
        colour_by: intent.colour,
        colour_key: resolved.colourKey,
        treatment: resolved.binary ? 'visualization' : 'points',
        presentation: PRESENTATION,
      },
      visualization: resolved.binary ? representationBinaryVisualization(subject.subjectId, 32) : null,
    }, null, 2);
  }
  function showLegend(entries: readonly Entry[], colourBy: RepresentationIntent['colour']) {
    // Only subjects this view can show: a subject hidden by residency or its parent adds no colour.
    const keys = [...new Set(entries.filter(item => item.subject.points !== null && item.resolved.geometryVisible)
      .map(item => item.resolved.colourKey))].sort();
    const key = `${colourBy}|${keys.join(',')}`;
    if (key === legendKey) return;
    legendKey = key;
    legend.replaceChildren(...keys.map(item => {
      const swatch = el('span', { class: 'representation-swatch', 'aria-hidden': 'true' });
      swatch.style.background = swatchColour(colourBy, item) ?? 'transparent';
      return el('li', {}, [swatch, el('span', { text: keyWords(colourBy, item) })]);
    }));
  }
  function refresh() {
    const binding = getBinding();
    current = binding?.representationReport ?? null;
    if (current?.selection !== null && current?.selection !== undefined) selectionRefusal = null;
    const inventory = current?.subjects ?? [];
    const query = search.value.trim();
    const matches = inventory.filter(item => subjectMatches(item, query));
    const selected = current?.selection;
    const selectedOutside = query === '' ? undefined : inventory.find(item =>
      item.subject.subjectId === selected
      && item.subject.availability === 'available'
      && !matches.includes(item));
    const entries = current?.subjects.filter(item => item.subject.availability === 'available') ?? [];
    const spatial = entries.filter(item => item.subject.rendered && item.subject.points !== null);
    const visibleSpatial = spatial.filter(item => item.resolved.geometryVisible);
    const intent = current?.intent;
    slider.disabled = spatial.length === 0;
    slider.value = String(Math.round((intent?.pointMix ?? 0) * 100));
    value.textContent = Number(slider.value) === 0 ? 'Rendered' : `${slider.value}% points`;
    const budget = current?.pointBudget;
    const drawn = current?.allocatedPoints ?? 0;
    const pending = current?.pendingSubjects ?? 0;
    const representationStatus = spatial.length === 0
      ? 'No switchable surface and point pair is available in this view.'
      : [
        `${visibleSpatial.length} of ${spatial.length} supported geometry groups are visible in this view.`,
        'Unsupported surfaces keep their existing appearance.',
        ...(intent !== undefined && intent.pointMix > 0 && budget !== undefined
          ? [`${drawn.toLocaleString('en-GB')} points prepared of a ${budget.toLocaleString('en-GB')} point budget.`] : []),
        ...(pending > 0 ? ['Preparing more points.'] : []),
      ].join(' ');
    status.textContent = selectionRefusal === null
      ? representationStatus
      : `${selectionRefusal} ${representationStatus}`;
    const controls = entries.length === 0 || intent === undefined;
    for (const [toggle, on] of [
      [boxes, intent?.boxes], [ids, intent?.ids], [labels, intent?.labels],
      [visualization, intent?.binary === 'visualization'],
    ] as const) {
      toggle.input.disabled = controls;
      toggle.input.checked = on === true;
    }
    colour.disabled = controls;
    colour.value = intent?.colour ?? 'origin';
    const style = current?.style ?? { id: DATA_VIEW_STYLE.id, version: DATA_VIEW_STYLE.version };
    styleLine.textContent = `Look ${style.id}, version ${style.version}. ${PRESENTATION}`;
    showLegend(entries, intent?.colour ?? 'origin');
    search.disabled = inventory.length === 0;
    searchStatus.textContent = query === ''
      ? `${inventory.length} ${inventory.length === 1 ? 'subject' : 'subjects'} in this view.`
      : matches.length === 0
        ? `No subjects match “${query}”.${selectedOutside === undefined
          ? ' Clear the search to see every subject.'
          : ' The selected subject remains inspectable outside this filter and is not included in the match count.'}`
        : `${matches.length} of ${inventory.length} subjects match “${query}”.${selectedOutside === undefined
          ? ''
          : ' The selected subject remains inspectable outside this filter and is not included in the match count.'}`;
    const shown = selectedOutside === undefined ? matches : [selectedOutside, ...matches];
    const key = JSON.stringify([query, selected, shown.map(item => [
      item.subject.subjectId,
      item.subject.label,
      item.subject.subjectKind,
      item.subject.origin,
      item.subject.record?.kind,
      item.subject.availability,
      item.subject.unavailableReason,
    ])]);
    if (key !== inventoryKey) {
      inventoryKey = key;
      subjects.replaceChildren(
        el('option', { value: '', text: 'No subject selected' }),
        ...shown.map(item => el('option', {
          value: item.subject.subjectId,
          text: `${item.subject.label ?? item.subject.subjectId}${item === selectedOutside
            ? ' (selected, outside search)'
            : item.subject.availability === 'available' ? '' : ' (unavailable)'}`,
          disabled: item.subject.availability !== 'available',
        })),
      );
    }
    subjects.value = selected !== null && selected !== undefined
      && entries.some(item => item.subject.subjectId === selected) ? selected : '';
    subjects.disabled = inventory.length === 0;
    showRecord();
  }
  function change(changes: Partial<RepresentationIntent>) {
    const binding = getBinding();
    if (binding === null) return;
    binding.setRepresentationIntent({ ...binding.representationReport.intent, ...changes });
    refresh();
  }
  function select() {
    const binding = getBinding();
    const id = subjects.value === '' ? null : subjects.value;
    if (binding?.setRepresentationSelection === undefined) return;
    try {
      if (binding.representationReport.selection !== id) binding.setRepresentationSelection(id);
      selectionRefusal = null;
    } catch (error) {
      if (!(error instanceof TypeError)
        || !/^(Unknown|Unavailable) representation subject /.test(error.message)) throw error;
      selectionRefusal = 'That subject is no longer available. No subject is selected.';
      subjects.value = '';
      try {
        if (binding.representationReport.selection !== null) binding.setRepresentationSelection(null);
      } catch (clearError) {
        if (!(clearError instanceof TypeError)
          || !/^(Unknown|Unavailable) representation subject /.test(clearError.message)) throw clearError;
      }
    }
  }
  slider.addEventListener('input', () => {
    if (slider.disabled) return;
    change({ pointMix: Number(slider.value) / 100 });
  });
  boxes.input.addEventListener('change', () => change({ boxes: boxes.input.checked }));
  ids.input.addEventListener('change', () => change({ ids: ids.input.checked }));
  labels.input.addEventListener('change', () => change({ labels: labels.input.checked }));
  visualization.input.addEventListener('change', () => change({
    binary: visualization.input.checked ? 'visualization' : 'off',
  }));
  colour.addEventListener('change', () => change({ colour: colour.value === 'kind' ? 'kind' : 'origin' }));
  search.addEventListener('input', refresh);
  subjects.addEventListener('change', () => { select(); refresh(); });
  root.addEventListener('toggle', () => {
    if (timer !== null) clearInterval(timer);
    timer = null;
    if (root.open) {
      refresh();
      timer = setInterval(() => {
        if (root.closest('[hidden]') === null) refresh();
      }, 250);
    }
  });
  return { root, refresh, dispose() { if (timer !== null) clearInterval(timer); timer = null; } };
}
