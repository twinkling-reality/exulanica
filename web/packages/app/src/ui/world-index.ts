/**
 * The keyboard-first World Index binding.
 *
 * `@exulanica/world-index` owns filtering, row semantics, ranking, and URL encoding. This file only
 * turns that existing view model into the protected three-part evidence workspace described by
 * interaction-model.md 6.1. Bare occurrences remain a separate list because an anonymous
 * occurrence is not an entity and must not be given entity-shaped facet state.
 */

import type {
  AssertionKind,
  EntityKind,
  GraphSnapshot,
  IndexStatus,
  OccurrenceRecord,
} from '@exulanica/graph-client';
import type { IndexFacets, IndexRow, IndexView } from '@exulanica/world-index';
import { ALL_FACETS, FACET_VALUES, buildIndexView } from '@exulanica/world-index';
import { say } from './copy.js';
import { commandAction, el, replace } from './dom.js';
import { buildRegionPlan, type RegionPoint } from './region-plan.js';

export interface IndexHandlers {
  onEntity(entityId: string, activation?: 'keyboard' | 'pointer'): void;
  onOccurrence(occurrenceId: string, activation?: 'keyboard' | 'pointer'): void;
  onSearch(text: string): void;
  onFacets?(facets: IndexFacets): void;
  onClose?(): void;
}

export interface IndexPane {
  readonly root: HTMLElement;
  render(snapshot: GraphSnapshot, state: string | IndexFacets, selected: string | null): void;
  /** Reveal the search field and put the caret in it. */
  focusSearch(): void;
  /** Put search away. Refuses while a query is live, because a hidden filter is a lie. */
  closeSearch(): boolean;
}

export interface IndexPresentation {
  readonly preview?: boolean;
  /**
   * Region plan positions for the inset, in Atlas ground coordinates.
   *
   * Presentation only. The inset shows WHERE a row's regions sit relative to each other; it is
   * never a source of identity, never a navigation control, and it does not decide membership.
   * Omitted, the inset simply does not render.
   */
  readonly regions?: readonly RegionPoint[];
}

/** How many bare detections are listed before the workspace states the remainder. */
const DETECTION_PAGE = 60;

const KIND_LABELS: Readonly<Record<EntityKind, string>> = Object.freeze({
  person: 'People', place: 'Places', object: 'Objects', event: 'Events', region: 'Regions',
});
const STATUS_LABELS: Readonly<Record<IndexStatus, string>> = Object.freeze({
  confirmed: 'Confirmed',
  needs_review: 'Needs review',
  inferred_only: 'Inferred only',
  user_asserted: 'User asserted',
  rejected: 'Rejected',
  merged_away: 'Merged away',
});
const SOURCE_LABELS: Readonly<Record<AssertionKind, string>> = Object.freeze({
  user: 'You provided',
  capture: 'Capture supported',
  inference: 'System inferred',
  external: 'External, present only',
});

