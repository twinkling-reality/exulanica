// @vitest-environment happy-dom
// The Compare view shows the server's verdict in the server's words, every score as written, the
// two runs of one seed on one clock, and a person on either side in the inspector; its mount reads
// only the three comparison documents, and drops a response a newer choice has overtaken.
import { readFileSync } from 'node:fs';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { mountSocietyComparison } from '../src/composition/society-comparison-mount.js';
import {
  parseComparison,
  parseComparisons,
  parseRunReplay,
  type ComparisonResult,
  type RunReplay,
  type SocietyComparisonReadPort,
} from '../src/society-comparison-api.js';
import {
  buildSocietyComparisonView,
  FAILURE_WORDS,
  type ComparisonDay,
  type SocietyComparisonView,
} from '../src/ui/society-comparison.js';

// Vitest runs from web/, as every page test that reads a repository file assumes.
const repository = `${process.cwd()}/..`;
const golden = JSON.parse(
  readFileSync(`${repository}/tests/snapshots/society-comparison-documents.json`, 'utf8'),
) as { readonly listing: unknown; readonly result: Record<string, unknown>; readonly run: Record<string, unknown> };

const views: SocietyComparisonView[] = [];
afterEach(() => {
  for (const view of views.splice(0)) view.dispose();
  document.body.replaceChildren();
});

function result(change: (document: Record<string, unknown>) => void = () => undefined): ComparisonResult {
  const document = structuredClone(golden.result);
  change(document);
  return parseComparison(document);
}

function run(arm: string): RunReplay {
  return parseRunReplay({ ...structuredClone(golden.run), arm });
}

function view(): SocietyComparisonView {
  const built = buildSocietyComparisonView({ onClose: vi.fn(), onComparison: vi.fn(), onDay: vi.fn() });
  document.body.append(built.root);
  built.root.hidden = false;
  views.push(built);
  return built;
}

const day = (read: ComparisonResult): ComparisonDay => ({
  seedDigest: read.seeds[0]!.seedDigest, left: 'model_a', right: 'model_b',
});

describe('the Compare view', () => {
  it('reads a difference inside its interval as no measured difference, from the verdict alone', () => {
    const inside = result((document) => {
      document['phase'] = 'held_out';
      document['verdict'] = { code: 'no_measured_difference', higher: null, reason: null };
      document['differences'] = [
        { first: 'model_a', second: 'model_b', mean: '0.0400', low: '-0.0300', high: '0.1100', rejected: false },
      ];
      document['primary'] = ['model_a', 'model_b'];
    });
    const shown = view();
    shown.showResult(inside, day(inside));
    const verdict = shown.root.querySelector('.comparison-verdict')!;
    expect(verdict.getAttribute('data-verdict')).toBe('no_measured_difference');
    expect(verdict.querySelector('h3')!.textContent).toBe('No measured difference');
    expect(verdict.textContent).toContain('−0.0300');
    expect(verdict.textContent).not.toContain('fared better');
    // The same numbers under the server's other verdict read as it says: the page decides nothing.
    const called = result((document) => {
      document['verdict'] = { code: 'different', higher: 'model_b', reason: null };
      document['differences'] = inside.differences.map((d) => ({ ...d }));
      document['primary'] = ['model_a', 'model_b'];
      document['control_bound'] = '0.0100';
    });
    shown.showResult(called, day(called));
    expect(shown.root.querySelector('.comparison-verdict h3')!.textContent).toBe('Different');
    expect(shown.root.querySelector('.comparison-verdict')!.textContent).toContain('fared better');
  });

  it('names a model by the name the server serves, never by reading its description', () => {
    const read = result((document) => {
      const arms = document['arms'] as { key: string; decider: Record<string, unknown> }[];
      arms.find((arm) => arm.key === 'model_b')!.decider['name'] = 'The served name';
    });
    const shown = view();
    shown.showResult(read, day(read));
    expect(shown.root.querySelector('.comparison-verdict')!.textContent).toContain('The served name minus');
    const texts = (selector: string) => [...shown.root.querySelectorAll(selector)].map((node) => node.textContent);
    expect(texts('.comparison-seeds th[scope=col]')).toContain('The served name');
    expect(texts('.comparison-arm-name')).toContain('The served name');
    expect(shown.root.querySelector('option[value=model_b]')!.textContent).toBe('The served name');
    shown.showDay(run('model_a'), run('model_b'));
    expect(texts('.comparison-side-name')).toContain('The served name');
    // The listing names each model as the server does too, never by its stored description.
    const listed = structuredClone(golden.listing) as { comparisons: { arms: { decider: Record<string, unknown> }[] }[] };
    listed.comparisons[0]!.arms.find((arm) => arm.decider['kind'] === 'model')!.decider['name'] = 'Listed by name';
    const [listing] = parseComparisons(listed);
    shown.showList([listing!], listing!.comparisonId);
    expect(texts('.comparison-listing-models li')).toContain('Listed by name');
    const described = [...shown.root.querySelectorAll('.comparison-listing-models li, .comparison-arm-name, .comparison-side-name')]
      .map((node) => node.textContent ?? '');
    expect(described.some((words) => words.includes(', an open'))).toBe(false);
  });

  it('shows a score as the server wrote it, below zero with a true minus sign, and above one', () => {
    const read = result((document) => {
      const summaries = document['summaries'] as Record<string, Record<string, unknown>>;
      summaries['model_a']!['mean_score'] = '-0.2500';
      summaries['model_b']!['mean_score'] = '1.2500';
    });
    const shown = view();
    shown.showResult(read, day(read));
    const cells = (arm: string) => shown.root.querySelector(`tr[data-arm=${arm}] td`)!.textContent;
    expect(cells('model_a')).toBe('−0.2500');
    expect(cells('model_b')).toBe('1.2500');
  });

  it('draws one seed\'s two runs on one clock, and the inspector reads a person on either side', () => {
    const read = result();
    const shown = view();
    shown.showResult(read, day(read));
    shown.showDay(run('model_a'), run('model_b'));
    const plans = shown.root.querySelectorAll('.comparison-plan');
    expect(plans).toHaveLength(2);
    const person = run('model_a').people[0]!;
    const dot = (side: number) =>
      plans[side]!.querySelector<SVGGElement>(`[data-subject-id="${person.id}"]`)!;
    const before = dot(0).getAttribute('transform');
    const scrubber = shown.root.querySelector<HTMLInputElement>('.comparison-scrubber')!;
    scrubber.value = String(run('model_a').minutes.length - 1);
    scrubber.dispatchEvent(new Event('input'));
    expect(shown.root.querySelector('.comparison-minute')!.textContent)
      .toBe(`Minute ${run('model_a').minutes.length - 1} of ${run('model_a').minutes.length - 1}`);
    expect(dot(0).getAttribute('transform')).toBe(dot(1).getAttribute('transform'));
    expect(typeof before).toBe('string');
    dot(0).dispatchEvent(new MouseEvent('click'));
    const inspector = shown.root.querySelector('.living-world-inspector')!;
    expect(inspector.querySelector('h3')!.textContent).toBe(person.name);
    expect(shown.root.querySelector('.comparison-inspector-side')!.textContent).toMatch(/^Left: /);
    dot(1).dispatchEvent(new MouseEvent('click'));
    expect(shown.root.querySelector('.comparison-inspector-side')!.textContent).toMatch(/^Right: /);
    expect(inspector.textContent).toContain('simulated person');
  });

  it('says why a side has no hour to show, by its run\'s failure code', () => {
    const read = result((document) => {
      const seeds = document['seeds'] as Record<string, Record<string, Record<string, unknown>>>[];
      const failed = seeds[0]!['runs']!['model_a']!;
      failed['status'] = 'failed';
      failed['failure'] = 'provider_credential_absent';
      failed['score'] = null;
      failed['calls'] = null;
    });
    const shown = view();
    shown.showResult(read, day(read));
    shown.showDay(null, run('model_b'));
    expect(shown.root.querySelector('.comparison-day')!.textContent)
      .toContain(FAILURE_WORDS['provider_credential_absent']);
  });
});

