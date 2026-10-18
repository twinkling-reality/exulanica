// The record pages' states (a character's day r06, a decision r10, Compare r12; DESIGN's R-DAY-DECISION build sheet)
// from what the world view holds: its reads, the decision records it read and the moments read (R1), with the parts
// the pages draw from them: each moment's title in JOURNEY's moment words, its picture and its people's portraits
// (MOTION's, through history-host.ts). contextual-world.ts opens the pages, asks and answers keys; this says what
// each page shows.
import { askedAt, choiceRows, choicesLabel, choicesOver, decisionTitle, overLabel, resultLines, toldLabel, toldSections } from './decision-words.mjs';
import { COMPARE_WORDS, again as againName, answerTag, askLine, asking as askingWords, atMoment, atMost, cannotAskAgain, choseWords, compareMoments, explanation, laneMarks, nothingToAsk, resultOver, resultTitle, sameCounts, spentAsking, spentOf, useFor, whatEachChose } from './compare-words.mjs';
import { CHARACTER_WORDS, decidesPrint, modelRefusalWords, quoted } from './character-words.mjs';
import { deciderOf } from './character-group.mjs';
import { thingName } from './build-words.mjs';
import { momentTitle, targetObject } from './history-rows.mjs';
import { didWords, momentWords, saidWords, worldWhen } from './history-words.mjs';
import { MOMENT_FRAMING } from './moment-framing.mjs';
import { timeLeft } from './run-words.mjs';
import { worldTime } from './world-clock.mjs';
import { choiceAccount, parseDecisionEvents } from '../../../web/packages/app/src/decision-record.ts';
import type { RecordPictures } from './history-host.ts';

type Json = Record<string, any>;

/** How many of the version's newest moments a page reads to find its rows' and decisions' moments in. */
export const MOMENTS_READ = 200;

/** What the world view lends the record pages: its reader, its pictures and what it knows of each character. */
export interface RecordHost {
  /** `/world/versions/{version}`, and the world's query (`?world_id=…`). */
  readonly versionPath: string;
  readonly scope: string;
  read(path: string): Promise<any>;
  readonly pictures: RecordPictures;
  subjectView(row: Json): Json;
  modelOf(row: Json): Json;
  /** A person inside a sentence as History names them (J20): their tag's name, else "the" and their kind. */
  nameOf(id: string): string;
  personName(id: string): string | null;
  modelName(model: Json | null | undefined): string | null;
  /** The models read's latest decision under a request, or null. */
  latest(requestId: string): Json | null;
  compareModels(row: Json): Json[] | null;
  modelKey(model: Json | null): string;
  comparedDecisions(compare: Json, offer: Json | null): Json[];
  boundOf(decisions: Json[]): number;
  /** A made kind's label (J20), or null until it lands. */
  label(kind: unknown): string | null;
  /** The run on now, or null. */
  run(): Json | null;
  /** Whether this page may choose the character's model. */
  assignable(): boolean;
}

const sentenceCase = (text: string | null) => (text ? text.charAt(0).toUpperCase() + text.slice(1) : text);

/**
 * The moment a character's decision belongs to, from the moments read: the one this request made with them acting
 * first, or holding a line they said under it. No subject filter is served, so a moment someone else made is never
 * theirs, whatever request it names.
 */
export function ownMoment(moments: readonly Json[] | null | undefined, requestId: string | null | undefined, subjectId: string | null | undefined): Json | null {
  if (!requestId || !subjectId) return null;
  return (moments ?? []).find((moment) => (moment.request_id === requestId && moment.subjects?.[0] === subjectId)
    || (moment.said ?? []).some((line: Json) => line.request_id === requestId && line.by === subjectId)) ?? null;
}

