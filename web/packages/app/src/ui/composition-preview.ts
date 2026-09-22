/**
 * What a composition verdict says to a person, and the element that says it.
 *
 * The server answers with a stable code; a person is owed a sentence saying what happened and
 * what they can do about it. Every code the contract lists has one here, checked at compile time
 * by the `Record` below. A code this client does not know gets a generic sentence rather than a
 * guess, and the raw code only ever appears inside a details element, for whoever needs it.
 */

import { ApiError } from '@exulanica/graph-client';
import {
  CompositionContractError,
  CompositionRequestError,
  isCompositionBlockedReason,
  type AddressedCompositionApplyRequest,
  type AddressedCompositionRequest,
  type CompositionBlockedReason,
  type CompositionPreview,
  type CompositionPreviewClient,
} from '../composition-preview-api.js';
import { WorldObjectsContractError, problemDetail } from '../world-objects-api.js';
import { el, replace } from './dom.js';

export interface CompositionExplanation {
  /** What happened, in one plain sentence. */
  readonly happened: string;
  /** What the person can do next. */
  readonly next: string;
  /** The stable code, for the details element only. */
  readonly code: string | null;
  /** The server's own words, for the details element only. */
  readonly detail: string | null;
  /**
   * `unchanged` when the world is known not to have changed; `unknown` when a write's answer did
   * not arrive, so whether it was recorded is not known.
   */
  readonly outcome: 'unchanged' | 'unknown';
}

type Words = Readonly<{ happened: string; next: string }>;

export const COMPOSITION_BLOCKED_WORDS: Readonly<Record<CompositionBlockedReason, Words>> =
  Object.freeze({
    source_invalidated: {
      happened: 'The place this world version was built from has been deleted.',
      next: 'What is already here is kept, but nothing more can be added to this version.',
    },
    stale_base: {
      happened: 'This world changed after it was last read, so this check no longer applies.',
      next: 'Check again against the world as it is now.',
    },
    unknown_asset: {
      happened: 'That object is not in the reviewed collection.',
      next: 'Choose a different object.',
    },
    asset_bytes_unavailable: {
      happened: 'The file for that object is missing from storage, so it cannot be drawn.',
      next: 'Choose a different object, or ask whoever hosts this world to restore the file.',
    },
    environment_binding_unknown: {
      happened: 'That landscape could not be found for this world.',
      next: 'Choose it again from the landscapes this world can use.',
    },
    environment_withdrawn: {
      happened: 'That landscape has been withdrawn by its source.',
      next: 'It can no longer be added. Choose a different one.',
    },
    compose_not_permitted: {
      happened: 'The permissions on that source do not allow adding it to a world.',
      next: 'Choose a different source.',
    },
    environment_bytes_unavailable: {
      happened: 'Files that landscape needs are missing from storage.',
      next: 'Choose a different one, or ask whoever hosts this world to restore them.',
    },
    environment_binding_drift: {
      happened: 'That landscape has been updated since it was chosen.',
      next: 'Choose it again from its current version.',
    },
    unknown_attachment: {
      happened: 'That reference photo is not part of this world.',
      next: 'Open the photo drawer to see the references this world keeps.',
    },
    expired_source_not_composable: {
      happened: 'Permission to use that photo has expired.',
      next: 'Review the photo again before using it.',
    },
    attachment_is_not_composition: {
      happened: 'A reference photo stays a reference. It is kept with this world and is never placed into it.',
      next: 'To add something you can see, choose an object in the object panel.',
    },
    placement_required: {
      happened: 'No spot was chosen for this addition.',
      next: 'Stand where you want it and choose Place before me.',
    },
    invalid_placement: {
      happened: 'That spot or setting is not one this world accepts.',
      next: 'Face open ground inside this world and try again.',
    },
    subject_already_present: {
      happened: 'Something in this world already has the name this addition was given.',
      next: 'Check again to give it a new one.',
    },
  });

const UNRECOGNISED: Words = Object.freeze({
  happened: 'This world did not accept the change, for a reason this version of the app does not recognise.',
  next: 'Nothing was changed. Try again, or choose something else.',
});

/** The sentence pair for one blocked code, known or not. */
export function explainBlockedReason(
  code: string | null,
  detail: string | null = null,
): CompositionExplanation {
  const words = isCompositionBlockedReason(code) ? COMPOSITION_BLOCKED_WORDS[code] : UNRECOGNISED;
  return Object.freeze({ ...words, code, detail, outcome: 'unchanged' as const });
}

/** The explanation for a blocked preview document. */
export function explainPreview(preview: CompositionPreview): CompositionExplanation | null {
  return preview.availability === 'ready'
    ? null
    : explainBlockedReason(preview.blockedReason, preview.blockedDetail);
}

/**
 * The ready sentence. That the rest of the world stays as it is is said only when the server
 * listed the other subjects among what apply preserves.
 */
export function describeReady(preview: CompositionPreview, title: string): string {
  return `Ready to add. “${title}” will stand where the mark shows.`
    + (preview.wouldChange.preserves.includes('other_subjects')
      ? ' Everything else in this world stays as it is.'
      : '');
}

