/**
 * The words. This is the only file in the workspace that authors user-facing prose.
 *
 * `atlas-core`, `companion-runtime` and `world-index` all emit message KEYS and refuse to write
 * sentences, and their docstrings say why: `companion-runtime`'s phrasing seam hands a model
 * keys and no consequences, and `atlas-core`'s rung labels record that the exact copy is OPEN in
 * `product-specification.md` P-2 while the constraint is fixed. Keeping the copy out of those
 * packages is what lets a wording change be a wording change rather than a behaviour change.
 *
 * The consequence is that somebody has to own the table, and it is this file.
 *
 * **An unmapped key renders as the key, visibly.** Not as a blank, and not as a plausible
 * fallback sentence generated from the key's own words. A blank hides a missing string, and a
 * generated sentence is prose nobody reviewed appearing in a product whose whole claim is that
 * its sentences are backed. A key on the screen is ugly and findable, which is the correct
 * trade.
 *
 * **One rule constrains the wording rather than taste.** `product-specification.md` 5.2: no
 * label may imply free movement in a region that does not have it, and no copy anywhere may say
 * private, on-device, encrypted, immutable, WORM, tamper-proof or regulatory-compliant. The rung
 * strings below are written against that and `copyIsHonest` asserts it in a test rather than
 * leaving it to review.
 */

/** Words no copy in this product may contain, whatever the sentence around them. */
export const FORBIDDEN_WORDS: readonly string[] = Object.freeze([
  'private',
  'on-device',
  'encrypted',
  'end-to-end',
  'immutable',
  'worm',
  'tamper-proof',
  'compliant',
]);