export function recordStates(host: RecordHost) {
  /** Reads the moments and the version's placed things for a page (`showing`): kept on it, re-read with its rows. */
  async function readMoments(showing: Json): Promise<void> {
    const [moments, version] = await Promise.all([
      host.read(`${host.versionPath}/history/moments${host.scope}&limit=${MOMENTS_READ}&recipe=${encodeURIComponent(MOMENT_FRAMING.recipe)}`).catch(() => null),
      showing.things ? null : host.read(`${host.versionPath}${host.scope}`).catch(() => null),
    ]);
    if (moments) {
      showing.moments = moments.moments ?? [];
      // Where the read stopped short of the oldest moment, a choice older than its oldest moment is not known to have
      // made none (R5e): it never folds.
      const ticks = showing.moments.map((moment: Json) => moment.tick).filter(Number.isSafeInteger);
      showing.momentsFrom = moments.more && ticks.length ? Math.min(...ticks) : moments.more ? Number.POSITIVE_INFINITY : null;
    }
    if (version) showing.things = new Map((version.things ?? []).map((thing: Json) => [thing.thing_id, thing]));
  }

  /** The names a moment's words take, as History names them: people as their tags do, placed things as build mode. */
  function names(showing: Json) {
    const thingOf = (id: unknown) => (typeof id === 'string' && showing.things?.has(id) ? thingName(showing.things.get(id), host.label) : null);
    return {
      subject: (id: string) => host.nameOf(id),
      placed: () => null,
      thing: (id: string) => thingOf(id),
      place: (place: Json) => thingOf(place?.thing_id),
      target: (target: Json) => thingOf(targetObject(target?.target_id)),
    };
  }

  /** The line a character said under a request: from the said events read, else from its moment. */
  function lineOf(showing: Json, requestId: string, subjectId: string, moment: Json | null): { line: string; to: string | null } | null {
    const spoken = (showing.events ?? []).find((event: Json) => event.event_kind === 'said' && event.subject_id === subjectId && event.document?.thing?.request_id === requestId);
    if (typeof spoken?.document?.thing?.line === 'string') return { line: spoken.document.thing.line, to: spoken.document.thing.to ?? null };
    const said = (moment?.said ?? []).find((line: Json) => line.request_id === requestId && line.by === subjectId);
    return typeof said?.line === 'string' ? { line: said.line, to: (moment!.subjects ?? []).find((id: string) => id !== subjectId) ?? null } : null;
  }

  return {
    readMoments,

    /** Whether a row of What Teo did may fold with the same choice beside it (R5e): its decision made no moment of
     * Teo's own in the moments read, and is not older than what that read covers. Nothing folds before it answers. */
    foldable(showing: Json, row: Json): boolean {
      if (!Array.isArray(showing.moments) || !Number.isSafeInteger(row.tick)) return false;
      if (showing.momentsFrom !== null && showing.momentsFrom !== undefined && row.tick < showing.momentsFrom) return false;
      return ownMoment(showing.moments, row.requestId, showing.row.scene.id) === null;
    },

    /** A row of What Teo did, filled from its moment: the title in the moment words, the line said, its picture. A
     * choice with no moment says what Teo did in the past ("Waited", R5e), else keeps its words, and draws no
     * picture tile. */
    dayRow(showing: Json, row: Json): Json {
      const subjectId = showing.row.scene.id;
      const moment = row.heard ? null : ownMoment(showing.moments, row.requestId, subjectId);
      if (!moment) {
        const did = row.heard ? null : row.did;
        // didWords reads the target's name as a place for a going and as a thing in hand for the hands' kinds.
        const named = did?.target ? names(showing).target(did.target) : null;
        const title = did?.kind ? didWords({ kind: did.kind, to: named, thing: named, activity: did.target?.activity ?? null, withName: did.with ? host.nameOf(did.with) : null }) : null;
        return title ? { title } : {};
      }
      const said = lineOf(showing, row.requestId, subjectId, moment);
      return { moment: true, title: sentenceCase(momentTitle(moment, names(showing))), said: said ? quoted(said.line) : null, picture: host.pictures.momentNow(moment as never) };
    },

    /** The day page's who column beyond what the page reads itself: portrait, what they are doing, who decides. */
    day(showing: Json, view: Json, modelsRead: boolean): Json {
      const who = view.who, run = host.run();
      const deciding = deciderOf({ decider: view.decider ?? null, model: view.model ?? null });
      return {
        portrait: host.pictures.portraitNow(showing.row.scene.id),
        doing: view.doing ?? null,
        decider: view.decider ?? null,
        // A routine keeps the Run section's line, which says how a model could decide.
        ...(modelsRead && deciding !== 'routine' ? { decides: decidesPrint(who, { decider: deciding, model: view.model ?? null }) } : {}),
        running: run && view.model ? decidesPrint(who, { decider: 'model', model: view.model, left: timeLeft(run.endsBy, Date.now()) }) : null,
      };
    },

    /** A decision (frame 10) from its record, its moment and the said events; `order` and `canCompare` are the page's. */
    decision(showing: Json, decision: Json, { earlier = false, later = false, canCompare = false } = {}): Json {
      const view = host.subjectView(showing.row), who = view.who, subjectId = showing.row.scene.id;
      const blank = { over: '', title: '', model: null, done: null, verdict: null, toldLabel: toldLabel(who), told: decision.failure ? [] : null,
        choicesLabel: '', choices: [], earlier, later, record: null, failure: decision.failure, canCompare, ground: decision.ground ?? host.pictures.still() };
      const detail = decision.detail;
      if (!detail) return blank;
      const request = detail.request, receipt = detail.decision, context = request.context ?? null;
      const events = parseDecisionEvents({ events: showing.events ?? [] }).events;
      const latest = host.latest(decision.requestId);
      // The choice account's verdict; a record it cannot read says nothing of what came of it.
      let verdict: Json | null = null;
      try { verdict = choiceAccount(detail, latest as never, events).verdict; } catch { verdict = null; }
      const consumed = events.find((event: Json) => event.kind === 'decision_applied' && event.requestId === decision.requestId)?.tick ?? latest?.consumedTick ?? null;
      const start = view.facts?.startMinute ?? null;
      const moment = ownMoment(showing.moments, decision.requestId, subjectId);
      const said = lineOf(showing, decision.requestId, subjectId, moment);
      const named = names(showing);
      const to = said?.to ? named.subject(said.to) : null;
      const proposal = receipt?.proposal ?? null, provider = receipt?.provider ?? null, config = request.provider_config ?? null;
      const choices = choiceRows(context, proposal?.label ?? null);
      const result = resultLines({ verdict, doneAt: consumed === null ? null : worldTime(consumed, start)?.hhmm ?? null,
        latencyMs: provider?.latency_ms ?? null, costUsd: provider?.cost_usd ?? null, costKnown: provider?.cost_known === true });
      const at = askedAt(request.base_tick, start);
      const applied = (showing.events ?? []).find((event: Json) => (event.event_kind === 'decision_applied' && event.document?.request_id === decision.requestId)
        || (event.event_kind === 'said' && event.document?.thing?.request_id === decision.requestId));
      // Who decided (T7): a model's request names its provider; a person playing or an outside program, its kind.
      const origin = config?.provider ? 'model' : config?.kind ?? applied?.document?.origin ?? applied?.document?.thing?.decider ?? moment?.decider?.kind ?? null;
      const actor = named.subject(subjectId);
      const decider = origin === 'model' || origin === 'person' || origin === 'external' ? origin : null;
      return { ...blank,
        // The moment it belongs to, where the moments read has it: "06:52 · Day 1 · Teo met Ines at the bench".
        over: moment ? [worldWhen(at), sentenceCase(momentTitle(moment, named))].filter(Boolean).join(' · ')
          : overLabel({ at, who, said: Boolean(said), to: said?.to ? host.personName(said.to) : null }),
        title: decisionTitle({ line: said?.line ?? null, chose: proposal?.label ?? null }) || showing.did?.[decision.rowIndex]?.what || '',
        model: config ? host.modelName({ provider: config.provider, model_id: config.model_id }) ?? config.model_id ?? null : null,
        done: result.done, verdict: result.verdict, told: toldSections(context, who),
        personality: context?.character ? { name: context.character.name ?? null, about: context.character.about ?? null } : null,
        choicesLabel: choicesLabel(who, choices.length), choices,
        record: decision.record ? JSON.stringify({ request, decision: receipt }, null, 2) : null,
        // What Teo decided in the moment words, and what happened: the line said, or the action where none was.
        decided: said ? sentenceCase(momentWords({ kind: to ? 'spoke' : 'spoke_to_all', place: null, to: null, activity: null, thing: null, firstLine: said.line }, actor, to ? [to] : []))
          : moment ? sentenceCase(momentTitle(moment, named)) : null,
        said: said ? saidWords(who.title ?? who.start, said.line) : null,
        action: !said && moment ? sentenceCase(momentTitle(moment, named)) : null,
        decider,
        // What a person playing them was shown, or what their model or outside program was told (DESIGN, WORDS.md R5b, R5c).
        toldLabel: toldLabel(who, decider),
        answered: origin === 'model' && provider ? { latencyMs: provider.latency_ms ?? null, costUsd: provider.cost_usd ?? null, costKnown: provider.cost_known === true } : null,
        choicesHeading: choicesOver(who),
        picture: moment ? host.pictures.momentNow(moment as never) : null,
        portraits: (moment?.subjects ?? [subjectId, said?.to].filter(Boolean)).map((id: string) => ({ name: named.subject(id), url: host.pictures.portraitNow(id) })),
      };
    },

    /** Compare's question (frame 12a), in the right column of the character's page. */
    compare(showing: Json, who: Json): Json {
      const compare = showing.compare;
      const models = host.compareModels(showing.row);
      const model = models?.[compare.focus] ?? null;
      const held = model ? compare.offers.get(host.modelKey(model)) : null;
      const offer = held?.offer ?? null;
      const decisions = host.comparedDecisions(compare, offer);
      const recorded = decisions.at(-1)?.model ?? null;
      const recordedName = recorded ? host.modelName({ provider: recorded.provider, model_id: recorded.modelId }) ?? recorded.modelId : host.modelOf(showing.row).model?.name ?? '';
      const most = host.boundOf(decisions);
      const note = offer?.refusal ? modelRefusalWords(offer.refusal, who) : held?.failed ? CHARACTER_WORDS.askFailed : null;
      // Nothing to ask of any model (C4): none offered, or every one refused; the line stands alone.
      const single = compare.single !== null;
      const offered = (offer?.decisions ?? []).filter((decision: Json) => !single || decision.requestId === compare.single);
      const nothing = !offer || offer.refusal || decisions.length ? null
        : offered.length || single ? cannotAskAgain(who, single) : nothingToAsk(who);
      return {
        nothing,
        big: offer && decisions.length ? askLine(who, decisions.length, compare.single !== null) : '',
        explain: offer && decisions.length ? explanation(who, recordedName) : '',
        choices: models ? models.map((item) => ({ model: item, current: false })) : null,
        focus: compare.focus,
        figure: offer && decisions.length ? atMost(most) : null,
        asking: false,
        note,
        canStart: Boolean(offer && decisions.length && !offer.refusal),
      };
    },

    /** Compare (frame 12b): what each model chose, on History's line; while the asks run, how far they are. */
    comparison(showing: Json): Json {
      const comparison = showing.comparison, view = host.subjectView(showing.row), who = view.who;
      const { other, single, focus, asking } = comparison;
      const moments = compareMoments(comparison.decisions, comparison.answers);
      const start = view.facts?.startMinute ?? null;
      const at = (moment: Json | null | undefined) => (moment ? worldTime(moment.tick, start) : null);
      const first = at(moments[0]), last = at(moments.at(-1));
      const recordedName = comparison.recordedName;
      const otherName = other.name;
      const moment = moments[focus] ?? null;
      // Who a line was said to is in the decision's own options, read once a moment.
      const saidTo = (requestId: string, chose: string | null) => {
        const option = (comparison.details.get(requestId)?.request?.context?.options ?? []).find((item: Json) => item.label === chose);
        return option?.addressee_id ? host.personName(option.addressee_id) : null;
      };
      const words = (requestId: string, answer: Json) => (answer.asked || answer.recorded
        ? choseWords({ chose: answer.chose, line: answer.line, to: answer.line ? saidTo(requestId, answer.chose) : null }) ?? '' : COMPARE_WORDS.notAsked);
      const step = Math.max(1, Math.ceil(moments.length / 4));
      const times = moments.flatMap((item: Json, index: number) => ((index % step === 0 || index === moments.length - 1) && at(item) ? [{ index, text: at(item)!.hhmm }] : []));
      return {
        over: resultOver({ who, count: moments.length, from: first?.hhmm ?? null, to: last?.hhmm ?? null, day: first?.day ?? null }),
        title: resultTitle(who, moments.length, single),
        sub: single ? COMPARE_WORDS.sameMoment(who) : COMPARE_WORDS.sameMoments(who),
        spent: spentAsking(spentOf(moments)),
        moment: moment ? {
          label: atMoment(at(moment)?.hhmm ?? null, focus, moments.length),
          rows: [
            { model: recordedName, again: false, what: words(moment.requestId, { ...moment.recorded, recorded: true }), tag: answerTag({ recorded: true }) },
            { model: otherName, again: false, what: words(moment.requestId, moment.other), tag: answerTag(moment.other) },
            { model: againName(recordedName), again: true, what: words(moment.requestId, moment.again), tag: answerTag(moment.again) },
          ],
        } : null,
        eachChose: single ? [] : whatEachChose({ recordedName, otherName, other: sameCounts(moments, 'other'), again: sameCounts(moments, 'again'), count: moments.length, againRefused: comparison.againRefused }),
        lanes: single ? [] : [
          { name: recordedName, faint: false, marks: laneMarks(moments, 'recorded') },
          { name: otherName, faint: false, marks: laneMarks(moments, 'other') },
          { name: againName(recordedName), faint: true, marks: laneMarks(moments, 'again') },
        ],
        times: single ? [] : times,
        focus,
        use: !asking && host.assignable() && !comparison.busy ? useFor(otherName, who) : null,
        // Every moment on the line, oldest first, each different answer under its branch; a single moment draws none.
        ...(single ? {} : { line: moments.map((item: Json) => ({ time: at(item)?.hhmm ?? null, asked: item.other.asked, different: item.other.asked && item.other.same === false ? words(item.requestId, item.other) : null })) }),
        // While the asks run, how far they are in the answer's place, with [Esc] Stop alone (C2).
        asking: asking ? askingWords(asking.done, asking.total, asking.spent, comparison.most) : null,
        ground: comparison.ground ?? host.pictures.still(),
      };
    },
  };
}
