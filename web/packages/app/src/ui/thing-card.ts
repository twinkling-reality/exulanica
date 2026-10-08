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

/** A link the card shows: its words and where it goes (an https address). */
export interface CardLink {
  readonly text: string;
  readonly href: string;
}

/** One look the card offers when its look is changed: its name, who made it and its licence. */
export interface CardLookChoice {
  /** What `onLook` is called with. */
  readonly key: string;
  readonly name: string;
  readonly line: string;
  readonly now: boolean;
}

/** How it looks: the look's name, who made it and its licence, where it came from, and any credit owed. */
export interface CardLooks {
  readonly name: string;
  readonly line: string;
  readonly source: CardLink | null;
  /** The credit its licence asks for (attribution or share-alike), with a link where there is one. */
  readonly credit: { readonly text: string; readonly href: string | null } | null;
  /** The looks it may be drawn as; absent, or fewer than two, offers no Change. */
  readonly choices?: readonly CardLookChoice[];
}

/** What came of changing a look, in words, and the proof that nothing else changed (null where there is none to show). */
export interface CardLookOutcome {
  readonly words: string;
  readonly proof: string | null;
}

/**
 * One line a being said or heard: who said it to whom in words ("To the traveller", "The knight,
 * to everyone near"), the speaker's mark, the line itself (shown as plain text, never markup) and
 * the world minute it was said in.
 */
export interface CardLine {
  readonly mark: CardMark | null;
  readonly who: string;
  readonly line: string;
  readonly minute: number;
}

/** What came across with a visitor from its game, and what stayed behind, in the game's own words. */
export interface CardCrossing {
  /** Each thing that came across, and why it changed where it did. */
  readonly came: readonly { readonly words: string; readonly reason: string | null }[];
  /** What stayed behind, grouped by the reason it did. */
  readonly stayed: readonly { readonly words: readonly string[]; readonly reason: string }[];
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
  /** Null leaves the row out (a person drawn from the world's people catalog). */
  readonly looks?: CardLooks | null;
  /** What it holds, in words ("a sword"); null leaves the row out. */
  readonly holding?: string | null;
  /** What it can do here, in the abilities catalog's words; empty or absent leaves the row out. */
  readonly can?: readonly string[];
  /** What others can do with it, in the offers catalog's words; empty or absent leaves the row out. */
  readonly offers?: readonly string[];
  /** Its own last lines, newest first; empty or absent leaves the row out. */
  readonly said?: readonly CardLine[];
  /** The last lines it heard, newest first; empty or absent leaves the row out. */
  readonly heard?: readonly CardLine[];
  /** For a visitor: what came across and what stayed behind; null or absent leaves the rows out. */
  readonly crossing?: CardCrossing | null;
  readonly cameFrom: string;
}

export interface ThingCardHandlers {
  /** Choose a mind by its key; resolves to what came of it, in words. */
  onChoose(key: string): Promise<string>;
  /** Open every mind in this world (Who decides) with this one chosen. */
  onAllMinds(): void;
  /** Open Compare; null where this world offers no comparison. */
  onCompare: (() => void) | null;
  /** Draw it in another look, by the look's key; absent where no look can be changed from the card. */
  onLook?(key: string): Promise<CardLookOutcome>;
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
  let lookChoosing = false;
  let lookBusy = false;
  let lookOutcome: CardLookOutcome | null = null;
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

  const link = (target: CardLink): HTMLElement => el('a', {
    class: 'thing-card-link', href: target.href, target: '_blank', rel: 'noopener noreferrer', text: target.text,
  });

