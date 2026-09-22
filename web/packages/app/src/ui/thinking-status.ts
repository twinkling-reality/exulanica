import {
  MODE_DRAWS,
  resolvePreset,
  type OrbState,
} from 'thinking-orbs/engine';
import { el } from './dom.js';

const ORB_SIZE = 64;

function animateOrb(canvas: HTMLCanvasElement, state: OrbState): void {
  const ratio = Math.min(2, window.devicePixelRatio || 1);
  canvas.width = Math.round(ORB_SIZE * ratio);
  canvas.height = Math.round(ORB_SIZE * ratio);
  const context = canvas.getContext('2d');
  if (context === null) return;
  const { mode, speed, opts } = resolvePreset(state, ORB_SIZE);
  const draw = MODE_DRAWS[mode];
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  const paint = (seconds: number): void => {
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.clearRect(0, 0, ORB_SIZE, ORB_SIZE);
    draw(context, ORB_SIZE, seconds * speed, false, opts);
  };

  if (reduced || typeof requestAnimationFrame !== 'function') {
    paint(0.6);
    return;
  }

  let frame = 0;
  const tick = (now: number): void => {
    if (!canvas.isConnected) return;
    paint(now / 1000);
    frame = requestAnimationFrame(tick);
  };
  frame = requestAnimationFrame(tick);
  window.addEventListener('pagehide', () => cancelAnimationFrame(frame), { once: true });
}

export function buildThinkingStatus(
  label = 'Opening your world',
  detail = '',
  state: OrbState = 'connecting',
): HTMLElement {
  const canvas = el('canvas', {
    class: 'thinking-orb',
    'aria-hidden': 'true',
  }) as HTMLCanvasElement;
  canvas.style.width = `${ORB_SIZE}px`;
  canvas.style.height = `${ORB_SIZE}px`;

  const status = el('section', { class: 'startup-thinking', role: 'status' }, [
    canvas,
    el('div', { class: 'startup-thinking-copy' }, [
      el('p', { class: 'startup-thinking-label', text: label }),
      // A second line only when there is something true to say. The one this replaces described
      // machinery to somebody who has not added a photograph yet.
      ...(detail === '' ? [] : [el('p', { class: 'startup-thinking-detail', text: detail })]),
    ]),
  ]);
  animateOrb(canvas, state);
  return status;
}
