/**
 * The right pane: one thing, and everything that is known about it.
 *
 * Two shapes, because there are two kinds of thing to look at and they are not the same kind.
 *
 * **An entity** renders through `world-index`'s `buildEntityDetail`, in the fixed section order
 * that package exports: identity, the four-band provenance panel, occurrences, relations,
 * history. The order is not chosen here. `DETAIL_SECTION_ORDER` is exported so a test can assert
 * it survives somebody adding a section, and this iterates it rather than hard-coding a sequence.
 *
 * **A bare occurrence** renders as a citation and an offer. It has no provenance panel because
 * there is nothing to panel: nobody has said anything about it, and the four bands over an
 * anonymous detection would be three empty bands and one that says "we do not know what this
 * is", which is exactly what the sentence above it already says in words.
 *
 * **Band 4 is never omitted**, and that is enforced by the type in `companion-runtime` rather
 * than by care here: `omitted` is the literal `false`. What is renderable here is the decision to
 * draw an empty band as an empty band. A panel that hid its empty bands would be a panel that
 * showed only what is known, and the whole point of the fourth band is what is not.
 */

import type { EntityRecord, GraphSnapshot, OccurrenceRecord } from '@exulanica/graph-client';
import type { BandRow, ConfirmationBand } from '@exulanica/companion-runtime';
import type { EntityDetailView, OccurrenceCitation } from '@exulanica/world-index';
import { DETAIL_SECTION_ORDER, buildEntityDetail } from '@exulanica/world-index';
import type { EvidenceCache } from '../evidence.js';
import type { PlaceNameRightsSource } from '../place-name-rights-api.js';
import type { SourceMediaCatalog } from '@exulanica/atlas-react/playcanvas';
import { say } from './copy.js';
import { el, replace } from './dom.js';
import { buildPlaceNameRights } from './place-name-rights.js';

export interface DetailHandlers {
  /** The user asks to say who or what a detection is. Produces a proposal, never a write. */
  onName(occurrence: OccurrenceRecord): void;
  /** An evidence chip was opened. The corresponding anchor pulses at the same moment. */
  onEvidenceOpened(anchorId: string | null): void;
  /** Move the live Atlas to the citation's anchor, or its region when no anchor is available. */
  onLocate(anchorId: string | null, islandId: string): void;
  /** Return to the Index when this pane occupies the narrow-screen surface. */
  onClose(): void;
}

export interface DetailPane {
  readonly root: HTMLElement;
  showNothing(): void;
  showEntity(snapshot: GraphSnapshot, entity: EntityRecord): void;
  showOccurrence(occurrence: OccurrenceRecord): void;
}

export interface DetailPresentation {
  /** Synthetic development data has a small source fixture but no write path. */
  readonly preview?: boolean;
  readonly sourceMedia?: SourceMediaCatalog;
  /**
   * Where a named place's name may go. When present, a named place's detail shows where its name
   * can go, directly under the name, with the control to allow or stop each use. Absent in the
   * synthetic preview, which has no decisions to read and refuses every write.
   */
  readonly placeNames?: PlaceNameRightsSource;
}

export function buildDetail(
  evidence: EvidenceCache,
  handlers: DetailHandlers,
  presentation: DetailPresentation = {},
): DetailPane {
  const root = el('section', { class: 'detail', 'aria-label': 'Detail' });
  const close = el('button', {
    type: 'button',
    class: 'detail-close',
    'aria-label': 'Back to the index',
    text: 'Back to Index',
  });
  close.addEventListener('click', () => handlers.onClose());

  const show = (children: readonly (Node | string)[]): void => {
    replace(root, [close, ...children]);
  };

  return {
    root,
    showNothing() {
      show([
        el('p', {
          class: 'detail-empty',
          text: 'Pick something on the left, or aim at an anchor in your world.',
        }),
      ]);
    },
    showEntity(snapshot, entity) {
      const view = buildEntityDetail({ snapshot, entity });
      const sections: (HTMLElement | string)[] = [...sectionsOf(view, evidence, handlers, presentation)];
      if (entity.kind === 'place' && entity.displayName !== null && presentation.placeNames !== undefined) {
        // Under the name it is about, and outside world-index's section order, which describes what
        // is known about a thing rather than what may be done with its name.
        sections.splice(
          DETAIL_SECTION_ORDER.indexOf('identity') + 1,
          0,
          buildPlaceNameRights(entity.entityId, presentation.placeNames).root,
        );
      }
      show(sections);
    },
    showOccurrence(occurrence) {
      show([
        el('h1', { class: 'detail-title', text: `An unidentified ${occurrence.kind}` }),
        el('p', { class: 'detail-lede' }, [
          'Nobody has said what this is. A detector saw something here, which is an inference ' +
            'and not a fact about anybody, so it supports nothing until you say so.',
        ]),
        citationList([citationOf(occurrence)], evidence, handlers, presentation),
        presentation.preview === true
          ? el('p', {
              class: 'detail-note preview-read-only-note',
              text: 'Naming is unavailable in the synthetic read-only preview.',
            })
          : nameOffer(occurrence, handlers),
      ]);
    },
  };
}

