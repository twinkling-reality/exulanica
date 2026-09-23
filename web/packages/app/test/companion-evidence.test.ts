// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { CompanionSession, SelectionOutcome, Turn } from '@exulanica/companion-runtime';
import type { GraphSnapshot } from '@exulanica/graph-client';

import type { CompanionAnswer } from '../src/companion-ask-api.js';
import { mountCompanion } from '../src/composition/companion.js';
import type { SessionState } from '../src/composition/session-state.js';
import type { OpenedEvidence } from '../src/evidence.js';
import { DEFAULT_PREFERENCES } from '../src/preferences.js';
import { buildCompanionEncounter } from '../src/ui/companion-encounter.js';
import type { ConfirmPanel } from '../src/ui/confirm.js';
import { say } from '../src/ui/copy.js';

/**
 * Opening a citation draws the photograph inside the Companion, with the way back to the answer.
 *
 * The photograph is the masked view `EvidenceCache` reads. When it does not open, the Companion
 * says so with the server's reason and draws nothing in its place, because a stand-in picture
 * would claim the evidence exists and looks like that.
 */

const SPAN_A = '11111111-1111-4111-8111-111111111111';
const PLACE = '0190a000-0000-7000-8000-00000000000b';
const SHOWN: OpenedEvidence = { ok: true, url: 'blob:https://exulanica.test/photograph-a', type: 'image/jpeg' };
const DELETED: OpenedEvidence = { ok: false, reason: 'this evidence was deleted' };

