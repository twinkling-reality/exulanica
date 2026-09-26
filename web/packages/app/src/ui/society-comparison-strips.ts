/**
 * What each person did, minute by minute, on each side of a comparison, one above the other.
 *
 * A row per person: the left run's minutes, then the right run's, each minute a cell coloured by
 * what the person was doing, and between them a mark wherever the two runs had them doing
 * different things or heading for different places. The same people, the same seed and the same
 * start: a marked minute is where the two sides' deciders made the hour go differently for them.
 */

import type { RunPerson, RunReplay } from '../society-comparison-api.js';
import { el } from './dom.js';
import { classWords, minuteClass, type MinuteClass } from './society-comparison-plan.js';

/** Whether a person's minute differs between two runs: what they do, or where they are headed. */
export function differs(left: RunReplay, leftPerson: RunPerson, right: RunReplay, rightPerson: RunPerson): boolean {
  return classWords(left, minuteClass(left, leftPerson)) !== classWords(right, minuteClass(right, rightPerson)) ||
    (leftPerson.goal?.targetId ?? null) !== (rightPerson.goal?.targetId ?? null);
}

export interface ComparisonStrips {
  readonly root: HTMLElement;
  /** Mark the clock's minute and the selected person. */
  draw(minute: number, selected: string | null): void;
}

/**
 * Strips for the people both runs hold, in the left run's order. `onPick(side, subjectId, minute)`
 * is called when a cell is chosen, with the side it belongs to.
 */
export function buildComparisonStrips(
  left: RunReplay,
  right: RunReplay,
  sideNames: readonly [string, string],
  onPick: (side: 0 | 1, subjectId: string, minute: number) => void,
): ComparisonStrips {
  const minutes = Math.min(left.minutes.length, right.minutes.length) - 1;
  const byId = (run: RunReplay, index: number) =>
    new Map(run.minutes[index]!.people.map((person) => [person.id, person] as const));
  const leftMinutes = Array.from({ length: minutes }, (_, index) => byId(left, index + 1));
  const rightMinutes = Array.from({ length: minutes }, (_, index) => byId(right, index + 1));
  const runs = [left, right] as const;
  const rows: HTMLElement[] = [];
  const cursors: HTMLElement[] = [];
  const holders = new Map<string, HTMLElement>();
  for (const person of left.people) {
    if (!right.people.some((other) => other.id === person.id)) continue;
    const line = (side: 0 | 1): HTMLElement => {
      const run = runs[side];
      const cells = (side === 0 ? leftMinutes : rightMinutes).map((minute, index) => {
        const found = minute.get(person.id)!;
        const kind: MinuteClass = minuteClass(run, found);
        const cell = el('button', {
          type: 'button',
          class: 'comparison-strip-cell',
          'data-class': kind,
          'aria-label': `${person.name}, ${sideNames[side]}, minute ${index + 1}: ${classWords(run, kind)}`,
        });
        cell.addEventListener('click', () => onPick(side, person.id, index + 1));
        return cell;
      });
      return el('div', { class: 'comparison-strip-line', 'data-side': side === 0 ? 'left' : 'right' }, cells);
    };
    const marks = leftMinutes.map((minute, index) => el('span', {
      class: 'comparison-strip-mark',
      'data-differs': differs(left, minute.get(person.id)!, right, rightMinutes[index]!.get(person.id)!)
        ? 'yes' : 'no',
    }));
    const cursor = el('span', { class: 'comparison-strip-cursor', 'aria-hidden': 'true' });
    cursors.push(cursor);
    const track = el('div', { class: 'comparison-strip-track', style: `--minutes: ${minutes}` }, [
      line(0), el('div', { class: 'comparison-strip-marks', 'aria-hidden': 'true' }, marks), line(1), cursor,
    ]);
    const row = el('div', { class: 'comparison-strip', 'data-subject-id': person.id }, [
      el('span', { class: 'comparison-strip-name', text: person.name }), track,
    ]);
    holders.set(person.id, row);
    rows.push(row);
  }
  const classes: MinuteClass[] = ['walking', 'waiting', ...left.activities.map((_, index) => `activity-${index}` as const)];
  const legend = el('p', { class: 'comparison-strip-legend' }, classes.map((kind) =>
    el('span', { class: 'comparison-strip-key', 'data-class': kind, text: classWords(left, kind) })));
  const root = el('section', { class: 'comparison-strips', 'aria-label': 'What each person did' }, [
    el('h3', { text: 'What each person did' }),
    el('p', {
      class: 'comparison-strip-note',
      text: `Each row is one person, ${sideNames[0]} above and ${sideNames[1]} below. A mark between them is a minute the two hours went differently for that person.`,
    }),
    legend,
    ...rows,
  ]);
  return {
    root,
    draw(minute, selected) {
      const share = minutes === 0 ? 0 : Math.min(1, Math.max(0, minute / minutes));
      for (const cursor of cursors) cursor.style.left = `${share * 100}%`;
      for (const [id, row] of holders) row.classList.toggle('is-selected', id === selected);
    },
  };
}
