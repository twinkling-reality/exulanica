import type { Turn, TurnOption } from '@exulanica/companion-runtime';
import type { CompanionAnswer } from '../companion-ask-api.js';
import { buildCompanionComposer, type CompanionComposer } from './companion-composer.js';
import { commandAction, el, replace } from './dom.js';
import { say } from './copy.js';

export interface CompanionChoiceHandlers {
  readonly onSelect: (optionId: string) => void;
  readonly onSubmit: (optionIds: readonly string[]) => void;
  readonly onSay: (text: string) => void;
  /** Open the exact photograph the current turn, or the current answer, cites. */
  readonly onEvidence: (handleIndex: number) => void;
}

export interface CompanionChoiceRail {
  readonly root: HTMLElement;
  render(turn: Turn): void;
  /**
   * What a person can do with an answer: open what it cited, or ask something else.
   *
   * There is deliberately nothing else. An answer is a READ, and every control the rail offers
   * a turn exists to build an update proposal; offering one here would put the answer path one
   * click from the write path it is defined as not having.
   */
  renderAnswer(answer: CompanionAnswer, onBack: () => void): void;
  pressNumber(index: number): boolean;
  /** Whether the current turn cites anything, so `E` knows if it has a job. */
  openEvidence(): boolean;
}

function optionLabel(option: TurnOption): string {
  return option.phrasing ?? say(option.textKey);
}

function singleChoice(
  option: TurnOption,
  index: number | null,
  onSelect: (optionId: string) => void,
): HTMLElement {
  const button = el('button', {
    type: 'button',
    class: option.tier >= 2 ? 'companion-choice consequential' : 'companion-choice',
  });
  // `commandAction` is the one command-key element in the workspace. A choice is a keyed action
  // like every other keyed action, so it uses that rather than a second bespoke cap.
  if (index !== null) button.append(...commandAction(String(index), optionLabel(option)));
  else button.append(el('span', { class: 'command-action-label', text: optionLabel(option) }));
  if (option.available) button.addEventListener('click', () => onSelect(option.optionId));
  else {
    button.setAttribute('disabled', '');
    button.setAttribute('aria-disabled', 'true');
  }

  const children: (Node | string)[] = [button];
  if (!option.available) {
    children.push(el('span', {
      class: 'choice-unavailable-reason',
      text: option.unavailableReasonKey === null ? '' : say(option.unavailableReasonKey),
    }));
  }
  return el('li', { class: option.available ? 'choice-item' : 'choice-item unavailable' }, children);
}