export function buildWorldIndex(
  handlers: IndexHandlers,
  presentation: IndexPresentation = {},
): IndexPane {
  const root = el('section', {
    class: 'rail index-workspace held-plate',
    'aria-label': 'Index',
  });
  const titleId = 'world-index-title';
  root.setAttribute('aria-labelledby', titleId);
  /*
   * Search rests closed.
   *
   * A permanent input band spends the widest line of the surface on a control nobody has asked
   * for yet, and it made the first thing in the Index a request for typing rather than the
   * evidence. It is summoned with a key like every other Atlas verb, and it is announced in the
   * same command row as the rest of them.
   */
  root.dataset['searchOpen'] = 'false';

  const search = el('input', {
    type: 'search',
    class: 'rail-search',
    placeholder: 'Search people, places, and events',
    'aria-label': 'Search the index',
  });
  const counter = el('p', { class: 'rail-counter', 'aria-live': 'polite' });
  const resultSummary = el('p', { class: 'index-result-summary', 'aria-live': 'polite' });
  const filterState = el('p', { class: 'index-filter-state' });
  const clear = el('button', { type: 'button', class: 'text-action index-clear', text: 'Clear filters' });
  const close = el('button', {
    type: 'button', class: 'index-close', 'aria-label': 'Close the index', text: 'Return',
  });
  close.addEventListener('click', () => handlers.onClose?.());

  const keyHint = (key: string, verb: string): HTMLElement =>
    el('span', { class: 'index-key command-action' }, commandAction(key, verb));

  const identified = el('ul', { class: 'rail-list', 'aria-label': 'Index results' });
  const detections = el('ul', { class: 'rail-list detection-list', 'aria-label': 'Unidentified detections' });
  const detectionsNote = el('p', { class: 'rail-note' });
  const presenceGroup = el('fieldset', { class: 'index-facet-group index-presence-facet' });
  const presenceInputs = new Map<string, HTMLInputElement>();
  let presenceSignature = '';
  let currentFacets: IndexFacets = ALL_FACETS;

  const emit = (facets: IndexFacets): void => {
    if (handlers.onFacets === undefined) {
      handlers.onSearch(facets.text);
      return;
    }
    handlers.onFacets(Object.freeze({
      kinds: Object.freeze([...facets.kinds]),
      statuses: Object.freeze([...facets.statuses]),
      islands: Object.freeze([...facets.islands]),
      sources: Object.freeze([...facets.sources]),
      text: facets.text,
    }));
  };

  const kinds = facetGroup(
    'Kind',
    FACET_VALUES.kinds,
    KIND_LABELS,
    () => currentFacets.kinds,
    (values) => emit({ ...currentFacets, kinds: values }),
  );
  const statuses = facetGroup(
    'Status',
    FACET_VALUES.statuses,
    STATUS_LABELS,
    () => currentFacets.statuses,
    (values) => emit({ ...currentFacets, statuses: values }),
  );
  const sources = facetGroup(
    'Source of knowledge',
    FACET_VALUES.sources,
    SOURCE_LABELS,
    () => currentFacets.sources,
    (values) => emit({ ...currentFacets, sources: values }),
  );

  search.addEventListener('input', () => emit({ ...currentFacets, text: search.value }));
  clear.addEventListener('click', () => emit(ALL_FACETS));

  const legend = el('section', { class: 'provenance-legend', 'aria-label': 'Provenance legend' }, [
    el('h2', { text: 'Knowledge marks' }),
    legendItem('user', 'You provided'),
    legendItem('capture', 'Capture supported'),
    legendItem('inference', 'System inferred'),
    el('p', {
      class: 'legend-note',
      text: 'A missing mark means that source does not support this entity. Confidence appears only while an entity remains inferred.',
    }),
  ]);

  /*
   * Nineteen checkboxes standing open is a taxonomy lesson, not a filter. The facet contract,
   * its order, and its fieldset semantics are untouched; they simply start folded, so the
   * resting surface is search and results. <details> keeps them keyboard-reachable and
   * announced without a custom disclosure to get wrong.
   */
  const plan = buildRegionPlan(presentation.regions ?? [], { title: 'Region plan' });

  const filters = el('details', { class: 'index-filters' }, [
    el('summary', { class: 'index-filters-summary' }, [
      el('span', { class: 'index-filters-label', text: 'Filters' }),
      filterState,
    ]),
    el('div', { class: 'index-filter-body' }, [
      kinds.root,
      statuses.root,
      presenceGroup,
      sources.root,
      clear,
    ]),
  ]);

  root.append(
    el('header', { class: 'index-head' }, [
      el('h1', { id: titleId, text: 'Your library' }),
      el('div', { class: 'index-head-state' }, [resultSummary, counter]),
    ]),
    el('aside', { class: 'index-facets', 'aria-label': 'Index filters' }, [
      el('div', { class: 'index-search-wrap' }, [search]),
      filters,
    ]),
    el('section', { class: 'index-results', 'aria-label': 'Index entries' }, [
      el('header', { class: 'index-results-head' }, [
        el('p', { class: 'index-section-label', text: 'Entities' }),
      ]),
      identified,
      el('section', { class: 'detection-section', 'aria-label': 'Not identified' }, [
        el('h2', { class: 'rail-head', text: 'Not identified' }),
        detectionsNote,
        detections,
      ]),
    ]),
    plan.root,
    el('footer', { class: 'index-foot' }, [
      legend,
      el('p', { class: 'index-keys' }, [
        keyHint('Enter', 'Open'),
        keyHint('S', 'Search'),
        keyHint('Tab', 'Filters'),
        keyHint('I', 'Return'),
      ]),
      close,
    ]),
  );

  const renderPresence = (snapshot: GraphSnapshot): void => {
    const options = snapshot.islands.map((island, index) => ({
      value: island.islandId,
      label: `Region ${String(index + 1).padStart(2, '0')} · ${island.captureIds.length} ${island.captureIds.length === 1 ? 'capture' : 'captures'}`,
    }));
    const signature = options.map(({ value, label }) => `${value}\u0000${label}`).join('\u0001');
    if (signature !== presenceSignature) {
      presenceSignature = signature;
      presenceInputs.clear();
      const inputs = options.map(({ value, label }) => {
        const input = el('input', { type: 'checkbox', value });
        presenceInputs.set(value, input);
        input.addEventListener('change', () => {
          const selected = options
            .filter((option) => presenceInputs.get(option.value)?.checked)
            .map((option) => option.value);
          emit({ ...currentFacets, islands: Object.freeze(selected) });
        });
        return el('label', { class: 'index-facet-option' }, [input, el('span', { text: label })]);
      });
      replace(presenceGroup, [el('legend', { text: 'Presence' }), ...inputs]);
    }
    for (const [value, input] of presenceInputs) {
      input.checked = currentFacets.islands.includes(value);
    }
  };

  return {
    root,
    focusSearch() {
      root.dataset['searchOpen'] = 'true';
      search.focus();
      search.select();
    },
    closeSearch() {
      if (search.value.trim().length > 0) return false;
      root.dataset['searchOpen'] = 'false';
      return true;
    },
    render(snapshot, state, selected) {
      currentFacets = typeof state === 'string' ? { ...ALL_FACETS, text: state } : state;
      const view = buildIndexView({ snapshot, facets: currentFacets, search: currentFacets.text });
      currentFacets = view.facets;
      if (document.activeElement !== search) search.value = currentFacets.text;
      counter.textContent = `${view.openQuestions.count} open ${
        view.openQuestions.count === 1 ? 'question' : 'questions'
      }`;
      resultSummary.textContent = `${view.resultCount} ${view.resultCount === 1 ? 'entity' : 'entities'}`;
      const activeCount = activeFacetCount(currentFacets);
      filterState.textContent = activeCount === 0
        ? 'All entities'
        : `${activeCount} active`;
      clear.disabled = activeCount === 0;
      if (currentFacets.text.trim().length > 0) root.dataset['searchOpen'] = 'true';
      root.dataset['detailOpen'] = selected === null ? 'false' : 'true';

      kinds.reflect();
      statuses.reflect();
      sources.reflect();
      renderPresence(snapshot);

      replace(
        identified,
        view.rows.length > 0
          ? view.rows.map((row) => entityRow(row, row.entityId === selected, handlers))
          : [emptyState(view, snapshot)],
      );

      const activeRow = view.rows.find((row) => row.entityId === selected);
      plan.render(new Set(activeRow?.islandIds ?? []), activeRow?.displayName ?? null);

      const bare = snapshot.occurrences.filter((occurrence) => occurrence.entityId === null);
      detectionsNote.textContent = bare.length === 0
        ? 'Every detection in this library has been identified.'
        : presentation.preview === true
          ? `${bare.length} synthetic detections remain outside entity facets. Their fixture sources stay inspectable; unavailable evidence stays explicit.`
          : `${bare.length} detections remain outside entity facets until somebody identifies them.`;
      replace(
        detections,
        bare.slice(0, DETECTION_PAGE).map((occurrence) =>
          detectionRow(occurrence, occurrence.occurrenceId === selected, handlers)),
      );
      if (bare.length > DETECTION_PAGE) {
        detections.append(el('li', {
          class: 'rail-more', text: `${bare.length - DETECTION_PAGE} more, not listed here.`,
        }));
      }
    },
  };
}