describe('the Compare view\'s reads', () => {
  it('opens the newest comparison, its first seed and first two models, and nothing else', async () => {
    const listed = parseComparisons(golden.listing);
    const read = result();
    const client: SocietyComparisonReadPort = {
      list: vi.fn(async () => listed),
      read: vi.fn(async () => read),
      run: vi.fn(async (_version: string, _comparison: string, runId: string) =>
        run(runId === read.seeds[0]!.runs['model_a']!.runId ? 'model_a' : 'model_b')),
    };
    const mounted = mountSocietyComparison({
      getWorldId: () => 'world:authored:x', getVersionId: () => 'v', client, onClose: vi.fn(),
    });
    document.body.append(mounted.root);
    mounted.setVisible(true);
    await vi.waitFor(() => expect(mounted.root.querySelectorAll('.comparison-plan')).toHaveLength(2));
    expect(client.list).toHaveBeenCalledOnce();
    expect(client.read).toHaveBeenCalledWith('v', listed[0]!.comparisonId);
    expect(vi.mocked(client.run).mock.calls.map((call) => call[2])).toEqual([
      read.seeds[0]!.runs['model_a']!.runId, read.seeds[0]!.runs['model_b']!.runId,
    ]);
    mounted.dispose();
  });

  it('drops a replay a newer choice has overtaken', async () => {
    const listed = parseComparisons(golden.listing);
    const read = result();
    let release: (() => void) | null = null;
    const slow = new Promise<void>((resolve) => { release = resolve; });
    const replay = (runId: string, arm: string): RunReplay => parseRunReplay({
      ...structuredClone(golden.run), arm, run_id: runId,
    });
    const client: SocietyComparisonReadPort = {
      list: vi.fn(async () => listed),
      read: vi.fn(async () => read),
      run: vi.fn(async (_version: string, _comparison: string, runId: string) => {
        if (runId === read.seeds[0]!.runs['model_a']!.runId) await slow;
        return replay(runId, 'model_a');
      }),
    };
    const mounted = mountSocietyComparison({
      getWorldId: () => 'world:authored:x', getVersionId: () => 'v', client, onClose: vi.fn(),
    });
    document.body.append(mounted.root);
    mounted.setVisible(true);
    await vi.waitFor(() => expect(client.run).toHaveBeenCalledTimes(2));
    // Choose the second seed while the first seed's left run is still being replayed.
    const seed = mounted.root.querySelector<HTMLSelectElement>('.comparison-seed-select')!;
    seed.value = read.seeds[1]!.seedDigest;
    seed.dispatchEvent(new Event('change'));
    await vi.waitFor(() => expect(mounted.root.querySelectorAll('.comparison-plan')).toHaveLength(2));
    const drawn = () => [...mounted.root.querySelectorAll('.comparison-side')]
      .map((side) => side.getAttribute('data-run-id'));
    const second = [read.seeds[1]!.runs['model_a']!.runId, read.seeds[1]!.runs['model_b']!.runId];
    expect(drawn()).toEqual(second);
    release!();
    await new Promise((resolve) => setTimeout(resolve, 0));
    // The first seed's replay arrived last, and the second seed's runs are still the ones drawn.
    expect(drawn()).toEqual(second);
    expect(mounted.root.querySelector<HTMLSelectElement>('.comparison-seed-select')!.value)
      .toBe(read.seeds[1]!.seedDigest);
    mounted.dispose();
  });
});
