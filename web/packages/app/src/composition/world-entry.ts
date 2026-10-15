import { button } from '../ui/system/components.js';
/** Choosing between saved worlds. The one-world states live in `ui/startup-state.ts`. */

import { tierPolicy } from '@exulanica/companion-runtime';
import { ApiError } from '@exulanica/graph-client';
import type {
  PersonalWorldAction,
  PersonalWorldState,
  SavedWorldEntry,
} from '../world-entry-api.js';
import { say } from '../ui/copy.js';
import { el, commandAction } from '../ui/dom.js';
import { buildGenerationDetails } from '../ui/generation-details.js';
import '../ui/your-worlds.css';

export interface WorldEntrySurface {
  readonly entries: readonly SavedWorldEntry[];
  readonly initialEntryId?: string;
  readonly open: (entry: SavedWorldEntry) => Promise<void>;
  readonly adoptLatest: (entry: SavedWorldEntry) => Promise<void>;
  /**
   * Why no world opened, when that is known. A person reaching the list has a choice to make
   * either way, so this is a line under the chosen world rather than the subject of the screen.
   */
  readonly arrivalFailure?: string | null;
  /** The offer to make a world from reviewed photographs, placed after the saved worlds. */
  readonly personalWorld?: PersonalWorldControl;
  /** Opens Create a world; absent where no saved worlds are served. */
  readonly create?: () => void;
  /** A picture of a saved world, or null where there is none to show. */
  readonly picture?: (entry: SavedWorldEntry) => string | null;
  /**
   * Opens the saved generation parameters for inspection. Creating a new world from them is a
   * separate action; the world itself never changes. Absent where nothing can be shown.
   */
  readonly viewValues?: (entry: SavedWorldEntry) => void;
}

/** What Your worlds offers for making a world, as the action registry reads it from the server. */
export interface WorldEntryCreateState {
  readonly state: string;
  readonly words: { readonly happened: string } | null;
}

export interface WorldEntrySurfaceHandle {
  readonly root: HTMLElement;
  /** Whether Create a world is offered, and why not where it is refused. */
  setCreate(state: WorldEntryCreateState): void;
  /** Draw each card's picture again, as `picture` answers now. */
  refreshPictures(): void;
}

/** The values a generated world was made with, as its entry serves them, or null where there are none. */
function valuesOf(entry: SavedWorldEntry): Readonly<Record<string, number | string>> | null {
  return entry.generatedGround?.values ?? null;
}

/**
 * The starter every workspace is given, untouched: a person who has it and nothing else has not
 * made a world yet, so Your worlds asks them to create one rather than to choose.
 */
export function onlyUntouchedStarter(entries: readonly SavedWorldEntry[]): boolean {
  const only = entries.length === 1 ? entries[0]! : null;
  return only !== null && only.sourceKind === 'authored' && only.authoredScene !== null
    && only.currentAuthoredEditSeq === 0;
}

/** Whether a key press belongs to a field a person is typing in, where no shortcut may fire. */
function typing(target: EventTarget | null): boolean {
  return target instanceof HTMLElement
    && (target.isContentEditable || target.closest('input, textarea, select') !== null);
}

/**
 * Your worlds: the first thing a signed-in person sees, before any world opens.
 *
 * The chosen world is named large with Open World and View Parameters. A strip holds saved
 * worlds newest first. Create World sits below the selected world's actions. Clicking a card selects it; Open World, Enter or a double click opens it. Keys: arrows choose, Enter opens, N creates; none fires in a field.
 *
 * Opening a world that fails says why in the status line under the title and leaves the choice
 * open. A world changed elsewhere keeps its reconciliation: the acknowledgement and the adopt
 * button sit under the title while that world is chosen.
 */
export function buildWorldEntrySurface(deps: WorldEntrySurface): HTMLElement {
  return buildYourWorlds(deps).root;
}

