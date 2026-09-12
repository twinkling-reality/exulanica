/**
 * The confirmation surface. The only path from an intention to a write.
 *
 * interaction-model.md 5.1: "No free-text answer and no choice ever mutates the graph directly.
 * Every path, including a single click on 'Yes, the same person', produces an update proposal,
 * which is rendered, and only an explicit confirmation commits it."
 *
 * So this panel is not a nicety and it is not a dialog for dangerous things. It is the write
 * path. `commit` is reached from exactly one place in this package, here, and the proposal it
 * names must already have been staged and rendered.
 *
 * **Cancel restores instantly, because nothing was mutated** (5.3). There is no rollback here
 * for the same reason there is no spinner: discarding a proposal is forgetting a plan.
 *
 * **Reversibility is stated in words, and true.** The draft carries it; this renders it. A panel
 * that said "you can undo this" over an operation with no undo would be the one sentence in the
 * product it is least acceptable to get wrong.
 */

import type { BandRow, ConfirmationSummary } from '@exulanica/companion-runtime';
import { el, replace } from './dom.js';

export interface ConfirmHandlers {
  onConfirm(proposalId: string): void;
  onCancel(proposalId: string): void;
  onVisibilityChange?(visible: boolean): void;
}

export interface ConfirmPanel {
  readonly root: HTMLElement;
  /** Render a staged proposal for reading. Shows the panel; writes nothing. */
  show(proposalId: string, summary: ConfirmationSummary, utterance: string,
    options?: { readonly undoControlAvailable: boolean }): void;
  /** Report what happened to a commit, in the words the failure used. */
  reportFailure(reason: string): void;
  hide(): void;
}

export function buildConfirm(handlers: ConfirmHandlers): ConfirmPanel {
  const root = el('aside', {
    class: 'confirm',
    role: 'dialog',
    'aria-labelledby': 'confirm-title',
    hidden: '',
  });

  const reveal = (): void => {
    root.hidden = false;
    handlers.onVisibilityChange?.(true);
  };
  const conceal = (): void => {
    root.hidden = true;
    replace(root, []);
    handlers.onVisibilityChange?.(false);
  };

  return {
    root,
    show(proposalId, summary, utterance, options) {
      const confirm = el('button', { type: 'button', class: 'primary', text: 'Confirm' });
      const cancel = el('button', { type: 'button', class: 'ghost', text: 'Cancel' });
      confirm.addEventListener('click', () => handlers.onConfirm(proposalId));
      cancel.addEventListener('click', () => handlers.onCancel(proposalId));

      const children: (HTMLElement | string)[] = [
        el('h2', { id: 'confirm-title', text: 'Before anything is written' }),
      ];
      // A free reply is verbatim. A selected answer is the exact reviewed option phrasing.
      if (utterance.trim().length > 0) {
        children.push(el('blockquote', { class: 'confirm-utterance', text: utterance }));
      }
      children.push(
        el('p', { class: 'confirm-effect' }, [effectOf(summary)]),
        el('p', { class: 'confirm-reversible' }, [
          summary.reversible
            ? options?.undoControlAvailable === true
              ? 'This writes a reversible event. Use “Take back the last change” in the object panel to undo it.'
              : 'This writes a reversible event. This build does not yet expose the undo control.'
            : 'This cannot be undone.',
        ]),
      );

      if (summary.blastRadius !== null) {
        // Tier 2 and above must state what it touches before it touches it. Present exactly when
        // the tier requires it, which is a decision the policy table makes and this renders.
        children.push(
          el('p', { class: 'confirm-radius' }, [
            `This affects ${counted(summary.blastRadius.anchorCount, 'evidence point')} across ` +
              `${counted(summary.blastRadius.islandCount, 'memory region')}.`,
          ]),
        );
      }
      if (!summary.permittedHere) {
        children.push(
          el('p', { class: 'confirm-refused' }, [
            'This operation is not offered from this surface.',
          ]),
        );
      }

      children.push(el('div', { class: 'confirm-actions' }, [confirm, cancel]));
      replace(root, children);
      reveal();
      confirm.focus();
    },
    reportFailure(reason) {
      replace(root, [
        el('h2', { id: 'confirm-title', text: 'Nothing was written' }),
        el('p', { class: 'confirm-refused', text: reason }),
        el('div', { class: 'confirm-actions' }, [
          (() => {
            const close = el('button', { type: 'button', class: 'ghost', text: 'Close' });
            close.addEventListener('click', conceal);
            return close;
          })(),
        ]),
      ]);
      reveal();
    },
    hide: conceal,
  };
}

/**
 * What this proposal would do, from its bands rather than from a sentence somebody wrote.
 *
 * The pending rows ARE the change: `BandRow.pending` is what distinguishes a row that exists only
 * in this draft from one already in the graph. Deriving the sentence from them means the panel
 * cannot describe an effect the proposal does not have.
 */
function effectOf(summary: ConfirmationSummary): string {
  const pending = summary.bands.flatMap((band) => band.rows.filter((row) => row.pending));
  if (pending.length === 0) return 'This proposal changes nothing.';
  const written = joinDescriptions(pending.map(describePendingRow));
  return `This will record ${written}. It will be stored as your statement, not a system guess.`;
}

function counted(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? '' : 's'}`;
}

function recordValue(value: unknown): Readonly<Record<string, unknown>> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Readonly<Record<string, unknown>>
    : null;
}

function field(value: unknown, key: string): string | null {
  const candidate = recordValue(value)?.[key];
  return typeof candidate === 'string' && candidate.length > 0 ? candidate : null;
}

function describePendingRow(row: BandRow): string {
  if (row.verbatim !== null && row.verbatim.trim().length > 0) return `“${row.verbatim}”`;
  const displayName = field(row.value, 'displayName');
  const relation = field(row.value, 'value');
  const text = field(row.value, 'text');
  const scope = field(row.value, 'scope');
  const rejectedClass = field(row.value, 'rejectedClass');

  switch (row.labelKey) {
    case 'row.name':
      return displayName === null ? 'a name for this record' : `the name “${displayName}”`;
    case 'row.nameScope':
      if (displayName !== null && scope === 'everywhere') {
        return `the name “${displayName}” everywhere this person appears`;
      }
      return 'where this name applies';
    case 'row.relation':
      return relation === null ? 'a relationship for this record' : `the relationship “${relation}”`;
    case 'row.sameEntityAs':
      return 'that these records show the same person';
    case 'row.notThisClass':
      return rejectedClass === null
        ? 'that this detection is the wrong kind of thing'
        : `that this detection is not a ${rejectedClass}`;
    case 'row.uncertain':
      return 'that you are not sure about this question';
    case 'row.note':
      return text === null ? 'your decision about this evidence' : `the note “${text}”`;
    case 'row.reject_inference':
      return field(row.value, 'matchId') !== null
        ? 'that these records show different people'
        : 'that this system inference should not be used';
    case 'row.merge':
      return 'a merge of these records';
    case 'row.split':
      return 'a split of this record';
    case 'row.delete':
      return 'a deletion from the index';
    default:
      if (typeof row.value === 'string' && row.value.length > 0) return `“${row.value}”`;
      return 'this proposed change';
  }
}

function joinDescriptions(items: readonly string[]): string {
  if (items.length <= 1) return items[0] ?? 'this proposed change';
  if (items.length === 2) return `${items[0]} and ${items[1]}`;
  return `${items.slice(0, -1).join(', ')}, and ${items.at(-1)}`;
}
