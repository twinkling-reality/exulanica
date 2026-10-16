// History's light page (r23, the user's yes on 16 October; DESIGN's R23 build sheet): its styles, and the story
// line drawn as one SVG the width of the path; history.ts places everything from history-rows.mjs's layout.
import './world-ui-history.css';

const SVG = 'http://www.w3.org/2000/svg';

/** One part of the story line's SVG (a path, a dot, the Now ring), in the layout's pixels. */
export function svgPart(tag: string, attrs: Record<string, string | number>, className = ''): SVGElement {
  const made = document.createElementNS(SVG, tag);
  if (className) made.setAttribute('class', className);
  for (const [name, value] of Object.entries(attrs)) made.setAttribute(name, String(value));
  return made;
}

/** The SVG the line's parts are drawn in, as wide and tall as the path. */
export function storySvg(width: number, height: number): SVGSVGElement {
  const made = document.createElementNS(SVG, 'svg');
  made.setAttribute('class', 'wu-hr-path');
  made.setAttribute('width', String(width));
  made.setAttribute('height', String(height));
  made.setAttribute('viewBox', `0 0 ${width} ${height}`);
  made.setAttribute('aria-hidden', 'true');
  return made;
}
