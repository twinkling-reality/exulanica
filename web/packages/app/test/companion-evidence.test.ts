// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { CompanionSession, SelectionOutcome, Turn } from '@exulanica/companion-runtime';
import { ExulanicaClient, type GraphSnapshot } from '@exulanica/graph-client';

import type { AnswerEvidence, CompanionAnswer } from '../src/companion-ask-api.js';
import { mountCompanion, type MountedCompanion } from '../src/composition/companion.js';
import { mountInputModes, type InputModeDependencies } from '../src/composition/input-modes.js';
import type { SessionState } from '../src/composition/session-state.js';
import { EvidenceCache, type OpenedEvidence } from '../src/evidence.js';
import { DEFAULT_PREFERENCES } from '../src/preferences.js';
import { buildCompanionEncounter } from '../src/ui/companion-encounter.js';
import type { ConfirmPanel } from '../src/ui/confirm.js';
import { say } from '../src/ui/copy.js';

/**
 * Opening a citation draws the photograph inside the Companion, with the way back to what cited it.
 *
 * The photograph is the masked view `EvidenceCache` reads. When it does not open, the Companion
 * says so with the server's reason and draws nothing in its place, because a stand-in picture
 * would claim the evidence exists and looks like that.
 */

const SPAN_A = '11111111-1111-4111-8111-111111111111';
const SPAN_B = '22222222-2222-4222-8222-222222222222';
const PLACE = '0190a000-0000-7000-8000-00000000000b';
const SHOWN: OpenedEvidence = { ok: true, url: 'blob:https://exulanica.test/photograph-a', type: 'image/jpeg' };
const SHOWN_B: OpenedEvidence = { ok: true, url: 'blob:https://exulanica.test/photograph-b', type: 'image/jpeg' };
const DELETED: OpenedEvidence = { ok: false, reason: 'this evidence was deleted' };

function cited(token: string, handle: string, capturedAt: string): AnswerEvidence {
  return {
    token,
    uri: `exulanica://blob/ni:///sha-256;${token}/img`,
    handle,
    captureId: '33333333-3333-4333-8333-333333333333',
    capturedAt,
  };
}

const ANSWER: CompanionAnswer = {
  question: 'Which of my photographs were taken at Mireland Hall?',
  clauses: [{
    text: 'These photographs were taken at [place A].',
    type: 'historical',
    citations: ['TOKEN00001', 'TOKEN00002'],
  }],
  text: 'These photographs were taken at [place A].',
  abstained: null,
  deterministic: false,
  repaired: false,
  evidence: [
    cited('TOKEN00001', SPAN_A, '2026-08-14T10:20:00+00:00'),
    cited('TOKEN00002', SPAN_B, '2026-08-16T14:05:00+00:00'),
  ],
  names: { '[place A]': PLACE },
  provenance: {
    composed: 'model',
    servedModel: 'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B',
    plannedBy: 'Qwen/Qwen3-235B-A22B-Instruct-2507',
    latencyMs: 9800,
    usedFallback: false,
  },
  promptVersion: 'selection-7',
  calls: [],
};

/** A read the test finishes when it chooses, so the face can be seen before the bytes arrive. */
function pending(): { readonly opening: Promise<OpenedEvidence>; finish(opened: OpenedEvidence): void } {
  let finish: (opened: OpenedEvidence) => void = () => undefined;
  const opening = new Promise<OpenedEvidence>((resolve) => {
    finish = resolve;
  });
  return { opening, finish };
}

const settle = async (): Promise<void> => {
  for (let turn = 0; turn < 12; turn += 1) await Promise.resolve();
};

function answering(onDismiss?: () => void) {
  const panel = buildCompanionEncounter(
    { onSelect: () => undefined, onSubmit: () => undefined, onSay: () => undefined, onEvidence: () => undefined },
    onDismiss === undefined ? {} : { onDismiss },
  );
  document.body.append(panel.root);
  panel.setState('open');
  panel.showAnswer(ANSWER);
  return panel;
}

/** A question the Companion asks about one photograph, which it opens from the rail on `E`. */
const QUESTION = {
  turnId: 'turn-question',
  intent: 'identify',
  subjectEntityId: null,
  subjectAnchorId: null,
  utteranceKey: 'ask.identity',
  utterance: 'Is this the same person as in the earlier photograph?',
  evidence: [SPAN_A],
  choiceSet: null,
  freeTextAllowed: true,
  escapes: [],
  stateVersion: 1,
} as unknown as Turn;

const FIRST = { index: 0, capturedAt: ANSWER.evidence[0]!.capturedAt };
const SECOND = { index: 1, capturedAt: ANSWER.evidence[1]!.capturedAt };

const utterance = (root: HTMLElement): string =>
  root.querySelector('.companion-utterance')?.textContent ?? '';
