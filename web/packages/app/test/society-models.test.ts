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
  cameWords,
  chooseWords,
  choiceWords,
  costWords,
  hostWords,
  latestDecisionWords,
  modelLine,
  OVER_BOUND_WORDS,
  outsideLatestWords,
  outsideShort,
  outsideWords,
  peopleRoleWords,
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

/** Picks a model card as a person does: its radio checked, then its change. */
function pick(root: HTMLElement, value: string): void {
  const radio = root.querySelector<HTMLInputElement>(`input[type=radio][value="${value}"]`)!;
  radio.checked = true;
  radio.dispatchEvent(new Event('change'));
}

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

  it('reads where each choice comes from and each gate\'s traveller mind, and nothing from a server that predates them', () => {
    const view = parseSocietyModels(read({
      choices: [{ ...read().choices[0], from: 'travellers' }, { ...read().choices[0], subject_id: 'bea', model: null, from: 'travellers_over_bound' }],
      travellers: [{ grant_id: 'grant-1', choice_seq: 4, decider: { kind: 'model', provider: 'nebius_token_factory', model_id: MODEL },
        model: { provider: 'nebius_token_factory', model_id: MODEL, name: 'Nemotron 3 Nano 30B' } }],
    }));
    expect(view.choices.map((choice) => choice.from)).toEqual(['travellers', 'travellers_over_bound']);
    expect(view.travellers).toEqual([{ grantId: 'grant-1', choiceSeq: 4, deciderKind: 'model',
      model: { provider: 'nebius_token_factory', modelId: MODEL, name: 'Nemotron 3 Nano 30B' } }]);
    expect(parseSocietyModels(read()).choices[0]!.from).toBeNull();
    expect(parseSocietyModels(read()).travellers).toEqual([]);
    expect(() => parseSocietyModels(read({ choices: [{ ...read().choices[0], from: 'elsewhere' }] }))).toThrow();
  });

  it('says a gate\'s traveller mind decides for a visitor, and that a model waits past the world\'s bound', () => {
    const view = parseSocietyModels(read({
      choices: [{ ...read().choices[0], from: 'travellers' }, { ...read().choices[0], subject_id: 'bea', model: null, from: 'travellers_over_bound' }],
    }));
    expect(choiceWords(view, 'ada')).toBe('Nemotron 3 Nano 30B, the mind you named for travellers through their gate.');
    expect(choiceWords(view, 'bea')).toBe(OVER_BOUND_WORDS);
    expect(choiceWords(view, 'ada', 'the allowance for open models on this visit is used up')).toBe(
      'Their own routine for now, because the allowance for open models on this visit is used up. You named Nemotron 3 Nano 30B for travellers.');
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
      .toBe('At simulated minute 7, Nemotron 3 Nano 30B chose “rest, 4 m away”, but you asked them yourself, and that came first.');
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
    pick(mounted.root, `nebius_token_factory ${MODEL}`);
    mounted.root.querySelector<HTMLButtonElement>('button.society-models-choose')!.click();
    await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(3));
    const [url, init] = fetcher.mock.calls[1]!;
    expect(String(url)).toContain('/world/versions/version/society/models?world_id=world%3Apersonal%3Aa');
    expect(JSON.parse(String(init?.body))).toMatchObject({
      people: ['ada'], model: { provider: 'nebius_token_factory', model_id: MODEL },
    });
    expect(mounted.root.textContent).toContain('One person is now decided by the model you chose');
    // Once recorded, nobody stays ticked, so the action no longer offers the same choice again.
    expect(mounted.root.querySelector<HTMLInputElement>('input[type=checkbox]')!.checked).toBe(false);
    expect(mounted.root.querySelector('button.society-models-choose')!.textContent).toBe('Choose people to decide for');
  });

  it('reads nothing more at a new minute once the server says nobody here is decided for by a model', async () => {
    const fetcher = vi.fn(async () => answer(read({ takes_model_choices: false, engine: 'exulanica-society/v4', models: [], choices: [], latest: [], by_model: [] })));
    const client = new SocietyModelsClient({ baseUrl: 'https://example.test', token: 't', worldId: 'w', fetch: fetcher as typeof fetch });
    const mounted = mountSocietyModels({ credentials: { baseUrl: 'https://example.test', token: 't' }, world: { worldId: 'w', versionId: 'version' }, client });
    const people = [{ id: 'ada', name: 'Ada' }];
    await mounted.refresh(7, people);
    expect(mounted.root.hidden).toBe(true);
    await mounted.refresh(8, people);
    await mounted.refresh(9, people);
    expect(fetcher).toHaveBeenCalledTimes(1);
    await mounted.refresh(9, people, true);
    expect(fetcher).toHaveBeenCalledTimes(2);
    mounted.dispose();
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
    mounted.root.querySelector<HTMLButtonElement>('button.society-models-choose')!.click();
    await vi.waitFor(() => expect(mounted.root.textContent).toContain(CHOICE_REFUSAL_WORDS['too_many_model_people']));
    // Another surface asking the same gets the same words back, and nothing is said recorded.
    expect(await mounted.decide(['ada'], { provider: 'nebius_token_factory', modelId: MODEL })).toEqual({
      recorded: false, words: CHOICE_REFUSAL_WORDS['too_many_model_people'],
    });
    expect(await mounted.decide([], null)).toEqual({ recorded: false, words: 'Nobody was chosen, so nothing changed.' });
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
    pick(mounted.root, `nebius_token_factory ${MODEL}`);
    mounted.root.querySelector<HTMLButtonElement>('button.society-models-choose')!.click();
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
    pick(mounted.root, `nebius_token_factory ${MODEL}`);
    mounted.root.querySelector<HTMLButtonElement>('button.society-models-choose')!.click();
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

  it('names the model running each person for the card and the marks, and none where it is not asked', async () => {
    const answers = [
      read(),
      read({ host_refusal: 'process_budget_spent' }),
      read({ choices: [{ ...read().choices[0], refusal: 'model_not_offered' }] }),
    ];
    let index = 0;
    const fetcher = vi.fn(async () => answer(answers[index]!));
    const client = new SocietyModelsClient({ baseUrl: 'https://example.test', token: 't', worldId: 'w', fetch: fetcher as typeof fetch });
    const mounted = mountSocietyModels({ credentials: { baseUrl: 'https://example.test', token: 't' }, world: { worldId: 'w', versionId: 'version' }, client });
    const people = [{ id: 'ada', name: 'Ada' }, { id: 'bea', name: 'Bea' }];
    expect(mounted.mindOf('ada')).toBeNull();
    await mounted.refresh(1, people);
    const nemotron = { provider: 'nebius_token_factory', modelId: MODEL, name: 'Nemotron 3 Nano 30B' };
    expect(mounted.mindOf('ada')).toEqual({ running: nemotron, words: 'Nemotron 3 Nano 30B, which you chose.' });
    expect(mounted.mindOf('bea')).toEqual({ running: null, words: 'Their own routine.' });
    expect([...mounted.runningModels()]).toEqual([['ada', nemotron]]);
    // Chosen but not asked, by this host or for this choice: their routine runs them, so no mark.
    for (index = 1; index < answers.length; index += 1) {
      await mounted.refresh(1 + index, people);
      expect(mounted.mindOf('ada')?.running).toBeNull();
      expect(mounted.mindOf('ada')?.words).toMatch(/^Their own routine for now, because /u);
      expect(mounted.runningModels().size).toBe(0);
    }
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

describe('the cards of who decides', () => {
  const offered = (id: string, price: { input: string; output: string } | null) => ({
    provider: 'nebius_token_factory', model_id: id, name: id,
    description: `${id}, an open reasoning model from NVIDIA.`, provider_description: 'Nebius Token Factory.',
    mechanism: 'tool_call', ...(price === null ? {} : { usd_per_mtok: price }), refusal: null,
  });

  it('compares each served price with the cheapest model offered beside it, and states none it was not served', () => {
    const view = parseSocietyModels(read({ models: [
      offered('cheap', { input: '0.06', output: '0.24' }),
      offered('near', { input: '0.14', output: '0.28' }),
      offered('dear', { input: '0.20', output: '0.60' }),
      offered('unpriced', null),
    ] }));
    expect(view.models.map((model) => costWords(model, view.models))).toEqual([
      'Lowest cost', 'Near the lowest cost', 'About 3 times the lowest cost', null,
    ]);
    // A price the server serves in another shape is refused, not guessed.
    expect(() => parseSocietyModels(read({ models: [offered('odd', { input: '-1', output: '0.2' })] }))).toThrow();
  });

  it('shows a model\'s served description without repeating the name above it', () => {
    const [model] = parseSocietyModels(read()).models;
    expect(modelLine(model!)).toBe('An open reasoning model from NVIDIA.');
    expect(modelLine({ ...model!, description: 'Served words of its own.' })).toBe('Served words of its own.');
  });

  it('says what its one action will do for the model and people chosen', () => {
    const model = { provider: 'p', modelId: 'm', name: 'Qwen3 235B Instruct' };
    expect(chooseWords(model, 0, false)).toBe('Choose people to decide for');
    expect(chooseWords(model, 4, false)).toBe('Let Qwen3 235B Instruct decide for 4 people');
    expect(chooseWords(null, 1, false)).toBe('Give one person their own routine');
    expect(chooseWords(model, 4, true)).toBe('Choosing…');
  });

  it('says on the People card who decides for the people here now', () => {
    const people = [{ id: 'ada', name: 'Ada' }, { id: 'grace', name: 'Grace' }];
    const view = parseSocietyModels(read());
    expect(peopleRoleWords(view, people)).toBe('1 by Nemotron 3 Nano 30B');
    // Somebody no longer here is not counted, and nobody under a model is their own routine.
    expect(peopleRoleWords(view, people.slice(1))).toBe('Their own routine');
  });

  it('shows people first, and the traffic lights under their own card when this world has them', () => {
    const signals = document.createElement('div');
    const section = buildSocietyModels({ onChoose: () => undefined, signals });
    const cards = () => [...section.root.querySelectorAll<HTMLButtonElement>('button[role=tab]')];
    const people = section.root.querySelector<HTMLElement>('.society-models-people-group')!;
    section.setSignals({ count: 2, words: 'Fixed timing' });
    section.render({ view: parseSocietyModels(read()), people: [{ id: 'ada', name: 'Ada' }], busy: false, message: '' });
    expect(cards().filter((card) => !card.hidden).map((card) => card.textContent))
      .toEqual(['People · 11 by Nemotron 3 Nano 30B', 'Traffic lights · 2Fixed timing']);
    expect(people.hidden).toBe(false);
    expect(signals.parentElement!.hidden).toBe(true);
    cards()[1]!.click();
    expect(people.hidden).toBe(true);
    expect(signals.parentElement!.hidden).toBe(false);
    // A world whose people take no model shows its traffic lights alone.
    const lights = buildSocietyModels({ onChoose: () => undefined, signals: document.createElement('div') });
    lights.setSignals({ count: 2, words: 'Fixed timing' });
    lights.render({ view: parseSocietyModels(read({ takes_model_choices: false })), people: [], busy: false, message: '' });
    expect(lights.root.hidden).toBe(false);
    expect(lights.root.querySelector<HTMLElement>('.society-models-people-group')!.hidden).toBe(true);
    lights.setSignals(null);
    expect(lights.root.hidden).toBe(true);
  });
});

describe('open models not asked for the people here now', () => {
  const MINDS = {
    words: 'The allowance for open models on this visit is used up, so people here now follow their own routines. The world keeps playing.',
    why: 'the allowance for open models on this visit is used up',
  };

  it('says so in the host line, and every chosen person\'s line and the card say their routine decides for now', () => {
    const section = buildSocietyModels({ onChoose: () => undefined });
    const people = [{ id: 'ada', name: 'Ada' }];
    section.render({ view: parseSocietyModels(read()), people, busy: false, message: '', minds: MINDS });
    expect(section.root.querySelector('.society-models-host')!.textContent).toBe(MINDS.words);
    expect(section.root.querySelector('[data-subject-id="ada"]')!.textContent).toContain(
      'Their own routine for now, because the allowance for open models on this visit is used up. You chose Nemotron 3 Nano 30B.');
    expect(section.root.querySelector('.society-models-role-words')!.textContent).toBe('Their own routine for now');
    section.render({ view: parseSocietyModels(read()), people, busy: false, message: '', minds: null });
    expect(section.root.querySelector('.society-models-host')!.textContent).toBe(hostWords(null));
    expect(section.root.querySelector('.society-models-role-words')!.textContent).toBe('1 by Nemotron 3 Nano 30B');
  });

  it('runs nobody\'s model while it is said, so the card and the marks say so too, and again once it is not', async () => {
    const answer = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } });
    const fetcher = vi.fn(async () => answer(read()));
    const onRead = vi.fn();
    const client = new SocietyModelsClient({ baseUrl: 'https://example.test', token: 't', worldId: 'w', fetch: fetcher as typeof fetch });
    const mounted = mountSocietyModels({ credentials: { baseUrl: 'https://example.test', token: 't' }, world: { worldId: 'w', versionId: 'version' }, client, onRead });
    await mounted.refresh(1, [{ id: 'ada', name: 'Ada' }]);
    expect(mounted.runningModels().size).toBe(1);
    const reads = onRead.mock.calls.length;
    mounted.setModelMinds(MINDS);
    expect(onRead.mock.calls.length).toBe(reads + 1);
    expect(mounted.root.querySelector('.society-models-host')!.textContent).toBe(MINDS.words);
    expect(mounted.mindOf('ada')).toEqual({ running: null, words: expect.stringMatching(/^Their own routine for now, because the allowance/u) });
    expect(mounted.runningModels().size).toBe(0);
    // Said again unchanged: nothing to tell anyone.
    mounted.setModelMinds({ ...MINDS });
    expect(onRead.mock.calls.length).toBe(reads + 1);
    mounted.setModelMinds(null);
    expect(mounted.root.querySelector('.society-models-host')!.textContent).toBe(hostWords(null));
    expect(mounted.mindOf('ada')?.running).toMatchObject({ name: 'Nemotron 3 Nano 30B' });
    mounted.dispose();
  });
});

describe('Who decides opened for chosen subjects', () => {
  const people = [{ id: 'ada', name: 'Ada' }, { id: 'grace', name: 'Grace' }, { id: 'lin', name: 'Lin' }];
  const ticked = (root: HTMLElement) => [...root.querySelectorAll<HTMLInputElement>('.society-models-people-list input[type=checkbox]')]
    .filter((box) => box.checked).map((box) => box.value);

  it('ticks exactly the subjects asked for, leaves out anybody not here, and says what it will do', () => {
    const section = buildSocietyModels({ onChoose: () => undefined });
    section.render({ view: parseSocietyModels(read()), people, busy: false, message: '' });
    section.chooseFor(['grace']);
    expect(section.chooseFor(['lin', 'ada', 'nobody'])).toBe(2);
    expect(ticked(section.root)).toEqual(['ada', 'lin']);
    expect(section.choose.textContent).toBe('Give 2 people their own routine');
    expect(section.choose.disabled).toBe(false);
  });

  it('ticks them once they are listed when asked before the first read', () => {
    const section = buildSocietyModels({ onChoose: () => undefined });
    expect(section.chooseFor(['grace'])).toBe(0);
    section.render({ view: parseSocietyModels(read()), people, busy: false, message: '' });
    expect(ticked(section.root)).toEqual(['grace']);
    // Once only: a later read keeps what the person changed since.
    const box = section.root.querySelector<HTMLInputElement>('input[value="ada"]')!;
    box.checked = true;
    box.dispatchEvent(new Event('change'));
    section.render({ view: parseSocietyModels(read()), people, busy: false, message: '' });
    expect(ticked(section.root)).toEqual(['ada', 'grace']);
  });

  it('shows the traffic lights card when asked for that role', () => {
    const signals = document.createElement('div');
    const section = buildSocietyModels({ onChoose: () => undefined, signals });
    section.setSignals({ count: 2, words: 'Fixed timing' });
    section.render({ view: parseSocietyModels(read()), people, busy: false, message: '' });
    section.showRole('signals');
    expect(signals.parentElement!.hidden).toBe(false);
    expect(section.root.querySelector<HTMLElement>('.society-models-people-group')!.hidden).toBe(true);
  });
});

describe('who outside programs decide for', () => {
  const AGENT = {
    subject_id: 'grace', came: 'run', grant_id: 'grant-1', bridge: 'agents', bridge_label: 'Outside agents',
    run_by: 'owner', ai: true, connected: true, declared: { name: 'Scout', maker: 'Acme', mind: null },
  };
  const VISITOR = {
    subject_id: 'visitor-4', came: 'crossed', grant_id: 'grant-2', bridge: 'blocks', bridge_label: 'Block Game',
    run_by: 'server', ai: false, connected: false, declared: null,
  };
  const UNLISTED = { ...VISITOR, subject_id: 'visitor-5', bridge: 'gone', bridge_label: null, run_by: null, ai: null };
  const view = () => parseSocietyModels(read({ outside: [AGENT, VISITOR, UNLISTED] }));
  const people = [{ id: 'ada', name: 'Ada' }, { id: 'grace', name: 'Grace' }, { id: 'visitor-4', name: 'Visitor 4' }];

  it('reads who outside programs decide for, and nobody from a server that predates the field', () => {
    expect(view().outside!.map((entry) => [entry.subjectId, entry.came, entry.ai, entry.bridgeLabel])).toEqual([
      ['grace', 'run', true, 'Outside agents'], ['visitor-4', 'crossed', false, 'Block Game'], ['visitor-5', 'crossed', null, null],
    ]);
    expect(view().outside![0]!.declared).toEqual({ name: 'Scout', maker: 'Acme', mind: null });
    expect(parseSocietyModels(read()).outside).toEqual([]);
    expect(() => parseSocietyModels(read({ outside: [{ ...AGENT, came: 'walked' }] }))).toThrow();
    expect(() => parseSocietyModels(read({ outside: [{ ...AGENT, connected: 'yes' }] }))).toThrow();
  });

  it('says who runs them from outside, claiming an AI only where the door says so and nothing for a bridge it does not list', () => {
    const [agent, visitor, unlisted] = view().outside!;
    expect(outsideWords(agent!)).toBe('Decided from outside by Scout (Acme), an AI agent, through Outside agents.');
    expect(outsideWords({ ...agent!, declared: null })).toBe('Decided from outside by an AI agent, through Outside agents.');
    // No AI runs its bridge, and nothing says a person plays: no person is claimed.
    expect(outsideWords(visitor!)).toBe('Decided from outside, through Block Game. Its program is not connected now.');
    expect(outsideWords(visitor!)).not.toMatch(/person|AI/u);
    expect(outsideWords(unlisted!)).toBe('Decided from outside this world. Its program is not connected now.');
    expect(outsideWords(unlisted!)).not.toMatch(/AI|person/u);
    expect([outsideShort(agent!), outsideShort(visitor!), outsideShort(unlisted!)]).toEqual(['Scout', 'Block Game', 'outside']);
    expect(cameWords(visitor!)).toBe('Came in from Block Game.');
    expect(cameWords(unlisted!)).toBe('Came in from outside this world.');
    expect(cameWords(agent!)).toBe('One of this world\'s own people, run from outside through Outside agents.');
  });

  it('names the outside program as who decides, even where the choice record names no model', () => {
    const held = parseSocietyModels(read({ outside: [AGENT], choices: [...read().choices, { ...read().choices[0], subject_id: 'grace', model: null }] }));
    expect(choiceWords(held, 'grace')).toBe('Decided from outside by Scout (Acme), an AI agent, through Outside agents.');
    expect(choiceWords(held, 'ada')).toBe('Nemotron 3 Nano 30B, which you chose.');
    expect(peopleRoleWords(held, people)).toBe('1 by Nemotron 3 Nano 30B · 1 from outside');
    expect(peopleRoleWords(parseSocietyModels(read({ choices: [], outside: [AGENT, VISITOR] })), people)).toBe('2 from outside');
  });

  it('lists them with who decides, and never ticks them: not by a person, Choose everyone or another surface', () => {
    const onChoose = vi.fn();
    const section = buildSocietyModels({ onChoose });
    section.render({ view: view(), people, busy: false, message: '' });
    const row = (id: string) => section.root.querySelector<HTMLElement>(`[data-subject-id="${id}"]`)!;
    expect(row('grace').dataset['outside']).toBe('true');
    expect(row('grace').querySelector<HTMLInputElement>('input')!.disabled).toBe(true);
    expect(row('grace').textContent).toContain('Decided from outside by Scout (Acme)');
    expect(row('ada').dataset['outside']).toBeUndefined();
    section.root.querySelector<HTMLButtonElement>('[data-action="people.decides.everyone"]')!.click();
    section.model.value = `nebius_token_factory ${MODEL}`;
    section.choose.click();
    expect(onChoose).toHaveBeenLastCalledWith(['ada'], { provider: 'nebius_token_factory', modelId: MODEL });
    expect(section.chooseFor(['grace', 'visitor-4'])).toBe(0);
    expect(section.choose.disabled).toBe(true);
  });

  it('hands the card and the marks the outside program, and never a model, for them', async () => {
    const answer = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } });
    const fetcher = vi.fn(async () => answer(read({ outside: [AGENT], choices: [...read().choices, { ...read().choices[0], subject_id: 'grace' }] })));
    const client = new SocietyModelsClient({ baseUrl: 'https://example.test', token: 't', worldId: 'w', fetch: fetcher as typeof fetch });
    const mounted = mountSocietyModels({ credentials: { baseUrl: 'https://example.test', token: 't' }, world: { worldId: 'w', versionId: 'version' }, client });
    await mounted.refresh(1, people);
    expect(mounted.mindOf('grace')).toMatchObject({ running: null, outside: { subjectId: 'grace', declared: { name: 'Scout' } } });
    expect(mounted.mindOf('ada')).not.toHaveProperty('outside');
    expect([...mounted.runningModels().keys()]).toEqual(['ada']);
    expect([...mounted.outsideDeciders().keys()]).toEqual(['grace']);
    mounted.dispose();
  });
});

