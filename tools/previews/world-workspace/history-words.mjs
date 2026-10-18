// History's words (r23, the user's yes on 16 October; DESIGN's R23 build sheet, amended 08:36): every string the
// page shows, made from what the server served. The words of what happened are JOURNEY's catalog
// (journey-2026-10-14/HISTORY-MOMENTS-R1.md section 6, the sheet's section 9); the person's own changes are build
// mode's sentence kinds in History's "You" forms; money and time in WORDS.md's forms. A character by its name,
// never "it"; never a topic, a summary of a line, "simulated", or counts or money on a moment.

import { HISTORY } from './build-words.mjs';

export const PATH_WORDS = Object.freeze({
  history: 'History',
  madeFromWords: 'Made from your words',
  blankWorld: 'Started from a blank world',
  now: 'Now',
  personPlaying: 'By a person playing',
  outsideProgram: 'By an outside program',
  earlierLater: 'Earlier, later',
  openMoment: 'Open this moment',
  // A grouped changes dot, chosen (H15).
  openChanges: 'Open these changes',
  back: 'Back',
  openOnGitHub: 'Open on GitHub',
  chooseLine: 'Choose a line',
  seeDecision: 'See the decision',
  backToStory: 'Back to the story',
  askedAgain: 'Asked again',
  nothingYet: 'Nothing has happened here yet.',
  momentsFailed: "The world's moments could not be read. Try again.",
});

/** The head's GitHub line (sheet section 2): `words`, and whether it is a refusal (drawn in refusal ink). */
export const HEAD_WORDS = Object.freeze({
  noProject: 'Not kept in a project',
  localProject: 'Kept in a project on this computer, not on GitHub',
  starting: 'Starting a project…',
  putting: 'Putting it on GitHub…',
  unreachable: 'GitHub could not be reached. Your changes are kept here and sent when it answers.',
  refusals: Object.freeze({
    nothing_to_keep: 'Nothing to keep in a project yet: change something first.',
    world_unreadable: 'Not kept: the world could not be read. Try again.',
    too_many_projects: 'Not kept: this computer keeps as many projects as it can.',
    failed: 'Not kept: the project could not be started. Try again.',
  }),
});

const MONTHS = Object.freeze(['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']);
const SMALLEST = 0.0001;

/** Dollars as the workspace writes them: "$0.05", under a cent "$0.0042", "less than $0.0001", "$0". */
export function money(usd) {
  const value = Number(usd);
  if (!Number.isFinite(value) || value <= 0) return '$0';
  if (value < SMALLEST) return 'less than $0.0001';
  return value >= 0.01 ? `$${value.toFixed(2)}` : `$${value.toFixed(4)}`;
}

export function plural(count, noun, many) {
  return count === 1 ? `${count} ${noun}` : `${count} ${many ?? `${noun}s`}`;
}

export function possessive(name) {
  return `${name}'s`;
}

// -- Model names: a sentence holding one is a list of parts, plain text and `{ model }`, so the page keeps the
// name on one line wherever it falls (sheet section 6: a model's name never breaks).

/** A model's name inside a sentence's parts. */
export const modelPart = (name) => Object.freeze({ model: name });

/** A sentence's parts as plain text: what a reader hears and what the tests read. */
export function partsText(parts) {
  return parts.map((part) => (typeof part === 'string' ? part : part.model)).join('');
}

// -- Time: the world's clock for what the characters did, the person's clock for what the person did (sheet 3).

const pad = (n) => String(n).padStart(2, '0');