  function looksRow(looks: CardLooks): HTMLElement {
    const choices = looks.choices ?? [];
    const changeable = handlers.onLook !== undefined && choices.length > 1;
    const toggle = changeable
      ? el('button', {
        type: 'button', class: 'thing-card-change', text: lookChoosing ? 'Done' : 'Change',
        'data-action': 'card.look.change', 'aria-expanded': String(lookChoosing),
      })
      : null;
    toggle?.addEventListener('click', () => { lookChoosing = !lookChoosing; draw(); });
    const box = row('Looks like', [], toggle);
    if (changeable && lookChoosing) {
      const list = el('div', { class: 'thing-card-choices', role: 'list' });
      for (const choice of choices) {
        const button = el('button', {
          type: 'button', class: 'thing-card-choice', 'data-action': 'card.look.choose', 'data-key': choice.key,
          role: 'listitem',
        }, [
          el('span', { class: 'thing-card-choice-text' }, [
            el('span', { class: 'thing-card-choice-name', text: choice.name }),
            el('small', { text: choice.line }),
          ]),
          ...(choice.now ? [el('span', { class: 'thing-card-now-badge', text: 'Now' })] : []),
        ]);
        button.toggleAttribute('data-now', choice.now);
        button.disabled = lookBusy || choice.now;
        button.addEventListener('click', () => { void chooseLook(choice.key); });
        list.append(button);
      }
      box.append(list, el('p', { class: 'thing-card-faint', text: lookBusy ? 'Changing…' : 'Only how it is drawn changes.' }));
    } else {
      box.append(el('p', { class: 'thing-card-mind-name', text: looks.name }), el('p', { class: 'thing-card-muted', text: looks.line }));
      if (looks.source !== null) box.append(el('p', {}, [link(looks.source)]));
      if (looks.credit !== null) {
        const credit = looks.credit;
        box.append(el('p', { class: 'thing-card-credit' }, [credit.href === null ? credit.text : link({ text: credit.text, href: credit.href })]));
      }
    }
    if (lookOutcome !== null) {
      box.append(el('p', { class: 'thing-card-outcome', role: 'status', text: lookOutcome.words }));
      if (lookOutcome.proof !== null) {
        box.append(el('details', { class: 'thing-card-proof' }, [
          el('summary', { text: 'How we know' }),
          el('p', { class: 'thing-card-muted', text: lookOutcome.proof }),
        ]));
      }
    }
    return box;
  }

  /** A row of short phrases in the catalogs' own words. */
  function wordsRow(heading: string, words: readonly string[]): HTMLElement {
    const box = row(heading);
    box.append(el('ul', { class: 'thing-card-chips' }, words.map((phrase) => el('li', { text: phrase }))));
    return box;
  }

  function linesRow(heading: string, lines: readonly CardLine[]): HTMLElement {
    const box = row(heading);
    const list = el('ol', { class: 'thing-card-lines' });
    for (const said of lines) {
      list.append(el('li', { class: 'thing-card-line' }, [
        el('p', { class: 'thing-card-line-who' }, [
          ...(said.mark === null ? [] : [markPill(said.mark)]),
          el('span', { text: said.who }),
          el('span', { class: 'thing-card-faint', text: `minute ${said.minute}` }),
        ]),
        el('p', { class: 'thing-card-line-text', text: said.line }),
      ]));
    }
    box.append(list);
    return box;
  }

  function crossingRows(crossing: CardCrossing): HTMLElement[] {
    const rows: HTMLElement[] = [];
    if (crossing.came.length > 0) {
      const box = row('Came across');
      const list = el('ul', { class: 'thing-card-crossing' });
      for (const came of crossing.came) {
        list.append(el('li', {}, [
          el('p', { text: came.words }),
          ...(came.reason === null ? [] : [el('p', { class: 'thing-card-muted', text: came.reason })]),
        ]));
      }
      box.append(list);
      rows.push(box);
    }
    if (crossing.stayed.length > 0) {
      const box = row('Stayed behind');
      const list = el('ul', { class: 'thing-card-crossing' });
      for (const stayed of crossing.stayed) {
        list.append(el('li', {}, [
          el('p', { text: stayed.words.join('; ') }),
          el('p', { class: 'thing-card-muted', text: stayed.reason }),
        ]));
      }
      box.append(list);
      rows.push(box);
    }
    return rows;
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

  async function chooseLook(key: string): Promise<void> {
    const onLook = handlers.onLook;
    if (lookBusy || onLook === undefined) return;
    lookBusy = true;
    lookOutcome = null;
    draw();
    try {
      lookOutcome = await onLook(key);
      lookChoosing = false;
    } catch {
      lookOutcome = { words: 'The look was not changed. Try again in a moment.', proof: null };
    } finally {
      lookBusy = false;
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
    if (model.looks != null) parts.push(looksRow(model.looks));
    if (model.holding != null) {
      const holding = row('Holding');
      holding.append(el('p', { text: model.holding }));
      parts.push(holding);
    }
    if (model.can !== undefined && model.can.length > 0) parts.push(wordsRow('Can', model.can));
    if (model.offers !== undefined && model.offers.length > 0) parts.push(wordsRow('With it', model.offers));
    if (model.crossing != null) parts.push(...crossingRows(model.crossing));
    if (model.said !== undefined && model.said.length > 0) parts.push(linesRow('Said lately', model.said));
    if (model.heard !== undefined && model.heard.length > 0) parts.push(linesRow('Heard lately', model.heard));
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
        lookChoosing = false;
        lookOutcome = null;
      }
      current = model;
      // A refresh while a choice is out redraws when it settles, from the newest model.
      if (!busy && !lookBusy) draw();
    },
  };
}
