/**
 * The Companion: the presence on the stage, the controller that holds the turn, and the panel
 * that renders it.
 *
 * The three are one surface because they are one conversation. The controller decides what is
 * being said, the panel is how it is read, and the stage is the operational state of the thing
 * saying it; a turn that advanced without the stage following would be a presence that looks
 * settled while the graph is unresolved.
 *
 * **This module holds no credential.** `askQuestion` is the read half of the conversation and it
 * arrives here as a function. The composition root is the only place that constructs the client
 * that function calls, exactly as it is the only place that constructs the write gate.
 */

import type { CompanionSession, PersistedMemory, Turn } from '@exulanica/companion-runtime';
import { companionAppearanceConfiguration } from '@exulanica/presentation';

import { MemoryUnavailable, rememberedAsAnswer } from '../companion-memory-api.js';

import { createCompanionController, type CompanionController } from '../companion.js';
import type { CompanionAnswer, CompanionProposal, ModelCall } from '../companion-ask-api.js';
import type { EvidenceCache } from '../evidence.js';
import { say } from '../ui/copy.js';
import {
  worldStyleProposalInbox,
  worldStyleProposalOutcomes,
  type WorldStyleProposalOutcome,
} from '../world-style-proposals.js';
import { buildCompanionEncounter, type CompanionEncounter } from '../ui/companion-encounter.js';
import { resolveCompanionPlacement } from '../ui/companion-placement.js';
import { buildCompanionStage, type CompanionStage } from '../ui/companion-stage.js';
import type { ConfirmPanel } from '../ui/confirm.js';
import type { SessionState } from './session-state.js';

export interface CompanionDependencies {
  readonly state: SessionState;
  /** The turn engine, which outlives a mount and is told about the new graph rather than rebuilt. */
  readonly engine: CompanionSession;
  readonly evidence: EvidenceCache;
  /** The read half of the conversation. The root holds the credential this needs. */
  readonly ask: (question: string) => Promise<CompanionAnswer>;
  /**
   * What this person has already been asked and told, from `/companion/memory`.
   *
   * Null is a fact rather than an absence to paper over: either nothing is stored, or the read
   * failed. The root knows which and says which; what this file does with null is the same
   * either way, which is start with an empty memory rather than pretend.
   *
   * Passed in already resolved rather than as a loader, because the engine is built before this
   * mount runs and a mount that awaited would leave the stage empty while it did. The root loads
   * it beside `GET /graph` and hands over whatever arrived.
   *
   * **Optional, and undefined is not the same as null.** `main.ts` is the composition root and is
   * owned by several concurrent branches at once, so this one ships the wiring for it as
   * `docs/patches/companion-memory-main.patch` rather than editing it, exactly as
   * `companion-question-main.patch` did before it. Until that patch is applied the host has not
   * opted in, and a host that has not opted in gets the behaviour it had: an empty memory and no
   * write-back. Not a silent default that half works.
   */
  readonly persistedMemory?: PersistedMemory | null;
  /**
   * Keep an answer that has just been drawn. Resolves when it is stored, rejects when it is not.
   *
   * The rejection is not swallowed here and it does not reach the answer either: it is drawn
   * under the answer as its own sentence. A durability failure is not an answer failure, and the
   * answer on the screen is still correct and still cited.
   *
   * Absent on a host that has not opted in, and absent means the write-back hook is never
   * REGISTERED rather than registered and doing nothing. The difference matters: a registered
   * no-op would make "this answer was not kept" unreportable, because there would be nothing to
   * fail.
   */
  readonly rememberAnswer?: (answer: CompanionAnswer) => Promise<void>;
  /**
   * Read one utterance as a request to change how the world looks, before asking about it.
   *
   * The read half of the conversation could already answer a question. This is the one thing
   * the Companion may DO, and it arrives here as a function for exactly the reason `ask` does:
   * the composition root is the only place that holds a credential.
   *
   * **Optional, and a host that has not opted in behaves as it did.** Absent means every
   * utterance goes straight to `ask`, which is what happened before this path existed. Not a
   * registered function that returns "question" for everything: that would make "this build
   * cannot propose" and "this sentence was a question" the same observation.
   */
  readonly proposeAppearance?: (utterance: string) => Promise<CompanionProposal>;
  /** The element the presence draws into. Created by the root, because the world shows through it. */
  readonly stageParent: HTMLElement;
  /**
   * The confirmation surface, read late.
   *
   * A staged proposal is rendered by the write path, and the write path needs this stage to
   * report a pending commit on. The cycle is real and was a pair of mutually visible closures
   * before the split; reading one of the two late is what keeps it a cycle rather than a copy.
   */
  readonly confirm: () => ConfirmPanel;
  readonly reflectShell: () => void;
  /** One more step of first-use guidance has been earned by an answer. */
  readonly onAnswered: () => void;
  /** A system surface must not summon the Companion out from behind itself. */
  readonly isSystemSurfaceOpen: () => boolean;
}