/** "09:44", in the reader's own time. */
function clockAt(at) {
  const date = new Date(at);
  return `${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function sameDay(a, b) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

/** The day something was done: "Today", "Yesterday", "13 Oct" (H4). */
export function dayHeading(at, now) {
  const date = new Date(at), today = new Date(now);
  if (sameDay(date, today)) return HISTORY.today;
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  if (sameDay(date, yesterday)) return 'Yesterday';
  return `${date.getDate()} ${MONTHS[date.getMonth()]}`;
}

/** When the person did something, in their own time: "Yesterday · 21:40", "13 Oct · 21:40", today "08:30". */
export function personWhen(at, now) {
  const heading = dayHeading(at, now);
  return heading === HISTORY.today ? clockAt(at) : `${heading} · ${clockAt(at)}`;
}

/** The creation's time, always with its day: "Today · 09:12", "Yesterday · 21:40", "13 Oct · 21:40" (H4). */
export function creationWhen(at, now) {
  return `${dayHeading(at, now)} · ${clockAt(at)}`;
}

/** "06:52 · Day 1" from the world's clock ({hhmm, day}); the time alone where the day is unknown. */
export function worldWhen(clock) {
  if (!clock) return null;
  return clock.day ? `${clock.hhmm} · Day ${clock.day}` : clock.hhmm;
}

/** A date and time kept whole on one line: its spaces never break. */
const whole = (words) => words.replace(/ /g, '\u00a0');

/**
 * When a run of changes happened, in the person's own time: "11 Oct · 18:59 to 20:45" within one day (the day
 * named once), each date and time kept whole, so the words wrap only at "to"; one change, its time alone.
 */
export function personSpan(from, to, now) {
  const start = personWhen(from, now);
  const end = dayHeading(to, now) === dayHeading(from, now) ? clockAt(to) : personWhen(to, now);
  return start === end || from === to ? whole(start) : `${whole(start)} to ${whole(end)}`;
}

export function spanWhen(from, to) {
  return from === to ? from : `${from} to ${to}`;
}

/** Where the world's day changes on the line. */
export function dayMark(day) {
  return `Day ${day}`;
}

// -- What happened (JOURNEY's catalog, the sheet's section 9).

/** Names in a sentence: "Teo", "Teo and Ines", "Teo, Ines and Marco". */
export function namesWords(names) {
  if (names.length <= 1) return names[0] ?? '';
  return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`;
}

/** A place or a thing as the world names it, in a sentence: "bench" is "the bench". */
export function labelWords(label) {
  return label ? `the ${label}` : '';
}

/**
 * A moment's title, from its kind: "Teo met Ines at the bench", "Teo talked with Ines", "Teo spoke to Ines" (at
 * the bench when placed), "Marco asked Teo" when the first line asks, "Teo spoke up at the bench", "Ines went to
 * the market", "Ines and Teo went to the market" (a follower), "Teo went to rest at the bench", "Ines and Teo went
 * on" (no nameable target), "Teo followed Ines", "Teo stopped following Ines", "Teo picked up the lantern", "Teo put
 * down the lantern", "Teo gave Ines the lantern", "Teo took the lantern from Ines", "Teo left" (WORDS.md H14).
 * `place`, `to` and `thing` are names as the world gives them, or null; `activity` the going's, or null.
 */
export function momentWords({ kind, place, to, activity, thing, firstLine }, actor, others) {
  const at = place ? ` at ${labelWords(place)}` : '';
  const them = namesWords(others);
  switch (kind) {
    case 'met':
      return `${actor} met ${them}${at}`;
    case 'talked':
      return `${actor} talked with ${them}${at}`;
    case 'spoke':
      return firstLine && firstLine.trim().endsWith('?') ? `${actor} asked ${them}` : `${actor} spoke to ${them}${at}`;
    case 'spoke_to_all':
      return `${actor} spoke up${at}`;
    case 'went':
      if (activity === 'rest') return `${namesWords([actor, ...others])} went to rest${to ? ` at ${labelWords(to)}` : ''}`;
      return to ? `${namesWords([actor, ...others])} went to ${labelWords(to)}` : `${namesWords([actor, ...others])} went on`;
    case 'followed':
      return `${actor} followed ${them}`;
    case 'stopped_following':
      return `${actor} stopped following ${them}`;
    case 'picked_up':
      return thing ? `${actor} picked up ${labelWords(thing)}` : `${actor} picked something up`;
    case 'put_down':
      return thing ? `${actor} put down ${labelWords(thing)}` : `${actor} put something down`;
    case 'gave':
      return thing ? `${actor} gave ${them} ${labelWords(thing)}` : `${actor} gave ${them} something`;
    case 'took':
      return thing ? `${actor} took ${labelWords(thing)} from ${them}` : `${actor} took something from ${them}`;
    case 'left':
      return `${actor} left`;
    default:
      return namesWords([actor, ...others]);
  }
}