export type CompositionPhase = 'preview' | 'apply';

/**
 * A request that did not come back with a verdict, in words.
 *
 * `composition_blocked` carries its code as the problem detail, so a refused apply is explained by
 * the same sentence the preview would have used. After an apply whose answer never arrived, it is
 * not known whether the change was recorded, and the sentence says exactly that.
 */
export function explainCompositionFailure(
  error: unknown,
  phase: CompositionPhase,
): CompositionExplanation {
  const said = (
    happened: string,
    next: string,
    code: string | null,
    detail: string | null,
    outcome: CompositionExplanation['outcome'] = 'unchanged',
  ): CompositionExplanation => Object.freeze({ happened, next, code, detail, outcome });
  if (error instanceof WorldObjectsContractError) {
    if (error.code === 'saved_entry_conflict' || error.code === 'saved_entry_reconciliation_required') {
      return said(
        'This saved world changed elsewhere, so the change was not recorded.',
        'Reload the world before trying again.',
        error.code, null,
      );
    }
    return said(
      'The world answered in a form this app does not understand.',
      'Nothing was changed. Reload and try again.',
      error.code, error.message,
    );
  }
  if (error instanceof CompositionContractError) {
    return said(
      'The world answered in a form this app does not understand.',
      'Nothing was changed. Reload and try again.',
      'invalid_response', error.message,
    );
  }
  if (error instanceof CompositionRequestError) {
    return said(
      'This app built a request the world does not accept. That is a fault in this app, not something you did.',
      'Nothing was changed.',
      'invalid_request', error.message,
    );
  }
  if (error instanceof ApiError) {
    const detail = problemDetail(error);
    if (error.code === 'composition_blocked') {
      // The contract puts the stable code in the detail. Anything else is shown, not guessed at.
      return isCompositionBlockedReason(detail)
        ? explainBlockedReason(detail)
        : explainBlockedReason(error.code, detail);
    }
    if (error.code === 'stale_saved_world_entry') {
      return said(
        'This saved world changed elsewhere, so the change was not recorded.',
        'Reload the world before trying again.',
        error.code, detail,
      );
    }
    if (error.code === 'unknown_reference' || error.status === 404) {
      return said(
        'This world version is not available to this account.',
        'Reload the world and try again.',
        error.code, detail,
      );
    }
    if (error.status === 401 || error.status === 403) {
      return said(
        'This session is not allowed to change this world.',
        'Sign in again, then try again.',
        error.code, detail,
      );
    }
    if (error.status === 422) {
      return said(
        'The world could not read this request. That is a fault in this app, not something you did.',
        'Nothing was changed.',
        error.code, detail,
      );
    }
    // Any other refusal is still a refusal: the server answered, and it wrote nothing.
    if (error.status >= 400 && error.status < 500) {
      return said(
        phase === 'apply'
          ? 'The world refused this change as it stands.'
          : 'The world could not check this addition as it stands.',
        'Nothing was changed. Reload the world and try again.',
        error.code, detail,
      );
    }
    return phase === 'apply'
      ? said(
        'The world did not confirm this change.',
        'Reload the world to see whether it was added.',
        error.code, detail, 'unknown',
      )
      : said(
        'The world could not check this addition just now.',
        'Nothing was changed. Try again in a moment.',
        error.code, detail,
      );
  }
  const message = error instanceof Error ? error.message : null;
  return phase === 'apply'
    ? said(
      'The answer did not arrive, so it is not known whether this was added.',
      'Reload the world to see what it holds.',
      null, message, 'unknown',
    )
    : said(
      'The world could not be reached, so nothing was checked or changed.',
      'Try again in a moment.',
      null, message,
    );
}

/** The raw code and the server's words, folded away. Absent when there is neither. */
export function compositionDetails(explanation: CompositionExplanation): HTMLElement | null {
  if (explanation.code === null && explanation.detail === null) return null;
  const lines: HTMLElement[] = [];
  if (explanation.code !== null) {
    lines.push(el('p', {}, ['Code: ', el('code', { text: explanation.code })]));
  }
  if (explanation.detail !== null && explanation.detail !== explanation.code) {
    lines.push(el('p', { text: explanation.detail }));
  }
  return el('details', { class: 'composition-verdict-details' }, [
    el('summary', { text: 'Details' }),
    ...lines,
  ]);
}

export interface CompositionVerdictView {
  readonly root: HTMLElement;
  checking(): void;
  ready(sentence: string): void;
  /** A blocked verdict or a failed request, with an optional person-driven retry. */
  refused(explanation: CompositionExplanation, retry?: { readonly label: string; run(): void }): void;
}