export interface MountedCompanion {
  readonly stage: CompanionStage;
  readonly panel: CompanionEncounter;
  readonly controller: CompanionController;
  /** Push the presence appearance the current preferences describe. */
  applyAppearance(): void;
  /** Move the presence to whatever the current turn implies. */
  reflectTurnState(turn: Turn | null): void;
  summon(): void;
  dismiss(): void;
  /** Summon if away, dismiss if here. The key and the renderer verb both land here. */
  toggle(): void;
  dispose(): void;
}

/**
 * Stop the presence that a previous mount left on the field.
 *
 * Separate from `mountCompanion` because it has to run on the empty-world path too, where no new
 * presence is built at all: an in-session withdrawal can arrive after a populated world was
 * mounted, and a field left live offscreen keeps its frame loop and its observers.
 */
export function disposeCompanionStage(state: SessionState): void {
  state.mountedCompanionStage?.dispose();
  state.mountedCompanionStage = null;
}

/**
 * The live outcome subscription, at module scope because its lifetime is the application's.
 *
 * `SessionState` would be the tidier home and this module may not add a field to it. A module
 * binding is exactly as correct here: `mountCompanion` is called from one place, once per graph
 * mount, and what has to be true is that the previous mount's listener is gone before the next
 * one is added.
 */
let stopPreviousOutcomes: (() => void) | null = null;

