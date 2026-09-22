/**
 * What one placed depth estimate is, said in the order a person needs to hear it.
 *
 * The title, the truth line and the scale line come first because they are what stops this being
 * read as a photograph of a room or a measurement of one. The provenance follows, inside a
 * disclosure, because it is what makes the first three checkable rather than asserted.
 *
 * **The three sentences are the server's.** ``truth``, ``scale`` and ``coverage`` arrive on the
 * instance and are shown verbatim. Composing them here would let the words a person reads about
 * whether this is a measurement drift from what was actually placed, because a client can be
 * updated separately from the thing it describes.
 *
 * **Nothing here decides what may be drawn.** The panel reports ``availability`` and offers the
 * two controls that act on it. Whether the estimate appears in the world is the renderer's
 * question and the server's answer, and this surface is not a third opinion.
 */

import { el } from './dom.js';
import type { PointMapInstance } from '../world-objects-api.js';

/** Plain words for each state, and what the person can do about it. */
const AVAILABILITY: Readonly<Record<string, string>> = {
  available: 'Showing in this world.',
  unavailable_bytes: 'Not showing: this estimate cannot be read right now.',
  detached:
    'Not showing: this photo was removed from this world. Adding it back makes a new reference; '
    + 'this placement stays as it is.',
  binding_drift: 'Not showing: what this placement names is no longer current.',
  unknown: 'Not showing: this estimate could not be checked.',
};

/** Why a withdrawn estimate stopped, and what would bring one back. */
const WITHDRAWN: Readonly<Record<string, string>> = {
  model_right_withdrawn:
    'Not showing: you stopped 3D estimates for this photo. Reviewing it again and allowing them '
    + 'makes a new estimate; it does not restore this one.',
  review_expired: 'Not showing: the human review of this photo has ended. Review it again.',
  source_deleted: 'Not showing: the photo this was made from is no longer in your library.',
  person_withdrawn: 'Not showing: somebody in this photo withdrew.',
};

export function availabilitySentence(instance: PointMapInstance): string {
  if (instance.removed) return 'Removed from this world.';
  if (instance.availability === 'withdrawn') {
    return WITHDRAWN[instance.unavailableReason ?? ''] ?? 'Not showing: its permission has ended.';
  }
  return AVAILABILITY[instance.availability] ?? 'Not showing.';
}

function field(label: string, value: string): HTMLElement {
  return el('p', { class: 'photo-geometry-field' }, [
    el('span', { class: 'photo-geometry-label', text: `${label}: ` }),
    el('span', { class: 'photo-geometry-value', text: value }),
  ]);
}

function text(source: Readonly<Record<string, unknown>>, ...path: string[]): string {
  let cursor: unknown = source;
  for (const key of path) {
    if (cursor === null || typeof cursor !== 'object') return 'not recorded';
    cursor = (cursor as Record<string, unknown>)[key];
  }
  return typeof cursor === 'string' || typeof cursor === 'number' || typeof cursor === 'boolean'
    ? String(cursor)
    : 'not recorded';
}

export interface PhotoGeometryInspectorOptions {
  readonly instance: PointMapInstance;
  /**
   * Points in the decoded container, when the renderer has decoded it.
   *
   * Optional because the placement does not store it: the number belongs to the bytes, and a copy
   * in a row could disagree with what was drawn. Omitted rather than guessed when nothing decoded
   * the container.
   */
  readonly pointCount?: number;
  /** Take the placing edit back. The caller owns the version's base token. */
  readonly onUndo?: () => void;
  /** Stop 3D estimates for this photograph. Final, and confirmed by the caller's own surface. */
  readonly onStop?: () => void;
}

export function buildPhotoGeometryInspector(options: PhotoGeometryInspectorOptions): HTMLElement {
  const { instance } = options;
  const source = instance.source;
  const root = el('section', {
    class: 'photo-geometry-inspector',
    'aria-label': '3D estimate from a photo',
  });
  root.append(
    el('h3', { class: 'photo-geometry-title', text: '3D estimate from a photo' }),
    // First, in this order, and never behind a disclosure.
    el('p', { class: 'photo-geometry-truth', text: instance.truth }),
    el('p', { class: 'photo-geometry-scale', text: instance.scale }),
    el('p', { class: 'photo-geometry-coverage', text: instance.coverage }),
    el('p', {
      class: 'photo-geometry-availability', role: 'status', 'aria-live': 'polite',
      text: availabilitySentence(instance),
    }),
  );

  const fov = Number(text(source, 'artifact', 'declared_fov_y_microdegrees'));
  const provenance = el('div', { class: 'photo-geometry-provenance' }, [
    field('Photo', text(source, 'capture_id')),
    field('Photo bytes', text(source, 'source_sha256')),
    field('In this world as', text(source, 'attachment', 'attachment_id')),
    field('Under review', text(source, 'screening', 'screening_id')),
    field('Review receipt', text(source, 'screening', 'receipt_sha256')),
    field('Under your authority', text(source, 'authorization', 'authorization_id')),
    field(
      'Model',
      `${text(source, 'model', 'provider')} ${text(source, 'model', 'role')} `
      + `${text(source, 'model', 'identifier')}@${text(source, 'model', 'revision')}`,
    ),
    field('Where it ran', text(source, 'model', 'destination')),
    field('Permission', text(source, 'right', 'right_id')),
    field('Permission receipt', text(source, 'right', 'receipt_sha256')),
    field('Estimate', text(source, 'artifact', 'artifact_id')),
    field('Estimate bytes', text(source, 'artifact', 'content_sha256')),
    field('Size', `${text(source, 'artifact', 'byte_size')} bytes`),
    field('Container', text(source, 'artifact', 'container')),
    field('Rung', text(source, 'artifact', 'rung')),
    // DECLARED, and labelled as such in the field name rather than in a footnote. Nothing
    // validates the flag, so a field called "Metric" would be this panel making the claim.
    field('Scale declared by the model', text(source, 'artifact', 'declared_metric')),
    field(
      'Field of view the model estimated',
      Number.isFinite(fov)
        ? `${(fov / 1_000_000).toFixed(1)} degrees vertically, estimated, not measured`
        : 'not recorded',
    ),
    field('Placed in', instance.regionId),
    field('Placed as', `${instance.origin.kind} ${instance.origin.role}`),
  ]);
  if (options.pointCount !== undefined) {
    provenance.append(field('Points', String(options.pointCount)));
  }
  const details = el('details', { class: 'photo-geometry-details' });
  details.append(el('summary', { text: 'Where this came from' }), provenance);
  root.append(details);

  const actions = el('div', { class: 'photo-geometry-actions' });
  if (options.onUndo !== undefined) {
    const undo = el('button', { type: 'button', class: 'photo-geometry-undo', text: 'Undo' });
    undo.onclick = () => options.onUndo?.();
    actions.append(undo);
  }
  if (options.onStop !== undefined) {
    const stop = el('button', {
      type: 'button', class: 'photo-geometry-stop', text: 'Stop 3D estimates for this photo',
    });
    stop.onclick = () => options.onStop?.();
    actions.append(stop);
  }
  if (actions.childElementCount > 0) root.append(actions);
  return root;
}
