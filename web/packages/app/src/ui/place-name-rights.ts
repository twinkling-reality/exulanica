/**
 * Where one place's name can go, said plainly, with a way to allow or stop each use.
 *
 * A place's name stays in Exulanica unless the person who named it allows a use of it, asked for
 * each place. This control shows every use the server offers for one place: the server's own
 * notice, which names the model and where the name would go; what the use means now, in a
 * sentence; and one button, "Allow" or "Stop sending". It is drawn wherever a place shows its
 * confirmed name: the Library's detail pane and the places a Companion answer is about.
 *
 * **Nothing here decides.** The notice is the server's, sent back unchanged to allow it; the
 * state is the server's; and a refusal is shown in words chosen for its kind, never replaced by
 * a guess about what happened. After every decision the control shows what the server read back,
 * not what it expected to be true.
 *
 * **Every state has its sentence, and there is no default.** The sentences are a record keyed by
 * the state vocabulary, so a state added to that vocabulary fails the type check here until
 * somebody writes what it means for a person.
 */

import './place-name-rights.css';
import {
  PlaceNameUnavailable,
  type PlaceNameFailure,
  type PlaceNameRights,
  type PlaceNameRightsSource,
  type PlaceNameUse,
  type PlaceNameUseState,
} from '../place-name-rights-api.js';
import { el, replace } from './dom.js';

export interface PlaceNameRightsOptions {
  /** Spells an ISO instant for a person. Injectable so a test reads one fixed spelling. */
  readonly formatDate?: (iso: string) => string;
  /** 2 in the Library's detail pane; 3 where the control sits under another heading. */
  readonly headingLevel?: 2 | 3;
  /**
   * Draw nothing, rather than a refusal, when the id is not a place in this library. A Companion
   * answer lists the entities it names, and one that is not a place has no name to decide about.
   */
  readonly quietWhenMissing?: boolean;
}

export interface PlaceNameRightsControl {
  readonly root: HTMLElement;
  /** Settles once the first read has been drawn, whatever it found. */
  readonly ready: Promise<void>;
}

const STATE_SENTENCE: Readonly<Record<PlaceNameUseState, (use: PlaceNameUse, date: (iso: string) => string) => string>> = {
  allowed: (use, date) =>
    `Allowed since ${use.since === null ? 'now' : date(use.since)}. The name can be sent until ` +
    `${use.until === null ? 'the term ends' : date(use.until)}, or until you stop it.`,
  not_allowed: () => 'Not allowed. The name is not sent.',
  withdrawn: (use, date) =>
    `Stopped${use.changedAt === null ? '' : ` on ${date(use.changedAt)}`}. The name is not sent.`,
  ended: () => 'The time you allowed has ended, so the name is not sent.',
  name_changed: () =>
    'This place was renamed, merged or removed after you allowed it, so the name is not sent.',
  notice_changed: () =>
    'The wording above changed after you allowed it, so the name is not sent until you allow ' +
    'it again.',
  models_changed: () =>
    'The models changed after you allowed it, so the name is not sent until you allow it again.',
};

const FAILURE_SENTENCE: Readonly<Record<PlaceNameFailure, string>> = {
  missing: 'This place is not in your library.',
  forbidden: 'This session may not change where this name goes.',
  notice_changed:
    'The wording changed while you were reading it. Read it again, then allow it if you still ' +
    'want to.',
  not_yours: 'Only the person who named this place can allow its name to be sent.',
  unnamed: 'This place has no name to send.',
  not_offered: 'Exulanica does not offer that use.',
  busy: 'A question was using names at that moment. Nothing changed. Try again.',
  unreadable: 'The answer could not be read, so nothing is shown as allowed.',
  unreachable: 'Exulanica did not answer. Nothing changed.',
};

const DEFAULT_DATE = (iso: string): string =>
  new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });

function failureOf(error: unknown): PlaceNameFailure {
  return error instanceof PlaceNameUnavailable ? error.kind : 'unreachable';
}

/** The first letter raised, so a purpose reads as a heading. Nothing else is rewritten. */
function asHeading(purpose: string): string {
  return purpose.charAt(0).toUpperCase() + purpose.slice(1);
}

