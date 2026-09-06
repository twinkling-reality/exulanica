/**
 * One shape for three candidates, so the comparison is about form and nothing else.
 *
 * frontier-roadmap.md requires that genuine 3D Companion depth be treated as "a new renderer,
 * asset-provenance, performance, and accessibility decision rather than relabeling SVG shading as
 * 3D", and asks for 2D, bounded relief and world-rendered prototypes before that contract is
 * approved. Those four words are the columns of the dossier below: a candidate that renders well
 * and answers none of them has not earned anything.
 *
 * Every candidate draws the same silhouette, the same colour, the same expression and the same
 * operational states, from the same versioned contract, so a difference on screen is a difference
 * of form rather than of content.
 */

import type {
  CompanionAppearanceConfiguration,
  CompanionOperationalState,
} from '@exulanica/presentation';

export type CompanionFormId = 'flat' | 'relief' | 'world';

export interface FormDossier {
  readonly id: CompanionFormId;
  readonly title: string;
  /** One line on what the form is, for the person reading the bench. */
  readonly summary: string;
  /** What has to exist in the product before this form can ship. */
  readonly renderer: string;
  /** What art has to exist, and where it would come from. The licence question in one line. */
  readonly assets: string;
  /** How it behaves for reduced motion, forced colours, and a screen reader. */
  readonly accessibility: string;
  /** Which of the contract's silhouettes this form can actually draw. */
  readonly silhouettes: string;
  /** How this form renders `working`, the one state with a semantic render. */
  readonly workingState: string;
}

export interface CompanionForm {
  readonly dossier: FormDossier;
  /** The bench mounts this. Every candidate is one element, sized by the bench, not by itself. */
  readonly element: HTMLElement;
  setAppearance(configuration: CompanionAppearanceConfiguration): void;
  setState(state: CompanionOperationalState): void;
  /**
   * Begin and end the form's own frame production.
   *
   * The SVG candidates produce no frames of their own and implement these as no-ops, which is
   * itself part of the result: a form that costs nothing when nothing is happening is a different
   * proposition from one that holds a render loop open.
   */
  start(): void;
  stop(): void;
  dispose(): void;
}

export interface CompanionFormFactory {
  (): CompanionForm;
}

export const SVG_NS = 'http://www.w3.org/2000/svg';

export function svgElement<K extends keyof SVGElementTagNameMap>(
  tag: K,
  attributes: Readonly<Record<string, string>> = {},
): SVGElementTagNameMap[K] {
  const element = document.createElementNS(SVG_NS, tag);
  for (const [name, value] of Object.entries(attributes)) element.setAttribute(name, value);
  return element;
}

/** The three working dots, at the positions the shipping avatar uses. */
export const WORKING_DOTS = Object.freeze([
  { cx: 78, r: 13 },
  { cx: 120, r: 17 },
  { cx: 162, r: 13 },
]);
