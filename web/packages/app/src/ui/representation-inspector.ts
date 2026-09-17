import {
  DATA_VIEW_STYLE,
  isDataViewKindKey,
  representationBinaryVisualization,
  type RepresentationIntent,
  type RepresentationResolution,
  type RepresentationSubject,
} from '@exulanica/atlas-core';
import { el } from './dom.js';
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
  return isDataViewKindKey(key) ? palette.kind[key] : null;
}

function keyWords(colourBy: RepresentationIntent['colour'], key: string): string {
  return (colourBy === 'origin' ? ORIGIN_WORDS[key] : KIND_WORDS[key]) ?? key;
}

function checkbox(label: string): { readonly root: HTMLLabelElement; readonly input: HTMLInputElement } {
  const input = el('input', { type: 'checkbox', disabled: true });
  return { root: el('label', { class: 'representation-toggle' }, [input, el('span', { text: label })]), input };
}

/** A read-only lens on actual renderer capabilities. It never requests or changes source data. */
export function buildRepresentationInspector(getBinding: () => Binding | null) {
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
  const subjects = el('select', { 'aria-label': 'Inspect a displayed geometry group', disabled: true });
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
    el('label', {}, [el('span', { text: 'Inspect geometry' }), subjects]), description, data,
  );
  let current: Report | null = null;
  let inventoryKey = '';
  let legendKey = '';
  let timer: ReturnType<typeof setInterval> | null = null;

  function selectedEntry(): Entry | undefined {
    return current?.subjects.find(item => item.subject.subjectId === subjects.value
      && item.subject.availability === 'available');
  }
  function showRecord() {
    const entry = selectedEntry();
    data.hidden = entry === undefined;
    if (entry === undefined) { description.textContent = ''; record.textContent = ''; return; }
    const { subject, resolved } = entry;
    const intent = current!.intent;
    const refusals = (getBinding()?.representationOverlayPlan?.refusals ?? [])
      .filter(item => item.subjectId === subject.subjectId);
    description.textContent = [
      resolved.pointLabel ?? 'Surface only',
      ORIGIN_WORDS[subject.origin] ?? subject.origin,
      subject.subjectKind === 'geometry-group' ? 'Grouped geometry, not separately extracted objects'
        : subject.record?.kind ?? subject.subjectKind,
      BLEND_WORDS[resolved.blend],
      ...resolved.reasons,
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
    const keys = [...new Set(entries.filter(item => item.subject.points !== null).map(item => item.resolved.colourKey))].sort();
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
    status.textContent = spatial.length === 0
      ? 'No switchable surface and point pair is available in this view.'
      : [
        `${visibleSpatial.length} of ${spatial.length} supported geometry groups are visible in this view.`,
        'Unsupported surfaces keep their existing appearance.',
        ...(intent !== undefined && intent.pointMix > 0 && budget !== undefined
          ? [`${drawn.toLocaleString('en-GB')} points prepared of a ${budget.toLocaleString('en-GB')} point budget.`] : []),
        ...(pending > 0 ? ['Preparing more points.'] : []),
      ].join(' ');
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
    const key = JSON.stringify(entries.map(item => [item.subject.subjectId, item.subject.label]));
    if (key !== inventoryKey) {
      const selected = subjects.value;
      inventoryKey = key;
      subjects.replaceChildren(...entries.map(item => el('option', {
        value: item.subject.subjectId,
        text: item.subject.label ?? item.subject.subjectId,
      })));
      subjects.value = entries.some(item => item.subject.subjectId === selected)
        ? selected
        : (entries.find(item => item.resolved.geometryVisible) ?? entries[0])?.subject.subjectId ?? '';
      if (root.open) select();
    }
    subjects.disabled = entries.length === 0;
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
    if (binding?.setRepresentationSelection === undefined || binding.representationReport.selection === id) return;
    binding.setRepresentationSelection(id);
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
  subjects.addEventListener('change', () => { select(); refresh(); });
  root.addEventListener('toggle', () => {
    if (timer !== null) clearInterval(timer);
    timer = null;
    if (root.open) {
      refresh();
      select();
      timer = setInterval(() => {
        if (root.closest('[hidden]') === null) refresh();
      }, 250);
    } else {
      // The highlight belongs to this panel's list; closing the panel lets it go.
      getBinding()?.setRepresentationSelection?.(null);
    }
  });
  return { root, refresh, dispose() { if (timer !== null) clearInterval(timer); timer = null; } };
}
