// @vitest-environment happy-dom
// A things comparison's words and hands: reported, never weighed (score version 6). The reader takes
// the server's `reported` counts strictly; the view shows them in their own quieter section under the
// verdict, the routine's column in words, rows nobody did left out, the act kinds in What the group
// did, and a quiet line per seed on each side. Expected words come from UI's approved design
// (deliveries/CARD/design-things-compare/design.md, UI's decision) and the words catalog.
import { readFileSync } from 'node:fs';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { parseComparison, parseRunReplay } from '../src/society-comparison-api.js';
import { buildSocietyComparisonView, type SocietyComparisonView } from '../src/ui/society-comparison.js';

const repository = `${process.cwd()}/..`;
const golden = JSON.parse(readFileSync(`${repository}/tests/snapshots/society-comparison-documents.json`, 'utf8')) as
  { readonly result: Record<string, unknown>; readonly run: Record<string, unknown> };
const catalog = JSON.parse(readFileSync(`${repository}/assets/catalogs/society-words/society-inhabitant-words.v1.json`, 'utf8')) as
  { entries: { kind: string; code: string; words: string }[] };
const words = (kind: string, code: string) => catalog.entries.find((entry) => entry.kind === kind && entry.code === code)!.words;

const counts = (said: number, near: number, gave: number, missed: Record<string, number>) => ({
  acts: { said, picked_up: 2, put_down: 0, gave, took: 0 }, lines: { said, near_repeats: near }, hands_missed: missed,
});

/** The golden result with reported counts: model_a speaks and hands things over; model_b only speaks. */
function withReported(): Record<string, unknown> {
  const document = structuredClone(golden.result) as Record<string, any>;
  document['summaries']['model_a']['reported'] = counts(41, 9, 4, { out_of_reach: 2, thing_gone: 1 });
  document['summaries']['model_b']['reported'] = counts(18, 11, 0, { out_of_reach: 3 });
  // The routine's own record: it said nothing and moved nothing.
  document['summaries']['routine']['reported'] = { acts: { said: 0, picked_up: 0, put_down: 0, gave: 0, took: 0 },
    lines: { said: 0, near_repeats: 0 }, hands_missed: {} };
  for (const seed of document['seeds']) {
    seed['runs']['model_a']['reported'] = counts(7, 1, 1, {});
    seed['runs']['model_b']['reported'] = counts(3, 2, 0, {});
  }
  return document;
}

const views: SocietyComparisonView[] = [];
afterEach(() => { for (const shown of views.splice(0)) shown.dispose(); document.body.replaceChildren(); });
function view(): SocietyComparisonView {
  const built = buildSocietyComparisonView({ onClose: vi.fn(), onComparison: vi.fn(), onDay: vi.fn() });
  document.body.append(built.root);
  built.root.hidden = false;
  views.push(built);
  return built;
}

describe('a comparison\'s reported counts, read', () => {
  it('takes them per run and per arm, leaves them out before the sixth score, and refuses a malformed one', () => {
    const read = parseComparison(withReported());
    expect(read.summaries['model_a']!.reported).toEqual({
      acts: { said: 41, picked_up: 2, put_down: 0, gave: 4, took: 0 }, lines: { said: 41, nearRepeats: 9 },
      handsMissed: { out_of_reach: 2, thing_gone: 1 },
    });
    expect(read.seeds[0]!.runs['model_b']!.reported?.lines).toEqual({ said: 3, nearRepeats: 2 });
    expect(parseComparison(structuredClone(golden.result)).summaries['model_a']!.reported ?? null).toBeNull();
    const broken = withReported() as Record<string, any>;
    broken['summaries']['model_a']['reported']['lines']['near_repeats'] = 99;
    expect(() => parseComparison(broken)).toThrow();
  });
});

