/**
 * Honest availability of the five representation views the product names for one subject.
 *
 * Derived only from fields the data view already holds on a RepresentationSubject (or from the
 * fact that authored starter ground is already drawn). This invents no geometry, no memory and no
 * artifact-byte path the inspector does not have.
 */

import type { PointBasis, RepresentationSubject } from '@exulanica/atlas-core';

export type RepresentationViewKind =
  | 'rendered'
  | 'point'
  | 'semantic'
  | 'provenance'
  | 'artifact';

export type RepresentationAvailabilityState = 'available' | 'unavailable';

export interface RepresentationAvailabilityLine {
  readonly kind: RepresentationViewKind;
  readonly state: RepresentationAvailabilityState;
  readonly detail: string;
}

export const REPRESENTATION_VIEW_KIND_LABELS: Readonly<Record<RepresentationViewKind, string>> =
  Object.freeze({
    rendered: 'Rendered',
    point: 'Point',
    semantic: 'Semantic',
    provenance: 'Provenance',
    artifact: 'Artifact',
  });

const POINT_BASIS_WORDS: Readonly<Record<PointBasis, string>> = Object.freeze({
  'retained-points': 'Retained points are available.',
  'gaussian-centres': 'Trained Gaussian centres are available.',
  'mesh-vertices': 'Sampled mesh points are available.',
  'mesh-surface-samples': 'Generated surface samples are available.',
});

const VIEW_KINDS: readonly RepresentationViewKind[] = Object.freeze([
  'rendered', 'point', 'semantic', 'provenance', 'artifact',
]);

function line(
  kind: RepresentationViewKind,
  state: RepresentationAvailabilityState,
  detail: string,
): RepresentationAvailabilityLine {
  return Object.freeze({ kind, state, detail });
}

/**
 * True for an object a person placed from the reviewed catalog.
 *
 * The renderer registers exactly those as authored `object` subjects, with the asset key as the
 * label and the asset's content digest as the only reference. What exists for one is a display
 * record and that reviewed-asset identity; it has no source records and no evidence.
 */
function isPlacedCatalogObject(subject: RepresentationSubject): boolean {
  return subject.origin === 'authored' && subject.subjectKind === 'object';
}

/**
 * Availability of each named view for one registered representation subject.
 *
 * Artifact stays unavailable here: the inspector never opens an authorized artifact-byte window,
 * and a source digest alone is provenance, not that view.
 */
export function representationAvailabilityLines(
  subject: RepresentationSubject,
): readonly RepresentationAvailabilityLine[] {
  const live = subject.availability === 'available';
  const unavailable = subject.unavailableReason;
  const catalogObject = isPlacedCatalogObject(subject);

  return Object.freeze(VIEW_KINDS.map((kind) => {
    switch (kind) {
      case 'rendered':
        return live && subject.rendered
          ? line(kind, 'available', 'A rendered surface is held for this subject.')
          : line(kind, 'unavailable', unavailable
            ?? (live ? 'No rendered surface is available.' : `Subject is ${subject.availability}.`));
      case 'point':
        return live && subject.points !== null
          ? line(kind, 'available', POINT_BASIS_WORDS[subject.points])
          : line(kind, 'unavailable', unavailable
            ?? 'No compatible retained point buffer is available.');
      case 'semantic':
        if (catalogObject) {
          return line(kind, 'unavailable',
            'This object was added from the reviewed catalog. It has a display record only, '
              + 'not structured source records.');
        }
        return live && subject.dataAvailable
          ? line(kind, 'available', 'Structured source records are available for this subject.')
          : line(kind, 'unavailable', 'Selected source records are unavailable.');
      case 'provenance':
        if (catalogObject) {
          const digest = subject.sourceRefs[0];
          return digest === undefined
            ? line(kind, 'unavailable', 'No reviewed-asset identity is retained for this object.')
            : line(kind, 'available',
              `Reviewed catalog asset${subject.label === null ? '' : ` ${subject.label}`}, `
                + `SHA-256 ${digest.slice(0, 12)}…. It is not a photograph or a measurement.`);
        }
        return subject.sourceRefs.length > 0
          ? line(kind, 'available',
            `${subject.sourceRefs.length} source reference${subject.sourceRefs.length === 1 ? '' : 's'} retained.`)
          : line(kind, 'unavailable', 'No source references are retained for this subject.');
      case 'artifact':
        return line(kind, 'unavailable',
          'No authorized artifact-byte inspection is available for this subject.');
    }
  }));
}

/**
 * Availability for the empty authored starter ground when it is the current subject.
 *
 * Rendered is available only when the app already draws that authored ground. The starter seeds
 * no point map, semantic records, provenance refs or artifact bytes.
 */
export function starterGroundAvailabilityLines(
  renderedInView: boolean,
): readonly RepresentationAvailabilityLine[] {
  return Object.freeze([
    renderedInView
      ? line('rendered', 'available', 'Authored starter ground is drawn in the current view.')
      : line('rendered', 'unavailable', 'Authored starter ground is not drawn in this view.'),
    line('point', 'unavailable', 'The starter seeds no point representation.'),
    line('semantic', 'unavailable', 'The starter seeds no semantic records.'),
    line('provenance', 'unavailable', 'The starter seeds no source provenance references.'),
    line('artifact', 'unavailable', 'The starter seeds no inspectable artifact bytes.'),
  ]);
}

/** Plain words for one availability line, for the inspect panel and tests. */
export function representationAvailabilitySentence(
  item: RepresentationAvailabilityLine,
): string {
  const label = REPRESENTATION_VIEW_KIND_LABELS[item.kind];
  return item.state === 'available'
    ? `${label}: available. ${item.detail}`
    : `${label}: unavailable. ${item.detail}`;
}