const image = (root: HTMLElement): HTMLImageElement | null =>
  root.querySelector<HTMLImageElement>('.companion-evidence-figure img');
const back = (root: HTMLElement): void =>
  root.querySelector<HTMLButtonElement>('.companion-evidence-back')?.click();

describe('the photograph a citation opens', () => {
  beforeEach(() => document.body.replaceChildren());

  it('is drawn inside the Companion, dated, with the way back to the answer', async () => {
    const panel = answering();
    const read = pending();
    panel.showEvidence(read.opening, FIRST);

    expect(panel.mode()).toBe('evidence');
    expect(panel.root.textContent).toContain(say('evidence.opening'));
    expect(image(panel.root)).toBeNull();
    // The chip that was pressed is gone with the answer, so the way back holds the keyboard.
    expect(document.activeElement?.classList.contains('companion-evidence-back')).toBe(true);

    read.finish(SHOWN);
    await settle();
    expect(image(panel.root)?.getAttribute('src')).toBe(SHOWN.ok ? SHOWN.url : '');
    expect(panel.root.textContent).toContain('Taken on 2026-08-14.');
    expect(panel.root.getAttribute('data-evidence')).toBe('shown');
    // The arrival redraws the face, and the way back still holds the keyboard.
    expect(document.activeElement?.classList.contains('companion-evidence-back')).toBe(true);

    back(panel.root);
    expect(panel.mode()).toBe('answer');
    expect(image(panel.root)).toBeNull();
    expect(panel.root.querySelectorAll('.companion-evidence-chip')).toHaveLength(2);
  });

  it('gives the keyboard back to the citation that opened it', async () => {
    const panel = answering();
    panel.showEvidence(Promise.resolve(SHOWN_B), SECOND);
    await settle();
    back(panel.root);

    const chips = panel.root.querySelectorAll('.companion-evidence-chip');
    expect(document.activeElement).toBe(chips[1]);
  });

  it('opened from a question goes back to the question, and the keyboard to what opened it', async () => {
    const panel = buildCompanionEncounter(
      { onSelect: () => undefined, onSubmit: () => undefined, onSay: () => undefined, onEvidence: () => undefined },
      {},
    );
    document.body.append(panel.root);
    panel.setState('open');
    panel.render(QUESTION);
    panel.showEvidence(Promise.resolve(SHOWN), { index: 0, capturedAt: null });
    await settle();

    expect(panel.root.querySelector('.companion-evidence-back')?.textContent).toBe(
      say('answer.backToQuestion'),
    );
    back(panel.root);
    expect(panel.mode()).toBe('turn');
    expect(document.activeElement).toBe(panel.root.querySelector('.companion-evidence-action'));
  });

  it('that did not open is said with the server\'s reason, and nothing is drawn in its place', async () => {
    const panel = answering();
    panel.showEvidence(Promise.resolve(DELETED), FIRST);
    await settle();

    expect(image(panel.root)).toBeNull();
    expect(panel.root.querySelector('.companion-evidence-unavailable')?.textContent).toBe(
      say('evidence.unavailable'),
    );
    expect(panel.root.textContent).toContain('this evidence was deleted');
    // A date belongs to a photograph that is on the screen, and this one is not.
    expect(panel.root.textContent).not.toContain('Taken on');
    expect(panel.root.getAttribute('data-evidence')).toBe('unavailable');
  });

  it('whose copy the page has released is said to be unavailable, not drawn broken', async () => {
    const panel = answering();
    panel.showEvidence(Promise.resolve(SHOWN), FIRST);
    await settle();
    image(panel.root)?.dispatchEvent(new Event('error'));

    expect(image(panel.root)).toBeNull();
    expect(panel.root.textContent).toContain(say('evidence.unavailable'));
    expect(panel.root.textContent).toContain(say('evidence.released'));
    expect(panel.root.querySelector('.companion-evidence')?.getAttribute('data-evidence')).toBe(
      'unavailable',
    );
  });

  it('drops the transport\'s status code from a refusal, keeping the server\'s sentence', async () => {
    const panel = answering();
    panel.showEvidence(
      Promise.resolve({ ok: false, reason: 'http_409: current viewer image is unavailable' }),
      FIRST,
    );
    await settle();
    const detail = panel.root.querySelector('.companion-evidence-unavailable-detail')?.textContent;
    expect(detail).toBe('current viewer image is unavailable');
  });
});

