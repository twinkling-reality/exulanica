// @vitest-environment happy-dom
// Starting a comparison from the Compare view: the page reads the plan and start documents the
// server serves (tests/snapshots/society-comparison-start-documents.json, held to their keys by
// tests/test_society_comparison_start_postgres.py), has words for every code a start and a closed
// start carry (held here to the Python that states them), and sends exactly what was chosen with
// the bound the person stated, never before they stated one.
import { readFileSync } from 'node:fs';
import { URL as FileUrl } from 'node:url';
import { describe, expect, it, vi } from 'vitest';
import {
  START_STATES,
  parseComparison,
  parseComparisons,
  parsePlan,
  planQuery,
  startBody,
  type ComparisonPlan,
  type StartRequest,
} from '../src/society-comparison-api.js';
import {
  CLOSED_WORDS,
  START_REFUSAL_WORDS,
  STATE_WORDS,
  SUBJECT_WORDS,
  boundOf,
  buildComparisonStartForm,
  dollars,
  inProgress,
  progressWords,
  refusalWords,
} from '../src/ui/society-comparison-start.js';

const REPOSITORY = new FileUrl('../../../../', import.meta.url);
const read = (path: string): string => readFileSync(new FileUrl(path, REPOSITORY), 'utf8');
const documents = JSON.parse(read('tests/snapshots/society-comparison-start-documents.json')) as Record<string, unknown>;

/** The codes one tuple or mapping a Python module states, read from its declaration to its close. */
function stated(path: string, name: string): string[] {
  const source = read(path);
  const start = source.indexOf(`${name}: Final = `);
  expect(start, `${name} in ${path}`).toBeGreaterThan(-1);
  const end = source.slice(start).search(/\n[)}]/);
  expect(end, `the end of ${name} in ${path}`).toBeGreaterThan(-1);
  return [...source.slice(start, start + end).matchAll(/"([a-z_]+)"/g)].map((match) => match[1]!);
}

describe('the documents of a comparison started from the application', () => {
  it('reads what the server offers, a selection\'s plan, a start and a finished start', () => {
    const offered = parsePlan(documents['plan']);
    expect(offered.refusal).toBeNull();
    expect(offered.plan).toBeNull();
    const [role] = offered.roles;
    expect(role!.subject).toBe('person');
    expect(role!.groups[0]!.kind).toBe('everyone');
    expect(role!.models.length).toBeGreaterThan(0);

    const planned = parsePlan(documents['planned']);
    expect(planned.plan!.runs).toBe(3);
    expect(Number(planned.plan!.mostUsd)).toBeGreaterThan(Number(planned.plan!.typicalUsd));
    expect(planned.plan!.typicalRecord).toMatch(/^docs\/evaluation\/.+\.json$/);

    const [started] = parseComparisons(documents['started']);
    expect(started!.start!.state).toBe('waiting');
    expect(inProgress(started!)).toBe(true);
    const [finished] = parseComparisons(documents['finished']);
    expect(finished!.start!.state).toBe('finished');
    expect(finished!.runsFinished).toBe(finished!.runs);
    expect(inProgress(finished!)).toBe(false);
    expect(parseComparison(documents['result']).start!.state).toBe('finished');
  });
});

