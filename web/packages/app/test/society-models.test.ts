// @vitest-environment happy-dom
// Who decides for a saved world's people: the page's reading of the models route, the section that
// chooses, and the mount that keeps it current. The words for each code are held to the server's
// codes in society-models-words-parity.test.ts.
import { describe, expect, it, vi } from 'vitest';
import { mountSocietyModels } from '../src/composition/society-models-mount.js';
import { SocietyModelsClient, parseSocietyModels } from '../src/society-models-api.js';
import {
  CHOICE_REFUSAL_WORDS,
  HOST_REFUSAL_WORDS,
  MODEL_REFUSAL_WORDS,
  buildSocietyModels,
  choiceWords,
  hostWords,
  latestDecisionWords,
  summaryWords,
} from '../src/ui/society-models.js';

const MODEL = 'nvidia/nemotron';
const read = (overrides: Record<string, unknown> = {}) => ({
  profile: 'exulanica.society-models/v1', society_id: 'society', engine: 'exulanica-society/v2',
  takes_model_choices: true, host_refusal: null,
  contract: { versions: {}, sha256: 'c'.repeat(64), model_people_maximum: 8 },
  models: [{
    provider: 'nebius_token_factory', model_id: MODEL, name: 'Nemotron 3 Nano 30B',
    description: 'Nemotron 3 Nano 30B, an open reasoning model from NVIDIA.',
    provider_description: 'Nebius Token Factory, which serves open models.',
    mechanism: 'tool_call', usd_per_mtok: { input: '0.06', output: '0.24' }, refusal: null,
  }],
  choices: [{ subject_id: 'ada', model: { provider: 'nebius_token_factory', model_id: MODEL, name: 'Nemotron 3 Nano 30B' }, choice_seq: 1,
    chosen_by: 'owner', recorded_at: '2026-09-25T10:00:00Z', refusal: null }],
  latest: [{ subject_id: 'ada', decision_seq: 3, base_tick: 6, consumed_tick: 7, provider: 'nebius_token_factory',
    model_id: MODEL, name: 'Nemotron 3 Nano 30B', status: 'accepted', reason: 'validated_choice', disposition: 'applied', disposition_reason: 'validated_choice', chose: 'rest, 4 m away' }],
  by_model: [{ provider: 'nebius_token_factory', model_id: MODEL, name: 'Nemotron 3 Nano 30B', decisions: 5, asked: 5, accepted: 4, applied: 3,
    by_reason: { validated_choice: 4, model_timed_out: 1 },
    by_disposition: { applied: 3, rejected: 1, unavailable: 1 },
    not_acted_on: { model_timed_out: 1, place_taken_this_minute: 1 },
    latency_ms: { p50: 1140, p95: 2900, longest: 3100 }, cost_usd: '0.000420', cost_known: true }],
  decisions_read: { counted: 5, maximum: 2000 },
  ...overrides,
});

