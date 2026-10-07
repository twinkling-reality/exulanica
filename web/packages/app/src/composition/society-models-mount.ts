/**
 * Who decides for a saved world's people, mounted beside its inhabitants: the server's models read,
 * kept current as the drawn minute moves, and the owner's choice sent and read back.
 *
 * It reads once per simulated minute the page draws, never more often, and never while a read is
 * already out: a minute that moves during a read is read after it. It reads only while it is shown:
 * once a read says nobody here can be decided for by a model (a society whose engine takes no
 * owner's choice, such as a district's), the section stays hidden and a new minute reads nothing;
 * only a forced read, such as the one after a choice, asks again. A choice is recorded by the
 * server and then read back, so the section only ever says what the server holds.
 */

import { problemSentence, problemWords } from '../ui/words/problems.js';
import { ApiError } from '@exulanica/graph-client';
import type { Credentials } from '../config.js';
import {
  SocietyModelsClient, type ModelRef, type NamedModelRef, type SocietyModel, type SocietyModels,
} from '../society-models-api.js';
import { WorldModelsClient, type SignalRole } from '../world-models-api.js';
import {
  buildSocietyModels,
  choiceRefusalWords,
  choiceWords,
  decisionWordsFor,
  recordedWords,
  type ChoosablePerson,
} from '../ui/society-models.js';
import { buildSignalModels } from '../ui/world-signals-models.js';

/** What a choice came to: whether the server recorded it, and the words the panel says for it. */
export interface ChoiceOutcome {
  readonly recorded: boolean;
  readonly words: string;
}

/** Whose decider another surface asks Who decides to show, by role and the server's subject ids. */
export interface DecidesTarget {
  readonly role: 'people' | 'signals';
  readonly subjectIds: readonly string[];
}

/** Who runs one person now, for another surface (the thing card and the marks over people). */
export interface PersonMind {
  /** The model this host asks for them now, or null when their own routine decides. */
  readonly running: NamedModelRef | null;
  /** Who decides for them, in Who decides' own words. */
  readonly words: string;
}

/**
 * The model asked for a person now: the one chosen for them, unless this host asks no model or
 * not theirs (a refusal on the read or on their choice), when their own routine decides.
 */
function runningModel(view: SocietyModels, subjectId: string): NamedModelRef | null {
  if (view.hostRefusal !== null) return null;
  const choice = view.choices.find((held) => held.subjectId === subjectId);
  return choice === undefined || choice.refusal !== null ? null : choice.model;
}

export interface MountedSocietyModels {
  readonly root: HTMLElement;
  /**
   * Read again when `tick` is not the minute last read, or always with `force`. A null tick is a
   * world nobody lives in, where there is nobody to choose for and nothing is read.
   */
  refresh(tick: number | null, people: readonly ChoosablePerson[], force?: boolean): Promise<void>;
  /** A person's lines for the inspector: who decides for them, and their latest decision. */
  personDetails(subjectId: string): readonly (readonly [string, string])[];
  /**
   * Show who decides for these subjects of one role, chosen as a person chooses them: people
   * ticked, or the one traffic light selected. Returns how many it chose.
   */
  chooseFor(target: DecidesTarget): number;
  /**
   * Choose who decides for these people from another surface (the thing card), by the same path
   * as the panel's own action: what the server recorded, said in the panel's own words, after a
   * read begun after it.
   */
  decide(subjectIds: readonly string[], model: ModelRef | null): Promise<ChoiceOutcome>;
  /** The models the last read offered for people, or null before it or where none is chosen here. */
  models(): readonly SocietyModel[] | null;
  /** Who runs this person now, or null before the first read or where none is chosen here. */
  mindOf(subjectId: string): PersonMind | null;
  /** Every person a model is asked for now, by the same rule as `mindOf`. */
  runningModels(): ReadonlyMap<string, NamedModelRef>;
  dispose(): void;
}

/** What the traffic lights' card says: how many, and whether a model runs any of them. */
function signalSummary(view: SignalRole): { readonly count: number; readonly words: string } {
  const decided = view.choices.filter((choice) => choice.model !== null).length;
  return {
    count: view.subjects.length,
    words: decided === 0 ? 'Fixed timing' : `${decided} by a model you chose`,
  };
}