/**
 * What another model would have done at the same moment, with no full stop like a card's title (sheet sections
 * 6 and 9, WORDS.md H14): "Teo would have gone to the market", "… rested at the bench" (a going to rest), "… said
 * “…” to Ines", "… followed Ines", "… picked up the lantern", "… stood a while", "… waited a minute", "… carried
 * on as before". `to` and `thing` are names, `withName` the one the answer named, `activity` a going's, or null.
 */
export function branchWords({ kind, to, activity, thing, withName, line }, actor) {
  const would = (rest) => `${actor} would have ${rest}`;
  switch (kind) {
    case 'went':
      if (activity === 'rest') return would(to ? `rested at ${labelWords(to)}` : 'gone to rest');
      return would(to ? `gone to ${labelWords(to)}` : 'gone on');
    case 'talked':
    case 'met':
      return would(withName ? `talked with ${withName}` : 'talked with someone');
    case 'spoke':
      return line ? would(`said “${line}”${withName ? ` to ${withName}` : ''}`) : would(withName ? `spoken to ${withName}` : 'spoken');
    case 'spoke_to_all':
      return line ? would(`said “${line}”`) : would('spoken up');
    case 'followed':
      return would(withName ? `followed ${withName}` : 'followed someone');
    case 'stopped_following':
      return would(withName ? `stopped following ${withName}` : 'stopped following');
    case 'picked_up':
      return would(thing ? `picked up ${labelWords(thing)}` : 'picked something up');
    case 'put_down':
      return would(thing ? `put down ${labelWords(thing)}` : 'put something down');
    case 'gave':
      return would(withName ? `given ${withName} ${thing ? labelWords(thing) : 'something'}` : 'given something away');
    case 'took':
      return would(`taken ${thing ? labelWords(thing) : 'something'}${withName ? ` from ${withName}` : ''}`);
    case 'left':
      return would('left');
    case 'waited':
      return would('waited a minute');
    case 'stood':
      return would('stood a while');
    default:
      return would('carried on as before');
  }
}

/**
 * What a person did at a choice of their day (R5e), said in the past with no full stop like a row's title: the
 * chosen option as the events read serves it (`did`, a branch's kind, or `went_to_spot` for a walk to a spot the
 * person playing chose), "Went to the market", "Went to rest at the bench", "Waited", "Talked with Ines" (WORDS.md
 * "R5e item 4's words"). Fields as branchWords takes them, with no actor: a row is the person's own. Null for a kind
 * it has no words for, so the row keeps the choice as offered.
 */