describe('a read that arrives late', () => {
  beforeEach(() => document.body.replaceChildren());

  it('is not drawn once the person has gone back', async () => {
    const panel = answering();
    const read = pending();
    panel.showEvidence(read.opening, FIRST);
    back(panel.root);

    read.finish(SHOWN);
    await settle();
    expect(panel.mode()).toBe('answer');
    expect(image(panel.root)).toBeNull();
    expect(panel.root.hasAttribute('data-evidence')).toBe(false);
  });

  it('is not drawn over another photograph opened after it', async () => {
    const panel = answering();
    const first = pending();
    const second = pending();
    panel.showEvidence(first.opening, FIRST);
    back(panel.root);
    panel.showEvidence(second.opening, SECOND);

    first.finish(SHOWN);
    await settle();
    expect(image(panel.root)).toBeNull();
    expect(panel.root.textContent).toContain(say('evidence.opening'));

    second.finish(SHOWN_B);
    await settle();
    expect(image(panel.root)?.getAttribute('src')).toBe(SHOWN_B.ok ? SHOWN_B.url : '');
  });

  it('is not drawn after the Companion was sent away, and summoning shows the answer', async () => {
    const panel = answering();
    const read = pending();
    panel.showEvidence(read.opening, FIRST);
    panel.setState('summon');

    read.finish(SHOWN);
    await settle();
    panel.setState('open');
    expect(panel.mode()).toBe('answer');
    expect(image(panel.root)).toBeNull();
    expect(utterance(panel.root)).toContain('These photographs were taken at');
  });
});

describe('Escape with a photograph open', () => {
  beforeEach(() => document.body.replaceChildren());

  it('closes the photograph before the Companion, wherever the keyboard is in the panel', () => {
    const dismissed = vi.fn();
    const panel = answering(dismissed);
    panel.showEvidence(Promise.resolve(SHOWN), FIRST);
    expect(panel.openEvidence()).toBe(false);

    // A click on the photograph focuses its face, which stays inside the panel.
    const face = panel.root.querySelector<HTMLElement>('.companion-evidence');
    // The attribute, not the property: every element reports a tabIndex of -1 until it has one.
    expect(face?.getAttribute('tabindex')).toBe('-1');
    face?.focus();
    face?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(panel.mode()).toBe('answer');
    expect(dismissed).not.toHaveBeenCalled();

    panel.root.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(dismissed).toHaveBeenCalledTimes(1);
  });

  it('is offered to the photograph first by the page\'s own Escape, through closeEvidence', () => {
    const panel = answering();
    expect(panel.closeEvidence()).toBe(false);
    panel.showEvidence(Promise.resolve(SHOWN), FIRST);
    expect(panel.closeEvidence()).toBe(true);
    expect(panel.mode()).toBe('answer');
    expect(panel.closeEvidence()).toBe(false);
  });
});

// -- the whole Companion, as the composition root mounts it ----------------------------------

const ACKNOWLEDGE = {
  turnId: 'turn-ack',
  intent: 'acknowledge',
  subjectEntityId: null,
  subjectAnchorId: null,
  utteranceKey: 'utterance.acknowledge',
  utterance: null,
  evidence: [],
  choiceSet: null,
  freeTextAllowed: true,
  escapes: [],
  stateVersion: 1,
} as unknown as Turn;

/** An engine that reads every sentence as a question, which is the branch that reaches `ask`. */
function questioning(): CompanionSession {
  return {
    advance: () => ACKNOWLEDGE,
    say: () => ({ kind: 'refused', reasonKey: 'refused.couldNotParse' }) as SelectionOutcome,
    adoptPersistedMemory: () => undefined,
    lastAnswer: null,
  } as unknown as CompanionSession;
}

/**
 * The real read path under the Companion: `EvidenceCache` over `ExulanicaClient`, with only the
 * network faked, so what is asserted is the request the page makes and not a stand-in for it.
 */
function mounted(respond: (url: string) => Response) {
  const requested: string[] = [];
  const fetch = vi.fn(async (url: string | URL | Request) => {
    requested.push(String(url));
    return respond(String(url));
  });
  const client = new ExulanicaClient({
    baseUrl: 'https://exulanica.test/api',
    token: 'not-a-real-token',
    fetch: fetch as unknown as typeof globalThis.fetch,
  });
  const snapshot = {
    entities: [{ entityId: PLACE, displayName: 'MIRELAND HALL', mergedInto: null, assertions: [] }],
    deletedEntityIds: [],
  } as unknown as GraphSnapshot;
  const state = { preferences: DEFAULT_PREFERENCES, snapshot } as unknown as SessionState;
  const companion = mountCompanion({
    state,
    engine: questioning(),
    evidence: new EvidenceCache(client),
    ask: async () => ANSWER,
    stageParent: document.body,
    confirm: () => ({ show: vi.fn(), hide: vi.fn(), reportFailure: vi.fn() }) as unknown as
      ConfirmPanel,
    reflectShell: vi.fn(),
    onAnswered: vi.fn(),
    isSystemSurfaceOpen: () => false,
  });
  document.body.append(companion.panel.root);
  return { companion, requested, state };
}