describe('the words a start is told in', () => {
  it('has words for exactly the ways a start is refused and a started comparison is closed', () => {
    const refusals = stated('exulanica/api/society_comparison_start.py', 'START_REFUSALS');
    // A positive control: codes the server is known to answer are found by the same reading.
    expect(refusals).toEqual(expect.arrayContaining(['comparisons_not_set_up', 'bound_over_budget']));
    expect(Object.keys(START_REFUSAL_WORDS).sort()).toEqual([...refusals].sort());
    const closed = stated('exulanica/api/society_comparison_worker.py', 'CLOSED_REASONS');
    expect(closed).toContain('claims_spent');
    expect(Object.keys(CLOSED_WORDS).sort()).toEqual([...closed].sort());
  });

  it('reads exactly the states the server gives a start, and names every registered subject', () => {
    const states = stated('exulanica/world/society_comparison_start_repository.py', 'START_STATES');
    expect(states).toContain('running');
    expect([...START_STATES]).toEqual(states);
    expect(Object.keys(STATE_WORDS).sort()).toEqual([...states].sort());
    const registry = JSON.parse(read('assets/catalogs/roles/decision-roles.v1.json')) as {
      readonly entries: readonly { readonly subject: string }[];
    };
    for (const entry of registry.entries) expect(SUBJECT_WORDS[entry.subject]).toBeDefined();
  });

  it('says what a comparison could cost as the server wrote it, and a start\'s progress', () => {
    expect(dollars('0.05000000')).toBe('$0.05');
    expect(dollars('0.00182500')).toBe('$0.001825');
    expect(dollars('2.74310400')).toBe('$2.743104');
    const [finished] = parseComparisons(documents['finished']);
    expect(progressWords(finished!)).toMatch(/^Finished: 3 of 3 runs finished; \$0\.\d+ of the \$0\.05 bound spent\.$/);
    // What a server that stopped may have spent unrecorded is said beside what was recorded.
    const presumed = { ...finished!, start: { ...finished!.start!, presumedUsd: '0.02000000' } };
    expect(progressWords(presumed)).toMatch(
      /bound spent, and \$0\.02 counted for asks a server that stopped may have made\.$/,
    );
    expect(refusalWords('comparisons_not_set_up')).toContain('not set up on this computer');
    expect(refusalWords('comparisons_not_played')).toContain('Nothing on this computer runs comparisons');
    expect(refusalWords('something_new', 'why')).toBe('The server refused it (something_new: why).');
  });

  it('takes a bound only above zero and at most the most the comparison can cost', () => {
    expect(boundOf('0.05', '2.74')).toBe('0.05');
    expect(boundOf('$0.05', '2.74')).toBe('0.05');
    expect(boundOf('0', '2.74')).toBeNull();
    expect(boundOf('3', '2.74')).toBeNull();
    expect(boundOf('0.123456789', '2.74')).toBeNull();
    expect(boundOf('', '2.74')).toBeNull();
  });
});

describe('the start controls', () => {
  const planned = parsePlan(documents['planned']);
  const setUp = (plan: ComparisonPlan) => {
    const onSelection = vi.fn();
    const onStart = vi.fn<(request: StartRequest) => void>();
    const form = buildComparisonStartForm({ onSelection, onStart, newId: () => 'the-start-id' });
    document.body.replaceChildren(form.root);
    form.showPlan(plan);
    return { form, onSelection, onStart };
  };

  it('shows the most a comparison could cost and what one like it typically costs, as the server wrote them', () => {
    const { form } = setUp(planned);
    const shown = form.root.querySelector<HTMLElement>('.comparison-start-plan')!;
    const words = shown.textContent!;
    expect(words).toContain(`at most ${dollars(planned.plan!.mostUsd)}`);
    expect(words).toContain(`typically costs about ${dollars(planned.plan!.typicalUsd!)}`);
    // The record the typical figure was measured in is named beside it.
    expect(shown.title).toBe(planned.plan!.typicalRecord);
  });

  it('starts nothing until the person states a bound, then sends what was chosen with it', () => {
    const { form, onStart } = setUp(planned);
    const start = form.root.querySelector<HTMLButtonElement>('.comparison-start-button')!;
    expect(start.disabled).toBe(true);
    const bound = form.root.querySelector<HTMLInputElement>('.comparison-start-bound')!;
    bound.value = '0.05';
    bound.dispatchEvent(new Event('input'));
    expect(start.disabled).toBe(false);
    start.click();
    const [request] = onStart.mock.calls[0]!;
    const role = planned.roles[0]!;
    const first = role.models.find((model) => model.refusal === null)!;
    expect(request).toEqual({
      comparisonId: 'the-start-id',
      role: role.key,
      group: { kind: 'everyone' },
      models: [{ provider: first.provider, modelId: first.modelId }],
      control: false,
      seeds: 1,
      boundUsd: '0.05',
    });
    expect(startBody(request)).toEqual({
      comparison_id: 'the-start-id',
      role: role.key,
      group: { kind: 'everyone' },
      models: [{ provider: first.provider, model_id: first.modelId }],
      control: false,
      seeds: 1,
      bound_usd: '0.05',
    });
  });

  it('asks for the plan of each new choice, and keeps the bound the person typed', () => {
    const { form, onSelection } = setUp(planned);
    const bound = form.root.querySelector<HTMLInputElement>('.comparison-start-bound')!;
    bound.value = '0.04';
    bound.dispatchEvent(new Event('input'));
    const control = form.root.querySelector<HTMLInputElement>('.comparison-start-control')!;
    control.checked = true;
    control.dispatchEvent(new Event('change'));
    const [selection] = onSelection.mock.calls[0]!;
    expect(selection.control).toBe(true);
    expect(planQuery(selection).getAll('model').length).toBe(1);
    form.showPlan(planned);
    expect(form.root.querySelector<HTMLInputElement>('.comparison-start-bound')!.value).toBe('0.04');
    expect(form.root.querySelector<HTMLInputElement>('.comparison-start-control')!.checked).toBe(true);
  });

  it('asks for the plan of the choice it shows, where the server answered without one', () => {
    const { onSelection } = setUp({ ...planned, plan: null });
    expect(onSelection).toHaveBeenCalledOnce();
    const role = planned.roles[0]!;
    const first = role.models.find((model) => model.refusal === null)!;
    expect(onSelection.mock.calls[0]![0]).toEqual({
      role: role.key,
      group: { kind: 'everyone' },
      models: [{ provider: first.provider, modelId: first.modelId }],
      control: false,
      seeds: 1,
    });
  });

  it('keeps the controls a person is using when the plan of their choice answers', () => {
    const { form } = setUp(planned);
    const start = form.root.querySelector('.comparison-start-button');
    const bound = form.root.querySelector('.comparison-start-bound');
    form.showPlan({ ...planned, plan: { ...planned.plan!, runs: 5 } });
    expect(form.root.querySelector('.comparison-start-button')).toBe(start);
    expect(form.root.querySelector('.comparison-start-bound')).toBe(bound);
    expect(form.root.querySelector('.comparison-start-plan')!.textContent).toMatch(/^5 runs of one simulated hour/);
  });

  it('says why nothing can be started, in words, where the server refuses', () => {
    const { form } = setUp({ ...planned, refusal: { code: 'comparisons_not_set_up', detail: '' } });
    expect(form.root.textContent).toContain(START_REFUSAL_WORDS['comparisons_not_set_up']);
    expect(form.root.querySelector('.comparison-start-button')).toBeNull();
    const refused = setUp({ ...planned, plan: null, planRefusal: { code: 'seeds_out_of_range', detail: '' } });
    expect(refused.form.root.querySelector('.comparison-start-plan')!.textContent)
      .toBe(START_REFUSAL_WORDS['seeds_out_of_range']);
  });
});

