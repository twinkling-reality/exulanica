// Beside a character or thing in the world (DESIGN's redraws r04, r05, r07 and r08): one soft label over
// the head while it is looked at (r04), the group beside a chosen character (character-group.ts: J30, its
// model list and its Run question) or the card beside a chosen thing. It only draws; character-group.mjs and
// character-view.mjs decide what it says and contextual-world.ts places it each frame from the projected points. The ring at a chosen character's feet is drawn in the
// world (atlas-react ground-ring.ts), so walls cover it as they cover the feet.
import { chip, keyWord, promptColumn, promptRow, rule, scaleOf, sideCard, cardWords, orb, type NameTagWords, type SubjectBounds } from './world-ui.ts';
import { characterGroup, lookLabel, type GroupContent } from './character-group.ts';
import type { SocietySnapshot } from '/src/society-api.ts';
import { DEFAULT_SOCIETY_ENGINE, societyEngine } from '/src/society-engines.ts';
import { inhabitantWords } from '/src/ui/world-inhabitants.ts';
import { livingInhabitantWords } from '/src/society-inhabitant-words.ts';

export interface CardPrompt {
  readonly action: string;
  readonly keys: readonly string[];
  readonly word: string;
  readonly shortcut: string;
}

export interface CardContent {
  readonly label?: string;
  readonly title: string;
  readonly lines: readonly string[];
  readonly chip: string | null;
  /** The chip's live dot while a run is on and this character's model is deciding. */
  readonly live?: boolean;
  readonly prompts: readonly CardPrompt[];
}

/** The question before a run (frame 08): its words, the orb's figures and its two answers. */
export interface QuestionContent {
  readonly label: string;
  readonly title: string;
  readonly lines: readonly string[];
  readonly chip: string | null;
  readonly orbWord: string;
  readonly big: string;
  readonly small: string;
  /** A refusal in plain words, shown in the card where it happened; null when there is none. */
  readonly refusal: string | null;
  readonly answers: readonly CardPrompt[];
  readonly busy: boolean;
}

export interface CharacterPresence {
  /** The tag and prompt over the looked-at subject's head point; null hides them. */
  look(words: NameTagWords | null, head?: { readonly x: number; readonly y: number }, inspectable?: boolean): void;
  /** What the chosen subject's card says; null hides the card. */
  choose(content: CardContent | null): void;
  /** What a chosen character's group says (J30), in place of the card; null puts it away. */
  group(content: GroupContent | null): void;
  /** What the question card says; null puts it away. */
  ask(content: QuestionContent | null): void;
  /**
   * Places whichever card or group is up beside the subject, each frame; null for a subject out of view. `head` is the
   * top of a character's head on screen, where the group's leader starts.
   */
  place(at: { readonly bounds: SubjectBounds; readonly prefer?: 'right' | 'left' | null; readonly head?: { readonly x: number; readonly y: number } } | null): void;
  /** Hides the tag and cards while a page is up, and brings them back after. */
  setCovered(covered: boolean): void;
  readonly asking: boolean;
  /** The top of the looked-at label (r04) on screen while it shows, or null: a pop sits 12 px over it. */
  tagTop(): number | null;
  /** The looked-at label's box on screen while it shows, so lines over others keep clear of it; else null. */
  tagBox(): { readonly x: number; readonly y: number; readonly width: number; readonly height: number } | null;
  dispose(): void;
}