function citationOf(occurrence: OccurrenceRecord): OccurrenceCitation {
  return {
    occurrenceId: occurrence.occurrenceId,
    anchorId: occurrence.anchorId,
    islandId: occurrence.islandId,
    capturedAtMs: occurrence.capturedAtMs,
    linkState: occurrence.linkState,
    confidence: occurrence.confidence,
    evidence: occurrence.evidence,
    timeUnknown: occurrence.capturedAtMs === null,
  };
}

function nameOffer(occurrence: OccurrenceRecord, handlers: DetailHandlers): HTMLElement {
  const form = el('form', { class: 'name-offer' });
  const input = el('input', {
    type: 'text',
    name: 'display-name',
    maxlength: 200,
    placeholder: 'Name or describe this',
    'aria-label': 'Name or describe this',
  });
  form.append(
    input,
    el('button', { type: 'submit', class: 'primary', text: 'Propose' }),
    el('p', { class: 'name-note' }, [
      'Nothing is written yet. This produces a proposal you can read before anything changes.',
    ]),
  );
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    if (input.value.trim().length === 0) return;
    handlers.onName(occurrence);
  });
  // Read back by the caller, which is why it carries a stable name rather than a closure.
  form.dataset['occurrenceId'] = occurrence.occurrenceId;
  return form;
}

function sectionsOf(
  view: EntityDetailView,
  evidence: EvidenceCache,
  handlers: DetailHandlers,
  presentation: DetailPresentation,
): readonly HTMLElement[] {
  // Iterated from the exported order rather than written out, so a section added to that array
  // appears here and a section removed from it disappears, in one place.
  return DETAIL_SECTION_ORDER.map((section) => {
    switch (section) {
      case 'identity':
        return el('header', { class: 'detail-identity' }, [
          el('h1', {
            class: 'detail-title',
            text: view.identity.displayName ?? `Unnamed ${view.identity.kind}`,
          }),
          el('p', {
            class: 'detail-sub',
            text: `${view.identity.occurrenceCount} occurrences, ${view.identity.status.replace(/_/g, ' ')}`,
          }),
        ]);
      case 'provenance':
        return el('section', { class: 'band-panel', 'aria-label': 'What is known, and how' }, [
          ...view.provenance.bands.map(band),
        ]);
      case 'occurrences':
        return el('section', { class: 'detail-section', 'aria-label': 'Occurrences' }, [
          el('h2', { text: 'Occurrences' }),
          el('p', { class: 'detail-note' }, [
            presentation.preview === true
              ? 'These synthetic citations exercise source, focus, and direct travel together.'
              : 'Every one of these opens the exact photograph it came from.',
          ]),
          citationList(
            view.occurrences,
            evidence,
            handlers,
            presentation,
          ),
        ]);
      case 'relations':
        return el('section', { class: 'detail-section', 'aria-label': 'Relations' }, [
          el('h2', { text: 'Relations' }),
          view.relations.length === 0
            ? el('p', { class: 'detail-note' }, [
                'None recorded. Nothing in this system writes a relation yet, which is not the ' +
                  'same as there being none.',
              ])
            : el(
                'ul',
                {},
                view.relations.map((relation) =>
                  el('li', { text: `${relation.predicateKey}: ${relation.objectEntityId}` }),
                ),
              ),
        ]);
      case 'history':
        return el('section', { class: 'detail-section', 'aria-label': 'History' }, [
          el('h2', { text: 'History' }),
          el(
            'ol',
            { class: 'history' },
            view.history.map((event) =>
              el('li', {}, [
                el('span', { class: 'history-type', text: event.type.replace(/_/g, ' ') }),
                ' ',
                el('time', { text: new Date(event.atMs).toISOString().slice(0, 16) }),
              ]),
            ),
          ),
        ]);
    }
  });
}