describe('what became of an outside program\'s latest answer', () => {
  const ENTRY = {
    subject_id: 'grace', came: 'crossed', grant_id: 'grant-1', bridge: 'blocks', bridge_label: 'Block Game',
    run_by: 'server', ai: false, connected: true, declared: null,
  };
  const receipt = (status: string, reason: string) => ({ decision_seq: 4, base_tick: 7, consumed_tick: null, status, reason });

  it('reads the latest receipt, none, or nothing from a server that predates it', () => {
    const read1 = parseSocietyModels(read({ outside: [{ ...ENTRY, latest: receipt('unavailable', 'no_answer_in_time') }] }));
    expect(read1.outside![0]!.latest).toEqual({ decisionSeq: 4, baseTick: 7, consumedTick: null, status: 'unavailable', reason: 'no_answer_in_time' });
    expect(parseSocietyModels(read({ outside: [{ ...ENTRY, latest: null }] })).outside![0]!.latest).toBeNull();
    expect(parseSocietyModels(read({ outside: [ENTRY] })).outside![0]).not.toHaveProperty('latest');
    expect(parseSocietyModels(read({ outside: [{ ...ENTRY, latest: receipt('stale', 'decision_context_changed') }] })).outside![0]!.latest!.status).toBe('stale');
    expect(() => parseSocietyModels(read({ outside: [{ ...ENTRY, latest: receipt('lost', 'no_answer_in_time') }] }))).toThrow();
  });

  it('says why their routine decided when the latest answer was not taken, and nothing when it was', () => {
    const entry = (latest: unknown) => parseSocietyModels(read({ outside: [{ ...ENTRY, latest }] })).outside![0]!;
    expect(outsideLatestWords(entry(receipt('unavailable', 'no_answer_in_time')))).toBe(
      'Lately: the program that decides for them did not answer in time, so their own routine decided.');
    expect(outsideLatestWords(entry(receipt('accepted', 'validated_choice')))).toBeNull();
    expect(outsideLatestWords(entry(null))).toBeNull();
    expect(outsideLatestWords(parseSocietyModels(read({ outside: [ENTRY] })).outside![0]!)).toBeNull();
  });

  it('shows it under who decides on their row, and nothing for one whose latest answer was taken', () => {
    const section = buildSocietyModels({ onChoose: () => undefined });
    const people = [{ id: 'grace', name: 'Grace' }, { id: 'bea', name: 'Bea' }];
    section.render({ view: parseSocietyModels(read({ outside: [
      { ...ENTRY, latest: receipt('unavailable', 'no_answer_in_time') },
      { ...ENTRY, subject_id: 'bea', latest: receipt('accepted', 'validated_choice') },
    ] })), people, busy: false, message: '' });
    const lately = (id: string) => section.root.querySelector(`[data-subject-id="${id}"] .society-models-person-lately`);
    expect(lately('grace')!.textContent).toBe('Lately: the program that decides for them did not answer in time, so their own routine decided.');
    expect(lately('bea')).toBeNull();
  });
});