export function didWords({ kind, to = null, activity = null, thing = null, withName = null } = {}) {
  switch (kind) {
    case 'went':
      if (activity === 'rest') return `Went to rest${to ? ` at ${labelWords(to)}` : ''}`;
      return to ? `Went to ${labelWords(to)}` : 'Moved on';
    case 'went_to_spot':
      return 'Went to the chosen spot';
    case 'talked':
    case 'met':
      return withName ? `Talked with ${withName}` : 'Talked with someone';
    case 'spoke':
      return withName ? `Spoke to ${withName}` : 'Spoke';
    case 'spoke_to_all':
      return 'Spoke up';
    case 'followed':
      return withName ? `Followed ${withName}` : 'Followed someone';
    case 'stopped_following':
      return withName ? `Stopped following ${withName}` : 'Stopped following';
    case 'picked_up':
      return thing ? `Picked up ${labelWords(thing)}` : 'Picked something up';
    case 'put_down':
      return thing ? `Put down ${labelWords(thing)}` : 'Put something down';
    case 'gave':
      return withName ? `Gave ${withName} ${thing ? labelWords(thing) : 'something'}` : 'Gave something away';
    case 'took':
      return `Took ${thing ? labelWords(thing) : 'something'}${withName ? ` from ${withName}` : ''}`;
    case 'left':
      return 'Went away';
    case 'waited':
      return 'Waited';
    case 'stood':
      return 'Stood a while';
    case 'carried_on':
      return 'Carried on as before';
    default:
      return null;
  }
}

/** The branch's head: "Asked again with Qwen3 235B". */
export function askedAgainParts(modelName) {
  return ['Asked again with ', modelPart(modelName)];
}

/** Another model chose what happened: one small line on the card, "Qwen3 235B chose the same". */
export function sameChoiceParts(modelName) {
  return [modelPart(modelName), ' chose the same'];
}

/** One answer in the opened moment: "Qwen3 235B: Teo would have gone to the market", or the same line. */
export function answerParts(modelName, same, outcome) {
  return same ? sameChoiceParts(modelName) : [modelPart(modelName), `: ${outcome}`];
}

/** Who decided, as parts: "By Nemotron 3 Nano 30B", "By a person playing", "By an outside program"; a routine's
 * moment has none (null). */
export function byParts(decider) {
  if (decider?.kind === 'model' && decider.model?.name) return ['By ', modelPart(decider.model.name)];
  if (decider?.kind === 'person') return [PATH_WORDS.personPlaying];
  if (decider?.kind === 'external') return [PATH_WORDS.outsideProgram];
  return null;
}

/** A line said, its speaker first: "Teo: “Morning, Ines.”" (quoted as said, never edited). */
export function saidWords(speaker, line) {
  return `${speaker}: “${line}”`;
}

/** Lines a card does not show: "3 more lines", "1 more line". */
export function moreLinesWords(count) {
  return `${plural(count, 'more line', 'more lines')}`;
}

// -- The person's own changes (sheet section 7): History's "You" form for each of build mode's sentence kinds
// (build-words.mjs's changeParts), so no sentence is made by cutting another.

const storeysWords = (count) => `${count} ${count === 1 ? 'storey' : 'storeys'}`;

const YOU_FORMS = Object.freeze({
  placed: ({ what }) => `You placed ${what}`,
  moved: ({ what }) => `You moved ${what}`,
  removed: ({ what }) => `You took out ${what}`,
  storeys_set: ({ what, after }) => `You set ${what} to ${storeysWords(after)}`,
  storeys_raised: ({ what, after }) => `You raised ${what} to ${storeysWords(after)}`,
  storeys_lowered: ({ what, after }) => `You lowered ${what} to ${storeysWords(after)}`,
  placed_object: () => 'You placed an object',
  moved_object: () => 'You moved an object',
  removed_object: () => 'You took out an object',
  changed_object: () => 'You changed an object',
  changed_world: () => 'You changed the world',
  undid: () => 'You undid a change',
  did_again: () => 'You did a change again',
  brought_back: ({ what }) => `You brought back ${what}`,
  back_where_it_was: ({ what }) => `You put ${what} back where it was`,
  took_away: ({ what }) => `You took away ${what} you had placed`,
  back_to_made_storeys: ({ what }) => `You put ${what} back to the storeys it was made with`,
  back_to_storeys: ({ what, before }) => `You put ${what} back to ${storeysWords(before)}`,
});

/** A change of build mode's, in History's words: "You placed the bench", "You took out the fan palm". */
export function youChangeWords(parts) {
  if (parts.form === 'again') return `${youChangeWords(parts.again)} again`;
  return (YOU_FORMS[parts.form] ?? YOU_FORMS.changed_world)(parts);
}