export function mountCompanion(deps: CompanionDependencies): MountedCompanion {
  const { state } = deps;

  /*
   * The reload stops being amnesia here, and this is the whole of it.
   *
   * `interaction-model.md` 4.3 and 5.5 both say the Companion may never speak "within 7 days of a
   * Skip or 14 days of a Not sure on the same entity". Until this line those windows were held in
   * a page, so a fourteen-day window had never once survived a reload: the person who said "not
   * sure" and came back the next day was asked again, by a system whose own contract said it
   * would not.
   *
   * Folded against the mount's clock rather than a stored expiry, because a cooldown is a
   * duration from when the escape was taken and the browser is the only clock in this process.
   * `memoryFromPersisted` does the fold using `recordEscape` itself, so the durable path and the
   * live path cannot drift apart into two versions of the same arithmetic.
   */
  /** A remembered answer is put back once, on the first summon. See `summon`. */
  let restored = false;
  const persisted = deps.persistedMemory ?? null;
  if (persisted !== null) {
    deps.engine.adoptPersistedMemory(persisted, Date.now());
  }

  const stage = buildCompanionStage({ parent: deps.stageParent });
  const appearance = (): ReturnType<typeof companionAppearanceConfiguration> =>
    companionAppearanceConfiguration({
      body: state.preferences.companionBody,
      color: state.preferences.companionColor,
      face: state.preferences.companionFace,
    });
  const applyAppearance = (): void => stage.setAppearance(appearance());
  applyAppearance();
  state.mountedCompanionStage = stage;

  function reflectTurnState(turn: Turn | null): void {
    if (turn === null || turn.intent === 'acknowledge') {
      stage.setState('resting');
      return;
    }
    if (turn.intent === 'enrich_relation') {
      stage.setState('attending');
      return;
    }
    // Identity, continuity, and contradiction turns all exist because the graph is unresolved.
    stage.setState('uncertain');
  }

  /*
   * Asking for the world to look different, at the seam where asking already happens.
   *
   * `askQuestion` is reached only when the turn engine has already decided this free text is
   * not an answer to an open question, which is exactly the gate a proposal needs: a person
   * typing "not sure" at a question about a photograph must never have that read as a request
   * to redecorate. So the classifier sits here and nowhere earlier.
   *
   * What comes back is a `CompanionAnswer` in every branch, because the encounter renders one
   * and because a proposal IS an answer to what was typed: a model wrote the sentence, the
   * provenance line says which model wrote it, and `onAnswerShown` keeps it, so a proposal is
   * recorded through the write-back that already exists rather than through a second one.
   */
  const proposalUtterances = new Map<string, string>();

  async function askOrPropose(utterance: string): Promise<CompanionAnswer> {
    const propose = deps.proposeAppearance;
    if (propose === undefined) return deps.ask(utterance);
    const outcome = await propose(utterance);
    if (outcome.classification === 'question') return deps.ask(utterance);
    if (outcome.proposal === null) return refusalAnswer(outcome);

    const originReference = `companion-utterance:${crypto.randomUUID()}`;
    proposalUtterances.set(originReference, utterance);
    const reached = worldStyleProposalInbox.submit({
      origin: 'companion',
      originReference,
      scope: { kind: 'global' },
      profile: {
        profileId: outcome.proposal.profileId,
        profileVersion: outcome.proposal.profileVersion,
        parameters: outcome.proposal.parameters,
      },
      referenceIds: outcome.proposal.referenceIds,
      modelId: outcome.proposal.modelId,
      promptVersion: outcome.proposal.promptVersion,
    });
    // No Atlas integration was mounted to receive it, which is a real state on the empty-world
    // path. Said out loud rather than left as a sentence describing a change nobody can find.
    if (!reached) {
      proposalUtterances.delete(originReference);
      return spokenAnswer(
      outcome, [outcome.proposal.spoken, say('proposal.unavailable')], 'proposed',
    );
    }
    return spokenAnswer(outcome, [outcome.proposal.spoken, say('proposal.staged')], 'proposed');
  }

  /*
   * What became of a proposal, kept through the write-back that already exists.
   *
   * A second remembered answer rather than a correction of the first, and the reason is the
   * wiring rather than the meaning: `rememberAnswer` resolves to nothing, so this module never
   * learns the id a correction would have to name, and `main.ts` is what holds the client. Two
   * rows is also the more honest record of two things that happened at two times.
   */
  /*
   * The previous mount's subscription, stopped here rather than in `dispose`.
   *
   * `mountCompanion` runs again on every graph mount, and the composition root's teardown is
   * `disposeCompanionStage`, which stops the stage and nothing else. So a `dispose` that nobody
   * calls is not a teardown: each mount added another listener to a module singleton, and after
   * three remounts one accepted proposal wrote three identical rows into durable memory. The
   * inbox in `appearance.ts` has the same shape and stops the previous one for the same reason.
   */
  stopPreviousOutcomes?.();
  const stopOutcomes = worldStyleProposalOutcomes.subscribe((outcome) => {
    const utterance = proposalUtterances.get(outcome.originReference);
    if (utterance === undefined) return;
    // 'previewed' is the state the proposal was already recorded in. Keeping it again would
    // write one row per stale-base recovery for a proposal nobody has decided about yet.
    if (outcome.kind === 'previewed') return;
    /*
     * Forgotten only when the decision is FINAL. A refused Apply is not final: the preview is
     * still open, the panel re-enables Apply, and a person who presses it again gets an
     * acceptance that this listener would otherwise have had no utterance to attach to. So a
     * refusal is recorded and remembered, and a later acceptance is recorded too, because two
     * things happened.
     */
    if (outcome.kind !== 'refused') proposalUtterances.delete(outcome.originReference);
    const remember = deps.rememberAnswer;
    if (remember === undefined) return;
    void remember(outcomeAnswer(utterance, outcome)).catch((error: unknown) => {
      const failure =
        error instanceof MemoryUnavailable
          ? error
          : new MemoryUnavailable(
              'unreachable',
              error instanceof Error ? error.message : String(error),
            );
      panel.noteMemoryFailure(`memory.notKept.${failure.kind}`, failure.detail);
    });
  });

  stopPreviousOutcomes = stopOutcomes;

  const controller = createCompanionController({
    companion: deps.engine,
    askQuestion: (question) => askOrPropose(question),
    onWorking: (working) => stage.setState(working ? 'working' : 'attending'),
    onAwaitingConfirmation: (proposalId, summary, utterance) => {
      // A staged proposal is still unconfirmed. It may not borrow the settled presentation.
      stage.setState('uncertain');
      deps.confirm().show(proposalId, summary, utterance);
    },
  });

  function dismiss(): void {
    controller.dismiss();
    stage.setState('resting');
    stage.hide();
    deps.reflectShell();
  }

  const panel = buildCompanionEncounter({
    onSelect: (optionId) => {
      controller.select(optionId);
      reflectTurnState(controller.current());
      deps.onAnswered();
    },
    onSubmit: (optionIds) => {
      controller.submit(optionIds);
      reflectTurnState(controller.current());
      deps.onAnswered();
    },
    onEvidence: (index) => {
      const handle = controller.evidenceAt(index);
      if (handle !== null) void deps.evidence.open(handle);
    },
    onSay: (text) => {
      controller.say(text);
      reflectTurnState(controller.current());
      deps.onAnswered();
    },
    },
    {
    /*
     * The write-back, and the ordering is the point rather than a detail.
     *
     * `companion-encounter.ts` fires this AFTER the answer is drawn and fires it unconditionally,
     * so keeping an answer cannot delay one reaching the screen and a host that refused to keep
     * one could not stop it arriving. That is why the hook is in the file that renders instead of
     * a microtask queued around `ask`: "after it is on the screen" is a fact at that call site
     * and would be an assumption about scheduling anywhere else.
     *
     * Not awaited, for the same reason. The person has their answer; storing it is this session's
     * problem and not theirs to wait on.
     */
    onAnswerShown: (answer) => {
      const remember = deps.rememberAnswer;
      if (remember === undefined) return;
      void remember(answer).catch((error: unknown) => {
        // Said under the answer rather than in place of it. A durability failure is not an
        // answer failure: what is on the screen is still correct and still cited, and what is
        // wrong is that the Companion will not have it next time. Both sentences are true and
        // the person is owed both.
        const failure =
          error instanceof MemoryUnavailable
            ? error
            : new MemoryUnavailable(
                'unreachable',
                error instanceof Error ? error.message : String(error),
              );
        panel.noteMemoryFailure(`memory.notKept.${failure.kind}`, failure.detail);
      });
    },
  });
  controller.attach(panel);

  /** Open the fixed visual-novel composition over the current memory backdrop. */
  function summon(): void {
    // Pointer Lock freezes clientX/clientY by specification. The SVG Companion follows the free
    // page pointer, so summoning releases the real browser lock instead of fabricating a cursor.
    if (document.pointerLockElement !== null) document.exitPointerLock();
    const placement = resolveCompanionPlacement({
      viewport: { width: window.innerWidth, height: window.innerHeight },
      // The reference deliberately treats the memory as backdrop, so it does not mirror the
      // reading order around a projected source rectangle.
      memoryBounds: null,
      preferredSide: state.preferences.companionSide,
    });
    panel.setPlacement(placement);
    controller.summon(Date.now());
    reflectTurnState(controller.current());
    /*
     * The reload keeps the last answer, which is the visible half of all of this.
     *
     * Once per mount and only before this person has asked anything, so a remembered answer never
     * draws over a live one and never comes back after they moved on. `restoreAnswer` rather than
     * `showAnswer` on purpose: a restored answer is not a new answer, and storing it again on
     * every summon would write one row per page load of a conversation that happened once.
     */
    if (!restored && controller.answer() === null) {
      restored = true;
      const last = deps.engine.lastAnswer;
      // Through the controller, never straight at the panel: `evidenceAt` resolves a chip
      // against the controller's own held answer, so a restored answer the controller does
      // not know about renders chips that open nothing.
      if (last !== null) controller.restoreAnswer(rememberedAsAnswer(last));
    }
    stage.show();
    deps.reflectShell();
  }

  // X and right click reach this through the renderer controls, so the verb observes the same
  // enabled/disabled boundary as movement and interaction instead of bypassing system surfaces.
  function toggle(): void {
    // A system surface must not summon the Companion out from behind itself. This used to fall
    // out of disabling the controls wholesale; it is now stated where the policy actually lives.
    if (deps.isSystemSurfaceOpen()) return;
    if (panel.state() === 'open') {
      dismiss();
      return;
    }
    summon();
  }

  return {
    stage,
    panel,
    controller,
    applyAppearance,
    reflectTurnState,
    summon,
    dismiss,
    toggle,
    dispose: () => {
      stopOutcomes();
      if (stopPreviousOutcomes === stopOutcomes) stopPreviousOutcomes = null;
      disposeCompanionStage(state);
    },
  };
}

