/**
 * A major surface whose code is loaded when it is first wanted, so the page starts without it.
 *
 * Until it loads, a small stand-in holds its place in the shell. Opening it before then shows
 * "Opening Compare." in the stand-in while the module loads; the loaded surface then takes the
 * stand-in's place and is opened or left closed as the shell last asked. A load that fails says so,
 * with Try again, and nothing is left half open.
 */

import { el } from '../ui/dom.js';
import { button, errorState } from '../ui/system/components.js';

export interface PanelSurface {
  readonly root: HTMLElement;
  setVisible(visible: boolean): void;
  dispose(): void;
}

export function lazyPanel(name: string, load: () => Promise<PanelSurface>): PanelSurface {
  const stand = el('section', { class: 'lazy-panel', 'aria-label': name, tabindex: '-1', hidden: true });
  let surface: PanelSurface | null = null;
  let loading: Promise<void> | null = null;
  let visible = false;
  let disposed = false;

  const showOpening = (): void => {
    stand.replaceChildren(el('p', { class: 'lazy-panel-opening', role: 'status', text: `Opening ${name}.` }));
  };
  const showFailure = (error: unknown): void => {
    const retry = button({ label: 'Try again', variant: 'primary' });
    retry.addEventListener('click', () => {
      showOpening();
      start();
    });
    stand.replaceChildren(errorState({
      happened: `${name} did not open.`,
      next: 'Check the connection, then try again.',
      action: retry,
      technical: { detail: error instanceof Error ? error.message : String(error) },
    }));
    if (visible) retry.focus({ preventScroll: true });
  };

  function start(): void {
    loading ??= load().then((loaded) => {
      if (disposed) {
        loaded.dispose();
        return;
      }
      surface = loaded;
      if (stand.isConnected) stand.replaceWith(loaded.root);
      stand.hidden = true;
      if (visible) loaded.setVisible(true);
    }, (error: unknown) => {
      loading = null;
      if (!disposed) showFailure(error);
    });
  }

  return {
    get root() {
      return surface?.root ?? stand;
    },
    setVisible(next) {
      if (disposed) return;
      visible = next;
      if (surface !== null) {
        surface.setVisible(next);
        return;
      }
      stand.hidden = !next;
      if (next && loading === null) {
        showOpening();
        start();
      }
      if (next) stand.focus({ preventScroll: true });
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      surface?.dispose();
    },
  };
}
