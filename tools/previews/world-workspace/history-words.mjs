// History's words (DESIGN's WORDS.md: frame 23, rulings H1 to H4 and W2): every string the page
// shows, made from what the server served. Money and time in WORDS.md's forms; a character by
// its name, never "it".

import { HISTORY } from './build-words.mjs';

export const HISTORY_WORDS = Object.freeze({
  title: HISTORY.title,
  today: HISTORY.today,
  yesterday: 'Yesterday',
  empty: HISTORY.empty,
  loading: 'Reading what changed…',
  whatHappened: 'What happened',
  onGitHub: 'On GitHub',
  now: 'Now',
  earlierLater: 'Earlier, later',
  undo: 'Undo',
  openOnGitHub: 'Open on GitHub',
  back: 'Back',
  tryAgain: 'Try again',
  worldOffline: 'This world could not be read. Try again.',
  githubOffline: 'GitHub could not be reached. Your changes are kept here and sent when it answers.',
  notLinked: 'not linked to GitHub',
  upToDate: 'up to date',
  paused: 'sending to GitHub is paused',
  notSent: 'Not sent to GitHub yet',
  notKept: 'Not kept in the project yet: it is kept once the changes stop.',
  sent: 'Sent to GitHub',
  routine: 'Routine',
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

/** A cost on a row: only money that was spent. */
export function cost(usd) {
  const value = Number(usd);
  return Number.isFinite(value) && value > 0 ? money(value) : '';
}

export function plural(count, noun, many) {
  return count === 1 ? `${count} ${noun}` : `${count} ${many ?? `${noun}s`}`;
}

export function possessive(name) {
  return `${name}'s`;
}

const pad = (n) => String(n).padStart(2, '0');

/** "09:44", in the reader's own time. */
export function clockAt(at) {
  const date = new Date(at);
  return `${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function sameDay(a, b) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

function dayOf(at, now) {
  const date = new Date(at), today = new Date(now);
  if (sameDay(date, today)) return 'today';
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  if (sameDay(date, yesterday)) return 'yesterday';
  return `${date.getDate()} ${MONTHS[date.getMonth()]}`;
}

/** The list's day heading: "Today", "Yesterday", "13 Oct" (H3). */
export function dayHeading(at, now) {
  const day = dayOf(at, now);
  if (day === 'today') return HISTORY_WORDS.today;
  if (day === 'yesterday') return HISTORY_WORDS.yesterday;
  return day;
}

/** The chosen change's label: "09:44 today", "09:44 yesterday", "09:44, 14 Oct" (H3). */
export function chosenLabel(at, now) {
  const day = dayOf(at, now);
  return day === 'today' || day === 'yesterday' ? `${clockAt(at)} ${day}` : `${clockAt(at)}, ${day}`;
}

/** The repository's name without its owner, as frame 23 writes it. */
function repositoryName(repository) {
  return String(repository).split('/').pop();
}

/**
 * The sub-line: the world's title, then where it is kept: "Terraces on the bay · kept in your
 * GitHub project terraces-on-the-bay, private · up to date", or "· not linked to GitHub". Where
 * the projects could not be read (`project` undefined), the title alone: never "not linked" unread.
 */
export function subLine(title, project) {
  if (project === undefined) return title;
  const parts = [title];
  if (!project || !project.link) {
    parts.push(HISTORY_WORDS.notLinked);
    return parts.join(' · ');
  }
  const github = project.github;
  const visibility = github && github.visibility !== 'unstated' ? `, ${github.visibility.toLowerCase()}` : '';
  parts.push(`kept in your GitHub project ${repositoryName(project.link.repository)}${visibility}`);
  if (github && github.paused) parts.push(HISTORY_WORDS.paused);
  else if (github && github.not_sent > 0) parts.push(`${plural(github.not_sent, 'change')} not sent yet`);
  else if (github && github.reached) parts.push(HISTORY_WORDS.upToDate);
  return parts.join(' · ');
}

/**
 * A change the project does not hold yet (H5): kept once nothing has changed for the project's
 * settle period, "2 minutes" or "90 seconds", as its follower states it; without one, once the
 * changes stop.
 */
export function notKeptWords(settleSeconds) {
  if (!Number.isSafeInteger(settleSeconds) || settleSeconds < 1) return HISTORY_WORDS.notKept;
  const period = settleSeconds % 60 === 0 ? plural(settleSeconds / 60, 'minute') : plural(settleSeconds, 'second');
  return `Not kept in the project yet: it is kept once nothing has changed for ${period}.`;
}

/**
 * What GitHub holds of a change made at `at`: in the open pull request, sent, not sent yet, or
 * not kept in the project yet; or the pause, or GitHub out of reach. Null where no project
 * follows the world (the sub-line says so).
 */
export function onGitHub(project, at) {
  if (!project || !project.link) return null;
  const github = project.github;
  const kept = project.last_checkpoint_at ? Date.parse(project.last_checkpoint_at) : null;
  if (kept === null || at > kept) return notKeptWords(project.settle_seconds);
  if (!github) return HISTORY_WORDS.notSent;
  if (!github.reached) return HISTORY_WORDS.githubOffline;
  const through = github.sent_through_at ? Date.parse(github.sent_through_at) : null;
  if (through === null || at > through) {
    return github.paused ? `${capital(HISTORY_WORDS.paused)}: ${github.paused.reason}.` : HISTORY_WORDS.notSent;
  }
  const pull = github.pull_request;
  return pull ? `Pull request ${pull.number}, “${pull.title}”, waiting for you to merge` : HISTORY_WORDS.sent;
}

function capital(text) {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** A run: "Ran 10 minutes with Teo's model"; several characters: "with 2 characters' models". */
export function runWords(minutes, names) {
  const whose = names.length === 1 ? `${possessive(names[0])} model` : `${names.length} characters' models`;
  return `Ran ${plural(minutes, 'minute')} with ${whose}`;
}

export function runMark(minutes) {
  return `Ran ${plural(minutes, 'minute')}`;
}

/**
 * A run's facts: "World time 06:00 to 07:15 · 12 decisions · spent $0.0042 of at most $0.05";
 * world time only where the world's clock is read.
 */
export function runFacts({ from, to, decisions, spent, limit }) {
  const parts = [];
  if (from && to) parts.push(`World time ${from} to ${to}`);
  parts.push(plural(decisions, 'decision'));
  parts.push(`spent ${money(spent)}${limit ? ` of at most ${money(limit)}` : ''}`);
  return parts.join(' · ');
}

/** What happened in a run, in counts until a read says where the character went (H1). */
export function runHappened(decisions, done) {
  return `${plural(decisions, 'decision')}, ${done} done.`;
}

/** A model given, changed or taken away: one sentence (P4). */
export function modelWords(name, modelName) {
  return `Changed ${possessive(name)} model to ${modelName ?? HISTORY_WORDS.routine}`;
}

export function modelMark(name) {
  return `Changed ${possessive(name)} model`;
}

/** A personality written, changed or cleared (H6). */
export function personalityWords(name, change) {
  const verb = change === 'cleared' ? 'Cleared' : change === 'changed' ? 'Changed' : 'Wrote';
  return `${verb} ${possessive(name)} personality`;
}

export function compareWords(name) {
  return name ? `Compared two models for ${name}` : 'Compared two models';
}

export const COMPARE_MARK = 'Compared two models';

/** How the world began: "Created from your words", or "Started from Canopy garden" (H6). */
export function creationWords(readyWorld) {
  return readyWorld ? `Started from ${readyWorld}` : 'Created from your words';
}
