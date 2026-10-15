// History's own parts (DESIGN's specification, 5.12 and 8.19; frame 23): the timeline and the
// one-line row. They only draw; choosing a change is the caller's. Their look lives in
// world-ui-history.css, built from world-ui.css's tokens.
import './world-ui-history.css';

const SVG = 'http://www.w3.org/2000/svg';
/** The timeline's frame in reference pixels (frame 23): 1680 wide, the line at 85 of 170. */
const WIDTH = 1680;
const HEIGHT = 170;
const LINE = 85;
/** Where the first mark and "Now" stand, and the room a comparison's branches take. */
const FIRST = 40;
const NOW = 1660;
const BRANCH = 220;

export interface TimelineMark {
  readonly id: string;
  readonly words: string;
  readonly time: string;
  readonly chosen: boolean;
  readonly above: boolean;
  /** A comparison's two models, drawn as branches named by them. */
  readonly branches: readonly string[] | null;
}

function svg<K extends keyof SVGElementTagNameMap>(tag: K, attributes: Record<string, string | number>, className = ''): SVGElementTagNameMap[K] {
  const made = document.createElementNS(SVG, tag);
  for (const [name, value] of Object.entries(attributes)) made.setAttribute(name, String(value));
  if (className) made.setAttribute('class', className);
  return made;
}

function text(words: string, x: number, y: number, className: string, chosen = false): SVGTextElement {
  const made = svg('text', { x, y }, className);
  if (chosen) made.dataset.chosen = 'true';
  made.textContent = words;
  return made;
}

/** Where each mark stands: evenly from the first to just short of "Now", a comparison taking the room of its branches. */
function positions(marks: readonly TimelineMark[]): number[] {
  const branched = marks.filter((mark) => mark.branches && mark.branches.length === 2).length;
  const span = NOW - FIRST - BRANCH * branched;
  const step = marks.length > 0 ? span / marks.length : 0;
  const placed: number[] = [];
  let x = FIRST;
  for (const mark of marks) {
    placed.push(x);
    x += step + (mark.branches && mark.branches.length === 2 ? BRANCH : 0);
  }
  return placed;
}

/**
 * The timeline (5.12): a line fading in from the left, a node and its words for each mark
 * (alternating above and below), a comparison's two branches named by their models, and "Now",
 * a pulsing ring at the right end. `choose` runs when a mark is pressed.
 */
export function timeline(marks: readonly TimelineMark[], now: { readonly words: string; readonly time: string }, choose: (id: string) => void): SVGSVGElement {
  const root = svg('svg', { viewBox: `0 0 ${WIDTH} ${HEIGHT}`, overflow: 'visible', role: 'list' }, 'wu-timeline');
  const defs = svg('defs', {});
  const glow = svg('filter', { id: 'wu-tl-glow', x: '-100%', y: '-100%', width: '300%', height: '300%' });
  glow.append(svg('feGaussianBlur', { stdDeviation: 4 }));
  // In the timeline's own units: a gradient sized by a level line's box (no height) draws nothing.
  const fade = svg('linearGradient', { id: 'wu-tl-fade', gradientUnits: 'userSpaceOnUse', x1: 0, y1: LINE, x2: WIDTH, y2: LINE });
  for (const [offset, opacity] of [[0, 0.15], [0.1, 0.55], [1, 0.75]]) {
    fade.append(svg('stop', { offset, style: 'stop-color: var(--ink)', 'stop-opacity': opacity }));
  }
  defs.append(glow, fade);
  root.append(defs, svg('line', { x1: 0, y1: LINE, x2: WIDTH, y2: LINE, stroke: 'url(#wu-tl-fade)' }, 'wu-tl-line'));
  const placed = positions(marks);
  marks.forEach((mark, index) => {
    const x = placed[index];
    const group = svg('g', { tabindex: 0, role: 'listitem', 'aria-label': `${mark.time}, ${mark.words}`, 'data-id': mark.id }, 'wu-tl-mark');
    if (mark.chosen) group.dataset.chosen = 'true';
    group.addEventListener('click', () => choose(mark.id));
    group.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') choose(mark.id);
    });
    if (mark.branches && mark.branches.length === 2) {
      const [upper, lower] = mark.branches;
      for (const [y, name] of [[22, upper], [148, lower]] as const) {
        const end = x + BRANCH;
        group.append(
          svg('path', { d: `M${x} ${LINE} L ${x + 80} ${LINE} C ${x + 125} ${LINE}, ${x + 130} ${y}, ${x + 175} ${y} L ${end} ${y}` }, 'wu-tl-branch'),
          svg('circle', { cx: end, cy: y, r: 5 }, 'wu-tl-end'),
          text(name, end + 14, y + 5, 'wu-tl-model'),
        );
      }
    }
    if (mark.chosen) group.append(svg('circle', { cx: x, cy: LINE, r: 16, filter: 'url(#wu-tl-glow)' }, 'wu-tl-glow'));
    const node = svg('circle', { cx: x, cy: LINE, r: mark.chosen ? 9 : 6 }, 'wu-tl-node');
    if (mark.chosen) node.dataset.chosen = 'true';
    group.append(node);
    if (mark.above) {
      group.append(text(mark.words, x, 56, 'wu-tl-label', mark.chosen), text(mark.time, x, 36, 'wu-tl-time'));
    } else {
      group.append(text(mark.words, x, 124, 'wu-tl-label', mark.chosen), text(mark.time, x, 144, 'wu-tl-time'));
    }
    root.append(group);
  });
  root.append(
    svg('circle', { cx: NOW, cy: LINE, r: 13 }, 'wu-tl-now-ring'),
    svg('circle', { cx: NOW, cy: LINE, r: 5 }, 'wu-tl-now'),
    text(now.words, NOW, 56, 'wu-tl-now-label'),
    text(now.time, NOW, 122, 'wu-tl-time'),
  );
  return root;
}

/**
 * Keeps every word of a drawn timeline inside its frame, 0 to 1680, the page's margins: an end mark's
 * label is moved in from its mark rather than centred out over the margin. Text is measured, so the
 * timeline must already be in the page; where nothing can be measured, nothing moves.
 */
export function keepInside(root: SVGSVGElement): void {
  for (const words of root.querySelectorAll('text')) {
    let box: { x: number; width: number };
    try {
      box = words.getBBox();
    } catch {
      continue;
    }
    const shift = box.x < 0 ? -box.x : box.x + box.width > WIDTH ? WIDTH - box.x - box.width : 0;
    if (shift) words.setAttribute('x', String(Number(words.getAttribute('x')) + shift));
  }
}

function element<K extends keyof HTMLElementTagNameMap>(tag: K, className = '', words = ''): HTMLElementTagNameMap[K] {
  const made = document.createElement(tag);
  if (className) made.className = className;
  if (words) made.textContent = words;
  return made;
}

/** One History row (5.12): its time, its words, and on the right what it spent. */
export function historyRow({ time, words, cost, chosen, onPress }: {
  readonly time: string;
  readonly words: string;
  readonly cost: string;
  readonly chosen: boolean;
  readonly onPress: () => void;
}): HTMLButtonElement {
  const row = element('button', 'wu-history-row');
  row.type = 'button';
  if (chosen) row.setAttribute('aria-current', 'true');
  row.append(element('span', 'wu-time', time), element('span', 'wu-what', words), element('span', 'wu-cost', cost));
  row.addEventListener('click', onPress);
  return row;
}
