/** Choosing between saved worlds. The one-world states live in `ui/startup-state.ts`. */

import { ApiError } from '@exulanica/graph-client';
import type {
  PersonalWorldAction,
  PersonalWorldState,
  SavedWorldEntry,
} from '../world-entry-api.js';
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
  /** The offer to make a world from reviewed photographs, placed after the saved worlds. */
  readonly personalWorld?: PersonalWorldControl;
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
  if (deps.personalWorld !== undefined) root.append(deps.personalWorld.root);
  return root;
}

/** How the choice to make a world from reviewed photographs reaches the server and the world. */
export interface PersonalWorldChoice {
  /** The server's current answer; see `WorldEntryClient.personalWorld`. */
  readonly read: () => Promise<PersonalWorldState>;
  /** Compose what `state` showed and return the saved world it makes or brings up to date. */
  readonly make: (state: PersonalWorldState, title: string) => Promise<SavedWorldEntry>;
  /** Open the returned world: from then on it is the world every request names. */
  readonly open: (entry: SavedWorldEntry) => Promise<void>;
}

/**
 * The words on the one button, by the action the server says composing would take. Updating is
 * offered only for a world that was composed and never made, so to the person it is making one.
 */
const PERSONAL_WORLD_ACTION_LABELS: Readonly<Record<PersonalWorldAction, string>> = {
  create_world: 'Make a world from my photographs',
  update_world: 'Make a world from my photographs',
  save_entry: 'Open a world from my photographs',
};

/** The name a new world from photographs is saved under unless the person gives another. */
const PERSONAL_WORLD_DEFAULT_TITLE = 'My photographs';

export interface PersonalWorldControl {
  readonly root: HTMLElement;
  /** Ask the server again, for example after a review is recorded. */
  readonly refresh: () => Promise<void>;
}

/**
 * Offer to make a world from the person's reviewed photographs, exactly when the server says so.
 *
 * The control holds no rule. It shows the server's refusal words when composing is not possible,
 * the server's counts when it is, and a button whose label follows the server's action. Pressing
 * it sends back the digest that read returned, so the server composes exactly what was shown or
 * refuses by name; a refusal is shown in the server's words and the state is read again.
 */
export function buildPersonalWorldChoice(deps: PersonalWorldChoice): PersonalWorldControl {
  const status = el('p', {
    class: 'personal-world-status', role: 'status', 'aria-live': 'polite',
  });
  const counts = el('p', { class: 'personal-world-counts' });
  const title = el('input', {
    type: 'text', class: 'personal-world-title', value: PERSONAL_WORLD_DEFAULT_TITLE,
    'aria-label': 'Name for the world',
  }) as HTMLInputElement;
  const titleRow = el('label', { class: 'personal-world-title-row' }, ['Name ', title]);
  const make = el('button', { type: 'button', class: 'personal-world-make' });
  const failure = el('p', { class: 'gate-failure personal-world-failure', role: 'alert' });
  const root = el('section', {
    class: 'personal-world-choice', 'aria-label': 'A world from your photographs',
  }, [
    el('h3', { text: 'A world from your photographs' }),
    status, counts, titleRow, make, failure,
  ]);
  let current: PersonalWorldState | null = null;
  let busy = false;

  const show = (state: PersonalWorldState | null): void => {
    current = state;
    root.dataset['state'] = state === null ? 'unknown' : state.action ?? 'refused';
    const action = state?.action ?? null;
    status.textContent = state === null
      ? 'Checking your reviewed photographs…'
      : state.refusal !== null
        ? state.refusal.detail
        : '';
    status.hidden = status.textContent === '';
    counts.hidden = state === null || state.photographs.reviewed === 0;
    if (state !== null) {
      const { composed, outsideSceneGroups } = state.photographs;
      counts.textContent = [
        composed > 0
          ? `${composed} reviewed photograph${composed === 1 ? '' : 's'} ` +
            `in ${state.regions} place${state.regions === 1 ? '' : 's'}.`
          : '',
        outsideSceneGroups > 0
          ? outsideSceneGroups === 1
            ? '1 reviewed photograph is not in any place, so it is left out.'
            : `${outsideSceneGroups} reviewed photographs are not in any place, so they are left out.`
          : '',
      ].filter(Boolean).join(' ');
    }
    // A name is asked for only where a new saved world will be made under it.
    titleRow.hidden = action === null || state?.savedEntryId !== null;
    make.hidden = action === null;
    make.textContent = action === null ? '' : PERSONAL_WORLD_ACTION_LABELS[action];
    make.disabled = busy || action === null;
  };

  const refresh = async (): Promise<void> => {
    try {
      // A refused press keeps its words on screen through this read; only a new press clears them.
      show(await deps.read());
    } catch (error) {
      show(null);
      status.textContent = entryFailure(error, 'Your photographs could not be checked.');
    }
  };

  make.addEventListener('click', () => {
    const state = current;
    if (state === null || state.action === null || busy) return;
    busy = true;
    failure.hidden = true;
    make.disabled = true;
    status.hidden = false;
    status.textContent = 'Making your world from your photographs…';
    void deps.make(state, title.value.trim() || PERSONAL_WORLD_DEFAULT_TITLE)
      .then((entry) => deps.open(entry))
      .catch(async (error: unknown) => {
        failure.hidden = false;
        failure.textContent = entryFailure(error, 'The world could not be made.');
        busy = false;
        await refresh();
      })
      .finally(() => { busy = false; });
  });

  failure.hidden = true;
  show(null);
  return { root, refresh };
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
  // The server's own words: the detail after the code, never the code itself.
  if (error instanceof ApiError) {
    return error.message.startsWith(`${error.code}: `)
      ? error.message.slice(error.code.length + 2)
      : error.message;
  }
  return error instanceof Error ? error.message : fallback;
}
