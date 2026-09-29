/**
 * What each person did, minute by minute, on each side of a comparison, one above the other.
 *
 * A row per person: the left run's minutes, then the right run's, each minute a cell coloured by
 * what the person was doing, and between them a mark wherever the two runs had them doing
 * different things or heading for different places. The same people, the same seed and the same
 * start: a marked minute is where the two sides' deciders made the hour go differently for them.
 *
 * A town holds tens of people, so the rows come in two parts: first the group the two sides
 * decide for, then everybody else, who keep one decider on both sides. Each part says how many of
 * its people's hours went differently, and lists them by how many minutes did, most first, each
 * row with its count. Everybody else is folded behind one control that says as much, and their
 * rows are only built when it is opened: what the group did changes the hour around them, so in a
 * town nearly everybody's hour goes differently, and the group's rows are the ones a comparison
 * is about.
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

/** One person both runs hold, with each minute's difference between the two sides. */
interface Compared {
  readonly id: string;
  readonly name: string;
  readonly inGroup: boolean;
  readonly marks: readonly boolean[];
  readonly differing: number;
}

const people = (count: number): string => `${count} ${count === 1 ? 'person' : 'people'}`;

/** Each minute after the start of ``run``, as the minutes both runs hold, its people by id. */
function minutesById(run: RunReplay, other: RunReplay): readonly ReadonlyMap<string, RunPerson>[] {
  const minutes = Math.min(run.minutes.length, other.minutes.length) - 1;
  return Array.from({ length: minutes }, (_, index) =>
    new Map(run.minutes[index + 1]!.people.map((person) => [person.id, person] as const)));
}

/**
 * The people both runs hold, each with the minutes their hour went differently, split into the
 * group the two sides decide for and everybody else, each part ordered by how many minutes
 * differed, most first, then as the left run lists them.
 */
export function comparedPeople(left: RunReplay, right: RunReplay): { readonly group: readonly Compared[]; readonly others: readonly Compared[] } {
  const [leftMinutes, rightMinutes] = [minutesById(left, right), minutesById(right, left)];
  const held = new Set(right.people.map((person) => person.id));
  const compared = left.people.filter((person) => held.has(person.id)).map((person, order) => {
    const marks = leftMinutes.map((minute, index) =>
      differs(left, minute.get(person.id)!, right, rightMinutes[index]!.get(person.id)!));
    return { order, value: { id: person.id, name: person.name, inGroup: person.inGroup, marks, differing: marks.filter(Boolean).length } };
  });
  const ordered = compared
    .sort((a, b) => b.value.differing - a.value.differing || a.order - b.order)
    .map((entry) => entry.value);
  return { group: ordered.filter((person) => person.inGroup), others: ordered.filter((person) => !person.inGroup) };
}

/**
 * Strips for the people both runs hold. `onPick(side, subjectId, minute)` is called when a cell is
 * chosen, with the side it belongs to.
 */
export function buildComparisonStrips(
  left: RunReplay,
  right: RunReplay,
  sideNames: readonly [string, string],
  onPick: (side: 0 | 1, subjectId: string, minute: number) => void,
): ComparisonStrips {
  const minutes = Math.min(left.minutes.length, right.minutes.length) - 1;
  const byMinute = [minutesById(left, right), minutesById(right, left)] as const;
  const runs = [left, right] as const;
  const cursors: HTMLElement[] = [];
  const holders = new Map<string, HTMLElement>();
  let drawn: { minute: number; selected: string | null } = { minute: 0, selected: null };

  const row = (person: Compared): HTMLElement => {
    const line = (side: 0 | 1): HTMLElement => {
      const run = runs[side];
      const cells = Array.from({ length: minutes }, (_, index) => {
        const kind: MinuteClass = minuteClass(run, byMinute[side][index]!.get(person.id)!);
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
    const marks = person.marks.map((different) => el('span', {
      class: 'comparison-strip-mark', 'data-differs': different ? 'yes' : 'no',
    }));
    const cursor = el('span', { class: 'comparison-strip-cursor', 'aria-hidden': 'true' });
    cursors.push(cursor);
    const track = el('div', { class: 'comparison-strip-track', style: `--minutes: ${minutes}` }, [
      line(0), el('div', { class: 'comparison-strip-marks', 'aria-hidden': 'true' }, marks), line(1), cursor,
    ]);
    const built = el('div', {
      class: 'comparison-strip', 'data-subject-id': person.id, 'data-in-group': String(person.inGroup),
      'data-differing': String(person.differing),
    }, [
      el('span', {
        class: 'comparison-strip-name',
        title: person.inGroup ? `${person.name}, of the group the arms decide for` : `${person.name}, outside the group`,
      }, [
        el('span', { class: 'comparison-strip-person', text: person.name }),
        el('span', {
          class: 'comparison-strip-count',
          text: person.differing === 0 ? 'the same' : `${person.differing} min differ`,
        }),
      ]),
      track,
    ]);
    holders.set(person.id, built);
    return built;
  };

  const { group, others } = comparedPeople(left, right);
  const everybody = others.length === 0;
  const moved = (part: readonly Compared[]) => part.filter((person) => person.differing > 0).length;
  const parts: HTMLElement[] = [];
  parts.push(el('section', { class: 'comparison-strip-part', 'data-part': 'group' }, [
    el('h4', {
      class: 'comparison-strip-part-title',
      text: everybody
        ? `Everybody, ${people(group.length)}: ${sideNames[0]} above, ${sideNames[1]} below. ${moved(group)} of ${group.length} hours went differently.`
        : `The group, ${people(group.length)}: ${sideNames[0]} above, ${sideNames[1]} below. ${moved(group)} of ${group.length} hours went differently.`,
    }),
    ...group.map(row),
  ]));
  if (!everybody) {
    const folded = el('details', { class: 'comparison-strip-others' }, [
      el('summary', {
        class: 'comparison-strip-part-title',
        text: `Everybody else, ${people(others.length)}, with one decider on both sides: ${moved(others)} of their hours went differently, since what the group did changes the hour around them. Show them.`,
      }),
    ]);
    folded.addEventListener('toggle', () => {
      if (!folded.open || folded.childElementCount > 1) return;
      folded.append(...others.map(row));
      strips.draw(drawn.minute, drawn.selected);
    });
    parts.push(el('section', { class: 'comparison-strip-part', 'data-part': 'others' }, [folded]));
  }
  const classes: MinuteClass[] = ['walking', 'waiting', ...left.activities.map((_, index) => `activity-${index}` as const)];
  const legend = el('p', { class: 'comparison-strip-legend' }, classes.map((kind) =>
    el('span', { class: 'comparison-strip-key', 'data-class': kind, text: classWords(left, kind) })));
  const root = el('section', { class: 'comparison-strips', 'aria-label': 'What each person did' }, [
    el('h3', { text: 'What each person did' }),
    el('p', {
      class: 'comparison-strip-note',
      text: `Each row is one person, ${sideNames[0]} above and ${sideNames[1]} below. A mark between them is a minute the two hours went differently for that person; the people whose hours went differently for longest come first.`,
    }),
    legend,
    ...parts,
  ]);
  const strips: ComparisonStrips = {
    root,
    draw(minute, selected) {
      drawn = { minute, selected };
      const share = minutes === 0 ? 0 : Math.min(1, Math.max(0, minute / minutes));
      for (const cursor of cursors) cursor.style.left = `${share * 100}%`;
      for (const [id, held] of holders) held.classList.toggle('is-selected', id === selected);
    },
  };
  return strips;
}