describe('reading who decides', () => {
  it('calls a model by the name the server gives it, even one this host no longer offers', () => {
    // The Companion names a model by the same rule (`Manifest.model_name`), so the two never
    // disagree: a choice and a decision by a withdrawn model are not called by its identifier.
    const view = parseSocietyModels(read({ models: [] }));
    expect(choiceWords(view, 'ada')).toBe('Nemotron 3 Nano 30B, which you chose.');
    expect(latestDecisionWords(view.latest[0]!)).toContain('Nemotron 3 Nano 30B chose');
    expect(summaryWords(view.byModel[0]!)).toMatch(/^Nemotron 3 Nano 30B: /);
    expect(() => parseSocietyModels(read({ latest: [{ ...read().latest[0], name: undefined }] }))).toThrow();
  });

  it('reads the route exactly, and refuses a read that is not one', () => {
    const view = parseSocietyModels(read());
    expect(view.models[0]).toMatchObject({ modelId: MODEL, mechanism: 'tool_call', refusal: null });
    expect(view.byModel[0]).toMatchObject({ applied: 3, latencyP50Ms: 1140, byDisposition: { applied: 3 } });
    expect(() => parseSocietyModels(read({ profile: 'other' }))).toThrow('society models response');
    expect(() => parseSocietyModels(read({ models: [{ ...read().models[0], mechanism: 'guess' }] }))).toThrow();
  });

  it('says who decides, what the latest decision came to, and what each model decided', () => {
    const view = parseSocietyModels(read());
    expect(choiceWords(view, 'ada')).toBe('Nemotron 3 Nano 30B, which you chose.');
    expect(choiceWords(view, 'grace')).toBe('Their own routine.');
    expect(latestDecisionWords(view.latest[0]!))
      .toBe('At simulated minute 7, Nemotron 3 Nano 30B chose “rest, 4 m away”, and they did it.');
    expect(latestDecisionWords({ ...view.latest[0]!, disposition: 'rejected', dispositionReason: 'place_taken_this_minute' }))
      .toBe('At simulated minute 7, Nemotron 3 Nano 30B chose “rest, 4 m away”, but someone else took that place first, so their routine decided.');
    expect(latestDecisionWords({ ...view.latest[0]!, status: 'unavailable', reason: 'model_timed_out', disposition: 'unavailable', chose: null }))
      .toBe('At simulated minute 7, their routine decided: Nemotron 3 Nano 30B was not followed because it did not answer in time.');
    // A request closed after its minute is told by the minute the routine decided, not the later
    // minute that took up its receipt.
    expect(latestDecisionWords({ ...view.latest[0]!, baseTick: 6, consumedTick: 9, status: 'unavailable',
      reason: 'unanswered_in_its_minute', disposition: 'unavailable', dispositionReason: null, chose: null }))
      .toBe('At simulated minute 7, their routine decided: Nemotron 3 Nano 30B was not followed because this server '
        + 'stopped before it heard the answer.');
    // A person's own request, or another decision, came first: neither is their routine.
    expect(latestDecisionWords({ ...view.latest[0]!, disposition: 'superseded', dispositionReason: 'person_asked_directly' }))
      .toBe('At simulated minute 7, Nemotron 3 Nano 30B chose “rest, 4 m away”, but you asked them to go somewhere yourself, and that came first.');
    expect(latestDecisionWords({ ...view.latest[0]!, disposition: 'superseded', dispositionReason: 'subject_already_decided' }))
      .toBe('At simulated minute 7, Nemotron 3 Nano 30B chose “rest, 4 m away”, but something else already decided for them this minute, and that came first.');
    // Every decision not acted on is counted once, under why.
    expect(summaryWords(view.byModel[0]!)).toBe(
      'Nemotron 3 Nano 30B: 5 decisions, 3 acted on, 2 not acted on (1 because it did not answer in time; '
      + '1 because someone else took that place first). Half its answers came within 1.2 s, 95 in 100 within 2.9 s. '
      + 'Cost $0.000420.',
    );
  });

  it('says their routine decides for now, and why, whenever their chosen model is not asked here', () => {
    const chosen = read().choices[0]!;
    const causes = [
      ...Object.entries(HOST_REFUSAL_WORDS).map(([code, why]) => [read({ host_refusal: code }), why] as const),
      ...Object.entries(MODEL_REFUSAL_WORDS).map(([code, why]) => [read({ choices: [{ ...chosen, refusal: code }] }), why] as const),
    ];
    // A positive control: every cause the server states is among those read here.
    expect(causes).toHaveLength(11);
    for (const [body, why] of causes) {
      expect(choiceWords(parseSocietyModels(body), 'ada'))
        .toBe(`Their own routine for now, because ${why}. You chose Nemotron 3 Nano 30B.`);
    }
    // The host's reason holds for everyone here, so it is the one given.
    const both = parseSocietyModels(read({ host_refusal: 'process_budget_spent', choices: [{ ...chosen, refusal: 'provider_changed' }] }));
    expect(choiceWords(both, 'ada')).toContain(HOST_REFUSAL_WORDS['process_budget_spent']);
    // Someone who follows their own routine by choice is never told why.
    expect(choiceWords(parseSocietyModels(read({ host_refusal: 'models_not_run_here' })), 'grace')).toBe('Their own routine.');
  });
});