export function buildCompanionChoiceRail(
  handlers: CompanionChoiceHandlers,
): CompanionChoiceRail {
  const root = el('section', {
    class: 'companion-choice-rail',
    'aria-label': 'Response choices',
  });
  let lastTurn: Turn | null = null;
  let composer: CompanionComposer | null = null;

  function render(turn: Turn): void {
    lastTurn = turn;
    composer = null;
    const content: (Node | string)[] = [];
    const choice = turn.choiceSet;
    const list = el('ol', { class: 'companion-choices' });

    if (choice?.mode === 'single') {
      list.append(...choice.options.map((option, index) =>
        singleChoice(option, index + 1, handlers.onSelect)));
    } else if (choice !== null) {
      const checks: HTMLInputElement[] = [];
      for (const [index, option] of choice.options.entries()) {
        const box = el('input', {
          type: 'checkbox',
          value: option.optionId,
          class: 'choice-checkbox',
        });
        if (!option.available) box.setAttribute('disabled', '');
        checks.push(box);
        const label = el('label', { class: 'companion-choice multi-choice' }, [
          box,
          el('b', { class: 'choice-key', text: String(index + 1) }),
          el('span', { class: 'choice-label', text: optionLabel(option) }),
        ]);
        const itemContent: (Node | string)[] = [label];
        if (!option.available) {
          itemContent.push(el('span', {
            class: 'choice-unavailable-reason',
            text: option.unavailableReasonKey === null ? '' : say(option.unavailableReasonKey),
          }));
        }
        list.append(el(
          'li',
          { class: option.available ? 'choice-item' : 'choice-item unavailable' },
          itemContent,
        ));
      }
      const submit = el('button', {
        type: 'button',
        class: 'companion-choices-submit',
        text: 'Submit selected',
      });
      submit.addEventListener('click', () => {
        handlers.onSubmit(checks.filter((check) => check.checked).map((check) => check.value));
      });
      content.push(submit);
    }

    if (turn.freeTextAllowed) {
      composer = buildCompanionComposer(handlers.onSay);
      const otherIndex = (choice?.options.length ?? 0) + 1;
      const other = el('button', {
        type: 'button',
        class: 'companion-choice companion-other-reveal',
        'aria-expanded': 'false',
      }, [
        el('b', { class: 'choice-key', text: String(otherIndex) }),
        el('span', { class: 'choice-label', text: 'Other…' }),
      ]);
      other.replaceChildren(...commandAction(String(otherIndex), 'Other…'));
      const otherItem = el('li', { class: 'choice-item companion-other' }, [other, composer.root]);
      other.addEventListener('click', () => {
        const opening = !composer?.opened();
        if (opening) composer?.open();
        else composer?.close();
        other.setAttribute('aria-expanded', String(opening));
        other.toggleAttribute('hidden', opening);
      });
      list.append(otherItem);
    }

    if (list.childElementCount > 0) content.unshift(list);

    const visibleEscapes = turn.escapes.filter((option) => option.escape !== 'later');
    if (visibleEscapes.length > 0) {
      content.push(el(
        'ul',
        { class: 'companion-escapes', 'aria-label': 'Other responses' },
        visibleEscapes.map((option) => singleChoice(option, null, handlers.onSelect)),
      ));
    }

    /*
     * The citation, on a key, at the foot of the panel where the actions are.
     *
     * It used to be a control inside the sentence the Companion had just spoken, which put an
     * action in the one region reserved for speech. It matters too much to simply delete: seeing
     * the exact photograph is how a person answers the question being asked. So it lives with the
     * other things you can press, on `E`, which is already the Atlas verb for "interact with what
     * is in front of you".
     */
    if (turn.evidence.length > 0) {
      const open = el('button', {
        type: 'button',
        class: 'companion-choice companion-evidence-action',
      }, commandAction('E', turn.evidence.length === 1 ? 'Open the source' : 'Open the sources'));
      open.addEventListener('click', () => handlers.onEvidence(0));
      content.push(el('div', { class: 'companion-rail-foot' }, [open]));
    }

    replace(root, content);
  }

  /*
   * One chip per cited photograph, in the order the answer mentions them.
   *
   * `E` opens the first, matching the turn rail above it, and each chip opens its own. A
   * citation the packet could not locate is rendered UNAVAILABLE WITH ITS REASON rather than
   * hidden, which is the availability semantics interaction-model.md 4.3 fixes for options and
   * is the right shape here for the same reason: a chip silently missing from a cited answer
   * reads as an answer that cited less than it did.
   */
  function renderAnswer(answer: CompanionAnswer, onBack: () => void): void {
    lastTurn = null;
    composer = buildCompanionComposer(handlers.onSay);
    const content: (Node | string)[] = [];

    if (answer.evidence.length > 0) {
      const list = el('ul', {
        class: 'companion-answer-evidence',
        'aria-label': 'Photographs this answer cites',
      });
      for (const [index, cited] of answer.evidence.entries()) {
        const openable = cited.handle !== null;
        const chip = el('button', {
          type: 'button',
          class: 'companion-choice companion-evidence-chip',
        }, index === 0
          ? commandAction('E', say('answer.openEvidence'))
          : [el('span', { class: 'command-action-label', text: say('answer.openEvidence') })]);
        if (openable) chip.addEventListener('click', () => handlers.onEvidence(index));
        else {
          chip.setAttribute('disabled', '');
          chip.setAttribute('aria-disabled', 'true');
        }
        const item: (Node | string)[] = [chip];
        if (!openable) {
          item.push(el('span', {
            class: 'choice-unavailable-reason',
            text: say('answer.evidenceNotLocated'),
          }));
        }
        list.append(el(
          'li',
          { class: openable ? 'choice-item' : 'choice-item unavailable' },
          item,
        ));
      }
      content.push(list);
    }

    // The open turn did not go anywhere. A question asked mid-turn is a detour, and a detour
    // with no way back is a dead end: without this the only route to the unanswered question is
    // to dismiss the Companion and summon it again.
    const back = el('button', {
      type: 'button',
      class: 'companion-choice companion-answer-back',
    }, [el('span', { class: 'command-action-label', text: say('answer.backToQuestion') })]);
    back.addEventListener('click', onBack);

    // The composer stays revealed, because the natural next move after an answer is another
    // question, and making a person reopen `Other…` to ask it would be a form. Revealed and not
    // focused: the answer has just been written into a live region and moving focus into a text
    // field would take a screen reader off it.
    content.push(el('div', { class: 'companion-rail-foot companion-answer-foot' }, [
      back,
      composer.root,
    ]));
    composer.reveal();

    replace(root, content);
  }

  return {
    root,
    render,
    renderAnswer,
    openEvidence() {
      const action = root.querySelector<HTMLButtonElement>(
        '.companion-evidence-action, .companion-evidence-chip:not([disabled])',
      );
      if (action === null) return false;
      action.click();
      return true;
    },
    pressNumber(index) {
      const choice = lastTurn?.choiceSet ?? null;
      if (lastTurn === null) return false;
      const option = choice?.options[index - 1];
      if (option === undefined) {
        const otherIndex = (choice?.options.length ?? 0) + 1;
        if (!lastTurn.freeTextAllowed || index !== otherIndex) return false;
        root.querySelector<HTMLButtonElement>('.companion-other-reveal:not([hidden])')?.click();
        return true;
      }
      if (!option.available) return false;
      if (choice?.mode === 'single') {
        handlers.onSelect(option.optionId);
        return true;
      }
      const box = root.querySelector<HTMLInputElement>(
        `.choice-checkbox[value="${option.optionId}"]`,
      );
      if (box === null) return false;
      box.checked = !box.checked;
      return true;
    },
  };
}
