import type { RepresentationIntent, RepresentationSubject, RepresentationResolution } from '@exulanica/atlas-core';
import { el } from './dom.js';
import './representation-inspector.css';

interface Entry {
  readonly subject: RepresentationSubject;
  readonly resolved: RepresentationResolution;
  readonly allocatedPoints?: number;
}
interface Report { readonly intent: RepresentationIntent; readonly subjects: readonly Entry[] }
interface Binding {
  readonly representationReport: Report;
  setRepresentationIntent(intent: RepresentationIntent): Report;
}

/** A read-only lens on actual renderer capabilities. It never requests or changes source data. */
export function buildRepresentationInspector(getBinding: () => Binding | null) {
  const root = el('details', { class: 'representation-inspector' });
  const slider = el('input', { type: 'range', min: '0', max: '100', step: '1', value: '0',
    'aria-label': 'Rendered world to points', disabled: true });
  const value = el('output', { text: 'Rendered' });
  const status = el('p', { class: 'representation-status', role: 'status', text: 'Open to inspect the current view.' });
  const subjects = el('select', { 'aria-label': 'Inspect a displayed geometry group', disabled: true });
  const description = el('p', { class: 'representation-description' });
  const record = el('pre', { class: 'representation-record' });
  const data = el('details', {}, [el('summary', { text: 'Display record' }), record]);
  root.append(
    el('summary', { text: 'World → data' }),
    el('p', { text: 'Reveal the points behind the surfaces. Your position stays the same.' }),
    el('div', { class: 'representation-range-head' }, [el('span', { text: 'Rendered' }), value, el('span', { text: 'Points' })]),
    slider, status,
    el('label', {}, [el('span', { text: 'Inspect geometry' }), subjects]), description, data,
  );
  let current: Report | null = null;
  let inventoryKey = '';
  let timer: ReturnType<typeof setInterval> | null = null;

  function showRecord() {
    const entry = current?.subjects.find(item => item.subject.subjectId === subjects.value
      && item.subject.availability === 'available');
    data.hidden = entry === undefined;
    description.textContent = entry === undefined ? ''
      : [entry.resolved.pointLabel ?? 'Surface only', entry.subject.origin,
        entry.subject.subjectKind === 'geometry-group' ? 'Grouped geometry, not separately extracted objects' : entry.subject.subjectKind,
        ...entry.resolved.reasons].join(' · ');
    // The display descriptor is already resident and authorized. This is not original artifact bytes.
    record.textContent = entry === undefined ? '' : JSON.stringify({
      id: entry.subject.subjectId, kind: entry.subject.subjectKind,
      scene: entry.subject.sceneId, frame: entry.subject.frameId,
      origin: entry.subject.origin, point_basis: entry.subject.points,
      displayed_points: entry.allocatedPoints ?? 0,
      bounds: entry.subject.bounds, source_references: entry.subject.sourceRefs,
    }, null, 2);
  }
  function refresh() {
    const binding = getBinding();
    current = binding?.representationReport ?? null;
    const entries = current?.subjects.filter(item => item.subject.availability === 'available') ?? [];
    const spatial = entries.filter(item => item.subject.rendered && item.subject.points !== null);
    const visibleSpatial = spatial.filter(item => item.resolved.geometryVisible);
    slider.disabled = spatial.length === 0;
    slider.value = String(Math.round((current?.intent.pointMix ?? 0) * 100));
    value.textContent = Number(slider.value) === 0 ? 'Rendered' : `${slider.value}% points`;
    status.textContent = spatial.length > 0
      ? `${visibleSpatial.length} of ${spatial.length} supported geometry groups are visible in this view. Unsupported surfaces keep their existing appearance.`
      : 'No switchable surface and point pair is available in this view.';
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
    }
    subjects.disabled = entries.length === 0;
    showRecord();
  }
  slider.addEventListener('input', () => {
    const binding = getBinding();
    if (binding === null || slider.disabled) return;
    binding.setRepresentationIntent({ ...binding.representationReport.intent, pointMix: Number(slider.value) / 100 });
    refresh();
  });
  subjects.addEventListener('change', showRecord);
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
