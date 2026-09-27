// @vitest-environment happy-dom
// A score says how a group's people fared; the routine decides every turn a model leaves, so a
// model that answers nothing scores the routine's 1. The Compare view therefore never shows a score
// without what its arm's model answered beside it, says in the verdict's own sentence whether two
// models' answered shares differ by more than the same model's two runs, names the group and who
// decides for everybody else, and says in plain words what a first-version comparison did not
// record. Every number is the server's.
import { readFileSync } from 'node:fs';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  parseComparison,
  parseRunReplay,
  type ComparisonResult,
  type RunReplay,
} from '../src/society-comparison-api.js';
import {
  buildSocietyComparisonView,
  decidedWords,
  groupWords,
  OTHERS_ASKED_WORDS,
  percentText,
  reasonWords,
  type SocietyComparisonView,
} from '../src/ui/society-comparison.js';
import { DECISION_WORDS } from '../src/society-inhabitant-words.js';

// Vitest runs from web/, as every page test that reads a repository file assumes.
const repository = `${process.cwd()}/..`;
const documents = (name: string) => JSON.parse(readFileSync(`${repository}/tests/snapshots/${name}`, 'utf8')) as {
  readonly listing: unknown; readonly result: Record<string, unknown>; readonly run: Record<string, unknown>;
};
const everybody = documents('society-comparison-documents.json');
const grouped = documents('society-group-comparison-documents.json');

const views: SocietyComparisonView[] = [];
afterEach(() => {
  for (const view of views.splice(0)) view.dispose();
  document.body.replaceChildren();
});

function read(golden: typeof everybody, change: (document: Record<string, unknown>) => void = () => undefined): ComparisonResult {
  const document = structuredClone(golden.result);
  change(document);
  return parseComparison(document);
}

function replayed(golden: typeof everybody, arm: string): RunReplay {
  return parseRunReplay({ ...structuredClone(golden.run), arm });
}

function shown(result: ComparisonResult, left = 'model_a', right = 'model_b'): SocietyComparisonView {
  const built = buildSocietyComparisonView({ onClose: vi.fn(), onComparison: vi.fn(), onDay: vi.fn() });
  document.body.append(built.root);
  built.root.hidden = false;
  views.push(built);
  built.showResult(result, { seedDigest: result.seeds[0]!.seedDigest, left, right });
  return built;
}