/** One live region for the verdict: checking, ready, or refused with its reason. */
export function buildCompositionVerdict(): CompositionVerdictView {
  const root = el('div', {
    class: 'composition-verdict',
    role: 'status',
    'aria-live': 'polite',
  });
  const state = (next: 'checking' | 'ready' | 'refused'): void => {
    root.dataset['state'] = next;
  };
  return {
    root,
    checking() {
      state('checking');
      replace(root, [el('p', {
        class: 'composition-verdict-sentence',
        text: 'Checking with the world whether this can be added…',
      })]);
    },
    ready(sentence) {
      state('ready');
      replace(root, [el('p', { class: 'composition-verdict-sentence', text: sentence })]);
    },
    refused(explanation, retry) {
      state('refused');
      const children: HTMLElement[] = [
        el('p', { class: 'composition-verdict-sentence', text: explanation.happened }),
        el('p', { class: 'composition-verdict-next', text: explanation.next }),
      ];
      const details = compositionDetails(explanation);
      if (details !== null) children.push(details);
      if (retry !== undefined) {
        const again = el('button', {
          type: 'button', class: 'ghost composition-verdict-retry', text: retry.label,
        });
        again.addEventListener('click', () => retry.run());
        children.push(again);
      }
      replace(root, children);
    },
  };
}

// -- one control addressed by explicit ids ---------------------------------------------------------

export interface CompositionPreviewControl {
  readonly root: HTMLElement;
  readonly previewButton: HTMLButtonElement;
  readonly applyButton: HTMLButtonElement;
  readonly status: HTMLElement;
  /** Last preview document, or null before the first successful request. */
  previewDocument(): CompositionPreview | null;
  requestPreview(): Promise<CompositionPreview | null>;
  requestApply(): Promise<boolean>;
  setBusy(busy: boolean): void;
  reflect(): void;
}

type PreviewPort = Pick<CompositionPreviewClient, 'preview' | 'apply'>;

/**
 * Preview and, when the server says ready, apply for one source addressed by explicit ids.
 *
 * `buildApply` may return null when this surface cannot supply a placement; Apply then stays
 * hidden even for a ready preview.
 */
export function buildCompositionPreviewControl(options: {
  readonly client: PreviewPort;
  readonly getVersionId: () => string | null;
  readonly buildPreview: () => AddressedCompositionRequest | null;
  readonly buildApply?: (preview: CompositionPreview) => AddressedCompositionApplyRequest | null;
  readonly onPreview?: (preview: CompositionPreview) => void;
  readonly onApplied?: () => void;
  readonly label?: string;
  /** What the addition is called in the ready sentence. */
  readonly title?: string;
}): CompositionPreviewControl {
  const previewButton = el('button', {
    type: 'button',
    class: 'composition-preview-request',
    text: options.label ?? 'Preview composition',
  }) as HTMLButtonElement;
  const applyButton = el('button', {
    type: 'button',
    class: 'composition-preview-apply',
    text: 'Apply composition',
  }) as HTMLButtonElement;
  applyButton.hidden = true;
  const verdict = buildCompositionVerdict();
  const root = el('div', { class: 'composition-preview-control' }, [
    el('div', { class: 'composition-preview-actions' }, [previewButton, applyButton]),
    verdict.root,
  ]);

  let held: CompositionPreview | null = null;
  let busy = false;

  const reflect = (): void => {
    const versionId = options.getVersionId();
    const request = options.buildPreview();
    previewButton.disabled = busy || versionId === null || request === null;
    const canApply = !busy
      && held !== null
      && held.availability === 'ready'
      && versionId !== null
      && options.buildApply?.(held) != null;
    applyButton.hidden = !canApply;
    applyButton.disabled = !canApply;
  };

  const requestPreview = async (): Promise<CompositionPreview | null> => {
    const versionId = options.getVersionId();
    const request = options.buildPreview();
    if (versionId === null || request === null || busy) {
      reflect();
      return null;
    }
    busy = true;
    reflect();
    verdict.checking();
    try {
      const preview = await options.client.preview(versionId, request);
      held = preview;
      const refused = explainPreview(preview);
      if (refused === null) verdict.ready(describeReady(preview, options.title ?? 'This'));
      else verdict.refused(refused);
      options.onPreview?.(preview);
      return preview;
    } catch (error) {
      held = null;
      verdict.refused(explainCompositionFailure(error, 'preview'));
      return null;
    } finally {
      busy = false;
      reflect();
    }
  };

  const requestApply = async (): Promise<boolean> => {
    const versionId = options.getVersionId();
    const apply = held === null || options.buildApply === undefined
      ? null
      : options.buildApply(held);
    if (versionId === null || held === null || held.availability !== 'ready' || apply === null || busy) {
      reflect();
      return false;
    }
    busy = true;
    reflect();
    verdict.checking();
    try {
      await options.client.apply(versionId, apply);
      held = null;
      verdict.ready('Added. It is saved in this world.');
      options.onApplied?.();
      return true;
    } catch (error) {
      verdict.refused(explainCompositionFailure(error, 'apply'));
      return false;
    } finally {
      busy = false;
      reflect();
    }
  };

  previewButton.addEventListener('click', () => { void requestPreview(); });
  applyButton.addEventListener('click', () => { void requestApply(); });
  reflect();

  return {
    root,
    previewButton,
    applyButton,
    status: verdict.root,
    previewDocument: () => held,
    requestPreview,
    requestApply,
    setBusy(next) {
      busy = next;
      reflect();
    },
    reflect,
  };
}
