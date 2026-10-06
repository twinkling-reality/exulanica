/** Choosing between saved worlds. The one-world states live in `ui/startup-state.ts`. */

import { tierPolicy } from '@exulanica/companion-runtime';
import { ApiError } from '@exulanica/graph-client';
import type {
  PersonalWorldAction,
  PersonalWorldState,
  SavedWorldEntry,
} from '../world-entry-api.js';
import { fill, say } from '../ui/copy.js';
import { el } from '../ui/dom.js';
import '../ui/your-worlds.css';

export interface WorldEntrySurface {
  readonly entries: readonly SavedWorldEntry[];
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
   * Opens Create a world holding the values a generated world was made with, so a new world can be
   * made from them; the world itself never changes. Absent where nothing can be made.
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
}

const DAY = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' });
const SHORT_DAY = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' });

/** The values a generated world was made with, as its entry serves them, or null where there are none. */
function valuesOf(entry: SavedWorldEntry): Readonly<Record<string, number | string>> | null {
  return entry.generatedGround?.values ?? null;
}

/** A day as a person reads it, from an ISO time the server served; null when it is not one. */
function servedDay(iso: string, format: Intl.DateTimeFormat): string | null {
  const time = Date.parse(iso);
  return Number.isNaN(time) ? null : format.format(time);
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

/** What kind of world an entry is, and that it keeps its changes: a card's detail, said once. */
function worldKind(entry: SavedWorldEntry): string {
  if (entry.generatedGround != null) return fill('world.entry.generated', { recipe: entry.generatedGround.recipeLabel });
  if (entry.generatedSite != null) return fill('world.entry.generated', { recipe: entry.generatedSite.kindLabel });
  return `${say(entry.sourceKind === 'authored' ? 'yourWorlds.kind.authored' : 'yourWorlds.kind.personal')}`
    + ' · saved changes and appearance';
}

/** The sentence under a world's title: what it is, and that it opens where it was left. */
function worldAbout(entry: SavedWorldEntry): string {
  if (entry.availability !== 'available') return unavailableMessage(entry.unavailableReason);
  if (entry.generatedGround != null) {
    const label = entry.generatedGround.recipeLabel;
    return fill('yourWorlds.about.generated', { recipe: label.charAt(0).toLowerCase() + label.slice(1) });
  }
  if (entry.generatedSite != null) return fill('yourWorlds.about.site', { kind: entry.generatedSite.kindLabel });
  return entry.sourceKind === 'authored'
    ? (entry.currentAuthoredEditSeq === 0 ? say('yourWorlds.about.starter') : say('yourWorlds.about.authored'))
    : say('yourWorlds.about.personal');
}

const kbd = (text: string): HTMLElement => el('kbd', { text });

/** Whether a key press belongs to a field a person is typing in, where no shortcut may fire. */
function typing(target: EventTarget | null): boolean {
  return target instanceof HTMLElement
    && (target.isContentEditable || target.closest('input, textarea, select') !== null);
}

/**
 * Your worlds: the first thing a signed-in person sees, before any world opens.
 *
 * The chosen world is named large with what it is, when it was established and its actions; under
 * it a strip of cards holds every saved world, newest first, and Create a world. Moving to a card
 * (pointer or arrow keys) chooses it; pressing a card, or Open, opens it. A person whose only world
 * is the untouched starter is asked to create one instead. Keys: arrows choose, Enter opens, N
 * creates; none fires while a person types.
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
  const first = onlyUntouchedStarter(entries);
  const arrivalFailure = deps.arrivalFailure ?? null;
  const status = el('p', {
    class: 'gate-failure world-entry-status your-worlds-status', role: 'status', 'aria-live': 'polite',
  });
  status.hidden = arrivalFailure === null;
  if (arrivalFailure !== null) status.textContent = arrivalFailure;

  const heading = el('h1', { class: 'your-worlds-title' });
  const about = el('p', { class: 'your-worlds-about' });
  const meta = el('p', { class: 'your-worlds-meta' });
  const openButton = el('button', { type: 'button', class: 'your-worlds-open', 'data-action': 'worlds.open' }, [
    el('span', { text: say('yourWorlds.open') }), kbd('↵'),
  ]);
  const values = el('button', {
    type: 'button', class: 'your-worlds-secondary your-worlds-values', 'data-action': 'worlds.values',
    'aria-describedby': 'your-worlds-values-why',
  }, [el('span', { text: say('yourWorlds.values') }), kbd('V')]);
  const valuesWhy = el('span', { id: 'your-worlds-values-why', class: 'your-worlds-hint', text: say('yourWorlds.values.none') });
  const createButton = el('button', {
    type: 'button', class: 'your-worlds-secondary your-worlds-create-action', 'data-action': 'worlds.create',
  }, [el('span', { text: say('yourWorlds.create') }), kbd('N')]);
  const reconcile = el('div', { class: 'your-worlds-reconcile' });
  const actions = el('div', { class: 'your-worlds-actions' }, [openButton, values, createButton]);

  const lede = el('section', { class: 'your-worlds-lede', 'aria-live': 'polite', 'aria-atomic': 'false' }, [
    el('p', { class: 'your-worlds-overline' }),
    heading, about, actions, valuesWhy, meta, status, reconcile,
  ]);
  const list = el('section', { class: 'world-entry-list your-worlds-strip', 'aria-label': say('yourWorlds.strip') });
  const keys = el('p', { class: 'your-worlds-keys', 'aria-hidden': 'true' }, [
    el('span', {}, [kbd('← →'), say('yourWorlds.key.choose')]),
    el('span', {}, [kbd('↵'), say('yourWorlds.key.open')]),
    el('span', { class: 'your-worlds-key-create' }, [kbd('N'), say('yourWorlds.create')]),
  ]);
  const corner = el('header', { class: 'your-worlds-corner' }, [
    el('span', { class: 'your-worlds-mark', 'aria-hidden': 'true' }, [el('i'), el('i')]),
    el('span', { class: 'your-worlds-rule', 'aria-hidden': 'true' }),
    el('p', { class: 'world-entry-brand your-worlds-label' }, [
      el('span', { text: 'Exulanica' }), el('span', { text: say('yourWorlds.label') }),
    ]),
  ]);
  // The chosen world's picture behind the page, faded into it at the edges; two layers so a new
  // choice fades in over the last. A world with no picture shows the plain page.
  const layers = [el('img', { alt: '', decoding: 'async' }), el('img', { alt: '', decoding: 'async' })];
  const backdrop = el('div', { class: 'your-worlds-backdrop', 'aria-hidden': 'true' }, layers);
  let front = 0;
  const showBackdrop = (picture: string | null): void => {
    const current = layers[front]!;
    if (picture === null) {
      for (const layer of layers) layer.classList.remove('is-shown');
      root.dataset['backdrop'] = 'none';
      return;
    }
    root.dataset['backdrop'] = 'picture';
    if (current.classList.contains('is-shown') && current.getAttribute('src') === picture) return;
    front = 1 - front;
    const next = layers[front]!;
    next.setAttribute('src', picture);
    next.classList.add('is-shown');
    current.classList.remove('is-shown');
  };
  const root = el('main', {
    class: 'gate world-entry-gate your-worlds', 'data-variant': first ? 'first' : 'worlds',
    // The way in is a stage: dark in every scheme (tokens.css), as the world keeps its own light.
    'data-ui-stage': 'dark',
  }, [backdrop, corner, keys, lede, list]);

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

  const overline = lede.querySelector('.your-worlds-overline') as HTMLElement;
  const choose = (entry: SavedWorldEntry): void => {
    if (chosen === entry) return;
    chosen = entry;
    for (const card of cards) card.setAttribute('aria-current', String(card.dataset['entryId'] === entry.entryId));
    overline.textContent = first ? '' : fill('yourWorlds.position', {
      position: String(entries.indexOf(entry) + 1), count: String(entries.length),
    });
    heading.textContent = first ? say('yourWorlds.first.title') : entry.title;
    about.textContent = first ? say('yourWorlds.first.about') : worldAbout(entry);
    const established = servedDay(entry.createdAt, DAY);
    meta.replaceChildren(...[
      established === null ? null : el('b', { text: fill('yourWorlds.established', { day: established }) }),
      el('span', {
        text: entry.generatedGround != null
          ? fill('yourWorlds.from', { recipe: entry.generatedGround.recipeLabel })
          : entry.generatedSite != null
          ? fill('yourWorlds.from', { recipe: entry.generatedSite.kindLabel })
          : say(entry.sourceKind === 'authored' ? 'yourWorlds.kind.authored' : 'yourWorlds.kind.personal'),
      }),
    ].filter((part): part is HTMLElement => part !== null));
    openButton.disabled = entry.availability !== 'available';
    openButton.querySelector('span')!.textContent = first
      ? fill('yourWorlds.openNamed', { title: entry.title })
      : say('yourWorlds.open');
    // With only the untouched starter, creating is the action asked for and opening the starter
    // the alternative, so the two swap places and weight.
    actions.dataset['primary'] = first ? 'create' : 'open';
    showBackdrop(first ? null : deps.picture?.(entry) ?? null);
    values.hidden = entry.generatedGround == null || deps.viewValues === undefined;
    const viewable = valuesOf(entry) !== null;
    values.setAttribute('aria-disabled', String(!viewable));
    valuesWhy.hidden = values.hidden || viewable;
    showReconcile(entry);
  };

  for (const entry of entries) {
    const picture = deps.picture?.(entry) ?? null;
    const established = servedDay(entry.createdAt, SHORT_DAY);
    const unavailable = entry.availability !== 'available';
    const card = el('button', {
      type: 'button', class: 'world-entry-choice your-worlds-card', 'data-entry-id': entry.entryId,
      'aria-disabled': unavailable ? 'true' : undefined,
    }, [
      el('span', { class: 'your-worlds-picture', 'aria-hidden': 'true' }, picture === null ? [] : [
        el('img', { src: picture, alt: '', loading: 'lazy', decoding: 'async' }),
      ]),
      el('span', { class: 'your-worlds-caption', text: established === null ? '' : fill('yourWorlds.caption', { day: established }) }),
      el('span', { class: 'world-entry-choice-title', text: entry.title }),
      el('span', {
        class: 'world-entry-choice-detail',
        text: unavailable ? unavailableMessage(entry.unavailableReason) : worldKind(entry),
      }),
    ]);
    card.addEventListener('focus', () => choose(entry));
    card.addEventListener('pointerenter', () => choose(entry));
    card.addEventListener('click', () => {
      choose(entry);
      openEntry(entry, card);
    });
    cards.push(card);
    list.append(el('article', { class: 'world-entry-item' }, [card]));
  }

  const createCard = el('button', {
    type: 'button', class: 'your-worlds-card your-worlds-create', 'data-action': 'worlds.create-card',
  }, [
    el('span', { class: 'your-worlds-picture', 'aria-hidden': 'true' }, [el('span', { class: 'your-worlds-plus', text: '+' })]),
    el('span', { class: 'your-worlds-caption', text: say('yourWorlds.create.caption') }),
    el('span', { class: 'world-entry-choice-title', text: say('yourWorlds.create') }),
    el('span', { class: 'world-entry-choice-detail your-worlds-create-detail', text: say('yourWorlds.create.detail') }),
  ]);
  list.append(el('article', { class: 'world-entry-item' }, [createCard]));

  const create = (): void => {
    if (deps.create === undefined) return;
    if (!createOffered()) {
      status.hidden = false;
      status.textContent = createState.words?.happened ?? say('yourWorlds.create.unavailable');
      return;
    }
    deps.create();
  };
  createCard.addEventListener('click', create);
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
    deps.viewValues?.(chosen);
  };
  values.addEventListener('click', viewValues);

  root.addEventListener('keydown', (event) => {
    if (event.metaKey || event.ctrlKey || event.altKey || typing(event.target)) return;
    const all = [...cards, createCard];
    const at = all.indexOf(document.activeElement as HTMLButtonElement);
    if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
      event.preventDefault();
      const step = event.key === 'ArrowRight' ? 1 : -1;
      const from = at >= 0 ? at : Math.max(0, cards.findIndex((card) => card.dataset['entryId'] === chosen?.entryId));
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
    if (event.key === 'Enter' && !(event.target instanceof HTMLButtonElement) && chosen !== null) {
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
    for (const control of [createCard, createButton]) {
      if (offered) control.removeAttribute('aria-disabled');
      else control.setAttribute('aria-disabled', 'true');
    }
    createCard.hidden = deps.create === undefined;
    createButton.hidden = deps.create === undefined;
    (keys.querySelector('.your-worlds-key-create') as HTMLElement).hidden = deps.create === undefined;
    const detail = createCard.querySelector('.your-worlds-create-detail') as HTMLElement;
    detail.textContent = offered || state.words === null ? say('yourWorlds.create.detail') : state.words.happened;
  };
  setCreate(createState);
  if (entries[0] !== undefined) choose(entries[0]);
  // The first world's own card is the button of record when it is the untouched starter: creating
  // is the action asked for, opening the starter the alternative.
  root.dataset['first'] = String(first);
  return { root, setCreate };
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
      show(null);
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
