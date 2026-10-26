import { el } from './dom.js';
import { icon } from './icons.js';
import { action } from './action.js';
import { WORLD_ORBIT_SLOTS, ORBIT_OUTER_COUNT, ORBIT_INNER_COUNT, ORBIT_PERIOD, orbitDrawn, orbitPose } from './world-orbit-geometry.js';
import { orbitGradient } from './world-materials.js';
import { mountWorldOptics } from './world-optics.js';
import { WORLD_SCENES, worldEntryHref } from './world-scenes.js';
export { WORLD_SCENES } from './world-scenes.js';
import '../world-showcase.css';

/** The room a centre preview's title keeps from the nearest orb on either side. */
export const PREVIEW_TITLE_ROOM_PX = 16;

/**
 * The widest a centre preview's title may stand on a stage: the ring's clear width at the title's middle line
 * (the least room, over a whole period, between the middle and any orb of the ring drawn nearest it that crosses
 * that line: the inner ring, or the outer where a narrow stage draws only that), less that orb's half width and
 * `PREVIEW_TITLE_ROOM_PX` either side, so a long title takes another line instead of running into an orb. The
 * preview stands at the orbit's own middle height.
 */
export function previewTitleWidth(width: number, height: number): number {
  const ring = orbitDrawn(ORBIT_OUTER_COUNT, width, height) ? ORBIT_OUTER_COUNT : 0;
  let least = Number.POSITIVE_INFINITY;
  // One orb of the ring travels its whole track in a period, so its passes are every orb's.
  for (let step = 0; step < 720; step += 1) {
    const pose = orbitPose(ring, (step * ORBIT_PERIOD) / 720, width, height);
    if (Math.abs(pose.y - height * .44) > Math.hypot(pose.ay, pose.by)) continue;
    least = Math.min(least, Math.abs(pose.x - width / 2) - Math.hypot(pose.ax, pose.bx));
  }
  return Number.isFinite(least) ? Math.max(0, 2 * (least - PREVIEW_TITLE_ROOM_PX)) : width;
}

export interface WorldShowcaseOptions { atlasHref?: string | null; portals?: boolean; onSelectionChange?: (selected: boolean) => void }