describe('the Compare view\'s start', () => {
  it('asks what may be started, starts once with the bound stated, and reads progress until it finishes', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const [waiting] = parseComparisons(documents['started']);
      const [finished] = parseComparisons(documents['finished']);
      const result = parseComparison(documents['result']);
      const listings = [[], [waiting!], [finished!]];
      let reads = 0;
      const client = {
        list: vi.fn(async () => listings[Math.min(reads++, listings.length - 1)]!),
        read: vi.fn(async () => result),
        run: vi.fn(async () => { throw new Error('no replay in this test'); }),
        plan: vi.fn(async () => planned),
        start: vi.fn(async (_version: string, _request: StartRequest) => [waiting!]),
      };
      const planned = parsePlan(documents['planned']);
      const { mountSocietyComparison, PROGRESS_READ_MS } = await import('../src/composition/society-comparison-mount.js');
      const mounted = mountSocietyComparison({
        getWorldId: () => 'world:authored:x', getVersionId: () => 'v', client, onClose: vi.fn(), newId: () => 'id-1',
      });
      document.body.replaceChildren(mounted.root);
      mounted.setVisible(true);
      await vi.waitFor(() => expect(client.plan).toHaveBeenCalledWith('v', null));
      await vi.waitFor(() => expect(mounted.root.querySelector('.comparison-start-bound')).not.toBeNull());
      const bound = mounted.root.querySelector<HTMLInputElement>('.comparison-start-bound')!;
      bound.value = '0.05';
      bound.dispatchEvent(new Event('input'));
      mounted.root.querySelector<HTMLButtonElement>('.comparison-start-button')!.click();
      await vi.waitFor(() => expect(client.start).toHaveBeenCalledOnce());
      expect(vi.mocked(client.start).mock.calls[0]![1]).toMatchObject({ comparisonId: 'id-1', boundUsd: '0.05' });
      await vi.waitFor(() => expect(mounted.root.querySelector('.comparison-listing-progress')?.textContent)
        .toMatch(/^Waiting for the server to run it: /));
      const before = client.list.mock.calls.length;
      await vi.advanceTimersByTimeAsync(PROGRESS_READ_MS);
      await vi.waitFor(() => expect(mounted.root.querySelector('.comparison-listing-progress')?.textContent)
        .toMatch(/^Finished: /));
      expect(client.list.mock.calls.length).toBe(before + 1);
      await vi.advanceTimersByTimeAsync(3 * PROGRESS_READ_MS);
      expect(client.list.mock.calls.length).toBe(before + 1);
      mounted.dispose();
    } finally {
      vi.useRealTimers();
    }
  });
});
