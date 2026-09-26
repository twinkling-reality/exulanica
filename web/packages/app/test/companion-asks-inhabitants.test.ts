// @vitest-environment happy-dom

// A question about the people in a person's world, on the page: what the ask client sends and
// reads, how an answer's simulated people and places are drawn from the society the page shows,
// and how its simulation citations are offered. Every wire body is written from
// `exulanica/api/routes/selection.py` (`AnswerView`, `SimulationCitationView`).
import { describe, expect, it, vi } from 'vitest';
import { companionNames } from '../src/companion-names.js';
import { CompanionAskClient, type CompanionAnswer } from '../src/companion-ask-api.js';
import { rememberedAsAnswer } from '../src/companion-memory-api.js';
import { drawSimulated, type SocietyNames } from '../src/companion-simulated.js';
import { buildCompanionChoiceRail } from '../src/ui/companion-choice-rail.js';
import { buildCompanionSpeech } from '../src/ui/companion-speech.js';

const json = (body: unknown, status = 200): Response =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });

const WORLD = 'world:authored:companion-inhabitants';
const WHERE = { baseUrl: 'https://exulanica.test/api', token: 'not-a-real-token', worldId: WORLD };
const VERSION = '44444444-4444-4444-8444-444444444444';
const ARI = '55555555-5555-4555-8555-555555555555';
const BELA = '66666666-6666-4666-8666-666666666666';
const EVENT = '77777777-7777-4777-8777-777777777777';
const BENCH = 'target:bench-1';

const SOCIETY: SocietyNames = {
  versionId: VERSION,
  people: new Map([[ARI, 'Ari Ash 1'], [BELA, 'Bela Ash 2']]),
  spots: new Map([[BENCH, 'Bench 2']]),
};

/** What the server answers to "why are they there?" about a selected person. */
const whyBody = {
  answer: {
    clauses: [
      { text: '[inhabitant A]: Resting at [spot A].', type: 'simulation', citations: ['STATEAAAA1'], value_refs: [] },
      { text: 'Because they need a rest.', type: 'simulation', citations: ['STATEAAAA1', 'EVENTAAAA1'], value_refs: [] },
      { text: 'These are simulated people.', type: 'meta', citations: [], value_refs: [] },
    ],
  },
  plan: { intent: 'society', society: { scope: 'selected', aspect: 'why' } },
  selection: null,
  citations: {},
  abstained: null,
  deterministic: true,
  repaired: false,
  execution: { prompt_version: 'selection-9', calls: [] },
  names: {},
  simulation: {
    STATEAAAA1: {
      truth_class: 'simulation', result_kind: 'synthetic_inhabitant', version_id: VERSION,
      inhabitant_id: ARI, event_id: null, tick: 6, line: '[inhabitant A]: Resting at [spot A].',
      personal_visit_evidence: false,
    },
    EVENTAAAA1: {
      truth_class: 'simulation', result_kind: 'simulation_event', version_id: VERSION,
      inhabitant_id: ARI, event_id: EVENT, tick: 5,
      line: 'Simulated minute 5: [inhabitant A] chose where to go next, because they need a rest.',
      personal_visit_evidence: false,
    },
  },
  inhabitants: { '[inhabitant A]': { version_id: VERSION, inhabitant_id: ARI } },
  spots: { '[spot A]': BENCH },
};

function transport(...responses: Response[]) {
  const seen: { url: string; body: unknown }[] = [];
  const fetch = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    seen.push({ url: String(url), body: init?.body === undefined ? null : JSON.parse(String(init.body)) });
    return responses[seen.length - 1] ?? json({}, 500);
  });
  return { fetch: fetch as unknown as typeof globalThis.fetch, seen };
}

async function askWhy(): Promise<{ answer: CompanionAnswer; seen: { url: string; body: unknown }[] }> {
  const { fetch, seen } = transport(json(whyBody));
  const answer = await new CompanionAskClient({ ...WHERE, fetch }).ask(
    'Why are they there?',
    null,
    { versionId: VERSION, inhabitantId: ARI },
    { scope: 'selected', aspect: 'why' },
  );
  return { answer, seen };
}