/** Hover, keyboard focus and tap share a stable contextual preview. */
export function buildWorldShowcase(options: WorldShowcaseOptions = {}): HTMLElement {
  const prefix = options.portals ? 'home' : 'worlds';
  const root = el('div', { class: options.portals ? 'world-portals' : 'world-catalog', 'aria-label': 'Preview worlds captured in Exulanica' });
  const heading = el('h2', { id: `${prefix}-preview-title` });
  const description = el('p', { class: 'preview-description' });
  const invitation = el('p', { class: 'preview-invitation', text: 'Click to explore' });
  const image = el('img', { alt: '', width: '1280', height: '720' });
  const imageNote = el('span', { class: 'capture-fallback', text: 'Loading capture…' });
  image.addEventListener('load', () => { imageNote.hidden = true; image.hidden = false; });
  image.addEventListener('error', () => { image.hidden = true; imageNote.hidden = false; imageNote.textContent = 'Capture unavailable. You can still read about this world.'; });
  const close = el('button', { type: 'button', class: 'context-close', 'aria-label': 'Close world preview', text: '×' });
  const linkLabel = options.atlasHref ? 'Create World' : 'Set Up Exulanica';
  // A showcase world is opened, not made: its link says so wherever an application can open it.
  const opens = (scene: (typeof WORLD_SCENES)[number]) => Boolean(scene.world && options.atlasHref);
  const link = action(linkLabel, options.atlasHref ?? '/docs/self-hosting', true);
  const panel = el('section', { id: `${prefix}-preview`, class: `world-context${options.portals ? ' world-center-preview' : ''}`, 'aria-labelledby': heading.id, hidden: '' }, options.portals ? [
    heading, description, invitation,
  ] : [
    el('div', { class: 'context-top' }, [el('span', { class: 'preview-note', text: 'Captured in Exulanica · Still preview' }), close]),
    el('div', { class: 'context-visual' }, [image, imageNote]), heading, description, link,
  ]);
  let selected: HTMLElement | null = null;
  let pinned = false;
  let dismissTimer = 0;
  let ignoreFocus = false;
  let dismissedHover: HTMLElement | null = null;
  let exitAnimation: Animation | undefined;
  const clearDismiss = () => window.clearTimeout(dismissTimer);
  const dismiss = (restore = false) => {
    clearDismiss();
    const previous = selected;
    if (restore) dismissedHover = previous;
    selected = null; pinned = false;
    if (previous) options.onSelectionChange?.(false);
    // Assigning inert notifies observers even when it is already set, so a page
    // that is already inert would otherwise close this panel forever.
    if (!panel.inert) panel.inert = true;
    if (panel.getAttribute('aria-hidden') !== 'true') panel.setAttribute('aria-hidden', 'true');
    exitAnimation?.cancel();
    if (!panel.hidden && typeof panel.animate === 'function' && !window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      exitAnimation = panel.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 160, easing: 'ease-out' });
      exitAnimation.onfinish = () => { if (!selected) panel.hidden = true; };
    } else panel.hidden = true;
    delete root.dataset.selected;
    previous?.setAttribute('aria-expanded', 'false');
    if (restore && previous) { ignoreFocus = true; previous.focus({ preventScroll: true }); ignoreFocus = false; }
  };
  // A centre preview's title keeps its room from the orbs on the stage as it stands now.
  const titleRoom = () => {
    if (!options.portals) return;
    const { width, height } = root.getBoundingClientRect();
    if (width > 0 && height > 0) panel.style.setProperty('--preview-title-width', `${Math.round(previewTitleWidth(width, height))}px`);
  };
  const place = () => {
    titleRoom();
    if (!selected || panel.hidden || options.portals) return;
    const width = panel.offsetWidth, height = panel.offsetHeight;
    const compact = window.innerWidth < 700;
    // A stable dock avoids panel jumps while moving rapidly between worlds.
    const field = root.getBoundingClientRect();
    const left = compact ? (window.innerWidth - width) / 2 : Math.min(field.right + 20, window.innerWidth - width - 24);
    const top = compact ? window.innerHeight - height - 18 : window.innerHeight * .44 - height / 2;
    const panelLeft = Math.max(16, left), panelTop = Math.max(118, Math.min(top, window.innerHeight - height - 16));
    panel.style.left = `${panelLeft}px`; panel.style.top = `${panelTop}px`;


  };
  const select = (button: HTMLElement, index: number, pin = false) => {
    clearDismiss();
    if (pinned && !pin && selected !== button) return;
    if (selected === button) { pinned ||= pin; return; }
    exitAnimation?.cancel(); panel.inert = false; panel.removeAttribute('aria-hidden');
    selected?.setAttribute('aria-expanded', 'false');
    const replacing = selected !== null;
    selected = button; pinned = pin;
    const scene = WORLD_SCENES[index]!;
    const updateCopy = () => {
      heading.textContent = options.portals ? scene.name ?? scene.title : scene.title;
      description.textContent = options.portals ? '' : scene.description;
      description.hidden = !description.textContent;
      invitation.textContent = opens(scene) ? 'Open this world' : 'Click to explore';
    };
    const animateCopy = options.portals && typeof panel.animate === 'function' && !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (!animateCopy || !replacing) updateCopy();
    imageNote.textContent = 'Loading capture…'; imageNote.hidden = false; image.hidden = false;
    image.src = scene.image; image.alt = scene.alt;
    if (image.complete && image.naturalWidth) imageNote.hidden = true;
    link.href = worldEntryHref(scene, options.atlasHref ?? null);
    const said = opens(scene) ? 'Open this world' : linkLabel;
    link.querySelector('.secondary-label')!.textContent = said;
    if (link.hasAttribute('aria-label')) link.setAttribute('aria-label', `${said} (external)`);
    link.dataset.returnFocus = button.id;
    link.dataset.returnWorld = scene.id;
    button.setAttribute('aria-expanded', 'true');
    root.dataset.selected = String(index);
    // Follow the selected control in tab order, even inside the orbit field.
    button.after(panel); panel.hidden = false; titleRoom();
    options.onSelectionChange?.(true);
    if (animateCopy) {
      const enter = () => {
        if (selected !== button) return;
        updateCopy();
        exitAnimation = panel.animate([{ opacity: 0, transform: 'translate(-50%, calc(-50% + 4px))' }, { opacity: 1, transform: 'translate(-50%, -50%)' }], { duration: 200, easing: 'cubic-bezier(.22,1,.36,1)' });
      };
      if (replacing) {
        exitAnimation = panel.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 120, easing: 'ease-out', fill: 'forwards' });
        exitAnimation.onfinish = () => { exitAnimation?.cancel(); enter(); };
      } else enter();
    }
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
  root.addEventListener('worldpose', place);
  requestAnimationFrame(() => root.closest('.pane')?.addEventListener('scroll', () => { if (selected) dismiss(panel.contains(document.activeElement)); }, { passive: true }));
  for (const [index, scene] of WORLD_SCENES.entries()) {
    const visual = el('span', { class: 'portal-window' }, [el('img', { src: scene.image, alt: '', width: '1280', height: '720', decoding: 'async', draggable: 'false' })]);
    const button: HTMLElement = el(options.portals ? 'a' : 'button', {
      id: `${prefix}-${scene.id}`, type: 'button', class: `world-choice world-choice-${index + 1}`,
      ...(options.portals ? { href: worldEntryHref(scene, options.atlasHref ?? null) } : {}),
      'data-scene-index': String(index), 'aria-label': `${options.portals ? (opens(scene) ? 'Open' : 'Explore') : 'Preview'} ${scene.title}`, 'aria-expanded': 'false', 'aria-controls': panel.id,
    }, [el('span', { class: 'portal-orbit' }, [visual]),
      el('span', { class: 'portal-label' }, [el('span', { text: scene.title }), el('span', { class: 'portal-invitation', text: 'Still preview' }), el('span', { class: 'catalog-arrow action-icon', 'aria-hidden': 'true' }, [icon('arrow')])]),
    ]);
    button.addEventListener('pointerenter', (event) => { if (event.pointerType === 'mouse' && dismissedHover !== button) select(button, index); });
    button.addEventListener('pointerleave', () => { if (dismissedHover === button) dismissedHover = null; delayDismiss(); });
    button.addEventListener('focus', () => { if (!ignoreFocus) select(button, index); });
    if (!options.portals) {
      button.addEventListener('click', () => { if (selected === button && pinned) dismiss(true); else select(button, index, true); });
      button.addEventListener('keydown', (event) => { if (event.key === 'ArrowDown') { event.preventDefault(); select(button, index, true); link.focus(); } });
    }
    root.append(button);
  }
  if (options.portals) {
    // Two ordered tracks share one period. Phase is spacing along a track, not a
    // separate drift for each object. Only genuine captures open a world preview.
    root.style.setProperty('--orbit-period', `${ORBIT_PERIOD}s`);
    const field = el('div', { class: 'orbit-field' });
    root.append(field);
    const choices = root.querySelectorAll<HTMLElement>('.world-choice');
    for (let ring = 0; ring < 2; ring += 1) {
      const count = ring === 0 ? ORBIT_OUTER_COUNT : ORBIT_INNER_COUNT;
      for (let slot = 0; slot < count; slot += 1) {
        const orbitIndex = ring === 0 ? slot : ORBIT_OUTER_COUNT + slot;
        const sceneIndex = WORLD_ORBIT_SLOTS.indexOf(orbitIndex);
        const interactive = sceneIndex >= 0 && sceneIndex < choices.length;
        const material = interactive ? 'capture' : 'gradient';
        const form = interactive ? choices[sceneIndex]! : el('span', {
          class: 'field-form', 'aria-hidden': 'true',
        }, [el('span', { class: 'portal-orbit' }, [el('span', { class: 'portal-window' })])]);
        form.classList.add('orbit-item', ring === 0 ? 'orbit-outer' : 'orbit-inner', `field-${material}`);
        form.style.setProperty('--phase', `${-(slot / count) * ORBIT_PERIOD}s`);
        form.dataset.orbitIndex = String(orbitIndex);
        if (!interactive) form.style.setProperty('--material', orbitGradient(orbitIndex));
        form.style.setProperty('--crop', `${30 + (slot % 4) * 15}%`);
        field.append(form);
      }
    }
  }
  root.append(panel);
  if (options.portals) mountWorldOptics(root, WORLD_SCENES.map(scene => scene.image));
  return root;
}
