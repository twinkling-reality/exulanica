/**
 * Candidate A: flat. The control.
 *
 * This is the grammar the product ships today: one filled silhouette and two slit eyes, no
 * gradient, no filter, no stroke. It is here to be beaten. If neither of the other two candidates
 * is worth its cost, the answer to the depth question is that there is nothing to approve, and
 * that is a result rather than a failure.
 */

import {
  companionAvatarBlueprint,
  DEFAULT_COMPANION,
  type CompanionAppearanceConfiguration,
  type CompanionEyePose,
  type CompanionOperationalState,
} from '@exulanica/presentation';

import { svgElement, WORKING_DOTS, type CompanionForm } from './form.js';

function applyEyePose(
  left: SVGRectElement,
  right: SVGRectElement,
  pose: CompanionEyePose,
): void {
  const apply = (eye: SVGRectElement, values: CompanionEyePose['left']): void => {
    const [x, y, width, height, rotation] = values;
    eye.setAttribute('x', String(x));
    eye.setAttribute('y', String(y));
    eye.setAttribute('width', String(width));
    eye.setAttribute('height', String(height));
    eye.setAttribute('rx', String(width / 2));
    eye.setAttribute('transform', `rotate(${rotation} ${x + width / 2} ${y + height / 2})`);
  };
  apply(left, pose.left);
  apply(right, pose.right);
}

export function createFlatForm(): CompanionForm {
  const element = document.createElement('div');
  element.className = 'form-canvas';

  const root = svgElement('svg', { viewBox: '0 0 240 240', 'aria-hidden': 'true' });
  const orb = svgElement('g', { class: 'flat-orb' });
  const body = svgElement('path', { class: 'flat-body', 'data-role': 'body' });
  const gaze = svgElement('g', { class: 'flat-gaze' });
  const leftEye = svgElement('rect', { class: 'flat-eye', 'data-role': 'eye' });
  const rightEye = svgElement('rect', { class: 'flat-eye', 'data-role': 'eye' });
  gaze.append(leftEye, rightEye);
  orb.append(body, gaze);

  const thinking = svgElement('g', { class: 'flat-thinking' });
  for (const dot of WORKING_DOTS) {
    thinking.append(svgElement('circle', {
      class: 'flat-dot', cx: String(dot.cx), cy: '120', r: String(dot.r),
    }));
  }
  root.append(orb, thinking);
  element.append(root);

  let appearance: CompanionAppearanceConfiguration = DEFAULT_COMPANION;

  const setAppearance = (next: CompanionAppearanceConfiguration): void => {
    appearance = next;
    const blueprint = companionAvatarBlueprint(next);
    body.setAttribute('d', blueprint.bodyPath);
    body.setAttribute('fill', next.bodyColor);
    for (const dot of thinking.querySelectorAll('circle')) dot.setAttribute('fill', next.bodyColor);
    leftEye.setAttribute('fill', next.eyeColor);
    rightEye.setAttribute('fill', next.eyeColor);
    applyEyePose(leftEye, rightEye, blueprint.eyePose);
  };

  const setState = (state: CompanionOperationalState): void => {
    root.dataset['state'] = state;
    // Only `working` has a distinct semantic render. Everything else is the same face, which is
    // what interaction-model.md says and what all three candidates must therefore do.
    const thinkingNow = state === 'working';
    orb.style.display = thinkingNow ? 'none' : '';
    thinking.style.display = thinkingNow ? '' : 'none';
    void appearance;
  };

  setAppearance(DEFAULT_COMPANION);
  setState('resting');

  return {
    dossier: {
      id: 'flat',
      title: 'Flat',
      summary: 'The shipping grammar. One filled silhouette, two slit eyes, nothing else.',
      renderer: 'None. Inline SVG in the existing DOM overlay.',
      assets: 'None. Geometry is the versioned blueprint, already in the repository.',
      accessibility:
        'Decorative and aria-hidden; the DOM lens carries every semantic. Survives forced '
        + 'colours because a fill can be overridden. Nothing to stop under reduced motion.',
      silhouettes: 'Every catalogued silhouette, exactly, because each one is a path.',
      workingState: 'Three pulsing dots replace the orb.',
    },
    element,
    setAppearance,
    setState,
    start: () => {},
    stop: () => {},
    dispose: () => element.replaceChildren(),
  };
}