const COPY: Readonly<Record<string, string>> = Object.freeze({
  // Provenance rows. Band 1 renders the user's verbatim words when it has them; these are the
  // labels for a row that has none.
  'row.name': 'Name',
  'row.nameScope': 'Where that name applies',
  'row.note': 'Note',
  'row.relation': 'Relation',
  'row.sameEntityAs': 'The same as',
  'row.notThisClass': 'Not this kind of thing',
  'row.uncertain': 'Uncertain',

  // Band 4. Each one is a question the system is holding open, not an error.
  'unknown.name': 'Nobody has said what this is called.',
  'unknown.nameScope': 'It is not settled whether that name applies everywhere.',
  'unknown.relation': 'Nothing is recorded about how this relates to anything else.',
  'unknown.contradiction': 'Something recorded here contradicts something else recorded here.',
  'unknown.whenFirstSeen': 'It is not known when this was first seen.',
  'unknown.nothingOpen': 'Nothing about this is outstanding.',

  'method.unknown': 'method not recorded',
  'external.asOf': 'as of',
  'placeholder.unnamed': 'Unnamed',

  // What a proposal would do. Written from the operation, never from a model.
  'provenance.userEditedName': 'You are naming this.',
  'provenance.userMergedEntities': 'You are saying these are one thing.',
  'provenance.userSplitEntity': 'You are saying these are not one thing.',
  'provenance.userDeletedEntity': 'You are removing this from the index.',
  // The exact distinction that makes delete honest: the index entry goes, the photographs do not.
  'delete.originalMediaIsNotDeleted':
    'The original photographs are not deleted. Only what the index knows about them is.',

  // Empty states. Which zero it is, in words.
  'index.noMatches': 'Nothing here matches that.',
  'review.nothingNeedsAttention': 'Nothing needs attention.',

  // Why a control is present and not available. The reason is the information.
  'unavailable.mergedAway': 'This was merged into something else.',
  'unavailable.nothingToReview': 'There is nothing waiting for an answer here.',
  'unavailable.nothingToSplit': 'There is only one occurrence, so there is nothing to split off.',
  'unavailable.outOfMvpCut': 'This instance does not do that yet.',

  // -- what the Companion says -------------------------------------------------------------
  //
  // Every one of these is a QUESTION or an offer, never a statement of something the system
  // worked out for itself. Cross-capture identity is proposed and never asserted: open-set face
  // identification reaches about 60% at FAR = 0.01, so a sentence like "this is your sister"
  // would be wrong for two people in five and would put a guess into the account holder's own
  // record. The hedges here are load bearing, not politeness.
  'utterance.resolveIdentity': 'Is this the same person as the one in the earlier photograph?',
  'utterance.confirmContinuity': 'These two moments may show the same person. Do they?',
  'utterance.disambiguate': 'More than one person you have named could be this one. Which?',
  'utterance.nameScope': 'Should that name be used everywhere this person appears, or only here?',
  'utterance.relation': 'How do you know them?',
  'utterance.acknowledge': 'Noted.',

  'option.yesSamePerson': 'Yes, the same person',
  'option.noDifferentPeople': 'No, different people',
  'option.someoneIAlreadyNamed': 'Someone I have already named',
  'option.giveName': 'Give a name',
  'option.useADifferentName': 'Use a different name',
  'option.useNameEverywhere': 'Use it everywhere they appear',
  'option.keepNamePrivate': 'Only use it here',
  'option.keepWhatIToldYou': 'Keep what I told you',
  'option.acceptTheOtherReading': 'Use the other reading',
  'option.showBothMoments': 'Show me both moments',
  'option.showMeTheEvidence': 'Show me the photograph',

  'option.relation.family': 'Family',
  'option.relation.friend': 'A friend',
  'option.relation.colleague': 'A colleague',
  'option.relation.partner': 'A partner',
  'option.relation.met_through_someone': 'Someone I met through another person',

  // The four escapes. Worded so none of them reads as the wrong answer, because none of them is:
  // an escape is data about the question, and a user who feels judged for taking one stops
  // taking them and starts guessing.
  'escape.notSure': 'Not sure',
  'escape.skip': 'Skip',
  'escape.later': 'Later',
  'escape.wrongQuestion': 'That is the wrong question',

  // Availability semantics: an option that cannot be taken is still shown, with the reason.
  'unavailable.alreadyAssertedDistinct': 'You have said these are different people.',
  'unavailable.rejectedOnTheSameEvidence': 'You turned this down on the same photograph.',

  // Refusals. Each says what happened rather than apologising for it.
  'refused.couldNotParse': 'I could not tell what that meant.',
  'refused.noSubject': 'There is nothing here to attach that to.',
  'refused.noTurn': 'There is no open question.',
  'refused.notAMultiSet': 'That question takes a single answer.',
  'refused.nothingSelected': 'Nothing was selected.',
  'refused.subjectMissing': 'What that question was about is no longer in the graph.',
  'refused.tierNotOfferableHere': 'That change reaches too far to offer from here.',
  'refused.unavailable': 'That option is not available on this question.',
  'refused.unknownOption': 'That option is not on this question.',
  'refused.useSubmit': 'Choose everything that applies, then press Submit.',

  // -- what the Companion says when the words were a QUESTION rather than an answer ----------
  //
  // Free text on an open turn is parsed into an update proposal. When the parser finds nothing
  // to change, or when the open turn is an acknowledgement with nothing to attach a change to,
  // the words were a question about the library, and `POST /selection/ask` answers it. Every
  // sentence below is about the ASKING, never about what was found: what was found is written
  // by the server from the evidence and is rendered verbatim.
  'ask.working': 'Looking through your library.',
  'ask.emptyAnswer': 'The answer came back with nothing in it.',

  // A question that did not reach an answer. Four different facts, said as four sentences,
  // because "something went wrong" is the one reply that tells a person nothing they can act on.
  // The server's own detail is shown alongside these rather than replaced by them.
  'ask.failed.no_model': 'This instance is running without a model, so it cannot answer a question in words.',
  'ask.failed.unauthenticated': 'This session is no longer allowed to ask.',
  'ask.failed.refused': 'The question was refused.',
  'ask.failed.unreachable': 'The question did not reach the library.',

  // An answer that reached the screen and was not kept. Said out loud, and said UNDER the answer
  // rather than instead of it, because the two facts are separate: the answer is correct and
  // cited, and the Companion will not have it next time. A Companion that quietly forgot what it
  // was told to keep is the state this whole path exists to leave, and one that forgets without
  // saying so is worse than one that never offered to remember.
  //
  // Five kinds rather than one sentence, on the same argument as the four above: "something went
  // wrong" is the reply that tells a person nothing they can act on.
  'memory.notKept.unauthenticated': 'This session is no longer allowed to keep what it was told.',
  'memory.notKept.unknown_reference': 'That answer is no longer here to change.',
  'memory.notKept.refused': 'The library would not keep this answer.',
  'memory.notKept.unreadable': 'The library answered in a form this page could not read.',
  'memory.notKept.unreachable': 'This answer did not reach the library, so it is not kept.',
  // The one refusal that is ours rather than the server's, and it says so.
  'memory.notKept.incomplete':
    'This answer is not kept, because one of the photographs it cites could not be located and a '
    + 'later deletion of that photograph could not have reached it.',

  // Asking the world to look different. What the Companion says ABOUT a proposal, never the
  // proposal itself: the sentence describing the change is written by the model from the
  // reviewed catalogue and arrives as `spoken`, and this table does not get to improve it.
  //
  // The two sentences below frame it, and they carry the one fact a person needs and cannot see
  // from the sentence alone: nothing has happened yet, and where to go to make it happen or make
  // it stop.
  'proposal.staged':
    'Nothing has changed yet. Open Customize to look at it, then Apply it or throw it away.',
  'proposal.unavailable':
    'That change could not be put in front of you, so nothing was proposed and nothing changed.',

  // A request to change how the world looks that produced no proposal. Seven different facts,
  // and none of them is silence: somebody asked for something and the reply has to say what
  // happened to it. Only the first is a limit of the design rather than a failure, which is why
  // it is the only one phrased as a thing the product does not do rather than a thing that went
  // wrong.
  //
  // The server's own detail is shown alongside these rather than replaced by them, exactly as
  // it is for a question that did not reach an answer.
  'proposal.refused.not_in_catalogue':
    'The reviewed design does not have a way to change that, so nothing was proposed.',
  'proposal.refused.unregistered':
    'The proposed change named a design, a part, or a control that is not in the reviewed set, '
    + 'so it was refused and nothing changed.',
  'proposal.refused.out_of_range':
    'The proposed change fell outside what that control is allowed to be, so it was refused '
    + 'rather than moved to the nearest value it could have had.',
  'proposal.refused.no_change':
    'That would leave the world exactly as it is, so there is nothing to show you.',
  'proposal.refused.unsupported_reference':
    'The proposed change did not name any of the photographs this world is drawn over, so there '
    + 'is nothing to review it against.',
  'proposal.refused.not_drafted':
    'That could not be turned into a change to this world, so nothing was proposed.',
  'proposal.refused.no_world':
    'There is no reviewed world design here yet, so there is nothing to propose a change to.',

  // What became of one, said the next time the Companion speaks and kept in its memory. The
  // world is what shows an applied change; these say which decision was recorded.
  'proposal.outcome.accepted': 'The change was applied to your world.',
  'proposal.outcome.discarded': 'The change was thrown away and your world is as it was.',
  'proposal.outcome.refused': 'The change was refused and your world is as it was.',
  'proposal.outcome.previewed': 'The change is waiting to be confirmed in Customize.',

  // The read half, which fails differently and costs something different. A question that cannot
  // be answered is a question; a memory that cannot be read is a Companion that has forgotten
  // somebody, and it will ask them things they have already answered.
  'memory.notLoaded': 'Earlier answers could not be loaded, so this Companion is starting fresh.',

  // The scored abstention categories, as labels for the answer the server already wrote. They
  // name the KIND of silence; the sentence itself stays the server's. evaluation-methodology.md
  // M3 keeps the three apart, because merging them lets a system that always declines score well.
  'abstention.UNANSWERABLE_NOT_CAPTURED': 'No photograph in the library matches that.',
  'abstention.UNANSWERABLE_AMBIGUOUS': 'That could be read more than one way.',
  'abstention.UNANSWERABLE_NOT_IN_MODALITY': 'Answering that would need something a photograph does not hold.',
  // The fourth is not about the library at all. It says the question never became a search, so
  // it must not borrow the wording of the first, which claims nothing matched.
  'abstention.UNANSWERABLE_NOT_UNDERSTOOD': 'That did not become a search, so nothing was looked at.',

  // Evidence behind an answer. A chip that cannot open says so instead of opening nothing.
  'answer.openEvidence': 'Open the photograph',
  'answer.evidenceNotLocated': 'This citation could not be located just now.',
  'answer.backToQuestion': 'Back to the question',

  // Who wrote the sentence, which is not always a model. When the composer's output fails
  // validation twice it is discarded and the answer is rendered from the query result instead;
  // naming the model on that answer would credit it with a sentence it did not write.
  'provenance.model': 'Answered by {model} in {duration}.',
  // A model read the question and no model wrote the answer. This is every abstention asked
  // through the interface: the browser sends no plan, so the planner always runs, and the
  // composer is never called on an empty packet. Saying "no model was asked" here was false.
  'provenance.search':
    '{model} read the question in {duration}. Nothing a model wrote is below: that is what the '
    + 'search itself found.',
  'provenance.modelOnFallback': 'Answered by the fallback model {model} in {duration}.',
  'provenance.discarded':
    '{model} was asked and answered in {duration}. What it wrote was not supported by the ' +
    'evidence, so this is the answer built from the search itself.',
  // The same outcome, with no model to name: a composer whose reply the endpoint truncated
  // raises before any result reaches the recorder, so the call that failed is not in the list.
  'provenance.discardedUnnamed':
    'A model was asked and took {duration}. What it wrote was not supported by the evidence, so '
    + 'this is the answer built from the search itself.',
  'provenance.none': 'No model was asked. This is what the search found.',
  // A model WAS asked and gave back something unusable. Saying "no model was asked" here would
  // be false, and saying anything about the search would be false too, because there was none.
  'provenance.unreadable': 'A model was asked and could not turn that into a search.',
  'provenance.unreadableNamed':
    '{model} read the question in {duration} and could not turn it into a search of your '
    + 'photographs.',
});

/**
 * A sentence from the table with its placeholders filled.
 *
 * The template lives in the table above, so the forbidden-claim assertion in `copy.test.ts`
 * walks it like every other string. A sentence assembled from fragments at the call site would
 * be prose this file does not own, which is the one thing it exists to prevent.
 */
export function fill(key: string, values: Readonly<Record<string, string>>): string {
  return say(key).replace(/\{(\w+)\}/g, (whole, name: string) => values[name] ?? whole);
}

/** The sentence for a key, or the key itself when nobody has written one. */
export function say(key: string): string {
  return COPY[key] ?? key;
}

/** Every key that has a sentence. Exported so a test can walk the whole table. */
export function everyPhrase(): readonly (readonly [string, string])[] {
  return Object.entries(COPY);
}