describe('a comparison\'s words and hands, shown', () => {
  it('sits under the verdict, quieter, with the routine in words and no row nobody did', () => {
    const shown = view();
    const read = parseComparison(withReported());
    shown.showResult(read, { seedDigest: read.seeds[0]!.seedDigest, left: 'model_a', right: 'model_b' });
    const section = shown.root.querySelector('.comparison-reported')!;
    // Directly after the verdict, before the choosers and every number.
    expect(section.previousElementSibling?.classList.contains('comparison-verdict')).toBe(true);
    expect(section.querySelector('.comparison-reported-head')?.textContent).toBe('Words and hands: reported, not judged');
    expect(section.querySelector('.comparison-reported-why')?.textContent).toBe(
      `What each model's people said and did with their hands, over all ${read.seeds.length} seeds. None of this decides who fared better. `
      + 'Lines are counted here, not read: open a person\'s hour below to read what they said.');
    const rows = [...section.querySelectorAll('tbody tr')].map((row) => row.querySelector('th')!.textContent);
    expect(rows).toEqual([
      'Lines said', 'nearly the same as an earlier line', 'Things handed to someone', 'Things picked up',
      'Hand moves that did not happen', words('phrase', 'hand_move_out_of_reach'), words('phrase', 'hand_move_thing_gone'),
    ]);
    expect(section.querySelector('thead th')?.textContent).toBe('What was counted');
    // Nobody took or put anything down: those rows are left out.
    expect(rows).not.toContain('Things taken from someone');
    // From the routine's own record: all 0 in both groups, so it says so in words.
    const routine = [...section.querySelectorAll('.comparison-reported-routine')].map((cell) => cell.textContent);
    expect(routine).toEqual(['The routine never speaks', 'The routine never uses its hands']);
    // One place for these counts: not in the numbers block.
    expect(shown.root.querySelector('.comparison-numbers')?.textContent).not.toContain('Lines said');
  });

  it('takes the routine\'s column from its own record: numbers where it has some, none where it has no record', () => {
    const columns = (change: (document: Record<string, any>) => void) => {
      const document = withReported() as Record<string, any>;
      change(document);
      const shown = view();
      const read = parseComparison(document);
      shown.showResult(read, { seedDigest: read.seeds[0]!.seedDigest, left: 'model_a', right: 'model_b' });
      const section = shown.root.querySelector('.comparison-reported')!;
      return { heads: [...section.querySelectorAll('thead th')].map((cell) => cell.textContent), section };
    };
    const spoke = columns((document) => { document['summaries']['routine']['reported'] = counts(5, 0, 0, {}); });
    // Its record has lines: its numbers stand in that group, and no sentence claims otherwise.
    expect(spoke.section.querySelector('tbody tr td:last-child')?.textContent).toBe('5');
    expect([...spoke.section.querySelectorAll('.comparison-reported-routine')].map((cell) => cell.textContent))
      .not.toContain('The routine never speaks');
    const unrecorded = columns((document) => { document['summaries']['routine']['reported'] = null; });
    expect(unrecorded.heads).toHaveLength(3);
    expect(unrecorded.section.querySelector('.comparison-reported-routine')).toBeNull();
  });

  it('adds the acts to what the group did, and a quiet line for the seed on each side', () => {
    const shown = view();
    const read = parseComparison(withReported());
    shown.showResult(read, { seedDigest: read.seeds[0]!.seedDigest, left: 'model_a', right: 'model_b' });
    const replay = structuredClone(golden.run) as Record<string, any>;
    const member = (replay['people'] as { id: string; in_group: boolean }[]).find((person) => person.in_group)!.id;
    replay['events'] = [...replay['events'], { kind: 'said', reason: '', subject_id: member, summary: '', tick: 2 }];
    shown.showDay(parseRunReplay({ ...replay, arm: 'model_a' }), parseRunReplay({ ...structuredClone(golden.run), arm: 'model_b' }));
    const sides = [...shown.root.querySelectorAll('.comparison-side')];
    const said = sides[0]!.querySelector('li[data-act="said"]');
    expect(said?.querySelector('.comparison-side-did-kind')?.textContent).toBe('Said something');
    expect(said?.querySelector('.comparison-side-did-count')?.textContent).toMatch(/^1 of \d+$/u);
    expect(sides[1]!.querySelector('li[data-act]')).toBeNull();
    expect(sides[0]!.querySelector('.comparison-side-reported')?.textContent)
      .toBe('On this seed: 7 lines said, 1 nearly the same as an earlier line; 1 thing handed over. Reported, not judged.');
    expect(sides[1]!.querySelector('.comparison-side-reported')?.textContent)
      .toBe('On this seed: 3 lines said, 2 nearly the same as an earlier line; nothing handed over. Reported, not judged.');
  });
});