const ANSWER: CompanionAnswer = {
  question: 'What does the sign say at Mireland Hall?',
  clauses: [{ text: 'The sign reads [place A].', type: 'historical', citations: ['TOKEN00001'] }],
  text: 'The sign reads [place A].',
  abstained: null,
  deterministic: false,
  repaired: false,
  evidence: [{
    token: 'TOKEN00001',
    uri: 'exulanica://blob/ni:///sha-256;aaaa/img',
    handle: SPAN_A,
    captureId: '33333333-3333-4333-8333-333333333333',
    capturedAt: '2026-08-14T10:20:00+00:00',
  }],
  names: { '[place A]': PLACE },
  provenance: {
    composed: 'model',
    servedModel: 'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B',
    plannedBy: 'Qwen/Qwen3-235B-A22B-Instruct-2507',
    latencyMs: 9800,
    usedFallback: false,
  },
  promptVersion: 'selection-6',
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

function answering(onEvidence: (index: number) => void = () => undefined) {
  const panel = buildCompanionEncounter({
    onSelect: () => undefined,
    onSubmit: () => undefined,
    onSay: () => undefined,
    onEvidence,
  });
  document.body.append(panel.root);
  panel.setState('open');
  panel.showAnswer(ANSWER);
  return panel;
}

const utterance = (root: HTMLElement): string =>
  root.querySelector('.companion-utterance')?.textContent ?? '';

describe('the photograph a citation opens', () => {
  beforeEach(() => document.body.replaceChildren());

  it('is drawn inside the Companion, dated, with the way back to the answer', async () => {
    const panel = answering();
    const read = pending();
    panel.showEvidence(read.opening, ANSWER.evidence[0]!.capturedAt);

    expect(panel.mode()).toBe('evidence');
    expect(panel.root.textContent).toContain(say('evidence.opening'));
    expect(panel.root.querySelector('img')).toBeNull();
    // The chip that was pressed is gone with the answer, so the way back holds the keyboard.
    expect(document.activeElement?.classList.contains('companion-evidence-back')).toBe(true);

    read.finish(SHOWN);
    await settle();
    const image = panel.root.querySelector<HTMLImageElement>('.companion-evidence-figure img');
    expect(image?.getAttribute('src')).toBe(SHOWN.ok ? SHOWN.url : '');
    expect(panel.root.textContent).toContain('Taken on 2026-08-14.');
    expect(panel.root.getAttribute('data-evidence')).toBe('shown');
    // The arrival redraws the face, and the way back still holds the keyboard.
    expect(document.activeElement?.classList.contains('companion-evidence-back')).toBe(true);

    panel.root.querySelector<HTMLButtonElement>('.companion-evidence-back')?.click();
    expect(panel.mode()).toBe('answer');
    expect(panel.root.querySelector('img')).toBeNull();
    expect(panel.root.querySelectorAll('.companion-evidence-chip')).toHaveLength(1);
  });

  it('that did not open is said with the server\'s reason, and nothing is drawn in its place', async () => {
    const panel = answering();
    panel.showEvidence(Promise.resolve(DELETED), ANSWER.evidence[0]!.capturedAt);
    await settle();

    expect(panel.root.querySelector('img')).toBeNull();
    expect(panel.root.querySelector('.companion-evidence-unavailable')?.textContent).toBe(
      say('evidence.unavailable'),
    );
    expect(panel.root.textContent).toContain('this evidence was deleted');
    // A date belongs to a photograph that is on the screen, and this one is not.
    expect(panel.root.textContent).not.toContain('Taken on');
    expect(panel.root.getAttribute('data-evidence')).toBe('unavailable');
  });

  it('drops the transport\'s status code from a refusal, keeping the server\'s sentence', async () => {
    const panel = answering();
    panel.showEvidence(
      Promise.resolve({ ok: false, reason: 'http_409: current viewer image is unavailable' }),
      null,
    );
    await settle();
    const detail = panel.root.querySelector('.companion-evidence-unavailable-detail')?.textContent;
    expect(detail).toBe('current viewer image is unavailable');
  });

  it('is not drawn once the person has gone back before it arrived', async () => {
    const panel = answering();
    const read = pending();
    panel.showEvidence(read.opening, null);
    panel.root.querySelector<HTMLButtonElement>('.companion-evidence-back')?.click();

    read.finish(SHOWN);
    await settle();
    expect(panel.mode()).toBe('answer');
    expect(panel.root.querySelector('img')).toBeNull();
    expect(panel.root.hasAttribute('data-evidence')).toBe(false);
  });

  it('closes on Escape before the Companion does, and E opens nothing over it', () => {
    const dismissed = vi.fn();
    const panel = buildCompanionEncounter(
      { onSelect: () => undefined, onSubmit: () => undefined, onSay: () => undefined, onEvidence: () => undefined },
      { onDismiss: dismissed },
    );
    document.body.append(panel.root);
    panel.setState('open');
    panel.showAnswer(ANSWER);
    panel.showEvidence(Promise.resolve(SHOWN), null);
    expect(panel.openEvidence()).toBe(false);

    panel.root.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(panel.mode()).toBe('answer');
    expect(dismissed).not.toHaveBeenCalled();

    panel.root.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(dismissed).toHaveBeenCalledTimes(1);
  });

  it('is closed by sending the Companion away, so summoning shows the answer again', () => {
    const panel = answering();
    panel.showEvidence(Promise.resolve(SHOWN), null);
    panel.setState('summon');
    panel.setState('open');

    expect(panel.mode()).toBe('answer');
    expect(utterance(panel.root)).toContain('The sign reads');
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

function mounted(opened: OpenedEvidence) {
  const snapshot = {
    entities: [{ entityId: PLACE, displayName: 'MIRELAND HALL', mergedInto: null }],
    deletedEntityIds: [],
  } as unknown as GraphSnapshot;
  const state = { preferences: DEFAULT_PREFERENCES, snapshot } as unknown as SessionState;
  const open = vi.fn(async () => opened);
  const companion = mountCompanion({
    state,
    engine: questioning(),
    evidence: { open } as never,
    ask: async () => ANSWER,
    stageParent: document.body,
    confirm: () => ({ show: vi.fn(), hide: vi.fn(), reportFailure: vi.fn() }) as unknown as
      ConfirmPanel,
    reflectShell: vi.fn(),
    onAnswered: vi.fn(),
    isSystemSurfaceOpen: () => false,
  });
  document.body.append(companion.panel.root);
  return { companion, open };
}

describe('the Companion, mounted', () => {
  beforeEach(() => {
    document.body.replaceChildren();
    // happy-dom has no Pointer Lock, and `summon` releases a real one before it draws.
    Object.defineProperty(document, 'pointerLockElement', { value: null, configurable: true });
    (document as unknown as { exitPointerLock: () => void }).exitPointerLock = () => undefined;
  });

  it('restores the confirmed name and opens the cited photograph through the masked read', async () => {
    const { companion, open } = mounted(SHOWN);
    companion.summon();
    companion.controller.say(ANSWER.question);
    await settle();

    expect(utterance(companion.panel.root)).toBe('The sign reads MIRELAND HALL.');

    companion.panel.root.querySelector<HTMLButtonElement>('.companion-evidence-chip')?.click();
    await settle();
    expect(open).toHaveBeenCalledWith(SPAN_A);
    expect(companion.panel.root.querySelector('.companion-evidence-figure img')?.getAttribute('src'))
      .toBe(SHOWN.ok ? SHOWN.url : '');
    expect(companion.panel.root.textContent).toContain('Taken on 2026-08-14.');

    companion.panel.root.querySelector<HTMLButtonElement>('.companion-evidence-back')?.click();
    expect(utterance(companion.panel.root)).toBe('The sign reads MIRELAND HALL.');
    companion.dispose();
  });

  it('says a photograph that did not open did not open', async () => {
    const { companion } = mounted(DELETED);
    companion.summon();
    companion.controller.say(ANSWER.question);
    await settle();

    expect(companion.panel.openEvidence()).toBe(true);
    await settle();
    expect(companion.panel.root.querySelector('img')).toBeNull();
    expect(companion.panel.root.textContent).toContain(say('evidence.unavailable'));
    companion.dispose();
  });
});