/**
 * The page's own key handling over the mounted Companion, with a world that has nothing in it.
 *
 * Only what mounting touches is given. Escape reaches the Companion before anything the world
 * owns, so the rest of the world never has to answer.
 */
function withKeys(companion: MountedCompanion, state: SessionState) {
  const binding = {
    controls: { mode: 'converse' },
    mapOverlay: null,
    releaseFocusedAnchor: () => undefined,
  };
  return mountInputModes({
    env: { canvas: document.createElement('canvas'), systemAppearance: new EventTarget() },
    state,
    snapshot: state.snapshot,
    atlas: { binding },
    companion,
    chrome: { setMode: () => undefined },
    worldIndex: { closeSearch: () => false },
    firstUse: { prompt: () => null, observeMode: () => undefined },
    shellState: () => ({ primary: 'world', camera: 'ground', detailId: null }),
    dispatchShell: vi.fn(),
    setInputMode: () => undefined,
    reflectFirstUse: () => undefined,
  } as unknown as InputModeDependencies);
}

/** Escape pressed wherever the keyboard is, which is where the browser would send it. */
const pressEscape = (): void => {
  (document.activeElement ?? document.body).dispatchEvent(
    new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', bubbles: true }),
  );
};

describe('the Companion, mounted', () => {
  beforeEach(() => {
    document.body.replaceChildren();
    // happy-dom has no Pointer Lock, and `summon` releases a real one before it draws.
    Object.defineProperty(document, 'pointerLockElement', { value: null, configurable: true });
    (document as unknown as { exitPointerLock: () => void }).exitPointerLock = () => undefined;
    vi.spyOn(URL, 'createObjectURL').mockImplementation(() => 'blob:test/photograph');
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('restores the confirmed name and opens the cited photograph through the masked route', async () => {
    const { companion, requested } = mounted(() => new Response(new Blob(['photograph'], { type: 'image/jpeg' })));
    companion.summon();
    companion.controller.say(ANSWER.question);
    await settle();

    expect(utterance(companion.panel.root)).toBe('These photographs were taken at MIRELAND HALL.');

    companion.panel.root.querySelector<HTMLButtonElement>('.companion-evidence-chip')?.click();
    await vi.waitFor(() => expect(image(companion.panel.root)).not.toBeNull());
    expect(requested).toEqual([`https://exulanica.test/api/evidence/${SPAN_A}/masked`]);
    expect(image(companion.panel.root)?.getAttribute('src')).toBe('blob:test/photograph');
    expect(companion.panel.root.textContent).toContain('Taken on 2026-08-14.');

    back(companion.panel.root);
    expect(utterance(companion.panel.root)).toBe('These photographs were taken at MIRELAND HALL.');
    companion.dispose();
  });

  it('says a photograph the masked route refused was not shown', async () => {
    const { companion, requested } = mounted(() => new Response(
      JSON.stringify({ detail: 'deleted' }),
      { status: 410, headers: { 'content-type': 'application/json' } },
    ));
    companion.summon();
    companion.controller.say(ANSWER.question);
    await settle();

    expect(companion.panel.openEvidence()).toBe(true);
    await vi.waitFor(() => expect(companion.panel.root.textContent).toContain(say('evidence.unavailable')));
    expect(requested).toEqual([`https://exulanica.test/api/evidence/${SPAN_A}/masked`]);
    expect(image(companion.panel.root)).toBeNull();
    expect(companion.panel.root.textContent).toContain('this evidence was deleted');
    companion.dispose();
  });

  it('takes the photograph back before the Companion when Escape is pressed outside the panel', async () => {
    const { companion, state } = mounted(() => new Response(new Blob(['photograph'], { type: 'image/jpeg' })));
    const keys = withKeys(companion, state);
    companion.summon();
    companion.controller.say(ANSWER.question);
    await settle();
    companion.panel.root.querySelector<HTMLButtonElement>('.companion-evidence-chip')?.click();
    await vi.waitFor(() => expect(image(companion.panel.root)).not.toBeNull());

    // The keyboard left the panel: a click on the world, say. Escape now reaches the page first.
    (document.activeElement as HTMLElement | null)?.blur();
    expect(document.activeElement).toBe(document.body);
    pressEscape();
    expect(companion.panel.state()).toBe('open');
    expect(companion.panel.mode()).toBe('answer');
    expect(document.activeElement).toBe(companion.panel.root.querySelector('.companion-evidence-chip'));

    // With no photograph open, the same key from the same place sends the Companion away.
    (document.activeElement as HTMLElement | null)?.blur();
    pressEscape();
    expect(companion.panel.state()).not.toBe('open');
    keys.dispose();
    companion.dispose();
  });
});