describe('a score and what its model answered', () => {
  it('never shows a score without its arm\'s reliability, in the arms, the seeds or a side', () => {
    for (const golden of [everybody, grouped]) {
      const result = read(golden);
      const view = shown(result);
      view.showDay(replayed(golden, 'model_a'), replayed(golden, 'model_b'));
      const root = view.root;
      // The positive control: scores are shown at all, in each place a score is shown.
      const armRows = [...root.querySelectorAll('.comparison-arms tbody tr')];
      const seedScores = [...root.querySelectorAll('.comparison-seeds .comparison-score')];
      const sideScores = [...root.querySelectorAll('.comparison-side-score')];
      expect(armRows.length).toBe(result.arms.length);
      expect(seedScores.length).toBeGreaterThan(0);
      expect(sideScores).toHaveLength(2);
      for (const row of armRows) {
        const words = row.querySelector('.comparison-reliability')?.textContent ?? '';
        expect(words.length, row.getAttribute('data-arm') ?? '').toBeGreaterThan(0);
        if (row.getAttribute('data-role') === 'candidate') expect(words).toMatch(/answered .*% of \d+ turns/);
      }
      for (const score of seedScores) {
        expect(score.nextElementSibling?.classList.contains('comparison-reliability')).toBe(true);
        expect(score.nextElementSibling?.textContent ?? '').not.toBe('');
      }
      for (const score of sideScores) {
        expect(score.nextElementSibling?.classList.contains('comparison-reliability')).toBe(true);
        expect(score.nextElementSibling?.textContent ?? '').toMatch(/answered|No model is asked/);
      }
    }
  });

  it('says in the verdict\'s own sentence whether two models\' answered shares differ materially', () => {
    const verdict = (differ: boolean | null) => read(everybody, (document) => {
      document['phase'] = 'held_out';
      document['verdict'] = { code: 'no_measured_difference', higher: null, reason: null, answered_shares_differ: differ };
      document['primary'] = ['model_a', 'model_b'];
      document['differences'] = [
        { first: 'model_a', second: 'model_b', mean: '0.0010', low: '-0.0100', high: '0.0120', rejected: false },
      ];
    });
    const sentence = (result: ComparisonResult) =>
      shown(result).root.querySelector('.comparison-verdict p')!.textContent ?? '';
    const apart = sentence(verdict(true));
    const summaries = verdict(true).summaries;
    // One sentence: the verdict, then both models' answered shares, then the difference.
    expect(apart).toMatch(/cannot tell how the people fared under the two apart[^.]*; but .* answered/);
    expect(apart).toContain(percentText(summaries['model_a']!.reliability!.shares!.answered));
    expect(apart).toContain(percentText(summaries['model_b']!.reliability!.shares!.answered));
    expect(apart).toContain('further apart than the same model\'s two runs');
    expect(sentence(verdict(false))).toContain('no further apart than the same model\'s two runs');
    expect(sentence(verdict(null))).not.toContain('further apart');
  });

  it('says in plain words what a first-version comparison did not record', () => {
    const first = read(everybody, (document) => {
      document['score_version'] = 1;
      const summaries = document['summaries'] as Record<string, Record<string, Record<string, unknown> | null>>;
      for (const summary of Object.values(summaries)) {
        const reliability = summary['reliability'];
        if (reliability !== null && reliability !== undefined) {
          reliability['per_routine_choice'] = null;
          reliability['routine_choice_points'] = null;
          reliability['not_answered'] = null;
          reliability['not_applied'] = null;
        }
      }
    });
    const view = shown(first);
    const rate = view.root.querySelector('tr[data-arm=model_a] .comparison-rate')!.textContent ?? '';
    expect(rate).toContain('Not recorded');
    // What it did record is still said beside its score.
    expect(view.root.querySelector('tr[data-arm=model_a] .comparison-reliability')!.textContent)
      .toMatch(/answered .*% of \d+ turns/);
  });

  it('says why the routine decided a model\'s turns instead, by the reasons the server kept', () => {
    const result = read(everybody);
    const summary = result.summaries['model_a']!.reliability!;
    // The positive control: the served result kept at least one reason for this arm.
    const [code, times] = Object.entries(summary.reasons)[0]!;
    const words = reasonWords(summary);
    expect(words).toContain(`${DECISION_WORDS[code]} (${times})`);
    const view = shown(result);
    expect(view.root.querySelector('tr[data-arm=model_a] .comparison-reasons')!.textContent).toBe(words);
    expect(reasonWords({ ...summary, reasons: {} })).toBe('');
  });

  it('writes a share as the percentage of the same digits, never re-rounded', () => {
    expect(percentText('0.8352')).toBe('83.52%');
    expect(percentText('1.0000')).toBe('100.00%');
    expect(percentText('0.0000')).toBe('0.00%');
    expect(percentText('0.0500')).toBe('5.00%');
    expect(percentText('-0.0100')).toBe('−1.00%');
  });
});

describe('a group and everybody else', () => {
  it('names the group, where it came from, and the decider everybody else keeps', () => {
    const result = read(grouped);
    const words = groupWords(result);
    for (const person of result.group.people!) expect(words).toContain(person.name);
    expect(words).toContain('the group you chose a model for');
    const kept = result.others.find((other) => other.decider.kind === 'model')!;
    expect(words).toContain(`${kept.name}: ${kept.decider.kind === 'model' ? kept.decider.name : ''}`);
    expect(words).toContain('their own routine');
    expect(groupWords(read(everybody))).toBe('Each arm decides for everybody in this world.');
  });

  it('says what a model outside the group means for the score, where the server says there is one', () => {
    const result = read(grouped);
    // The positive control: this development comparison has a model outside its group.
    expect(result.othersAsked).toBe(true);
    expect(groupWords(result)).toContain(OTHERS_ASKED_WORDS);
    expect(groupWords(read(grouped, (document) => { document['others_asked'] = false; })))
      .not.toContain(OTHERS_ASKED_WORDS);
    expect(groupWords(read(everybody))).not.toContain(OTHERS_ASKED_WORDS);
  });

  it('says in the inspector who decides for a person outside the group, the same in every arm', () => {
    const result = read(grouped);
    const run = replayed(grouped, 'model_b');
    const arm = result.arms.find((held) => held.key === 'model_b')!;
    const outside = run.people.find((person) => !person.inGroup && person.decider.kind === 'model')!;
    const inside = run.people.find((person) => person.inGroup)!;
    const last = run.minutes[run.minutes.length - 1]!.tick;
    expect(decidedWords(run, arm, outside.id, last)).toContain('outside the group');
    expect(decidedWords(run, arm, outside.id, last)).toContain(
      outside.decider.kind === 'model' ? outside.decider.name : 'routine');
    expect(decidedWords(run, arm, inside.id, last)).not.toContain('outside the group');
  });
});