interface FacetBinding {
  readonly root: HTMLElement;
  reflect(): void;
}

function facetGroup<T extends string>(
  title: string,
  values: readonly T[],
  labels: Readonly<Record<T, string>>,
  selected: () => readonly T[],
  onChange: (values: readonly T[]) => void,
): FacetBinding {
  const inputs = new Map<T, HTMLInputElement>();
  const root = el('fieldset', { class: 'index-facet-group' }, [el('legend', { text: title })]);
  for (const value of values) {
    const input = el('input', { type: 'checkbox', value });
    inputs.set(value, input);
    input.addEventListener('change', () => {
      onChange(Object.freeze(values.filter((candidate) => inputs.get(candidate)?.checked)));
    });
    root.append(el('label', { class: 'index-facet-option' }, [input, el('span', { text: labels[value] })]));
  }
  return {
    root,
    reflect() {
      const active = selected();
      for (const [value, input] of inputs) input.checked = active.includes(value);
    },
  };
}

function activeFacetCount(facets: IndexFacets): number {
  return facets.kinds.length + facets.statuses.length + facets.islands.length + facets.sources.length +
    (facets.text.trim().length > 0 ? 1 : 0);
}

function entityRow(row: IndexRow, selected: boolean, handlers: IndexHandlers): HTMLElement {
  const button = el('button', {
    type: 'button', class: 'rail-row', 'aria-current': selected ? 'true' : undefined,
  });
  button.addEventListener('click', (event) =>
    handlers.onEntity(row.entityId, event.detail === 0 ? 'keyboard' : 'pointer'));
  const name = row.displayName ?? `Unnamed ${row.placeholder?.kind ?? row.kind}, ${row.occurrenceCount} occurrences`;
  button.append(
    el('span', { class: 'rail-kind', text: row.kind }),
    el('span', { class: row.displayName === null ? 'rail-name is-placeholder' : 'rail-name', text: name }),
    el('span', { class: 'rail-presence', text: `${row.occurrenceCount} ${row.occurrenceCount === 1 ? 'occurrence' : 'occurrences'} · ${row.islandIds.length} ${row.islandIds.length === 1 ? 'region' : 'regions'}` }),
    triad(row),
    ...(row.confidence === null
      ? []
      : [el('span', {
          class: 'row-confidence-band',
          'data-confidence': row.confidence,
          'aria-label': `System confidence: ${row.confidence}`,
        }, [el('span', { text: `${row.confidence} confidence` })])]),
  );
  return el('li', {}, [button]);
}