describe('choosing who decides', () => {
  it('chooses a model for the people ticked, or their routine', () => {
    const onChoose = vi.fn();
    const section = buildSocietyModels({ onChoose });
    const people = [{ id: 'ada', name: 'Ada' }, { id: 'grace', name: 'Grace' }];
    section.render({ view: parseSocietyModels(read()), people, busy: false, message: '' });
    expect(section.root.hidden).toBe(false);
    expect(section.choose.disabled).toBe(true);
    const boxes = section.root.querySelectorAll<HTMLInputElement>('input[type=checkbox]');
    boxes[1]!.checked = true;
    boxes[1]!.dispatchEvent(new Event('change'));
    section.model.value = `nebius_token_factory ${MODEL}`;
    section.choose.click();
    expect(onChoose).toHaveBeenLastCalledWith(['grace'], { provider: 'nebius_token_factory', modelId: MODEL });
    section.model.value = '';
    section.choose.click();
    expect(onChoose).toHaveBeenLastCalledWith(['grace'], null);
  });

  it('is not offered for a society whose people no model runs, and says when this host asks none', () => {
    const section = buildSocietyModels({ onChoose: () => undefined });
    section.render({ view: parseSocietyModels(read({ takes_model_choices: false })), people: [], busy: false, message: '' });
    expect(section.root.hidden).toBe(true);
    section.render({ view: parseSocietyModels(read({ host_refusal: 'models_not_run_here' })), people: [], busy: false, message: '' });
    expect(section.root.textContent).toContain(
      'This server does not ask models for this world\'s people, so everyone here follows their own routine for now.',
    );
    expect(hostWords('models_not_run_here')).toBe(
      'This server does not ask models for this world\'s people, so everyone here follows their own routine for now.',
    );
  });
});

