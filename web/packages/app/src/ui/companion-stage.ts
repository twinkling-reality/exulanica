/**
 * The Companion's verified geometric-avatar stage.
 *
 * The visual grammar is grounded in the supplied Grok Bot reference and the public Bloub project
 * (https://github.com/jeremy-prt/bloub): one morphable silhouette with two slit eyes. This is an
 * original, deliberately smaller DOM/SVG renderer rather than copied Bloub source. It has no
 * torso, limbs, mouth, accessories, Spline scene, or second WebGL renderer.
 */

import {
  DEFAULT_COMPANION,
  type CompanionAppearanceConfiguration,
  type CompanionOperationalState,
} from '@exulanica/presentation';
import { createCompanionAvatar } from './companion-avatar.js';

export type CompanionPresenceState = CompanionOperationalState;

export interface CompanionStageOptions {
  readonly parent?: HTMLElement;
}

export interface CompanionStage {
  readonly root: HTMLElement;
  screenBox(): DOMRect | null;
  show(): void;
  hide(): void;
  visible(): boolean;
  state(): CompanionPresenceState;
  setState(next: CompanionPresenceState): void;
  setAppearance(configuration: CompanionAppearanceConfiguration): void;
  dispose(): void;
}

export function buildCompanionStage(options: CompanionStageOptions = {}): CompanionStage {
  const root = document.createElement('div');
  root.className = 'companion-stage';
  root.dataset['renderer'] = 'svg';
  root.dataset['state'] = 'resting';
  root.setAttribute('role', 'img');

  const avatar = createCompanionAvatar();
  root.append(avatar.root);
  options.parent?.append(root);

  const motionQuery = typeof window.matchMedia === 'function'
    ? window.matchMedia('(prefers-reduced-motion: reduce)')
    : null;
  let reducedMotion = motionQuery?.matches ?? false;
  let shown = false;
  let disposed = false;
  let presenceState: CompanionPresenceState = 'resting';
  let appearance = DEFAULT_COMPANION;

  const reflectMotion = (): void => {
    reducedMotion = motionQuery?.matches ?? false;
    root.toggleAttribute('data-reduced-motion', reducedMotion);
    if (reducedMotion) avatar.gaze.removeAttribute('transform');
  };
  const applyAppearance = (next: CompanionAppearanceConfiguration): void => {
    appearance = next;
    avatar.setAppearance(next);
    root.dataset['shape'] = next.bodyVariant;
    root.dataset['color'] = next.colorVariant;
    root.dataset['face'] = next.faceVariant;
    root.setAttribute(
      'aria-label',
      `Companion: ${next.colorVariant} ${next.bodyVariant}, ${next.faceVariant} expression`,
    );
  };
  const onPointer = (event: PointerEvent): void => {
    if (!shown || reducedMotion || presenceState === 'working') return;
    const box = root.getBoundingClientRect();
    if (box.width <= 0 || box.height <= 0) return;
    const dx = Math.max(-9, Math.min(9,
      ((event.clientX - (box.left + box.width / 2)) / Math.max(1, window.innerWidth / 2)) * 9));
    const dy = Math.max(-6, Math.min(6,
      ((event.clientY - (box.top + box.height / 2)) / Math.max(1, window.innerHeight / 2)) * 6));
    avatar.gaze.setAttribute('transform', `translate(${dx.toFixed(2)} ${dy.toFixed(2)})`);
  };
  const onBlur = (): void => avatar.gaze.removeAttribute('transform');
  const onMotion = (): void => reflectMotion();

  reflectMotion();
  applyAppearance(appearance);
  root.setAttribute('data-ready', 'true');
  window.addEventListener('pointermove', onPointer);
  window.addEventListener('blur', onBlur);
  motionQuery?.addEventListener('change', onMotion);

  return {
    root,
    visible: () => shown,
    state: () => presenceState,
    setState(next) {
      presenceState = next;
      root.dataset['state'] = next;
    },
    setAppearance(next) {
      applyAppearance(next);
    },
    show() {
      shown = true;
      root.setAttribute('data-shown', 'true');
    },
    hide() {
      shown = false;
      root.removeAttribute('data-shown');
      avatar.gaze.removeAttribute('transform');
    },
    screenBox() {
      return shown ? root.getBoundingClientRect() : null;
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      window.removeEventListener('pointermove', onPointer);
      window.removeEventListener('blur', onBlur);
      motionQuery?.removeEventListener('change', onMotion);
      root.remove();
    },
  };
}
