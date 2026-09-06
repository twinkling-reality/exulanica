/**
 * Candidate B: bounded relief.
 *
 * The same silhouette, lit. Every shading layer is clipped to the body path, so the relief can
 * never exceed the outline: no drop shadow, no glow, no halo, nothing outside the shape the
 * catalog authored. That boundary is the whole proposition. It is what separates this from the
 * thing frontier-roadmap.md forbids, which is "relabeling SVG shading as 3D". This is shading. It
 * is 2D, it says so, and the question the bench asks is whether being lit is worth anything.
 *
 * It introduces no new colour data. Every tone is mixed from the one body colour the contract
 * already resolves, so a colour added to the catalog is lit for free and there is no second
 * palette to keep in step.
 */

import {
  companionAvatarBlueprint,
  DEFAULT_COMPANION,
  type CompanionAppearanceConfiguration,
  type CompanionEyePose,
  type CompanionOperationalState,
} from '@exulanica/presentation';

import { svgElement, WORKING_DOTS, type CompanionForm } from './form.js';

let instance = 0;

const lighter = (color: string, amount: number): string =>
  `color-mix(in oklab, ${color} ${100 - amount}%, white)`;
const darker = (color: string, amount: number): string =>
  `color-mix(in oklab, ${color} ${100 - amount}%, black)`;

export function createReliefForm(): CompanionForm {
  const id = `relief-${(instance += 1)}`;
  const element = document.createElement('div');
  element.className = 'form-canvas';

  const root = svgElement('svg', { viewBox: '0 0 240 240', 'aria-hidden': 'true' });
  const defs = svgElement('defs');

  const clip = svgElement('clipPath', { id: `${id}-clip` });
  const clipPath = svgElement('path');
  clip.append(clipPath);

  const key = svgElement('radialGradient', {
    id: `${id}-key`, cx: '34%', cy: '28%', r: '78%',
  });
  const keyNear = svgElement('stop', { offset: '0%' });
  const keyFar = svgElement('stop', { offset: '100%', 'stop-opacity': '0' });
  key.append(keyNear, keyFar);

  const shade = svgElement('linearGradient', {
    id: `${id}-shade`, x1: '18%', y1: '10%', x2: '86%', y2: '96%',
  });
  const shadeNone = svgElement('stop', { offset: '38%', 'stop-opacity': '0' });
  const shadeDeep = svgElement('stop', { offset: '100%' });
  shade.append(shadeNone, shadeDeep);

  defs.append(clip, key, shade);

  const body = svgElement('path', { class: 'relief-body', 'data-role': 'body' });
  const lit = svgElement('g', { 'clip-path': `url(#${id}-clip)` });
  const keyWash = svgElement('rect', { x: '0', y: '0', width: '240', height: '240', fill: `url(#${id}-key)` });
  const shadeWash = svgElement('rect', { x: '0', y: '0', width: '240', height: '240', fill: `url(#${id}-shade)` });
  // The rim is the silhouette drawn as a stroke and clipped to itself, so only the inner half of
  // the stroke survives. That is what keeps the lit edge inside the shape.
  const rim = svgElement('path', { class: 'relief-rim', fill: 'none', 'stroke-width': '7' });
  lit.append(keyWash, shadeWash, rim);

  const gaze = svgElement('g', { class: 'relief-gaze' });
  const leftEye = svgElement('rect', { class: 'relief-eye', 'data-role': 'eye' });
  const rightEye = svgElement('rect', { class: 'relief-eye', 'data-role': 'eye' });
  gaze.append(leftEye, rightEye);

  const orb = svgElement('g', { class: 'relief-orb' });
  orb.append(body, lit, gaze);

  const thinking = svgElement('g', { class: 'relief-thinking' });
  for (const dot of WORKING_DOTS) {
    thinking.append(svgElement('circle', {
      class: 'relief-dot', cx: String(dot.cx), cy: '120', r: String(dot.r),
    }));
  }

  root.append(defs, orb, thinking);
  element.append(root);

  const applyEyePose = (pose: CompanionEyePose): void => {
    const apply = (eye: SVGRectElement, values: CompanionEyePose['left']): void => {
      const [x, y, width, height, rotation] = values;
      eye.setAttribute('x', String(x));
      eye.setAttribute('y', String(y));
      eye.setAttribute('width', String(width));
      eye.setAttribute('height', String(height));
      eye.setAttribute('rx', String(width / 2));
      eye.setAttribute('transform', `rotate(${rotation} ${x + width / 2} ${y + height / 2})`);
    };
    apply(leftEye, pose.left);
    apply(rightEye, pose.right);
  };

  const setAppearance = (next: CompanionAppearanceConfiguration): void => {
    const blueprint = companionAvatarBlueprint(next);
    for (const path of [body, clipPath, rim]) path.setAttribute('d', blueprint.bodyPath);
    body.setAttribute('fill', next.bodyColor);
    keyNear.setAttribute('stop-color', lighter(next.bodyColor, 46));
    keyFar.setAttribute('stop-color', lighter(next.bodyColor, 46));
    shadeNone.setAttribute('stop-color', darker(next.bodyColor, 40));
    shadeDeep.setAttribute('stop-color', darker(next.bodyColor, 40));
    shadeDeep.setAttribute('stop-opacity', '0.55');
    rim.setAttribute('stroke', lighter(next.bodyColor, 62));
    for (const dot of thinking.querySelectorAll('circle')) dot.setAttribute('fill', next.bodyColor);
    leftEye.setAttribute('fill', next.eyeColor);
    rightEye.setAttribute('fill', next.eyeColor);
    applyEyePose(blueprint.eyePose);
  };

  const setState = (state: CompanionOperationalState): void => {
    root.dataset['state'] = state;
    const thinkingNow = state === 'working';
    orb.style.display = thinkingNow ? 'none' : '';
    thinking.style.display = thinkingNow ? '' : 'none';
  };

  setAppearance(DEFAULT_COMPANION);
  setState('resting');

  return {
    dossier: {
      id: 'relief',
      title: 'Bounded relief',
      summary:
        'The same silhouette, lit from upper left. Every shading layer is clipped to the body, '
        + 'so nothing leaves the outline. Two dimensions, and it does not claim otherwise.',
      renderer: 'None. Still inline SVG in the existing DOM overlay.',
      assets:
        'None. Tones are mixed from the one body colour the contract already resolves, so a new '
        + 'catalogue colour is lit without any new art.',
      accessibility:
        'Same as flat, with one addition to answer for: forced colours removes the gradients and '
        + 'must leave a legible filled silhouette rather than an empty outline.',
      silhouettes: 'Every catalogued silhouette, exactly. The relief is clipped to the same path.',
      workingState: 'Three pulsing dots replace the orb, unlit, exactly as flat does.',
    },
    element,
    setAppearance,
    setState,
    start: () => {},
    stop: () => {},
    dispose: () => element.replaceChildren(),
  };
}