export function mountCharacterPresence(host: HTMLElement, { onInspect, onAction }: {
  readonly onInspect: () => void;
  readonly onAction: (action: string) => void;
}): CharacterPresence {
  const scale = (): number => scaleOf(host);
  // Looked at: one soft label over the head (r04), the name, what they are doing and [E] Inspect.
  const looked = lookLabel({ scale, onInspect });
  const card = sideCard({ scale });
  const question = sideCard({ question: true, scale });
  const grouped = characterGroup({ scale, onAction });
  for (const part of [card.root, grouped.root, question.root, looked.root]) host.append(part);
  let shown: string | null = null, asked: string | null = null, covered = false, chosen = false, grouping = false;
  const prompt = (item: CardPrompt): HTMLElement => keyWord({ keys: item.keys, word: item.word, shortcut: item.shortcut, onPress: () => onAction(item.action) });

  return {
    get asking() { return asked !== null; },
    tagTop: () => looked.box()?.y ?? null,
    tagBox: () => looked.box(),
    look(words, head, inspectable = false) {
      if (!words || !head || covered) { looked.set(null, false); return; }
      looked.set({ name: words.name, doing: words.doing ?? null }, inspectable);
      looked.place(head);
    },
    choose(content) {
      chosen = content !== null;
      if (!content) { shown = null; card.hide(); card.body.replaceChildren(); return; }
      const key = JSON.stringify(content);
      if (key === shown) return;
      shown = key;
      const body = card.body;
      body.replaceChildren(cardWords({ label: content.label, title: content.title, lines: content.lines }));
      if (content.chip) body.append(chip(content.chip, { live: content.live === true }));
      if (content.prompts.length) body.append(rule(), promptColumn(content.prompts.map(prompt)));
      body.setAttribute('aria-label', content.title);
    },
    group(content) {
      grouping = content !== null;
      grouped.set(content);
    },
    ask(content) {
      if (!content) { asked = null; question.hide(); question.body.replaceChildren(); return; }
      const key = JSON.stringify(content);
      if (key === asked) return;
      asked = key;
      const body = question.body;
      body.replaceChildren(cardWords({ label: content.label, title: content.title, lines: content.lines }));
      if (content.chip) body.append(chip(content.chip));
      body.append(rule());
      const decide = content.answers[0];
      const row = document.createElement('div');
      row.className = 'wu-orb-row';
      const figures = document.createElement('div');
      const big = document.createElement('p'); big.className = 'wu-big'; big.textContent = content.big;
      const small = document.createElement('p'); small.className = 'wu-small-text'; small.textContent = content.small;
      figures.append(big, small);
      row.append(orb({ word: content.orbWord, onPress: () => decide && onAction(decide.action), disabled: content.busy }), figures);
      body.append(row);
      if (content.refusal) {
        const refused = document.createElement('p');
        refused.className = 'wu-card-line wu-refusal';
        refused.setAttribute('role', 'status');
        refused.textContent = content.refusal;
        body.append(refused);
      }
      body.append(promptRow(content.answers.map(prompt)));
    },
    place(at) {
      if (!at) { card.hide(); question.hide(); grouped.place(null); return; }
      // Under a page the cards wait.
      if (covered) { card.hide(); question.hide(); grouped.place(null); return; }
      if (asked) { card.hide(); grouped.place(null); question.place(at.bounds, { prefer: at.prefer ?? null }); }
      else if (grouping) {
        card.hide(); question.hide();
        grouped.place({ head: at.head ?? { x: (at.bounds.left + at.bounds.right) / 2, y: at.bounds.headY ?? at.bounds.top }, bounds: at.bounds, prefer: at.prefer ?? null });
      }
      else if (chosen) { question.hide(); card.place(at.bounds, { prefer: at.prefer ?? null }); }
    },
    setCovered(on) {
      covered = on;
      if (on) { looked.set(null, false); card.hide(); question.hide(); grouped.place(null); }
    },
    dispose() { for (const part of [card.root, question.root, looked.root]) part.remove(); grouped.remove(); },
  };
}

/**
 * What the society read says of one character: the catalog's sentence for what they are doing (as
 * the Companion words it), whether the society is a living one, and its clock's first minute
 * (null where the society keeps no clock). Null when the read does not hold the character.
 */
export function characterFacts(snapshot: SocietySnapshot | null, subjectId: string, playedByPerson = false): CharacterFacts | null {
  const inhabitants = snapshot?.state.inhabitants ?? [];
  const ordinal = inhabitants.findIndex(item => item.id === subjectId);
  if (!snapshot || ordinal < 0) return null;
  const person = inhabitants[ordinal]!;
  const profile = snapshot.state.profile ?? null;
  const living = societyEngine(profile ?? DEFAULT_SOCIETY_ENGINE).stateFamily === 'living';
  const held = person as unknown as { readonly role?: unknown; readonly has_home?: boolean; readonly has_work?: boolean; readonly goal?: unknown };
  const role = typeof held.role === 'string' ? held.role : held.role && typeof (held.role as { label?: unknown }).label === 'string' ? (held.role as { label: string }).label : null;
  let doing: string | null = null;
  try {
    if (living) {
      const goal = held.goal && typeof held.goal === 'object' && 'activity' in held.goal ? held.goal as { activity: string; reason?: string } : null;
      doing = livingInhabitantWords({ role, has_home: held.has_home === true, has_work: held.has_work === true, action: person.action ?? null, goal }, ordinal).doing;
    } else {
      const listed = new Map((snapshot.places?.targets ?? []).filter(target => target.enabled).map(target => [target.targetId, target.place ?? null] as const));
      // In the world the activity is said alone, never how many minutes it has left.
      doing = inhabitantWords(person, [], inhabitants, profile, false, null, listed, playedByPerson, { still: false }).doing;
    }
  } catch { doing = null; }
  const state = snapshot.state as unknown as { readonly start_minute_of_day?: unknown; readonly clock?: { readonly start_minute_of_day?: unknown } | null };
  const start = living ? state.start_minute_of_day ?? state.clock?.start_minute_of_day : state.clock?.start_minute_of_day;
  return { person, kind: role, doing, living, startMinute: Number.isSafeInteger(start) ? start as number : null };
}

export interface CharacterFacts {
  readonly person: SocietySnapshot['state']['inhabitants'][number];
  /** What the society calls the character's role ("resident", "cook"), or null. */
  readonly kind: string | null;
  readonly doing: string | null;
  readonly living: boolean;
  readonly startMinute: number | null;
}