/** One of the four bands. Drawn whether or not it has rows: an empty band is information. */
function band(value: ConfirmationBand): HTMLElement {
  const section = el('section', { class: `band band-${value.band} tone-${value.toneKey}` }, [
    el('h3', { text: BAND_LABELS[value.band] }),
  ]);
  if (value.rows.length === 0) {
    section.append(el('p', { class: 'band-empty', text: EMPTY_BAND[value.band] }));
    return section;
  }
  section.append(el('ul', {}, value.rows.map(bandRow)));
  return section;
}

const BAND_LABELS: Readonly<Record<ConfirmationBand['band'], string>> = Object.freeze({
  told: 'What you told me',
  captures: 'What the captures show',
  inferred: 'What I inferred',
  unknown: 'What I do not know',
});

/** An empty band still says something, and what it says differs by band. */
const EMPTY_BAND: Readonly<Record<ConfirmationBand['band'], string>> = Object.freeze({
  told: 'You have not said anything about this.',
  captures: 'The photographs record nothing about this beyond that it is there.',
  inferred: 'Nothing was inferred about this.',
  unknown: 'Nothing is outstanding.',
});

function bandRow(row: BandRow): HTMLElement {
  const item = el('li', { class: row.pending ? 'band-row is-pending' : 'band-row' });
  // Band 1 renders the user's own words verbatim. 5.1: "always retained and never paraphrased
  // away." A row that showed a tidied version would put system wording in the user's own record.
  item.append(
    el('span', { class: 'row-label', text: row.verbatim ?? say(row.labelKey) }),
    el('span', { class: 'row-value', text: renderValue(row.value) }),
  );
  if (row.confidence !== null) {
    // Qualitative, never a percentage: a percentage implies a frequency guarantee nothing here
    // can make.
    item.append(el('span', { class: 'row-confidence', text: row.confidence }));
  }
  if (row.methodKey !== null) {
    item.append(el('span', { class: 'row-method', text: say(row.methodKey) }));
  }
  return item;
}

function renderValue(value: unknown): string {
  if (value === null || value === undefined) return '';
  return typeof value === 'string' ? value : JSON.stringify(value);
}

/**
 * The citation list. Clicking one opens the original inline and pulses its anchor.
 *
 * 5.2: "Clicking an evidence chip does not leave the Atlas. It opens the source image inline,
 * docked to the panel, AND SIMULTANEOUSLY THE CORRESPONDING ANCHOR IN THE WORLD PULSES. The
 * written claim and the spatial world point at the same evidence at the same time."
 */
function citationList(
  citations: readonly OccurrenceCitation[],
  evidence: EvidenceCache,
  handlers: DetailHandlers,
  presentation: DetailPresentation,
): HTMLElement {
  const list = el('ol', { class: 'citations' });
  for (const citation of citations) {
    const evidenceAvailable = presentation.preview !== true || citation.evidence.some(
      (handle) => presentation.sourceMedia?.get(handle)?.available === true,
    );
    const figure = el('figure', { class: 'citation' });
    const caption = el('figcaption', {
      text: citation.timeUnknown
        ? 'time not recorded'
        : new Date(citation.capturedAtMs ?? 0).toISOString().slice(0, 16).replace('T', ' '),
    });
    const open = el('button', {
      type: 'button',
      class: 'citation-open',
      text: evidenceAvailable ? 'Open the source' : 'Source unavailable',
      disabled: !evidenceAvailable,
    });
    if (evidenceAvailable) {
      open.addEventListener('click', () => {
        void openInto(figure, open, citation, evidence, handlers);
      });
    }
    const locate = el('button', {
      type: 'button',
      class: 'citation-locate',
      text: 'Locate in world',
    });
    locate.addEventListener('click', () => handlers.onLocate(citation.anchorId, citation.islandId));
    figure.append(el('div', { class: 'citation-actions' }, [locate, open]), caption);
    list.append(el('li', {}, [figure]));
  }
  return list;
}

async function openInto(
  figure: HTMLElement,
  trigger: HTMLButtonElement,
  citation: OccurrenceCitation,
  evidence: EvidenceCache,
  handlers: DetailHandlers,
): Promise<void> {
  const handle = citation.evidence[0];
  if (handle === undefined) {
    figure.append(el('p', { class: 'citation-failed', text: 'this citation names no evidence' }));
    return;
  }
  trigger.disabled = true;
  trigger.textContent = 'Opening';
  const opened = await evidence.open(handle);
  trigger.remove();
  if (!opened.ok) {
    // Stated, never substituted. A placeholder image would be a claim that the evidence exists
    // and looks like that.
    figure.prepend(el('p', { class: 'citation-failed', text: opened.reason }));
    return;
  }
  figure.prepend(el('img', { src: opened.url, alt: '', loading: 'lazy' }));
  handlers.onEvidenceOpened(citation.anchorId);
}
