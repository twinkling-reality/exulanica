/**
 * The thing card: what Selected says first about anything picked in a world. In a few lines it
 * answers what this is, what it is doing now, what mind runs it and where it came from; the mind
 * can be changed in place. Every word about the thing comes in its model; the card holds only
 * its own frame words, so one card serves every kind of thing.
 */

import { el } from './dom.js';

/** The mark beside the title and the mind: "AI", or where a visitor came from. */
export interface CardMark {
  readonly kind: 'ai' | 'from';
  /** The pill's words: "AI", or "from" and the label the door lists for a visitor's bridge. */
  readonly text: string;
  /** What a screen reader says for it. */
  readonly label: string;
}

/** One mind the card offers when its mind is changed. */
export interface CardMindChoice {
  /** What `onChoose` is called with. */
  readonly key: string;
  readonly name: string;
  readonly line: string;
  /** A short note at its right ("Lowest cost"), or null. */
  readonly badge: string | null;
  readonly now: boolean;
  /** Why it cannot be chosen here, in words, or null. */
  readonly refused: string | null;
}

export interface CardMind {
  /** Who runs it, large: a model's served name, or "Their own routine". */
  readonly name: string;
  readonly line: string;
  readonly mark: CardMark | null;
  /** Empty where its mind cannot be changed here. */
  readonly choices: readonly CardMindChoice[];
  /** Above the choices: "Choose who decides what they do." */
  readonly ask: string;
  /** Under the choices: when a new mind takes over. */
  readonly when: string;
}

export interface ThingCardModel {
  /** Which thing this is: a new subject closes an open choice and forgets the last outcome. */
  readonly subject: string;
  readonly title: string;
  readonly mark: CardMark | null;
  readonly summary: string;
  /** What it is doing, or where it is, now; null leaves the row out. */
  readonly now: string | null;
  readonly mind: CardMind | null;
  readonly cameFrom: string;
}

export interface ThingCardHandlers {
  /** Choose a mind by its key; resolves to what came of it, in words. */
  onChoose(key: string): Promise<string>;
  /** Open every mind in this world (Who decides) with this one chosen. */
  onAllMinds(): void;
  /** Open Compare; null where this world offers no comparison. */
  onCompare: (() => void) | null;
}

export interface ThingCard {
  readonly root: HTMLElement;
  render(model: ThingCardModel): void;
}

function markPill(mark: CardMark): HTMLElement {
  return el('span', {
    class: `thing-card-mark thing-card-mark-${mark.kind}`,
    text: mark.text,
    role: 'img',
    'aria-label': mark.label,
  });
}

export function buildThingCard(handlers: ThingCardHandlers): ThingCard {
  const root = el('section', { class: 'thing-card', 'aria-label': 'What this is' });
  let subject: string | null = null;
  let choosing = false;
  let busy = false;
  let outcome: string | null = null;
  let current: ThingCardModel | null = null;

  const row = (heading: string, extra: readonly Node[] = [], action: HTMLElement | null = null) => {
    const head = el('div', { class: 'thing-card-row-head' }, [el('h4', { text: heading }), ...extra]);
    if (action !== null) head.append(action);
    return el('div', { class: 'thing-card-row' }, [head]);
  };

  function mindRow(mind: CardMind): HTMLElement {
    const changeable = mind.choices.length > 0;
    const toggle = changeable
      ? el('button', {
        type: 'button', class: 'thing-card-change', text: choosing ? 'Done' : 'Change',
        'data-action': 'card.mind.change', 'aria-expanded': String(choosing),
      })
      : null;
    toggle?.addEventListener('click', () => { choosing = !choosing; draw(); });
    const box = row('Mind', mind.mark === null ? [] : [markPill(mind.mark)], toggle);
    if (!choosing) {
      box.append(
        el('p', { class: 'thing-card-mind-name', text: mind.name }),
        el('p', { class: 'thing-card-muted', text: mind.line }),
      );
    } else {
      box.append(el('p', { class: 'thing-card-muted', text: mind.ask }));
      const list = el('div', { class: 'thing-card-choices', role: 'list' });
      for (const choice of mind.choices) {
        const button = el('button', {
          type: 'button', class: 'thing-card-choice', 'data-action': 'card.mind.choose', 'data-key': choice.key,
          role: 'listitem',
        }, [
          el('span', { class: 'thing-card-choice-text' }, [
            el('span', { class: 'thing-card-choice-name', text: choice.name }),
            el('small', { text: choice.refused ?? choice.line }),
            ...(choice.now || choice.badge === null ? [] : [el('span', { class: 'thing-card-badge', text: choice.badge })]),
          ]),
          ...(choice.now ? [el('span', { class: 'thing-card-now-badge', text: 'Now' })] : []),
        ]);
        button.toggleAttribute('data-now', choice.now);
        button.disabled = busy || choice.now || choice.refused !== null;
        button.addEventListener('click', () => { void choose(choice.key); });
        list.append(button);
      }
      box.append(list, el('p', {
        class: 'thing-card-faint', text: busy ? 'Choosing…' : mind.when,
      }));
    }
    if (outcome !== null) box.append(el('p', { class: 'thing-card-outcome', role: 'status', text: outcome }));
    const all = el('button', { type: 'button', class: 'thing-card-link', text: 'All minds in this world', 'data-action': 'card.mind.all' });
    all.addEventListener('click', () => handlers.onAllMinds());
    const links = el('p', { class: 'thing-card-links' }, changeable ? [all] : []);
    if (changeable && handlers.onCompare !== null) {
      const compare = el('button', {
        type: 'button', class: 'thing-card-link', text: 'Compare with another mind', 'data-action': 'card.mind.compare',
      });
      const open = handlers.onCompare;
      compare.addEventListener('click', () => open());
      links.append(compare);
    }
    if (links.childElementCount > 0) box.append(links);
    return box;
  }

  async function choose(key: string): Promise<void> {
    if (busy) return;
    busy = true;
    draw();
    try {
      outcome = await handlers.onChoose(key);
      choosing = false;
    } catch {
      outcome = 'The mind was not changed. Try again in a moment.';
    } finally {
      busy = false;
      draw();
    }
  }

  function draw(): void {
    const model = current;
    if (model === null) { root.replaceChildren(); return; }
    const title = el('div', { class: 'thing-card-title' }, [
      el('h3', { text: model.title }),
      ...(model.mark === null ? [] : [markPill(model.mark)]),
    ]);
    const parts: HTMLElement[] = [title, el('p', { class: 'thing-card-summary', text: model.summary })];
    if (model.now !== null) {
      parts.push(el('p', { class: 'thing-card-now' }, [el('b', { text: 'Now' }), el('span', { text: model.now })]));
    }
    if (model.mind !== null) parts.push(mindRow(model.mind));
    const came = row('Came from');
    came.append(el('p', { text: model.cameFrom }));
    parts.push(came);
    root.replaceChildren(...parts);
    root.dataset['subject'] = model.subject;
  }

  return {
    root,
    render(model) {
      if (model.subject !== subject) {
        subject = model.subject;
        choosing = false;
        outcome = null;
      }
      current = model;
      // A refresh while a choice is out redraws when it settles, from the newest model.
      if (!busy) draw();
    },
  };
}