function triad(row: IndexRow): HTMLElement {
  const marks = el('span', { class: 'triad', 'aria-label': 'Knowledge sources' });
  for (const [key, present, label] of [
    ['user', row.triad.user, 'You provided'],
    ['capture', row.triad.capture, 'Capture supported'],
    ['inference', row.triad.inference, 'System inferred'],
  ] as const) {
    marks.append(el('span', {
      class: `mark mark-${key}${present ? '' : ' is-absent'}`,
      title: `${label}: ${present ? 'present' : 'not present'}`,
      'aria-label': `${label}: ${present ? 'present' : 'not present'}`,
    }));
  }
  if (row.external !== null) {
    marks.append(el('span', {
      class: 'mark mark-external',
      title: `External source as of ${new Date(row.external.latestRetrievedAtMs).toISOString().slice(0, 10)}`,
      'aria-label': `External source as of ${new Date(row.external.latestRetrievedAtMs).toISOString().slice(0, 10)}`,
    }));
  }
  return marks;
}

function legendItem(kind: 'user' | 'capture' | 'inference', label: string): HTMLElement {
  return el('p', { class: 'legend-item' }, [
    el('span', { class: `mark mark-${kind}`, 'aria-hidden': 'true' }),
    el('span', { text: label }),
  ]);
}

function detectionRow(
  occurrence: OccurrenceRecord,
  selected: boolean,
  handlers: IndexHandlers,
): HTMLElement {
  const button = el('button', {
    type: 'button', class: 'rail-row is-bare', 'aria-current': selected ? 'true' : undefined,
  });
  button.addEventListener('click', (event) =>
    handlers.onOccurrence(occurrence.occurrenceId, event.detail === 0 ? 'keyboard' : 'pointer'));
  button.append(
    el('span', { class: 'rail-kind', text: occurrence.kind }),
    el('span', { class: 'rail-name is-placeholder', text: whenOf(occurrence) }),
    el('span', { class: 'rail-presence', text: `Unidentified · ${occurrence.confidence} system confidence` }),
  );
  return el('li', {}, [button]);
}

function whenOf(occurrence: OccurrenceRecord): string {
  if (occurrence.capturedAtMs === null) return 'time not recorded';
  return new Date(occurrence.capturedAtMs).toISOString().slice(0, 16).replace('T', ' ');
}

function emptyState(view: IndexView, snapshot: GraphSnapshot): HTMLElement {
  const nothingIdentified = snapshot.entities.length === 0;
  return el('li', { class: 'rail-empty' }, [
    nothingIdentified
      ? 'Nobody and nothing has been identified yet. Every detection below is anonymous until you say what it is.'
      : say(view.emptyStateKey ?? 'index.noMatches'),
  ]);
}
