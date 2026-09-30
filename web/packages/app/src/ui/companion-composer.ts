import { el } from './dom.js';

export interface CompanionComposer {
  readonly root: HTMLFormElement;
  open(): void;
  /**
   * Show the composer without taking focus.
   *
   * `open` is the answer to a person pressing `Other…`, and moving the caret into the field is
   * exactly what they asked for. Revealing it under an ANSWER is not that: focus would land in
   * a text box the moment the answer appeared, and a screen reader would be moved off the
   * sentence it was about to read. Same element, different gesture, so a different verb.
   */
  reveal(): void;
  close(): void;
  opened(): boolean;
}

export function buildCompanionComposer(
  onSay: (text: string) => void,
  options: { readonly ariaLabel?: string; readonly placeholder?: string } = {},
): CompanionComposer {
  const input = el('input', {
    type: 'text',
    class: 'companion-reply-input',
    'aria-label': options.ariaLabel ?? 'Reply in your own words',
    placeholder: options.placeholder ?? 'Your reply',
    autocomplete: 'off',
  });
  const send = el('button', {
    type: 'submit',
    class: 'companion-reply-submit',
    'aria-label': 'Send reply',
    title: 'Send reply',
    text: 'Send',
  });
  const root = el('form', {
    class: 'companion-composer',
    hidden: true,
  }, [input, send]);

  root.addEventListener('submit', (event) => {
    event.preventDefault();
    const value = input.value.trim();
    if (value === '') return;
    onSay(value);
    input.value = '';
  });

  return {
    root,
    opened: () => !root.hasAttribute('hidden'),
    open() {
      root.removeAttribute('hidden');
      input.focus();
    },
    reveal() {
      root.removeAttribute('hidden');
    },
    close() {
      root.setAttribute('hidden', '');
    },
  };
}