describe('the mounted section', () => {
  const answer = (body: unknown, status = 200) => new Response(JSON.stringify(body), {
    status, headers: { 'content-type': 'application/json' },
  });

  it('reads once per drawn minute, sends a choice with the open world, and reads it back', async () => {
    const fetcher = vi.fn(async (_url: unknown, init?: RequestInit) => (init?.method === 'POST' ? answer({}) : answer(read())));
    const client = new SocietyModelsClient({ baseUrl: 'https://example.test', token: 't', worldId: 'world:personal:a', fetch: fetcher as typeof fetch });
    const mounted = mountSocietyModels({ credentials: { baseUrl: 'https://example.test', token: 't' }, world: { worldId: 'world:personal:a', versionId: 'version' }, client });
    const people = [{ id: 'ada', name: 'Ada' }];
    await mounted.refresh(7, people);
    await mounted.refresh(7, people);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(mounted.personDetails('ada')).toEqual([
      ['Decided by', 'Nemotron 3 Nano 30B, which you chose.'],
      ['Latest decision', 'At simulated minute 7, Nemotron 3 Nano 30B chose “rest, 4 m away”, and they did it.'],
    ]);
    const box = mounted.root.querySelector<HTMLInputElement>('input[type=checkbox]')!;
    box.checked = true;
    box.dispatchEvent(new Event('change'));
    (mounted.root.querySelector('select') as HTMLSelectElement).value = `nebius_token_factory ${MODEL}`;
    (mounted.root.querySelectorAll('button')[1] as HTMLButtonElement).click();
    await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(3));
    const [url, init] = fetcher.mock.calls[1]!;
    expect(String(url)).toContain('/world/versions/version/society/models?world_id=world%3Apersonal%3Aa');
    expect(JSON.parse(String(init?.body))).toMatchObject({
      people: ['ada'], model: { provider: 'nebius_token_factory', model_id: MODEL },
    });
    expect(mounted.root.textContent).toContain('One person is now decided by the model you chose');
  });

  it('says why a choice was refused, in words', async () => {
    const fetcher = vi.fn(async (_url: unknown, init?: RequestInit) => (init?.method === 'POST'
      ? answer({ code: 'too_many_model_people', detail: 'the choice would run more people by models than the contract allows' }, 422)
      : answer(read())));
    const client = new SocietyModelsClient({ baseUrl: 'https://example.test', token: 't', worldId: 'w', fetch: fetcher as typeof fetch });
    const mounted = mountSocietyModels({ credentials: { baseUrl: 'https://example.test', token: 't' }, world: { worldId: 'w', versionId: 'version' }, client });
    await mounted.refresh(1, [{ id: 'ada', name: 'Ada' }]);
    const box = mounted.root.querySelector<HTMLInputElement>('input[type=checkbox]')!;
    box.checked = true;
    box.dispatchEvent(new Event('change'));
    (mounted.root.querySelectorAll('button')[1] as HTMLButtonElement).click();
    await vi.waitFor(() => expect(mounted.root.textContent).toContain(CHOICE_REFUSAL_WORDS['too_many_model_people']));
  });

  it('says a recorded choice leaves them to their routine for now, and why, when this host asks no model', async () => {
    const fetcher = vi.fn(async (_url: unknown, init?: RequestInit) => (init?.method === 'POST'
      ? answer({})
      : answer(read({ host_refusal: 'provider_credential_absent' }))));
    const client = new SocietyModelsClient({ baseUrl: 'https://example.test', token: 't', worldId: 'w', fetch: fetcher as typeof fetch });
    const mounted = mountSocietyModels({ credentials: { baseUrl: 'https://example.test', token: 't' }, world: { worldId: 'w', versionId: 'version' }, client });
    await mounted.refresh(1, [{ id: 'ada', name: 'Ada' }]);
    const box = mounted.root.querySelector<HTMLInputElement>('input[type=checkbox]')!;
    box.checked = true;
    box.dispatchEvent(new Event('change'));
    (mounted.root.querySelector('select') as HTMLSelectElement).value = `nebius_token_factory ${MODEL}`;
    (mounted.root.querySelectorAll('button')[1] as HTMLButtonElement).click();
    await vi.waitFor(() => expect(mounted.root.querySelector('.society-models-result')?.textContent).toBe(
      'The model you chose is recorded for one person, but they follow their own routine for now, '
      + 'because this server has no key for a model service.',
    ));
    expect(mounted.root.textContent).not.toContain('now decided by the model you chose');
  });

  it('says what a choice came to from a read begun after it, when a read is already out', async () => {
    const waiting: (() => void)[] = [];
    let reads = 0;
    const fetcher = vi.fn(async (_url: unknown, init?: RequestInit) => {
      if (init?.method === 'POST') return answer({});
      reads += 1;
      // The first two reads were begun before the choice; the host asks no model by the third.
      const body = read(reads >= 3 ? { host_refusal: 'provider_credential_absent' } : {});
      if (reads === 2) await new Promise<void>((resolve) => { waiting.push(resolve); });
      return answer(body);
    });
    const client = new SocietyModelsClient({ baseUrl: 'https://example.test', token: 't', worldId: 'w', fetch: fetcher as typeof fetch });
    const mounted = mountSocietyModels({ credentials: { baseUrl: 'https://example.test', token: 't' }, world: { worldId: 'w', versionId: 'version' }, client });
    await mounted.refresh(1, [{ id: 'ada', name: 'Ada' }]);
    void mounted.refresh(2, [{ id: 'ada', name: 'Ada' }]);
    await vi.waitFor(() => expect(waiting).toHaveLength(1));
    const box = mounted.root.querySelector<HTMLInputElement>('input[type=checkbox]')!;
    box.checked = true;
    box.dispatchEvent(new Event('change'));
    (mounted.root.querySelector('select') as HTMLSelectElement).value = `nebius_token_factory ${MODEL}`;
    (mounted.root.querySelectorAll('button')[1] as HTMLButtonElement).click();
    await vi.waitFor(() => expect(fetcher.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(true));
    // The read begun before the choice ends now; the words must wait for the one after it.
    waiting[0]!();
    await vi.waitFor(() => expect(mounted.root.querySelector('.society-models-result')?.textContent).toBe(
      'The model you chose is recorded for one person, but they follow their own routine for now, '
      + 'because this server has no key for a model service.',
    ));
    expect(reads).toBe(3);
  });

  it('tells the inspector their routine decides for now, and why, when this host asks no model', async () => {
    const fetcher = vi.fn(async () => answer(read({ host_refusal: 'process_budget_spent' })));
    const client = new SocietyModelsClient({ baseUrl: 'https://example.test', token: 't', worldId: 'w', fetch: fetcher as typeof fetch });
    const mounted = mountSocietyModels({ credentials: { baseUrl: 'https://example.test', token: 't' }, world: { worldId: 'w', versionId: 'version' }, client });
    await mounted.refresh(1, [{ id: 'ada', name: 'Ada' }]);
    expect(mounted.personDetails('ada')[0]).toEqual([
      'Decided by',
      'Their own routine for now, because this server has spent its model budget until it restarts. You chose Nemotron 3 Nano 30B.',
    ]);
  });

  it('never reads while a read is out, and reads the latest minute once after it', async () => {
    const waiting: (() => void)[] = [];
    const fetcher = vi.fn(async () => {
      await new Promise<void>((resolve) => { waiting.push(resolve); });
      return answer(read());
    });
    const client = new SocietyModelsClient({ baseUrl: 'https://example.test', token: 't', worldId: 'w', fetch: fetcher as typeof fetch });
    const onRead = vi.fn();
    const mounted = mountSocietyModels({ credentials: { baseUrl: 'https://example.test', token: 't' }, world: { worldId: 'w', versionId: 'version' }, client, onRead });
    const people = [{ id: 'ada', name: 'Ada' }];
    const first = mounted.refresh(7, people);
    await vi.waitFor(() => expect(waiting).toHaveLength(1));
    // Two minutes drawn while the first read is out: neither sends a read of its own.
    void mounted.refresh(8, people);
    void mounted.refresh(9, people);
    expect(fetcher).toHaveBeenCalledTimes(1);
    waiting[0]!();
    // Then one read, for the latest minute drawn.
    await vi.waitFor(() => expect(waiting).toHaveLength(2));
    waiting[1]!();
    await first;
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(onRead).toHaveBeenCalledTimes(2);
    await mounted.refresh(9, people);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it('abandons a read that is out when it is taken away, and says nothing after', async () => {
    let signal: AbortSignal | null | undefined;
    const fetcher = vi.fn((_url: unknown, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
      signal = init?.signal;
      signal?.addEventListener('abort', () => reject(new DOMException('The read was abandoned.', 'AbortError')));
    }));
    vi.stubGlobal('fetch', fetcher);
    try {
      const onRead = vi.fn();
      // Its own client, so the section's own signal is the one the read carries.
      const mounted = mountSocietyModels({ credentials: { baseUrl: 'https://example.test', token: 't' }, world: { worldId: 'w', versionId: 'version' }, onRead });
      document.body.append(mounted.root);
      const reading = mounted.refresh(1, [{ id: 'ada', name: 'Ada' }]);
      await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
      expect(signal?.aborted).toBe(false);
      mounted.dispose();
      expect(signal?.aborted).toBe(true);
      await reading;
      expect(onRead).not.toHaveBeenCalled();
      expect(mounted.root.isConnected).toBe(false);
      expect(mounted.root.textContent).not.toContain('could not be read');
      await mounted.refresh(2, [{ id: 'ada', name: 'Ada' }]);
      expect(fetcher).toHaveBeenCalledTimes(1);
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
