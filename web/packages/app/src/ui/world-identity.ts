import type { SavedWorldEntry } from '../world-entry-api.js';
import { say } from './copy.js';
import { el } from './dom.js';
import { actionSpec } from './actions/registry.js';
import { button } from './system/components.js';

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
    type: 'text', maxlength: 200, value: current.title, 'aria-label': say('worldControls.title'),
  }) as HTMLInputElement;
  const save = el('button', { type: 'submit', class: 'world-title-save', text: say('worldControls.save') });
  const status = el('span', {
    class: 'world-title-status', role: 'status', 'aria-live': 'polite',
  });
  const form = el('form', { class: 'world-title-form' }, [title, save, status]);
  // The top bar's verbs are the registry's entries: their words, icons and keys live there once.
  const fromRegistry = (id: string, className: string, label?: string) => {
    const spec = actionSpec(id);
    return button({
      label: label ?? spec.label, icon: spec.icon, variant: 'quiet', className,
      ...(spec.shortcut === undefined ? {} : { shortcut: spec.shortcut }),
    });
  };
  const photos = fromRegistry('photos.open', 'world-add-photos');
  const addObject = fromRegistry('objects.open', 'world-add-object');
  const world = fromRegistry('menu.open', 'world-open-menu', say('worldControls.world'));
  world.setAttribute('aria-label', say('worldControls.openWorld'));
  const root = el('aside', { class: 'world-identity', 'aria-label': say('worldControls.label') }, [
    form,
    el('span', { class: 'x-topbar-spacer' }),
    addObject,
    photos,
    world,
  ]);

  const close = el('button', {
    type: 'button', class: 'photos-drawer-close',
    'aria-label': say('photosDrawer.return'), text: say('photosDrawer.return'),
  });
  const photosDrawer = el('section', {
    class: 'photos-drawer', 'aria-labelledby': 'photos-drawer-title', hidden: true,
  }, [
    el('header', { class: 'photos-drawer-header' }, [
      el('div', {}, [
        el('p', { class: 'overlay-kicker', text: say('photosDrawer.kicker') }),
        el('h2', { id: 'photos-drawer-title', text: say('photosDrawer.title') }),
      ]),
      close,
    ]),
    // The body scrolls and the header does not, so nothing scrolled or focused lands under it.
    el('div', { class: 'photos-drawer-body' }, [deps.personalIntake]),
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
    status.textContent = say('worldControls.saving');
    reflect();
    void deps.rename(candidate).then((entry) => {
      current = entry;
      title.value = entry.title;
      status.textContent = say('worldControls.saved');
    }).catch(() => {
      status.textContent = say('worldControls.saveFailed');
    }).finally(() => {
      saving = false;
      reflect();
    });
  });
  world.addEventListener('click', deps.onOpenWorld);
  addObject.addEventListener('click', deps.onAddObject);
  photos.addEventListener('click', deps.onOpenPhotos);
  close.addEventListener('click', deps.onClosePhotos);
  // Adding photographs is offered only where the server says this world's kind takes them.
  const offerPhotos = (): void => {
    photos.hidden = current.takesPhotographs === false;
  };
  reflect();
  offerPhotos();

  return {
    root,
    photosDrawer,
    setEntry(entry) {
      current = entry;
      title.value = entry.title;
      status.textContent = '';
      reflect();
      offerPhotos();
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