export function buildYourWorlds(deps: WorldEntrySurface): WorldEntrySurfaceHandle {
  const entries = [...deps.entries].sort((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt));
  const arrivalFailure = deps.arrivalFailure ?? null;
  const status = el('p', {
    class: 'gate-failure world-entry-status your-worlds-status', role: 'status', 'aria-live': 'polite',
  });
  status.hidden = arrivalFailure === null;
  if (arrivalFailure !== null) status.textContent = arrivalFailure;

  const heading = el('h1', { class: 'your-worlds-title', text: 'Your worlds' });
  const openButton = button({ label: say('yourWorlds.open'), variant: 'primary', size: 'lg', className: 'your-worlds-open' });
  openButton.dataset['action'] = 'worlds.open';
  openButton.setAttribute('aria-keyshortcuts', 'Enter');
  const values = button({ label: say('yourWorlds.values'), size: 'lg', className: 'your-worlds-values' });
  values.dataset['action'] = 'worlds.values';
  values.setAttribute('aria-describedby', 'your-worlds-values-why');
  values.setAttribute('aria-keyshortcuts', 'V');
  const valuesWhy = el('span', { id: 'your-worlds-values-why', class: 'your-worlds-hint', text: say('yourWorlds.values.none') });
  const createButton = button({ label: say('yourWorlds.create'), variant: 'secondary', size: 'lg', className: 'your-worlds-create' });
  createButton.dataset['action'] = 'worlds.create';
  createButton.setAttribute('aria-keyshortcuts', 'N');
  for (const control of [openButton, values, createButton]) control.classList.add('entry-command');
  openButton.replaceChildren(...commandAction('↵', say('yourWorlds.open')));
  values.replaceChildren(...commandAction('V', say('yourWorlds.values')));
  createButton.replaceChildren(...commandAction('N', say('yourWorlds.create')));
  const reconcile = el('div', { class: 'your-worlds-reconcile' });
  const actions = el('div', { class: 'your-worlds-actions' }, [openButton, values]);

  const lede = el('section', { class: 'your-worlds-lede', 'aria-live': 'polite', 'aria-atomic': 'false' }, [
    actions, valuesWhy,
    el('div', { class: 'your-worlds-create-row' }, [createButton]),
    status, reconcile,
  ]);
  const list = el('section', { class: 'world-entry-list your-worlds-strip', 'aria-label': say('yourWorlds.strip') });
  const corner = el('header', { class: 'your-worlds-corner' }, [
    el('p', { class: 'world-entry-brand your-worlds-wordmark', text: 'exulanica' }),
    heading,
  ]);
  const root = el('main', {
    class: 'gate world-entry-gate your-worlds entry-surface',
  }, [corner, list, lede]);

  const cards: HTMLButtonElement[] = [];
  let chosen: SavedWorldEntry | null = null;
  let createState: WorldEntryCreateState = { state: deps.create === undefined ? 'unsupported' : 'unknown', words: null };
  let busy = false;

  const createOffered = (): boolean => deps.create !== undefined
    && (createState.state === 'available' || createState.state === 'unknown');

  const openEntry = (entry: SavedWorldEntry, control: HTMLButtonElement): void => {
    if (busy) return;
    if (entry.availability !== 'available') {
      status.hidden = false;
      status.textContent = unavailableMessage(entry.unavailableReason);
      return;
    }
    busy = true;
    status.hidden = true;
    control.setAttribute('aria-busy', 'true');
    openButton.disabled = true;
    root.dataset['state'] = 'opening';
    void deps.open(entry).catch((error: unknown) => {
      status.hidden = false;
      status.textContent = entryFailure(error, 'The saved world could not be opened.');
    }).finally(() => {
      busy = false;
      control.removeAttribute('aria-busy');
      openButton.disabled = chosen === null || chosen.availability !== 'available';
      delete root.dataset['state'];
    });
  };

  const showReconcile = (entry: SavedWorldEntry): void => {
    reconcile.replaceChildren();
    if (entry.unavailableReason !== 'authored_version_changed') return;
    const acknowledge = el('input', { type: 'checkbox' }) as HTMLInputElement;
    const adopt = el('button', {
      type: 'button', class: 'world-entry-secondary your-worlds-secondary',
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
    reconcile.append(el('section', { class: 'world-entry-reconcile' }, [
      el('p', {
        text: `Your opening point includes ${entry.authoredEditSeq} saved changes. `
          + `The latest state includes ${entry.currentAuthoredEditSeq}.`,
      }),
      el('label', {}, [acknowledge, ' I understand this will use changes saved elsewhere.']),
      adopt,
    ]));
  };

  const choose = (entry: SavedWorldEntry): void => {
    if (chosen === entry) return;
    chosen = entry;
    for (const card of cards) card.setAttribute('aria-current', String(card.dataset['entryId'] === entry.entryId));
    openButton.setAttribute('aria-label', `Open ${entry.title}`);
    openButton.disabled = entry.availability !== 'available';

    if (entry.availability !== 'available') {
      status.hidden = false;
      status.textContent = unavailableMessage(entry.unavailableReason);
    } else {
      status.hidden = arrivalFailure === null;
      status.textContent = arrivalFailure ?? '';
    }
    values.hidden = entry.generatedGround == null || deps.viewValues === undefined;
    const viewable = valuesOf(entry) !== null;
    values.setAttribute('aria-disabled', String(!viewable));
    valuesWhy.hidden = values.hidden || viewable;
    showReconcile(entry);
  };

  for (const entry of entries) {
    const picture = deps.picture?.(entry) ?? null;
    const unavailable = entry.availability !== 'available';
    const card = el('button', {
      type: 'button', class: 'world-entry-choice your-worlds-card', 'data-entry-id': entry.entryId,
      'aria-disabled': unavailable ? 'true' : undefined,
    }, [
      el('span', { class: 'your-worlds-picture', 'aria-hidden': 'true' }, picture === null ? [] : [
        el('img', { src: picture, alt: '', loading: 'lazy', decoding: 'async' }),
      ]),
      el('span', { class: 'world-entry-choice-title', text: entry.title }),
      ...(unavailable ? [el('span', {
        class: 'world-entry-choice-detail', text: unavailableMessage(entry.unavailableReason),
      })] : []),
    ]);
    const current = (): SavedWorldEntry => entries.find(item => item.entryId === entry.entryId)!;
    card.addEventListener('focus', () => choose(current()));
    card.addEventListener('click', () => choose(current()));
    card.addEventListener('dblclick', () => openEntry(current(), card));
    cards.push(card);
    list.append(el('article', { class: 'world-entry-item' }, [card]));
  }

  const create = (): void => {
    if (deps.create === undefined) return;
    if (!createOffered()) {
      status.hidden = false;
      status.textContent = createState.words?.happened ?? say('yourWorlds.create.unavailable');
      return;
    }
    deps.create();
  };
  createButton.addEventListener('click', create);
  openButton.addEventListener('click', () => {
    if (chosen === null) return;
    const card = cards.find((one) => one.dataset['entryId'] === chosen!.entryId);
    if (card !== undefined) openEntry(chosen, card);
  });
  const viewValues = (): void => {
    if (chosen === null || values.hidden) return;
    if (valuesOf(chosen) === null) {
      status.hidden = false;
      status.textContent = say('yourWorlds.values.none');
      return;
    }
    const entry = chosen;
    buildGenerationDetails({ entry, ...(deps.viewValues === undefined ? {} : {
      createFrom: () => deps.viewValues!(entry),
    }) }).show();
  };
  values.addEventListener('click', viewValues);

  root.addEventListener('keydown', (event) => {
    if (event.metaKey || event.ctrlKey || event.altKey || typing(event.target)) return;
    const all = [...cards, createButton];
    const at = all.indexOf(document.activeElement as HTMLButtonElement);
    if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
      event.preventDefault();
      const step = event.key === 'ArrowRight' ? 1 : -1;
      const from = at >= 0 ? at : Math.max(0, all.findIndex((card) => card.dataset['entryId'] === chosen?.entryId));
      all[Math.min(all.length - 1, Math.max(0, from + step))]?.focus();
      return;
    }
    if ((event.key === 'v' || event.key === 'V') && !event.shiftKey) {
      event.preventDefault();
      viewValues();
      return;
    }
    if ((event.key === 'n' || event.key === 'N') && !event.shiftKey) {
      event.preventDefault();
      create();
      return;
    }
    // Enter on a focused control is that control's own press; elsewhere it opens the chosen world.
    if (event.key === 'Enter' && (!(event.target instanceof HTMLButtonElement) || event.target.classList.contains('your-worlds-card')) && chosen !== null) {
      event.preventDefault();
      openButton.click();
    }
  });

  if (deps.personalWorld !== undefined) {
    root.append(el('section', { class: 'your-worlds-more' }, [deps.personalWorld.root]));
  }

  const setCreate = (state: WorldEntryCreateState): void => {
    createState = state;
    const offered = createOffered();
    root.dataset['create'] = deps.create === undefined ? 'unsupported' : state.state;
    for (const control of [createButton]) {
      if (offered) control.removeAttribute('aria-disabled');
      else control.setAttribute('aria-disabled', 'true');
    }
    createButton.hidden = deps.create === undefined;

  };
  setCreate(createState);
  const refreshPictures = (): void => {
    for (const card of cards) {
      const entry = entries.find(item => item.entryId === card.dataset['entryId']);
      const picture = entry === undefined ? null : deps.picture?.(entry) ?? null;
      const frame = card.querySelector('.your-worlds-picture');
      const shown = frame?.querySelector('img') ?? null;
      if (frame === null || picture === null || shown?.getAttribute('src') === picture) continue;
      if (shown !== null) shown.src = picture;
      else frame.append(el('img', { src: picture, alt: '', loading: 'lazy', decoding: 'async' }));
    }
  };
  const initial = entries.find(entry => entry.entryId === deps.initialEntryId) ?? entries[0];
  if (initial !== undefined) choose(initial);
  return { root, setCreate, refreshPictures };
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
  add_photographs: 'Add my new photographs as places',
};

/**
 * Adding photographs to a made world changes more than one place and carries everything the person
 * made into a new version, so it is confirmed the way interaction-model.md section 5.3 asks of a
 * tier 2 consequence: its blast radius stated first, separate Cancel and Confirm, and Confirm
 * enabled only after the delay the tier policy states once.
 */
const ADDITION_CONFIRM_DELAY_MS = tierPolicy(2).confirmEnabledAfterMs;

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
 *
 * Adding photographs to a made world is confirmed first. Pressing the button writes nothing: it
 * shows the server's preview, every sentence as the server wrote it, with Cancel and Confirm.
 * Cancel returns to the offer and sends nothing; Confirm is enabled after the tier 2 delay and
 * sends back the digest of exactly the preview on screen.
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
  const previewList = el('ul', { class: 'personal-world-preview' });
  const cancel = el('button', {
    type: 'button', class: 'personal-world-cancel', text: 'Cancel',
  });
  const confirm = el('button', {
    type: 'button', class: 'personal-world-confirm-add', text: 'Confirm: add them as places',
  });
  const confirmation = el('section', {
    class: 'personal-world-confirm', 'aria-label': 'What adding your photographs as places does',
  }, [previewList, el('div', { class: 'personal-world-confirm-controls' }, [cancel, confirm])]);
  const failure = el('p', { class: 'gate-failure personal-world-failure', role: 'alert' });
  const root = el('section', {
    class: 'personal-world-choice', 'aria-label': 'A world from your photographs',
  }, [
    el('h3', { text: 'A world from your photographs' }),
    status, counts, titleRow, make, confirmation, failure,
  ]);
  let current: PersonalWorldState | null = null;
  let busy = false;
  let arming: ReturnType<typeof setTimeout> | null = null;

  const closeConfirmation = (): void => {
    if (arming !== null) clearTimeout(arming);
    arming = null;
    confirmation.hidden = true;
    confirm.disabled = true;
    previewList.replaceChildren();
  };

  const show = (state: PersonalWorldState | null): void => {
    closeConfirmation();
    current = state;
    root.dataset['state'] = state === null ? 'unknown' : state.action ?? 'refused';
    const action = state?.action ?? null;
    // The library offers photographs only when there is something to act on. Keep failures of
    // an attempted action visible, including after the server refreshes an empty source.
    root.hidden = action === null && (state === null || state.photographs.reviewed === 0) && failure.hidden;
    status.textContent = state === null
      ? 'Checking your reviewed photographs…'
      : state.refusal !== null
        ? state.refusal.detail
        : '';
    status.hidden = status.textContent === '';
    counts.hidden = state === null || state.photographs.reviewed === 0;
    if (state !== null && state.preview !== null) {
      // What adding does is the server's to say; its first sentence is the offer's count.
      counts.textContent = state.preview.sentences[0] ?? '';
    } else if (state !== null) {
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
      // A person whose access holds no photographs (a guest) is offered nothing about them.
      if (error instanceof ApiError && error.status === 403 && error.code === 'not_authorised') {
        root.hidden = true;
        return;
      }
      show(null);
      root.hidden = false;
      status.textContent = entryFailure(error, 'Your photographs could not be checked.');
    }
  };

  const commit = (state: PersonalWorldState): void => {
    busy = true;
    failure.hidden = true;
    make.disabled = true;
    status.hidden = false;
    status.textContent = state.action === 'add_photographs'
      ? 'Adding your photographs to your world…'
      : 'Making your world from your photographs…';
    closeConfirmation();
    void deps.make(state, title.value.trim() || PERSONAL_WORLD_DEFAULT_TITLE)
      .then((entry) => deps.open(entry))
      .catch(async (error: unknown) => {
        failure.hidden = false;
        failure.textContent = entryFailure(error, 'The world could not be made.');
        busy = false;
        await refresh();
      })
      .finally(() => { busy = false; });
  };

  make.addEventListener('click', () => {
    const state = current;
    if (state === null || state.action === null || busy) return;
    if (state.preview === null) {
      commit(state);
      return;
    }
    // Nothing is written yet: the preview, then a choice. The offer's button goes away, so
    // Confirm is not under the pointer that pressed it, and it wakes only after the delay.
    failure.hidden = true;
    make.hidden = true;
    // The offer's line is the preview's first sentence, which the list below says again.
    counts.hidden = true;
    previewList.replaceChildren(
      ...state.preview.sentences.map((sentence) => el('li', { text: sentence })),
    );
    confirmation.hidden = false;
    confirm.disabled = true;
    arming = setTimeout(() => {
      arming = null;
      confirm.disabled = false;
    }, ADDITION_CONFIRM_DELAY_MS);
  });

  cancel.addEventListener('click', () => {
    if (busy) return;
    show(current);
  });

  confirm.addEventListener('click', () => {
    const state = current;
    if (state === null || state.preview === null || busy || confirm.disabled) return;
    commit(state);
  });

  failure.hidden = true;
  closeConfirmation();
  show(null);
  return { root, refresh };
}

/** The reasons a generated world is served unavailable: its receipt no longer generates it. */
const GENERATED_UNREADABLE: ReadonlySet<string> = new Set([
  'generated_world_grammar_changed',
  'generated_world_catalogs_changed',
  'generated_world_output_changed',
  'generated_world_land_changed',
  'generated_world_land_rules_changed',
  'generated_world_landscape_changed',
  'generated_world_landscape_rules_changed',
  'generated_world_unreadable',
]);

function unavailableMessage(reason: string | null): string {
  return reason === 'source_deleted'
    ? 'Its source material was deleted. The saved record remains, but it cannot be opened.'
    : reason === 'authored_version_changed'
      ? 'Its saved changes were updated elsewhere. Reconcile that update before opening it.'
      : reason !== null && GENERATED_UNREADABLE.has(reason)
        ? say('world.entry.generated-unreadable')
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