describe('a being a person plays', () => {
  // 3p's models read (THINGS, 2026-10-09): the played being's choice reads decider person and
  // played_by_you, never an account; ada played by the reader, bea by someone else.
  const answer = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } });
  const played = (byYou: boolean, subject: string) => ({
    subject_id: subject, model: null, choice_seq: 2, chosen_by: null, recorded_at: '2026-10-09T01:00:00Z',
    refusal: null, decider: { kind: 'person' }, played_by_you: byYou,
  });

  it('says who plays them, rests their mind, and lets no model be chosen for them meanwhile', async () => {
    const view = read({ choices: [played(true, 'ada'), played(false, 'bea'), { ...read().choices[0], subject_id: 'cy' }] });
    const fetcher = vi.fn(async () => answer(view));
    const client = new SocietyModelsClient({ baseUrl: 'https://example.test', token: 't', worldId: 'w', fetch: fetcher as typeof fetch });
    const mounted = mountSocietyModels({ credentials: { baseUrl: 'https://example.test', token: 't' }, world: { worldId: 'w', versionId: 'version' }, client });
    const people = [{ id: 'ada', name: 'Ada' }, { id: 'bea', name: 'Bea' }, { id: 'cy', name: 'Cy' }];
    await mounted.refresh(1, people);
    expect(mounted.mindOf('ada')).toEqual({ running: null, words: 'Played by you. Its own mind rests until you give it back.', played: { byYou: true } });
    expect(mounted.mindOf('bea')?.words).toBe('Being played by another person.');
    expect(mounted.mindOf('cy')?.played).toBeUndefined();
    expect([...mounted.playedSubjects()]).toEqual([['ada', { byYou: true }], ['bea', { byYou: false }]]);
    expect([...mounted.runningModels().keys()]).toEqual(['cy']);
    // Their rows say so and cannot be ticked; Choose everyone passes them by.
    const box = (id: string) => mounted.root.querySelector<HTMLInputElement>(`[data-subject-id="${id}"] input[type=checkbox]`)!;
    expect([box('ada').disabled, box('bea').disabled, box('cy').disabled]).toEqual([true, true, false]);
    mounted.root.querySelector<HTMLButtonElement>('button.society-models-everyone')!.click();
    expect([box('ada').checked, box('bea').checked, box('cy').checked]).toEqual([false, false, true]);
    // A read from a server that predates playing says nothing of it.
    expect(parseSocietyModels(read()).choices[0]).not.toHaveProperty('played');
    mounted.dispose();
  });
});
