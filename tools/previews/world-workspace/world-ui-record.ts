// The record pages' shared light-page parts (History r23, a character's day r06, a decision r10, Compare r12; DESIGN's
// R23 and R-DAY-DECISION build sheets): the faded world behind a light wash, the head, a picture with its rim, round
// portraits, a model's name kept on one line, and the key row with its small caps. One source, so the pages read as
// one family; each page places these parts and adds only its own.
import './world-ui-record.css';

/** A sentence's parts: plain text, and a model's name the page keeps on one line. */
export type Parts = readonly (string | { readonly model: string })[];

export function element<K extends keyof HTMLElementTagNameMap>(tag: K, className = '', words = ''): HTMLElementTagNameMap[K] {
  const made = document.createElement(tag);
  if (className) made.className = className;
  if (words) made.textContent = words;
  return made;
}

/** A sentence from its parts, each model's name in a span that never breaks. */
export function sentence(tag: 'div' | 'span' | 'p', className: string, parts: Parts | string): HTMLElement {
  const made = element(tag, className);
  for (const part of typeof parts === 'string' ? [parts] : parts) {
    made.append(typeof part === 'string' ? document.createTextNode(part) : element('span', 'wu-hr-model', part.model));
  }
  return made;
}

export function px(node: HTMLElement, left: number, top: number, width?: number, height?: number) {
  node.style.left = `${left}px`;
  node.style.top = `${top}px`;
  if (width !== undefined) node.style.width = `${width}px`;
  if (height !== undefined) node.style.height = `${height}px`;
}

/** A key the page answers, drawn as the sheets draw it: its caps, then its word; pressing it does what the key does. */
export function keyButton(keys: readonly string[], word: string, onPress: () => void): HTMLButtonElement {
  const button = element('button', 'wu-hr-key');
  button.type = 'button';
  for (const key of keys) button.append(element('kbd', 'wu-hr-cap', key));
  button.append(element('span', 'wu-hr-key-word', word));
  button.addEventListener('click', onPress);
  return button;
}

/** The key row, bottom right (100px in and 40px up; 64 and 32 at 1440). */
export function keyRow(keys: readonly HTMLButtonElement[]): HTMLDivElement {
  const row = element('div', 'wu-hr-keys');
  row.append(...keys);
  return row;
}

/** The picture addresses the record pages have shown in this window: drawn again, they start shown, so none fades in twice. */
const shownPictures = new Set<string>();

/**
 * A picture, or the quiet tile while it does not exist (no spinner, no words); it fades in once, when it first arrives,
 * and a redraw of a picture already shown (a page drawn again each second during a run) starts shown.
 */
export function pictureBox(url: string | null, width: number, height: number): HTMLDivElement {
  const box = element('div', 'wu-hr-pic');
  box.style.width = `${width}px`;
  box.style.height = `${height}px`;
  if (url) {
    const image = element('img');
    image.alt = '';
    if (shownPictures.has(url)) image.setAttribute('data-loaded', 'true');
    else image.addEventListener('load', () => { shownPictures.add(url); image.setAttribute('data-loaded', 'true'); });
    image.src = url;
    box.append(image);
  }
  return box;
}

/** At most this many portraits in a row; more become "+n". */
export const ORBS = 3;

/** Round portraits, overlapping, the first who acted first: each a picture, or the name's first letter until one exists. */
export function orbs(subjects: readonly string[], size: number, portrait: (id: string) => string | null | undefined, nameOf: (id: string) => string): HTMLDivElement {
  const row = element('div', 'wu-hr-orbs');
  for (const subject of subjects.slice(0, ORBS)) row.append(orb(subject, size, portrait(subject) ?? null, nameOf(subject)));
  if (subjects.length > ORBS) {
    const more = element('span', 'wu-hr-orb more', `+${subjects.length - ORBS}`);
    more.style.width = more.style.height = `${size}px`;
    row.append(more);
  }
  return row;
}

/** One round portrait: the picture, or the first letter of the name as the tag says it ("the heron" is "H"). */
export function orb(_subject: string, size: number, url: string | null, name: string): HTMLSpanElement {
  const made = element('span', 'wu-hr-orb');
  made.style.width = made.style.height = `${size}px`;
  if (url) {
    const image = element('img');
    image.alt = '';
    image.src = url;
    made.append(image);
  } else {
    made.textContent = name.replace(/^the /, '').charAt(0).toUpperCase();
  }
  return made;
}

/** The page's ground: the world faded behind (a still or the entry's picture) under the light wash. */
export function ground(picture: string | null): readonly [HTMLDivElement, HTMLDivElement] {
  const world = element('div', 'wu-hr-world');
  if (picture) world.style.backgroundImage = `url("${picture}")`;
  return [world, element('div', 'wu-hr-wash')];
}