/**
 * A proposal, an outcome, or a refusal, shaped as the answer the encounter renders.
 *
 * **Every field below is what actually happened, and three of them are deliberately empty.**
 *
 * `evidence` is empty. The proposal names topology source slots, and a chip opens an EVIDENCE
 * SPAN through `/evidence/{span}/masked`: the two are joined on the server and turning one into
 * the other is a second authorized request. An answer that offered chips resolving to nothing
 * would be worse than one that offers none, so this offers none.
 *
 * `abstained` is null because nothing was abstained from. A refusal here is not an abstention:
 * an abstention says the library cannot answer, and this says the reviewed design cannot make
 * the change. Reporting one as the other would score a refusal under M3 as though a question had
 * gone unanswered.
 *
 * `deterministic` and `repaired` are false because neither concept applies. The answer validator
 * does not run on this path: there is no packet to check a claim against, because no claim about
 * the library is being made.
 */
function spokenAnswer(
  outcome: CompanionProposal,
  sentences: readonly string[],
  composed: 'proposed' | 'refused',
): CompanionAnswer {
  const calls = outcome.calls;
  return {
    question: outcome.utterance,
    clauses: sentences
      .filter((text) => text.trim().length > 0)
      .map((text) => ({ text, type: 'meta' as const, citations: [] })),
    text: sentences.filter((text) => text.trim().length > 0).join(' '),
    abstained: null,
    deterministic: false,
    repaired: false,
    evidence: [],
    provenance: {
      composed,
      // The identifier that DREW it, out of the response body. Null when no draft call
      // returned, which is the case a configuration-derived value would report wrongly.
      servedModel: draftingModel(calls),
      plannedBy: calls[0]?.servedModel ?? null,
      latencyMs: calls.reduce((total, call) => total + call.latencyMs, 0),
      usedFallback: calls.some((call) => call.usedFallback),
    },
    promptVersion: outcome.promptVersion,
    calls,
  };
}

