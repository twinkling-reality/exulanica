import { el } from './dom.js';
import { icon } from './icons.js';

/** Decorative state glyphs; the enclosing action supplies its accessible name. */
export const copyGlyph = (): HTMLElement => el('span', { class: 'copy-glyph', 'aria-hidden': 'true' }, [icon('copy'), icon('check')]);

/** Clipboard completion is the authority for visible and announced copy feedback. */
export function bindCopyFeedback(
  button: HTMLButtonElement,
  label: HTMLElement,
  status: HTMLElement,
  text: () => string,
  messages: { success: string; failure: string; errorClass?: string },
): void {
  const idleLabel = label.textContent;
  button.addEventListener('click', async () => {
    if (button.disabled) return;
    const hadFocus = document.activeElement === button;
    button.disabled = true;
    button.dataset.copyState = 'pending';
    status.dataset.copyState = 'pending';
    if (messages.errorClass) status.classList.remove(messages.errorClass);
    status.textContent = '';
    label.textContent = 'Copying…';
    try {
      await navigator.clipboard.writeText(text());
      button.dataset.copyState = 'success';
      status.dataset.copyState = 'success';
      label.textContent = 'Copied';
      status.textContent = messages.success;
    } catch {
      button.dataset.copyState = 'error';
      status.dataset.copyState = 'error';
      label.textContent = idleLabel;
      status.textContent = messages.failure;
      if (messages.errorClass) status.classList.add(messages.errorClass);
    } finally {
      button.disabled = false;
      if (hadFocus && button.isConnected && !button.closest('[inert]') && document.activeElement === document.body) button.focus({ preventScroll: true });
    }
  });
}
