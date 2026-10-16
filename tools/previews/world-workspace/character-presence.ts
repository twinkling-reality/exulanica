// Beside a character or thing in the world (DESIGN's frames 04, 05 and 08): the name tag and the
// [E] Inspect prompt while it is looked at, the card beside it once it is chosen, and the question
// before a run. It only draws; character-view.mjs decides what it says and contextual-world.ts places
// it each frame from the projected points. The ring at a chosen character's feet is drawn in the
// world (atlas-react ground-ring.ts), so walls cover it as they cover the feet.
import { chip, keyWord, nameTag, promptColumn, promptRow, rule, scaleOf, sideCard, cardWords, orb, type NameTagWords, type SubjectBounds } from './world-ui.ts';
import { promptPlace } from './character-view.mjs';
import { CHARACTER_WORDS } from './character-words.mjs';
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
  /** What the question card says; null puts it away. */
  ask(content: QuestionContent | null): void;
  /** Places whichever card is up beside the subject, each frame; null for a subject out of view. */
  place(at: { readonly bounds: SubjectBounds; readonly prefer?: 'right' | 'left' | null } | null): void;
  /** Hides the tag and cards while a page is up, and brings them back after. */
  setCovered(covered: boolean): void;
  readonly asking: boolean;
  /** The top of the name tag on screen while it shows, or null: a pop sits 12 px over it. */
  tagTop(): number | null;
  /** The name tag's box on screen while it shows, so lines over others keep clear of it; else null. */
  tagBox(): { readonly x: number; readonly y: number; readonly width: number; readonly height: number } | null;
  dispose(): void;
}

export function mountCharacterPresence(host: HTMLElement, { onInspect, onAction }: {
  readonly onInspect: () => void;
  readonly onAction: (action: string) => void;
}): CharacterPresence {
  const scale = (): number => scaleOf(host);
  const tag = nameTag({ scale });
  const inspect = keyWord({ keys: ['E'], word: CHARACTER_WORDS.inspect, shortcut: 'E', onPress: onInspect }) as HTMLButtonElement;
  inspect.classList.add('wu-anchored', 'wu-reveal');
  inspect.hidden = true;
  const card = sideCard({ scale });
  const question = sideCard({ question: true, scale });
  for (const part of [card.root, question.root, tag.root, inspect]) host.append(part);
  let shown: string | null = null, asked: string | null = null, covered = false, chosen = false;
  const prompt = (item: CardPrompt): HTMLElement => keyWord({ keys: item.keys, word: item.word, shortcut: item.shortcut, onPress: () => onAction(item.action) });

  return {
    get asking() { return asked !== null; },
    tagTop() {
      if (tag.root.hidden) return null;
      const box = tag.root.getBoundingClientRect();
      return box.height ? box.top : null;
    },
    tagBox() {
      if (tag.root.hidden) return null;
      const box = tag.root.getBoundingClientRect();
      return box.height ? { x: box.left, y: box.top, width: box.width, height: box.height } : null;
    },
    look(words, head, inspectable = false) {
      if (!words || !head || covered) { tag.hide(); inspect.hidden = true; return; }
      tag.set(words);
      tag.place(head.x, head.y);
      inspect.hidden = !inspectable;
      if (inspectable) {
        const s = scale();
        const at = promptPlace(head, { width: inspect.offsetWidth, height: inspect.offsetHeight }, { width: innerWidth, height: innerHeight }, s);
        const transform = `translate3d(${at.x.toFixed(1)}px,${at.y.toFixed(1)}px,0)`;
        if (inspect.style.transform !== transform) inspect.style.transform = transform;
        inspect.setAttribute('aria-label', `${CHARACTER_WORDS.inspect} ${words.name}`);
      }
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
      if (!at) { card.hide(); question.hide(); return; }
      // Under a page the cards wait.
      if (covered) { card.hide(); question.hide(); return; }
      if (asked) { card.hide(); question.place(at.bounds, { prefer: at.prefer ?? null }); }
      else if (chosen) { question.hide(); card.place(at.bounds, { prefer: at.prefer ?? null }); }
    },
    setCovered(on) {
      covered = on;
      if (on) { tag.hide(); inspect.hidden = true; card.hide(); question.hide(); }
    },
    dispose() { for (const part of [card.root, question.root, tag.root, inspect]) part.remove(); },
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
      doing = inhabitantWords(person, [], inhabitants, profile, false, null, listed, playedByPerson).doing;
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