export function buildPlaceNameRights(
  entityId: string,
  source: PlaceNameRightsSource,
  options: PlaceNameRightsOptions = {},
): PlaceNameRightsControl {
  const date = options.formatDate ?? DEFAULT_DATE;
  const headingTag = options.headingLevel === 3 ? 'h3' : 'h2';
  const useTag = options.headingLevel === 3 ? 'h4' : 'h3';
  const root = el('section', {
    class: 'place-name-rights',
    'aria-label': 'Where this place’s name can go',
    'data-entity-id': entityId,
  });
  const status = el('p', { class: 'place-name-status', role: 'status', 'aria-live': 'polite' });
  let busy = false;
  /** The last read drawn, so a refused decision can put the controls back exactly as they were. */
  let last: PlaceNameRights | null = null;

  const say = (text: string): void => {
    status.textContent = text;
  };

  const draw = (rights: PlaceNameRights): void => {
    last = rights;
    const allowedCount = rights.uses.filter((use) => use.allowed).length;
    const title = rights.name === null
      ? 'This place has no name to send'
      : `Where “${rights.name}” can go`;
    const total = rights.uses.length;
    const lede = rights.name === null
      ? 'Nothing about this place can be sent until it has a name you gave it.'
      : allowedCount === 0
        ? 'The name you gave this place stays in Exulanica. It is not sent to any AI model ' +
          'unless you allow it below.'
        : allowedCount < total
          ? `The name you gave this place can be sent for ${allowedCount} of the ${total} uses ` +
            'below, and for nothing else.'
          : total === 1
            ? 'The name you gave this place can be sent for the use below, and for nothing else.'
            : `The name you gave this place can be sent for each of the ${total} uses below, and ` +
              'for nothing else.';
    const list = el('ul', { class: 'place-name-uses' });
    for (const use of rights.uses) {
      const action = el('button', {
        type: 'button',
        class: use.allowed ? 'place-name-stop' : 'place-name-allow primary',
        text: use.allowed ? 'Stop sending' : 'Allow',
        disabled: rights.name === null && !use.allowed,
      });
      action.addEventListener('click', () => {
        void decide(use);
      });
      list.append(el('li', {
        class: 'place-name-use',
        'data-use': use.use,
        'data-state': use.state,
      }, [
        el(useTag, { class: 'place-name-use-title', text: asHeading(use.purpose) }),
        el('p', { class: 'place-name-notice', text: use.notice }),
        el('p', { class: 'place-name-state', text: STATE_SENTENCE[use.state](use, date) }),
        action,
      ]));
    }
    replace(root, [
      el(headingTag, { class: 'place-name-title', text: title }),
      el('p', { class: 'place-name-lede', text: lede }),
      list,
      status,
    ]);
  };

  const refused = (failure: PlaceNameFailure): void => {
    if (failure === 'missing' && options.quietWhenMissing === true) {
      replace(root, []);
      root.hidden = true;
      return;
    }
    say(FAILURE_SENTENCE[failure]);
    if (!root.contains(status)) replace(root, [status]);
  };

  const decide = async (use: PlaceNameUse): Promise<void> => {
    if (busy) return;
    busy = true;
    for (const button of root.querySelectorAll('button')) button.disabled = true;
    say(use.allowed ? 'Stopping…' : 'Allowing…');
    try {
      const after = use.allowed
        ? await source.stop(entityId, use.use)
        : await source.allow(entityId, use.use, use.notice);
      draw(after);
      const now = after.uses.find((each) => each.use === use.use);
      say(now?.allowed === true
        ? 'Allowed. The name can be sent for this use from the next request.'
        : 'Stopped. The name is not sent for this use from the next request.');
    } catch (error) {
      const failure = failureOf(error);
      // The wording or the models moved under the person: show what the server states now, and
      // say why nothing was recorded, so the next click is against words they have read.
      if (failure === 'notice_changed') await load();
      else if (last !== null) draw(last);
      refused(failure);
    } finally {
      busy = false;
    }
  };

  const load = async (): Promise<void> => {
    try {
      draw(await source.load(entityId));
      // The read has arrived, so "reading" is no longer true; the drawn states say the rest.
      say('');
    } catch (error) {
      refused(failureOf(error));
    }
  };

  say('Reading where this name can go…');
  replace(root, [status]);
  return { root, ready: load() };
}
