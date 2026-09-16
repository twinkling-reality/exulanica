/** Keyboard ownership for the two system dialogs. Escape is intentionally not handled here. */
export interface ModalFocus {
  setVisible(visible: boolean): void;
}

const FOCUSABLE = [
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  'a[href]',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

function focusableChildren(root: HTMLElement): HTMLElement[] {
  return [...root.querySelectorAll<HTMLElement>(FOCUSABLE)].filter(
    (item) => item.closest('[hidden]') === null && !item.matches(':disabled'),
  );
}

export function createModalFocus(root: HTMLElement, initial: HTMLElement): ModalFocus {
  let restoreFocus: HTMLElement | null = null;
  root.addEventListener('keydown', (event) => {
    if (event.key !== 'Tab' || root.hidden) return;
    const focusable = focusableChildren(root);
    const first = focusable[0];
    const last = focusable.at(-1);
    if (first === undefined || last === undefined) return;
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });

  return {
    setVisible(visible) {
      if (visible === !root.hidden) return;
      if (visible) {
        restoreFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
        root.hidden = false;
        initial.focus();
      } else {
        root.hidden = true;
        const target = restoreFocus;
        if (target?.isConnected) {
          target.focus();
          // The Atlas command bar remains inert until the shell finishes closing this modal.
          // Retry once after that synchronous shell reflection without stealing focus from a
          // different modal that may have opened in the meantime.
          if (document.activeElement !== target) {
            queueMicrotask(() => {
              if (
                target.isConnected &&
                (document.activeElement === document.body || document.activeElement === null)
              ) {
                target.focus();
              }
            });
          }
        }
        restoreFocus = null;
      }
    },
  };
}