describe('asking about the people in a world', () => {
  it('sends the society and the selected person, and never asks where a photograph is', async () => {
    const { answer, seen } = await askWhy();
    // One request: a simulation citation is not a photograph, so the packet route is not asked.
    expect(seen).toHaveLength(1);
    expect(seen[0]!.body).toEqual({
      question: 'Why are they there?',
      society_context: { version_id: VERSION, inhabitant_id: ARI },
      plan: { intent: 'society', society: { scope: 'selected', aspect: 'why' } },
    });
    expect(answer.evidence).toEqual([]);
    expect(answer.simulation?.map((cited) => [cited.token, cited.resultKind, cited.eventId])).toEqual([
      ['STATEAAAA1', 'synthetic_inhabitant', null],
      ['EVENTAAAA1', 'simulation_event', EVENT],
    ]);
    expect(answer.inhabitants).toEqual({ '[inhabitant A]': { versionId: VERSION, inhabitantId: ARI } });
    expect(answer.spots).toEqual({ '[spot A]': BENCH });
    // A simulated fact keeps its own clause type, never read as the person's past.
    expect(answer.clauses.map((clause) => clause.type)).toEqual(['simulation', 'simulation', 'meta']);
    // And the answer is marked as about the world's people, which the Companion does not keep.
    expect(answer.aboutSociety).toBe(true);
  });

  it('draws a remembered answer that cites nothing as a statement about the search', () => {
    const restored = rememberedAsAnswer({
      answerId: 'answer-1',
      askedAtMs: Date.UTC(2026, 8, 25, 12, 0, 0),
      question: 'Why is Ari there?',
      answerText: 'A name in your question belongs both to someone you saved and to a simulated person.',
      abstained: 'UNANSWERABLE_AMBIGUOUS',
      deterministic: false,
      repaired: false,
      servedModel: null,
      plannedBy: null,
      promptVersion: 'selection-9',
      latencyMs: 0,
      origin: 'asked' as const,
      supersedes: null,
      correctionNote: null,
      citations: [],
      names: {},
    });
    expect(restored.clauses.map((clause) => clause.type)).toEqual(['meta']);
  });

  it('draws a refusal about a typed label in its own words, as asked and as remembered', () => {
    // `SocietyRefusal.TYPED_INHABITANT_LABEL` in `exulanica/selection/society_question.py`, which
    // `tests/test_society_question.py` holds to carrying no bracketed label.
    const refusal =
      'A label in square brackets, copied from an earlier answer, names someone only in that answer, so it names ' +
      "nobody here. Use the person's name, or select them in the world, and ask again.";
    const drawn = drawSimulated([{ kind: 'text', text: refusal }], { inhabitants: {}, spots: {} }, SOCIETY);
    expect(drawn.map((piece) => piece.text).join('')).toBe(refusal);
    const restored = rememberedAsAnswer({
      answerId: 'answer-2',
      askedAtMs: Date.UTC(2026, 8, 25, 12, 0, 0),
      question: 'Why is [inhabitant B] there?',
      answerText: refusal,
      abstained: 'UNANSWERABLE_AMBIGUOUS',
      deterministic: false,
      repaired: false,
      servedModel: null,
      plannedBy: null,
      promptVersion: 'selection-9',
      latencyMs: 0,
      origin: 'asked' as const,
      supersedes: null,
      correctionNote: null,
      citations: [],
      names: {},
    });
    const speech = buildCompanionSpeech({ speakerName: 'Companion', names: companionNames(() => null), society: () => SOCIETY });
    speech.renderAnswer(restored);
    expect(speech.root.querySelector('.companion-utterance')?.textContent).toBe(refusal);
    expect(speech.root.querySelector('.companion-simulated')).toBeNull();
  });

  it('keeps only a citation the server marked simulation and never a visit', async () => {
    const marked = structuredClone(whyBody);
    marked.simulation.EVENTAAAA1.personal_visit_evidence = true as false;
    const { fetch } = transport(json(marked));
    const answer = await new CompanionAskClient({ ...WHERE, fetch }).ask('why?', null, { versionId: VERSION, inhabitantId: ARI });
    expect(answer.simulation?.map((cited) => cited.token)).toEqual(['STATEAAAA1']);
  });

  it('draws each simulated person and place from the society the page shows, as simulated', async () => {
    const { answer } = await askWhy();
    const speech = buildCompanionSpeech({
      speakerName: 'Companion',
      names: companionNames(() => null),
      society: () => SOCIETY,
    });
    speech.renderAnswer(answer);
    const first = speech.root.querySelectorAll('.companion-utterance')[0]!;
    expect(first.textContent).toBe('Ari Ash 1: Resting at Bench 2.');
    const drawn = [...first.querySelectorAll('.companion-simulated')];
    expect(drawn.map((node) => [node.getAttribute('data-simulated'), node.getAttribute('data-subject-id')])).toEqual([
      ['inhabitant', ARI],
      ['spot', BENCH],
    ]);
    // A simulated person is never drawn as somebody from the library.
    expect(first.querySelector('.companion-name:not(.companion-simulated)')).toBeNull();
    expect(speech.root.textContent).not.toContain('[inhabitant');
  });

  it('says in words a person the page is not showing, never brackets and never a saved name', () => {
    const pieces = drawSimulated(
      [{ kind: 'text', text: '[inhabitant A] waited at [spot A].' }],
      { inhabitants: { '[inhabitant A]': { versionId: 'another-version', inhabitantId: ARI } }, spots: { '[spot A]': 'target:gone' } },
      SOCIETY,
    );
    expect(pieces.map((piece) => piece.text).join('')).toBe(
      'A simulated person this page is not showing waited at a place that is no longer there.',
    );
  });

  it('offers each simulation citation as simulation, and opens it by its index', async () => {
    const { answer } = await askWhy();
    const opened: number[] = [];
    const rail = buildCompanionChoiceRail({
      onSelect: () => undefined,
      onSubmit: () => undefined,
      onSay: () => undefined,
      onEvidence: () => undefined,
      onSimulation: (index) => opened.push(index),
    });
    rail.renderAnswer(answer, () => undefined);
    const chips = [...rail.root.querySelectorAll<HTMLButtonElement>('.companion-simulation-chip')];
    expect(chips.map((chip) => [chip.textContent, chip.dataset['truthClass']])).toEqual([
      ['Simulation, minute 6', 'simulation'],
      ['Simulation, minute 5', 'simulation'],
    ]);
    // No photograph chip: nothing here is a photograph.
    expect(rail.root.querySelector('.companion-evidence-chip')).toBeNull();
    chips[1]!.click();
    expect(opened).toEqual([1]);
  });
});
