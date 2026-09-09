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

import type { CompanionSession, Turn } from '@exulanica/companion-runtime';
import { companionAppearanceConfiguration } from '@exulanica/presentation';

import { createCompanionController, type CompanionController } from '../companion.js';
import type { CompanionAnswer } from '../companion-ask-api.js';
import type { EvidenceCache } from '../evidence.js';
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

export function mountCompanion(deps: CompanionDependencies): MountedCompanion {
  const { state } = deps;

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

  const controller = createCompanionController({
    companion: deps.engine,
    askQuestion: (question) => deps.ask(question),
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
    dispose: () => disposeCompanionStage(state),
  };
}