export function mountSocietyModels(options: {
  readonly credentials: Credentials;
  readonly world: { readonly worldId: string; readonly versionId: string };
  readonly client?: SocietyModelsClient;
  readonly worldClient?: WorldModelsClient;
  /** Called after each read, so an open inspector can say what changed. */
  readonly onRead?: () => void;
}): MountedSocietyModels {
  const abort = new AbortController();
  const worldClient = options.worldClient ?? (options.client === undefined
    ? new WorldModelsClient({ ...options.credentials, signal: abort.signal, worldId: options.world.worldId })
    : null);
  const client = options.client ?? (worldClient === null
    ? new SocietyModelsClient({ ...options.credentials, signal: abort.signal, worldId: options.world.worldId })
    : null);
  let view: SocietyModels | null = null;
  let signalView: SignalRole | null = null;
  let personRoleKey = 'society_decision';
  let people: readonly ChoosablePerson[] = [];
  let busy = false;
  /** What the last choice came to, and why the last read failed, each until the next. */
  let message = '';
  let failure = '';
  let signalMessage = '';
  let readTick: number | null | undefined;
  let wanted: number | null = null;
  let reading: Promise<void> | null = null;
  let again = false;
  let disposed = false;
  /** How many reads have begun, and the number of the latest begun that has ended. */
  let begun = 0;
  let ended = 0;

  const signals = buildSignalModels({ onChoose: (signalId, model) => void chooseSignal(signalId, model) });
  const section = buildSocietyModels({
    onChoose: (chosen, model) => { void choose(chosen, model); },
    signals: signals.root,
  });
  const render = () => {
    signals.render(signalView, busy, [signalMessage, failure].filter(Boolean).join(' '));
    section.setSignals(signals.root.hidden || signalView === null ? null : signalSummary(signalView));
    section.render({ view, people, busy, message: [message, failure].filter(Boolean).join(' ') });
  };

  async function read(tick: number | null): Promise<void> {
    readTick = tick;
    const number = ++begun;
    try {
      if (worldClient !== null) {
        const world = await worldClient.read(options.world.versionId);
        const person = world.roles.find((role) => role.subject === 'person');
        const signal = world.roles.find((role) => role.subject === 'signal');
        view = person?.subject === 'person' ? person.view : null;
        if (person?.subject === 'person') personRoleKey = person.key;
        signalView = signal?.subject === 'signal' ? signal : null;
      } else if (client !== null) {
        view = await client.read(options.world.versionId);
      }
      failure = '';
    } catch (error) {
      if (disposed) return;
      failure = `Who decides for them could not be read. ${problemSentence(error)}`;
    } finally {
      ended = Math.max(ended, number);
    }
    if (disposed) return;
    render();
    options.onRead?.();
  }

  /** Resolves once a read begun after this call has ended, or at once where nothing is read. */
  async function readAfterNow(): Promise<void> {
    const since = begun;
    while (!disposed && (wanted !== null || worldClient !== null) && ended <= since) {
      if (reading === null) await refresh(wanted, people, true);
      else await reading;
    }
  }

  async function refresh(tick: number | null, held: readonly ChoosablePerson[], force = false): Promise<void> {
    if (disposed) return;
    people = held;
    wanted = tick;
    render();
    if ((tick === null && worldClient === null) || (!force && tick === readTick)) return;
    // Hidden by what the server said: a new minute changes nothing a hidden section shows.
    if (!force && view !== null && section.root.hidden) return;
    if (reading !== null) { again = true; return; }
    reading = read(tick);
    try { await reading; } finally { reading = null; }
    if (again && !disposed) { again = false; await refresh(wanted, people, true); }
  }

  async function choose(chosen: readonly string[], model: ModelRef | null): Promise<ChoiceOutcome> {
    if (disposed) return { recorded: false, words: 'This world is no longer open.' };
    if (busy) return { recorded: false, words: 'Another choice is still being recorded. Try again in a moment.' };
    if (chosen.length === 0) return { recorded: false, words: 'Nobody was chosen, so nothing changed.' };
    busy = true;
    message = '';
    render();
    let recorded = false;
    try {
      if (worldClient !== null) await worldClient.choose(options.world.versionId, personRoleKey, chosen, model);
      else if (client !== null) await client.choose(options.world.versionId, chosen, model);
      recorded = true;
    } catch (error) {
      message = error instanceof ApiError
        ? choiceRefusalWords(error.code, error.message)
        : `The choice was not recorded. ${problemWords(error).next}`;
    } finally {
      busy = false;
    }
    // A read already out began before the choice: the words wait for one begun after it.
    await readAfterNow();
    if (recorded && !disposed) {
      section.clearPeople();
      // Said from the read that followed the choice, so it never names a model nobody asks.
      message = recordedWords(view, chosen, model);
      render();
    }
    return { recorded, words: message };
  }

  async function chooseSignal(signalId: string, model: ModelRef | null): Promise<void> {
    if (disposed || busy || worldClient === null || signalView === null) return;
    busy = true;
    signalMessage = '';
    render();
    try {
      await worldClient.choose(options.world.versionId, signalView.key, [signalId], model);
      signalMessage = 'Choice recorded. The scheduled time and active status below come from the server.';
      await refresh(wanted, people, true);
    } catch (error) {
      signalMessage = error instanceof ApiError
        ? choiceRefusalWords(error.code, error.message)
        : `The choice was not recorded. ${problemWords(error).next}`;
    } finally {
      busy = false;
      render();
    }
  }

  const statusTimer = worldClient === null ? null : window.setInterval(() => {
    if (!disposed && !section.root.hidden) void refresh(wanted, people, true);
  }, 30_000);

  return {
    root: section.root,
    refresh,
    decide(subjectIds, model) {
      if (view === null || !view.takesModelChoices) {
        return Promise.resolve({ recorded: false, words: 'Nobody here can be decided for by a model.' });
      }
      return choose(subjectIds, model);
    },
    models() {
      return view === null || !view.takesModelChoices ? null : view.models;
    },
    chooseFor(target) {
      if (target.role === 'people') return section.chooseFor(target.subjectIds);
      section.showRole('signals');
      const light = target.subjectIds.find((id) => signals.choose(id));
      return light === undefined ? 0 : 1;
    },
    mindOf(subjectId) {
      if (view === null || !view.takesModelChoices) return null;
      return { running: runningModel(view, subjectId), words: choiceWords(view, subjectId) };
    },
    runningModels() {
      const running = new Map<string, NamedModelRef>();
      if (view === null || !view.takesModelChoices) return running;
      for (const choice of view.choices) {
        const model = runningModel(view, choice.subjectId);
        if (model !== null) running.set(choice.subjectId, model);
      }
      return running;
    },
    personDetails(subjectId) {
      if (view === null || !view.takesModelChoices) return [];
      return [
        ['Decided by', choiceWords(view, subjectId)],
        ['Latest decision', decisionWordsFor(view, subjectId) ?? 'None yet.'],
      ];
    },
    dispose() {
      disposed = true;
      abort.abort();
      if (statusTimer !== null) window.clearInterval(statusTimer);
      section.root.remove();
    },
  };
}
