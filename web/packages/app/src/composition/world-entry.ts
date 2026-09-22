/** Choosing between saved worlds. The one-world states live in `ui/startup-state.ts`. */

import { ApiError } from '@exulanica/graph-client';
import type { SavedWorldEntry } from '../world-entry-api.js';
import { el } from '../ui/dom.js';

export interface WorldEntrySurface {
  readonly entries: readonly SavedWorldEntry[];
  readonly open: (entry: SavedWorldEntry) => Promise<void>;
  readonly adoptLatest: (entry: SavedWorldEntry) => Promise<void>;
  /**
   * Why no world opened by itself, when that is known. A person reaching a list has a choice to
   * make either way, so this is a line above the list rather than the subject of the screen.
   */
  readonly arrivalFailure?: string | null;
}

/**
 * Pick between saved worlds. Only ever built for a real choice, which means more than one.
 *
 * `main.ts` sends a session with one world, or none, to {@link buildWorldOpeningFailure}
 * instead. This surface carries a reading column, a list and a reconciliation control, and none
 * of that is an honest frame for "the one world you have did not load its appearance".
 *
 * NO TRY AGAIN BUTTON. A reload returns to exactly this screen, because more than one saved
 * world means the choice is still required. Pressing a world is the action, and pressing it
 * reports its own failure in the status line.
 */
export function buildWorldEntrySurface(deps: WorldEntrySurface): HTMLElement {
  const arrivalFailure = deps.arrivalFailure ?? null;
  const status = el('p', {
    class: 'gate-failure world-entry-status', role: 'status', 'aria-live': 'polite',
  });
  status.hidden = arrivalFailure === null;
  if (arrivalFailure !== null) status.textContent = arrivalFailure;

  const root = el('main', { class: 'gate world-entry-gate' }, [
    el('header', { class: 'world-entry-heading' }, [
      el('p', { class: 'world-entry-brand', text: 'Exulanica' }),
      el('h1', { text: 'Choose a saved world' }),
      el('p', {
        class: 'world-entry-introduction',
        text: 'Open a saved world exactly where you left it.',
      }),
      status,
    ]),
  ]);
  const list = el('section', { class: 'world-entry-list', 'aria-label': 'Saved worlds' });
  for (const entry of deps.entries) {
    const item = el('article', { class: 'world-entry-item' });
    const unavailable = entry.availability !== 'available';
    const button = el('button', {
      type: 'button', class: 'world-entry-choice', disabled: unavailable,
    }, [
      el('span', { class: 'world-entry-choice-title', text: entry.title }),
      el('span', {
        class: 'world-entry-choice-detail',
        text: unavailable
          ? unavailableMessage(entry.unavailableReason)
          : entry.sourceKind === 'authored'
            ? 'Authored world · saved changes and appearance'
            : 'Personal world · saved changes and appearance',
      }),
    ]);
    button.addEventListener('click', () => {
      status.hidden = true;
      button.disabled = true;
      void deps.open(entry).catch((error: unknown) => {
        button.disabled = false;
        status.hidden = false;
        status.textContent = entryFailure(error, 'The saved world could not be opened.');
      });
    });
    item.append(button);
    if (entry.unavailableReason === 'authored_version_changed') {
      const acknowledge = el('input', { type: 'checkbox' }) as HTMLInputElement;
      const adopt = el('button', {
        type: 'button', class: 'world-entry-secondary',
        text: 'Use the latest saved changes and open', disabled: true,
      });
      acknowledge.addEventListener('change', () => { adopt.disabled = !acknowledge.checked; });
      adopt.addEventListener('click', () => {
        adopt.disabled = true;
        status.hidden = true;
        void deps.adoptLatest(entry).catch((error: unknown) => {
          adopt.disabled = !acknowledge.checked;
          status.hidden = false;
          status.textContent = entryFailure(
            error, 'The latest changes could not be adopted. Reload and compare again.',
          );
        });
      });
      item.append(el('section', { class: 'world-entry-reconcile' }, [
        el('p', {
          text: `Your opening point includes ${entry.authoredEditSeq} saved changes. `
            + `The latest state includes ${entry.currentAuthoredEditSeq}.`,
        }),
        el('label', {}, [
          acknowledge,
          ' I understand this will use changes saved elsewhere.',
        ]),
        adopt,
      ]));
    }
    list.append(item);
  }
  root.append(list);
  return root;
}

function unavailableMessage(reason: string | null): string {
  return reason === 'source_deleted'
    ? 'Its source material was deleted. The saved record remains, but it cannot be opened.'
    : reason === 'authored_version_changed'
      ? 'Its saved changes were updated elsewhere. Reconcile that update before opening it.'
      : 'This saved world is unavailable and cannot be opened.';
}

function entryFailure(error: unknown, fallback: string): string {
  if (error instanceof ApiError && error.code === 'stale_saved_world_entry') {
    return 'This saved world changed again. Reload to compare the latest changes before trying again.';
  }
  return error instanceof Error ? error.message : fallback;
}
