/** A decorative micro-render of the shared Companion blueprint for title-menu wayfinding. */

import {
  companionAppearanceConfiguration,
  companionAvatarBlueprint,
  DEFAULT_COMPANION,
  type CompanionEyeShape,
  type CompanionFaceVariant,
} from '@exulanica/presentation';

const SVG_NS = 'http://www.w3.org/2000/svg';

/**
 * The expressions this menu can wear.
 *
 * They are the appearance contract's own face variants, not new art. The Companion is one
 * character with one silhouette and one colour, so what distinguishes one station from another is
 * what it is doing with its eyes, which is exactly what `motionProfile: 'gaze-and-blink'` in
 * companion-appearance.ts says this thing expresses itself with.
 */
export const MENU_FACES: readonly CompanionFaceVariant[] = Object.freeze([
  'neutral',
  'attentive',
  'curious',
  'happy',
  'sleepy',
]);

function svgElement<K extends keyof SVGElementTagNameMap>(
  tag: K,
  attributes: Readonly<Record<string, string>> = {},
): SVGElementTagNameMap[K] {
  const element = document.createElementNS(SVG_NS, tag);
  for (const [name, value] of Object.entries(attributes)) element.setAttribute(name, value);
  return element;
}

function eye(values: CompanionEyeShape, color: string): SVGRectElement {
  const [x, y, width, height, rotation] = values;
  return svgElement('rect', {
    class: 'companion-menu-eye',
    x: String(x),
    y: String(y),
    width: String(width),
    height: String(height),
    rx: String(width / 2),
    fill: `var(--companion-eye, ${color})`,
    transform: `rotate(${rotation} ${x + width / 2} ${y + height / 2})`,
  });
}

/**
 * One eyelid, holding every expression at once.
 *
 * All five poses are rendered and the stylesheet reveals one, rather than rewriting rectangle
 * geometry when the Companion changes station. Two reasons. Attributes do not transition, so a
 * rewrite would need a timer to land while the lids are shut, and a timer racing a pointer
 * sweeping down five entries is a source of wrong faces. Reveal is a `visibility` change, which
 * takes a delay in CSS and can be parked at the closed frame of the blink for free.
 *
 * The blink also lives here rather than on the rectangles, because the pose rotation is a
 * `transform` attribute and a CSS transform on the same element would replace it.
 */
function eyelid(side: 'left' | 'right', eyeColor: string): SVGGElement {
  const lid = svgElement('g', { class: 'companion-menu-blink', 'data-eye': side });
  for (const face of MENU_FACES) {
    const pose = companionAvatarBlueprint(
      companionAppearanceConfiguration({
        body: DEFAULT_COMPANION.bodyVariant,
        color: DEFAULT_COMPANION.colorVariant,
        face,
      }),
    ).eyePose;
    const held = svgElement('g', { class: 'companion-menu-face', 'data-face': face });
    held.append(eye(pose[side], eyeColor));
    lid.append(held);
  }
  return lid;
}

export function createCompanionMenuMarker(): SVGSVGElement {
  const appearance = DEFAULT_COMPANION;
  const blueprint = companionAvatarBlueprint(appearance);
  const root = svgElement('svg', {
    class: 'companion-menu-marker',
    viewBox: blueprint.viewBox,
    'aria-hidden': 'true',
    focusable: 'false',
  });
  const gradientId = 'companion-menu-wake-gradient';
  const gradient = svgElement('linearGradient', {
    id: gradientId,
    x1: '0%',
    y1: '12%',
    x2: '100%',
    y2: '88%',
  });
  /*
   * The wake takes its colour from whichever station the Companion is standing in.
   *
   * The stops are custom properties so the stylesheet owns that, and the fallbacks are the
   * original fixed colours so the marker still renders correctly on its own. The body and the
   * eyes are deliberately left out of this: companion-appearance.ts records that a saturated
   * Companion reads as a sticker on the field, and ink is the default for that reason. The light
   * around it is not the Companion.
   */
  gradient.append(
    svgElement('stop', {
      offset: '0%',
      'stop-color': 'var(--companion-wake-near, #d9ff73)',
      'stop-opacity': '0.3',
    }),
    svgElement('stop', { offset: '54%', 'stop-color': 'var(--companion-wake-mid, #cfe4ff)' }),
    svgElement('stop', {
      offset: '100%',
      'stop-color': 'var(--companion-wake-far, #ddd7ff)',
      'stop-opacity': '0.65',
    }),
  );
  const definitions = svgElement('defs');
  definitions.append(gradient);
  const wake = svgElement('ellipse', {
    class: 'companion-menu-wake',
    cx: '120',
    cy: '120',
    rx: '180',
    ry: '80',
    fill: `url(#${gradientId})`,
  });
  const orb = svgElement('g', { class: 'companion-menu-orb' });
  const gaze = svgElement('g', { class: 'companion-menu-gaze' });
  gaze.append(eyelid('left', appearance.eyeColor), eyelid('right', appearance.eyeColor));
  orb.append(
    svgElement('path', {
      class: 'companion-menu-body',
      d: blueprint.bodyPath,
      fill: `var(--companion-body, ${appearance.bodyColor})`,
    }),
    gaze,
  );
  /*
   * The wake and the orb share one carrier so the whole character breathes together.
   *
   * It cannot go on the orb itself: the travel keyframes own that element's transform, and once a
   * visitor has moved the marker once the travel rule would suppress an idle animation declared
   * beside it for the rest of the session. It cannot go on the root either, which carries the
   * column travel. A carrier between them composes with both.
   */
  /*
   * A carrier for posture, between the breath and the travel.
   *
   * Head tilt cannot go on the orb, whose transform the travel keyframes own, nor on the carrier
   * below, whose transform the breath owns. It wraps the orb alone so the wake stays level: the
   * light around the Companion is the station's, not the Companion's, and it does not lean.
   */
  const pose = svgElement('g', { class: 'companion-menu-pose' });
  pose.append(orb);
  const life = svgElement('g', { class: 'companion-menu-life' });
  life.append(wake, pose);
  root.append(definitions, life);
  root.dataset['state'] = 'resting';
  root.dataset['face'] = 'neutral';
  return root;
}
