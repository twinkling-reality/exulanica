import type { SavedWorldEntry } from '../world-entry-api.js';
import { el } from './dom.js';

export interface WorldIdentity {
  readonly root: HTMLElement;
  readonly photosDrawer: HTMLElement;
  setEntry(entry: SavedWorldEntry): void;
  setPhotosVisible(visible: boolean): void;
}

/** Compact identity and source controls that stay attached to the live world. */
export function buildWorldIdentity(deps: {
  readonly entry: SavedWorldEntry;
  readonly personalIntake: HTMLElement;
  readonly rename: (title: string) => Promise<SavedWorldEntry>;
  readonly onOpenWorld: () => void;
  readonly onAddObject: () => void;
  readonly onOpenPhotos: () => void;
  readonly onClosePhotos: () => void;
}): WorldIdentity {
  let current = deps.entry;
  let saving = false;
  const title = el('input', {
    type: 'text', maxlength: 200, value: current.title, 'aria-label': 'World title',
  }) as HTMLInputElement;
  const save = el('button', { type: 'submit', class: 'world-title-save', text: 'Save' });
  const status = el('span', {
    class: 'world-title-status', role: 'status', 'aria-live': 'polite',
  });
  const form = el('form', { class: 'world-title-form' }, [title, save, status]);
  const photos = el('button', {
    type: 'button', class: 'world-add-photos', text: 'Add photos',
  });
  const addObject = el('button', {
    type: 'button', class: 'world-add-object', text: 'Add object',
  });
  const world = el('button', {
    type: 'button', class: 'world-open-menu', text: 'World',
    'aria-label': 'Open World menu',
  });
  const root = el('aside', { class: 'world-identity', 'aria-label': 'World controls' }, [
    form,
    world,
    addObject,
    photos,
  ]);

  const close = el('button', {
    type: 'button', class: 'photos-drawer-close', 'aria-label': 'Close Add photos', text: 'Close',
  });
  const photosDrawer = el('section', {
    class: 'photos-drawer', 'aria-labelledby': 'photos-drawer-title', hidden: true,
  }, [
    el('header', { class: 'photos-drawer-header' }, [
      el('div', {}, [
        el('p', { class: 'overlay-kicker', text: 'World sources' }),
        el('h2', { id: 'photos-drawer-title', text: 'Add photos' }),
      ]),
      close,
    ]),
    deps.personalIntake,
  ]);

  const reflect = (): void => {
    const candidate = title.value.trim();
    save.hidden = candidate === current.title;
    save.disabled = saving || candidate.length === 0 || candidate === current.title;
  };
  title.addEventListener('input', () => {
    status.textContent = '';
    reflect();
  });
  title.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      title.value = current.title;
      status.textContent = '';
      title.blur();
      reflect();
    }
  });
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    const candidate = title.value.trim();
    if (saving || candidate.length === 0 || candidate === current.title) return;
    saving = true;
    status.textContent = 'Saving…';
    reflect();
    void deps.rename(candidate).then((entry) => {
      current = entry;
      title.value = entry.title;
      status.textContent = 'Saved';
    }).catch(() => {
      status.textContent = 'Could not save. Reload if this world changed elsewhere.';
    }).finally(() => {
      saving = false;
      reflect();
    });
  });
  world.addEventListener('click', deps.onOpenWorld);
  addObject.addEventListener('click', deps.onAddObject);
  photos.addEventListener('click', deps.onOpenPhotos);
  close.addEventListener('click', deps.onClosePhotos);
  reflect();

  return {
    root,
    photosDrawer,
    setEntry(entry) {
      current = entry;
      title.value = entry.title;
      status.textContent = '';
      reflect();
    },
    setPhotosVisible(visible) {
      photosDrawer.hidden = !visible;
      photos.setAttribute('aria-expanded', visible ? 'true' : 'false');
      if (visible) {
        const focusable = deps.personalIntake.querySelector<HTMLElement>(
          '.photo-review-workflow > summary',
        );
        focusable?.focus({ preventScroll: true });
      }
    },
  };
}
