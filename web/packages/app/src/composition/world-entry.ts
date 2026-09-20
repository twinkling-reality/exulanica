/** Recovery and explicit choice when a saved world cannot resume automatically. */

import { ApiError } from '@exulanica/graph-client';
import type { SavedWorldEntry } from '../world-entry-api.js';
import { el } from '../ui/dom.js';

export function buildWorldEntrySurface(deps: {
  readonly entries: readonly SavedWorldEntry[];
  readonly open: (entry: SavedWorldEntry) => Promise<void>;
  readonly adoptLatest: (entry: SavedWorldEntry) => Promise<void>;
}): HTMLElement {
  const status = el('p', {
    class: 'gate-failure world-entry-status', role: 'status', 'aria-live': 'polite',
  });
  status.hidden = true;
  const root = el('main', { class: 'gate world-entry-gate' }, [
    el('header', { class: 'world-entry-heading' }, [
      el('p', { class: 'world-entry-brand', text: 'Exulanica' }),
      el('h1', { text: deps.entries.length === 0 ? 'Your world did not open' : 'Choose a saved world' }),
      el('p', {
        class: 'world-entry-introduction',
        text: deps.entries.length === 0
          ? 'Nothing was created. Reload to try opening your world again.'
          : 'Open a saved world exactly where you left it.',
      }),
      status,
    ]),
  ]);

  if (deps.entries.length === 0) return root;
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