/** A personality written, changed or cleared: "You wrote Teo's personality". */
export function youPersonalityWords(name, change) {
  const verb = change === 'cleared' ? 'cleared' : change === 'changed' ? 'changed' : 'wrote';
  return `You ${verb} ${possessive(name)} personality`;
}

/** A model given, changed or taken away, as parts: "You changed Teo's model to Qwen3 235B" ("… to routine"). */
export function youModelParts(whose, modelName) {
  return [`You changed ${whose} to `, modelName ? modelPart(modelName) : 'routine'];
}

/** Several changes between the same two moments: one dot. */
export function changesWords(count) {
  return `You made ${count} changes`;
}

// -- Runs, the creation, the head.

/**
 * A run over its moments (sheet section 8): "Teo's and Ines's models were deciding · 06:00 to 07:15 · spent
 * $0.0042"; one character "Teo's model was deciding"; three or more "3 characters' models were deciding"; while on
 * "… are deciding · 06:00 to now · 1:52 left"; without the clock "75 minutes of world time · …". `spent: null`
 * leaves the money out (the opened moment's small print).
 */
export function runSpanWords({ names, from, to, worldMinutes, spent, running, left }) {
  const verb = names.length === 1 ? (running ? 'is' : 'was') : running ? 'are' : 'were';
  const whose = names.length === 1
    ? `${possessive(names[0])} model`
    : names.length === 2
      ? `${namesWords(names.map((name) => possessive(name)))} models`
      : names.length > 2 ? `${names.length} characters' models` : 'Models';
  const parts = [`${whose} ${verb} deciding`];
  if (from && (to || running)) parts.push(`${from} to ${running ? 'now' : to}`);
  else if (Number.isSafeInteger(worldMinutes)) parts.push(`${plural(worldMinutes, 'minute')} of world time`);
  if (running && left) parts.push(`${left} left`);
  else if (!running && spent !== null && Number(spent) > 0) parts.push(`spent ${money(spent)}`);
  return parts.join(' · ');
}

/** How the world began: made from the person's words, started from a ready world, or from a blank one. */
export function creationPathWords(readyWorld, blank = false) {
  if (blank) return PATH_WORDS.blankWorld;
  return readyWorld ? `Started from ${readyWorld}` : PATH_WORDS.madeFromWords;
}

/**
 * The head's GitHub line (sheet section 2), `{ words, refused }`; empty where the projects were not read.
 * `request` is a request to keep the world in a project, waiting or refused; `putting`, after Create in H12's
 * question until the follower links the project.
 */
export function headLine(project, request = null, putting = false) {
  if (project === undefined) return { words: '', refused: false };
  if (putting && project && !project.link) return { words: HEAD_WORDS.putting, refused: false };
  if (!project) {
    if (request && !request.refused) return { words: HEAD_WORDS.starting, refused: false };
    const refusal = request?.refused ? HEAD_WORDS.refusals[request.refused.code] : null;
    return refusal ? { words: refusal, refused: true } : { words: HEAD_WORDS.noProject, refused: false };
  }
  if (!project.link) return { words: HEAD_WORDS.localProject, refused: false };
  const name = String(project.link.repository).split('/').pop();
  const github = project.github;
  if (github && !github.reached) return { words: HEAD_WORDS.unreachable, refused: false };
  if (github?.paused) return { words: `Kept on GitHub in ${name} · sending is paused: ${github.paused.reason}`, refused: true };
  const visibility = github && github.visibility !== 'unstated' ? `, ${github.visibility.toLowerCase()}` : '';
  const state = github && github.not_sent > 0 ? `${plural(github.not_sent, 'change')} not sent yet` : 'up to date';
  return { words: `Kept on GitHub in ${name}${visibility} · ${state}`, refused: false };
}
