/**
 * One run of a comparison drawn from above: the ground people walk, the places they use, and each
 * person where the run's recorded minutes put them.
 *
 * Drawn in the place's own frame, in millimetres, east to the right and south down, so nothing is
 * rescaled by hand and two plans of one world line up. A person between two minutes is drawn along
 * the path the engine recorded for the later minute, never across its corners; at a whole minute
 * they are exactly where that minute's state says. Nothing here decides what a person does.
 */

import type { RunPerson, RunReplay } from '../society-comparison-api.js';

const SVG = 'http://www.w3.org/2000/svg';
/** Room around the drawn place, in millimetres, so a person at the edge is not cut off. */
const MARGIN_MM = 1500;
/** Radii in millimetres: a person, a place to sit or stand, a target's own mark. */
const PERSON_MM = 420;
const PLACE_MM = 220;
const TARGET_MM = 320;

/**
 * What a person was doing in a recorded minute: walking when the minute's path moved, one of the
 * run's activities while it was under way or finished in that minute, and otherwise waiting. An
 * activity is named by its place in the run's own list, which carries the routine's words.
 */
export type MinuteClass = 'walking' | 'waiting' | `activity-${number}`;

const UNDER_WAY: ReadonlySet<string> = new Set(['active', 'completed']);

export function minuteClass(run: Pick<RunReplay, 'activities'>, person: RunPerson): MinuteClass {
  if (person.path.length > 1) return 'walking';
  const index = run.activities.findIndex((activity) => activity.kind === person.action);
  return UNDER_WAY.has(person.status) && index >= 0 ? `activity-${index}` : 'waiting';
}

/** The words a minute's class reads as: the routine's for an activity, the page's otherwise. */
export function classWords(run: Pick<RunReplay, 'activities'>, found: MinuteClass): string {
  if (found === 'walking') return 'walking';
  if (found === 'waiting') return 'waiting where they are';
  return run.activities[Number(found.slice('activity-'.length))]!.label;
}

/** Where a person is `fraction` of the way through a minute, walking its path at a steady pace. */
export function along(path: readonly (readonly [number, number])[], fraction: number): readonly [number, number] {
  if (path.length === 0) throw new Error('A recorded minute has at least one point');
  if (path.length === 1 || fraction <= 0) return path[0]!;
  if (fraction >= 1) return path[path.length - 1]!;
  const lengths = path.slice(1).map((point, index) =>
    Math.hypot(point[0] - path[index]![0], point[1] - path[index]![1]));
  const total = lengths.reduce((sum, length) => sum + length, 0);
  if (total === 0) return path[path.length - 1]!;
  let left = fraction * total;
  for (let index = 0; index < lengths.length; index += 1) {
    const length = lengths[index]!;
    if (left <= length) {
      const [x0, z0] = path[index]!;
      const [x1, z1] = path[index + 1]!;
      const t = length === 0 ? 0 : left / length;
      return [x0 + (x1 - x0) * t, z0 + (z1 - z0) * t];
    }
    left -= length;
  }
  return path[path.length - 1]!;
}

/**
 * The recorded minute a clock reading falls in, and how far through it the clock is. Minute 0 is
 * the start; a clock between two whole minutes is part way through the later one.
 */
export function minuteAt(run: Pick<RunReplay, 'minutes'>, clock: number): { readonly index: number; readonly fraction: number } {
  const last = run.minutes.length - 1;
  if (clock <= 0) return { index: 0, fraction: 1 };
  if (clock >= last) return { index: last, fraction: 1 };
  const index = Math.ceil(clock);
  return { index, fraction: clock - (index - 1) };
}

const node = <K extends keyof SVGElementTagNameMap>(
  tag: K, attributes: Record<string, string | number> = {},
): SVGElementTagNameMap[K] => {
  const element = document.createElementNS(SVG, tag);
  for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, String(value));
  return element;
};

export interface ComparisonPlan {
  readonly root: SVGSVGElement;
  /** Draw every person where the clock puts them, and ring the one selected. */
  draw(clock: number, selected: string | null): void;
}

/** A plan of `run`; `onPick` is called with a person's id when they are clicked or chosen. */
export function buildComparisonPlan(
  run: RunReplay,
  labelled: string,
  onPick: (subjectId: string) => void,
): ComparisonPlan {
  // The frame holds every place and every point anybody stands on or walks through in the run,
  // so nothing that moves leaves it and the ground beyond does not shrink the drawing.
  const points = [
    ...run.targets.flatMap((t) => [[t.x, t.z] as const, ...t.places]),
    ...run.minutes.flatMap((minute) => minute.people.flatMap((p) => [[p.x, p.z] as const, ...p.path])),
  ];
  const xs = points.map(([x]) => x);
  const zs = points.map(([, z]) => z);
  const minX = Math.min(...xs) - MARGIN_MM;
  const minZ = Math.min(...zs) - MARGIN_MM;
  const width = Math.max(...xs) + MARGIN_MM - minX;
  const depth = Math.max(...zs) + MARGIN_MM - minZ;
  const root = node('svg', {
    class: 'comparison-plan',
    viewBox: `${minX} ${minZ} ${width} ${depth}`,
    role: 'group',
    'aria-label': labelled,
    preserveAspectRatio: 'xMidYMid meet',
  });
  const ground = node('g', { class: 'comparison-plan-ground', 'aria-hidden': 'true' });
  const at = new Map(run.nodes.map((n) => [n.id, n] as const));
  for (const [from, to] of run.edges) {
    const a = at.get(from);
    const b = at.get(to);
    if (a === undefined || b === undefined) continue;
    ground.append(node('line', { x1: a.x, y1: a.z, x2: b.x, y2: b.z }));
  }
  const places = node('g', { class: 'comparison-plan-places' });
  for (const target of run.targets) {
    const mark = node('g', { class: 'comparison-plan-target', 'data-affordance': target.affordance });
    const title = node('title');
    title.textContent = target.label;
    mark.append(title, node('circle', { cx: target.x, cy: target.z, r: TARGET_MM }));
    for (const [x, z] of target.places) {
      mark.append(node('circle', { class: 'comparison-plan-seat', cx: x, cy: z, r: PLACE_MM }));
    }
    places.append(mark);
  }
  const people = node('g', { class: 'comparison-plan-people' });
  const dots = new Map<string, SVGGElement>();
  for (const person of run.people) {
    const dot = node('g', {
      class: 'comparison-plan-person',
      tabindex: 0,
      role: 'button',
      'aria-label': person.name,
      'data-subject-id': person.id,
    });
    const title = node('title');
    title.textContent = person.name;
    const initial = node('text', { 'text-anchor': 'middle', 'dominant-baseline': 'central' });
    initial.textContent = person.name.slice(0, 1);
    dot.append(title, node('circle', { r: PERSON_MM }), initial);
    dot.addEventListener('click', () => onPick(person.id));
    dot.addEventListener('keydown', (event) => {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      event.preventDefault();
      onPick(person.id);
    });
    dots.set(person.id, dot);
    people.append(dot);
  }
  root.append(ground, places, people);
  return {
    root,
    draw(clock, selected) {
      const { index, fraction } = minuteAt(run, clock);
      for (const person of run.minutes[index]!.people) {
        const dot = dots.get(person.id);
        if (dot === undefined) continue;
        const [x, z] = along(person.path, fraction);
        dot.setAttribute('transform', `translate(${x} ${z})`);
        dot.setAttribute('data-class', minuteClass(run, person));
        dot.classList.toggle('is-selected', person.id === selected);
      }
    },
  };
}
