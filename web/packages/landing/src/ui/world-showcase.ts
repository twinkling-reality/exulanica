import { el } from './dom.js';
import { icon } from './icons.js';
import { action } from './action.js';
import { mountWorldOptics } from './world-optics.js';
import { WORLD_SCENES, worldEntryHref } from './world-scenes.js';
export { WORLD_SCENES } from './world-scenes.js';
import '../world-showcase.css';

export interface WorldShowcaseOptions { atlasHref?: string | null; portals?: boolean }

/** Hover, keyboard focus and tap share a stable contextual preview. */
export function buildWorldShowcase(options: WorldShowcaseOptions = {}): HTMLElement {
  const prefix = options.portals ? 'home' : 'worlds';
  const root = el('div', { class: options.portals ? 'world-portals' : 'world-catalog', 'aria-label': 'Preview worlds captured in Exulanica' });
  const heading = el('h2', { id: `${prefix}-preview-title` });
  const description = el('p', { class: 'preview-description' });
  const image = el('img', { alt: '', width: '1280', height: '720' });
  const imageNote = el('span', { class: 'capture-fallback', text: 'Loading capture…' });
  image.addEventListener('load', () => { imageNote.hidden = true; image.hidden = false; });
  image.addEventListener('error', () => { image.hidden = true; imageNote.hidden = false; imageNote.textContent = 'Capture unavailable. You can still read about this world.'; });
  const close = el('button', { type: 'button', class: 'context-close', 'aria-label': 'Close world preview', text: '×' });
  const link = action(options.atlasHref ? 'Open in Exulanica' : 'Join Waitlist', options.atlasHref ?? '/waitlist', true);
  const panel = el('section', { id: `${prefix}-preview`, class: 'world-context', 'aria-labelledby': heading.id, hidden: '' }, [
    el('div', { class: 'context-top' }, [el('span', { class: 'preview-note', text: 'Captured in Exulanica · Still preview' }), close]),
    el('div', { class: 'context-visual' }, [image, imageNote]), heading, description, link,
  ]);
  let selected: HTMLButtonElement | null = null;
  let pinned = false;
  let dismissTimer = 0;
  let ignoreFocus = false;
  const clearDismiss = () => window.clearTimeout(dismissTimer);
  const dismiss = (restore = false) => {
    clearDismiss();
    const previous = selected;
    selected = null; pinned = false; panel.hidden = true;
    delete root.dataset.selected;
    previous?.setAttribute('aria-expanded', 'false');
    if (restore && previous) { ignoreFocus = true; previous.focus({ preventScroll: true }); ignoreFocus = false; }
  };
  const place = () => {
    if (!selected || panel.hidden) return;
    const bounds = selected.getBoundingClientRect();
    const width = panel.offsetWidth, height = panel.offsetHeight;
    const compact = window.innerWidth < 700;
    const preferLeft = bounds.left + bounds.width / 2 < window.innerWidth / 2;
    const outside = preferLeft ? bounds.left - width - 14 : bounds.right + 14;
    const opposite = preferLeft ? bounds.right + 14 : bounds.left - width - 14;
    const left = compact ? (window.innerWidth - width) / 2
      : outside >= 16 && outside + width <= window.innerWidth - 16 ? outside : opposite;
    const top = compact ? Math.max(130, window.innerHeight - height - 18) : bounds.top - 30;
    panel.style.left = `${Math.max(16, Math.min(left, window.innerWidth - width - 16))}px`;
    panel.style.top = `${Math.max(118, Math.min(top, window.innerHeight - height - 16))}px`;
  };
  const select = (button: HTMLButtonElement, index: number, pin = false) => {
    clearDismiss();
    if (selected === button) { pinned ||= pin; return; }
    selected?.setAttribute('aria-expanded', 'false');
    selected = button; pinned = pin;
    const scene = WORLD_SCENES[index]!;
    heading.textContent = scene.title; description.textContent = scene.description;
    imageNote.textContent = 'Loading capture…'; imageNote.hidden = false; image.hidden = false;
    image.src = scene.image; image.alt = scene.alt;
    if (image.complete && image.naturalWidth) imageNote.hidden = true;
    link.href = worldEntryHref(scene, options.atlasHref ?? null);
    link.dataset.returnFocus = button.id;
    link.dataset.returnWorld = scene.id;
    button.setAttribute('aria-expanded', 'true');
    root.dataset.selected = String(index);
    // Follow the selected control in tab order, even inside the orbit field.
    button.after(panel); panel.hidden = false;
    place(); requestAnimationFrame(() => requestAnimationFrame(place));
  };
  const delayDismiss = () => {
    clearDismiss();
    if (!pinned) dismissTimer = window.setTimeout(() => {
      if (!panel.contains(document.activeElement) && document.activeElement !== selected) dismiss();
    }, 450);
  };
  panel.addEventListener('pointerenter', clearDismiss);
  panel.addEventListener('pointerleave', delayDismiss);
  close.addEventListener('click', () => dismiss(true));
  root.addEventListener('focusout', (event) => {
    if (!(event.relatedTarget instanceof Node) || (!panel.contains(event.relatedTarget) && event.relatedTarget !== selected)) dismiss();
  });
  document.addEventListener('pointerdown', (event) => {
    if (selected && event.target instanceof Node && !panel.contains(event.target) && !selected.contains(event.target)) dismiss();
  });
  document.addEventListener('keydown', (event) => {
    if (selected && event.key === 'Escape') { event.preventDefault(); dismiss(true); }
  });
  // Route changes close the panel before its page becomes inert.
  new MutationObserver(() => { if (root.closest('[inert]')) dismiss(); }).observe(document.documentElement, { subtree: true, attributes: true, attributeFilter: ['inert'] });
  window.addEventListener('resize', place);
  requestAnimationFrame(() => root.closest('.pane')?.addEventListener('scroll', () => { if (selected) dismiss(panel.contains(document.activeElement)); }, { passive: true }));
  for (const [index, scene] of WORLD_SCENES.entries()) {
    const visual = el('span', { class: 'portal-window' }, [el('img', { src: scene.image, alt: '', width: '1280', height: '720', decoding: 'async', draggable: 'false' })]);
    const button = el('button', {
      id: `${prefix}-${scene.id}`, type: 'button', class: `world-choice world-choice-${index + 1}`,
      'aria-label': `Preview ${scene.title}`, 'aria-expanded': 'false', 'aria-controls': panel.id,
    }, [el('span', { class: 'portal-orbit' }, [visual]),
      el('span', { class: 'portal-label' }, [el('span', { text: scene.title }), el('span', { class: 'portal-invitation', text: 'Still preview' }), el('span', { class: 'catalog-arrow action-icon', 'aria-hidden': 'true' }, [icon('arrow')])]),
    ]);
    button.addEventListener('pointerenter', (event) => { if (event.pointerType === 'mouse') select(button, index); });
    button.addEventListener('pointerleave', delayDismiss);
    button.addEventListener('focus', () => { if (!ignoreFocus) select(button, index); });
    button.addEventListener('click', () => { select(button, index, true); });
    button.addEventListener('keydown', (event) => { if (event.key === 'ArrowDown') { event.preventDefault(); select(button, index, true); link.focus(); } });
    root.append(button);
  }
  if (options.portals) {
    // Two ordered tracks share one period. Phase is spacing along a track, not a
    // separate drift for each object. Only genuine captures open a world preview.
    const field = el('div', { class: 'orbit-field' });
    root.append(field);
    const materials = ['sky', 'market', 'leaf', 'gold', 'town', 'sky', 'leaf', 'market', 'gold', 'town', 'leaf', 'sky'];
    const choices = root.querySelectorAll<HTMLElement>('.world-choice');
    for (let ring = 0; ring < 2; ring += 1) {
      for (let slot = 0; slot < materials.length; slot += 1) {
        const interactive = slot === (ring === 0 ? 7 : 2);
        const material = interactive ? (ring === 0 ? 'market' : 'town') : materials[slot]!;
        const form = interactive ? choices[ring]! : el('span', {
          class: 'field-form', 'aria-hidden': 'true',
        }, [el('span', { class: 'portal-orbit' }, [el('span', { class: 'portal-window' })])]);
        form.classList.add('orbit-item', ring === 0 ? 'orbit-outer' : 'orbit-inner', `field-${material}`);
        form.style.setProperty('--phase', `${-(slot / materials.length) * 84}s`);
        form.style.setProperty('--crop', `${30 + (slot % 4) * 15}%`);
        field.append(form);
      }
    }
  }
  root.append(panel);
  if (options.portals) mountWorldOptics(root, WORLD_SCENES.map(scene => scene.image));
  return root;
}
