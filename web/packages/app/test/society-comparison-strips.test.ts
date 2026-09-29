// @vitest-environment happy-dom
// What each person did reads at a town's size: the group the two sides decide for comes first,
// then everybody else; each part says how many hours went differently and lists them by how many
// minutes did, most first; everybody else whose hour went the same is folded, and their rows are
// built only when a person opens them.
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { parseRunReplay, type RunReplay } from '../src/society-comparison-api.js';
import { buildComparisonStrips, comparedPeople } from '../src/ui/society-comparison-strips.js';

// Vitest runs from web/, as every page test that reads a repository file assumes.
const golden = JSON.parse(
  readFileSync(`${process.cwd()}/../tests/snapshots/society-comparison-documents.json`, 'utf8'),
) as { readonly run: Record<string, unknown> };

interface Held { id: string; name: string; in_group: boolean }
interface Minute { people: { id: string; goal: unknown }[] }

/**
 * Two runs of the golden hour: the group is the people ``group`` names, and on the right side each
 * person of ``moved`` heads somewhere else in as many minutes as it says, from the first minute.
 */
function pair(group: readonly number[], moved: Readonly<Record<number, number>>): [RunReplay, RunReplay] {
  const document = structuredClone(golden.run) as { people: Held[]; minutes: Minute[] };
  document.people.forEach((person, index) => { person.in_group = group.includes(index); });
  const left = parseRunReplay(structuredClone(document));
  for (const [index, minutes] of Object.entries(moved)) {
    const id = document.people[Number(index)]!.id;
    for (let minute = 1; minute <= minutes; minute += 1) {
      const person = document.minutes[minute]!.people.find((held) => held.id === id)!;
      person.goal = { kind: 'target', target_id: 'elsewhere', reason: 'moved_by_the_test' };
    }
  }
  return [left, parseRunReplay(document)];
}

const names = (root: HTMLElement, part: string): string[] =>
  [...root.querySelectorAll<HTMLElement>(`[data-part='${part}'] .comparison-strip .comparison-strip-person`)]
    .map((cell) => cell.textContent ?? '');

describe('what each person did, at a town\'s size', () => {
  it('lists the group first, then everybody else, each by how many minutes went differently', () => {
    const [left, right] = pair([0, 1, 2], { 1: 1, 2: 2, 4: 2, 5: 1 });
    const people = left.people.map((person) => person.name);
    const { group, others } = comparedPeople(left, right);
    expect(group.map((person) => [person.name, person.differing])).toEqual([
      [people[2], 2], [people[1], 1], [people[0], 0],
    ]);
    expect(others.slice(0, 2).map((person) => [person.name, person.differing])).toEqual([
      [people[4], 2], [people[5], 1],
    ]);
    const strips = buildComparisonStrips(left, right, ['Left model', 'Right model'], () => undefined);
    expect(names(strips.root, 'group')).toEqual([people[2], people[1], people[0]]);
    const titles = [...strips.root.querySelectorAll('.comparison-strip-part-title')].map((title) => title.textContent);
    expect(titles[0]).toContain('The group, 3 people');
    expect(titles[0]).toContain('2 of 3 hours went differently');
    expect(titles[1]).toContain('Everybody else, 5 people');
    expect(titles[1]).toContain('2 of their hours went differently');
    const counts = [...strips.root.querySelectorAll('[data-part=\'group\'] .comparison-strip-count')].map((count) => count.textContent);
    expect(counts).toEqual(['2 min differ', '1 min differ', 'the same']);
  });

  it('folds everybody else, and builds their rows only when opened, in order', () => {
    const [left, right] = pair([0, 1, 2], { 4: 2, 6: 1 });
    const people = left.people.map((person) => person.name);
    const strips = buildComparisonStrips(left, right, ['Left model', 'Right model'], () => undefined);
    const folded = strips.root.querySelector<HTMLDetailsElement>('.comparison-strip-others')!;
    expect(strips.root.querySelectorAll('.comparison-strip')).toHaveLength(3);
    strips.draw(1, left.people[6]!.id);
    folded.open = true;
    folded.dispatchEvent(new Event('toggle'));
    expect(strips.root.querySelectorAll('.comparison-strip')).toHaveLength(8);
    expect(names(strips.root, 'others').slice(0, 2)).toEqual([people[4], people[6]]);
    // A row built on opening is drawn as the clock and the selection last were.
    expect(strips.root.querySelector(`[data-subject-id='${left.people[6]!.id}']`)!.classList.contains('is-selected')).toBe(true);
  });

  it('has one part when the two sides decide for everybody', () => {
    const [left, right] = pair([0, 1, 2, 3, 4, 5, 6, 7], { 3: 1 });
    const strips = buildComparisonStrips(left, right, ['Left model', 'Right model'], () => undefined);
    expect(strips.root.querySelectorAll('.comparison-strip-part')).toHaveLength(1);
    expect(strips.root.querySelector('.comparison-strip-part-title')!.textContent).toContain('Everybody, 8 people');
    expect(strips.root.querySelector('.comparison-strip-same')).toBeNull();
    expect(names(strips.root, 'group')[0]).toBe(left.people[3]!.name);
  });
});