/**
 * The refusal, in reviewed words, with the server's own detail under it where it has one.
 *
 * The reviewed sentence is chosen by code and comes first, because it is the one this product
 * is accountable for. `not_in_catalogue` is the exception worth naming: its detail is the
 * model's own short account of what was asked for and could not be done, which is more useful
 * to the person than any general sentence, so it is shown too.
 *
 * `composed` is `refused` rather than `discarded`, and the difference is not pedantry: the
 * `discarded` sentence says "what it wrote was not supported by the evidence", and on this path
 * there is no evidence and no search. What happened is that the reviewed design has no such
 * control, and the model that read the request is named for having read it.
 */
function refusalAnswer(outcome: CompanionProposal): CompanionAnswer {
  const refusal = outcome.refusal;
  if (refusal === null) {
    return spokenAnswer(outcome, [say('proposal.refused.not_drafted')], 'refused');
  }
  const spoken = say(`proposal.refused.${refusal.code}`);
  const detail = refusal.code === 'not_in_catalogue' ? refusal.detail : '';
  return spokenAnswer(outcome, [spoken, detail], 'refused');
}

/** What became of a proposal, as a remembered answer to the sentence that asked for it. */
function outcomeAnswer(utterance: string, outcome: WorldStyleProposalOutcome): CompanionAnswer {
  const spoken = say(`proposal.outcome.${outcome.kind}`);
  return {
    question: utterance,
    clauses: [{ text: spoken, type: 'meta', citations: [] }],
    text: `${spoken} ${outcome.detail}`.trim(),
    abstained: null,
    deterministic: false,
    repaired: false,
    evidence: [],
    // No model decided this. A person did, or the authority refused it, and a provenance line
    // naming a model over either would be naming the wrong author.
    provenance: {
      composed: 'none',
      servedModel: null,
      plannedBy: null,
      latencyMs: 0,
      usedFallback: false,
    },
    // The write-back requires one and the server bounds it to 64 characters. This says which
    // path recorded the row, which is the question somebody reading the table will have.
    promptVersion: 'proposal-outcome',
    calls: [],
  };
}

/**
 * The call that DREW the proposal, which is the last one rather than the first.
 *
 * The classifier goes first and the drafter second, and a refused draft is retried once, so the
 * last recorded call is the one whose output reached the person. Reading the first would name
 * the classifier, which decided what the sentence was and wrote none of it.
 */
function draftingModel(calls: readonly ModelCall[]): string | null {
  return calls.length > 1 ? (calls.at(-1)?.servedModel ?? null) : null;
}
