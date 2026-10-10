/**
 * Who decides for each being, marked over it in the world, what it chose, and the lines it says.
 *
 * Every being a model decides for wears a small "AI" mark on its own head, always, and the model's
 * whole name in a row over the mark wherever the name can be tied to its being without doubt, never
 * in letters smaller than the rule's floor; every line a model writes is
 * drawn in a bubble that starts with the same word. An outside AI agent wears the name it gave,
 * outlined as a visitor's; a being a person runs from outside (a game's player) wears that game's
 * pill instead ("from Block Game"), and a visitor the world's own model runs wears the model's name
 * with where it came from after it, quieter; a being a person plays wears the person's word. A being
 * its own routine decides for wears nothing, unless the page hands it a mark saying so (it does for
 * the one that is picked), so the answer exists for every being without being painted on thousands.
 * What each mark says is the page's to decide, from each being's decider, in the one function the
 * card shares; this overlay only draws what it is given (`setMarks`), so the world and the card
 * never disagree. It reads nothing of the kind of world it is drawn over: a point over each being
 * and how tall the being stands, from the society drawn, are all it asks.
 *
 * WHEN A DECISION IS TAKEN UP the page hands its words (`showDecision`): a row opens with
 * the name (over it, as the page's stylesheet builds a mark up from the head), saying what was chosen, stays as long as a line of speech of that length would, and
 * closes. It has a place for the decider's own stated words, which stays empty and takes no room
 * until a decision serves any.
 *
 * EVERY MARK STANDS ON ITS OWN BEING'S HEAD and is never lifted off it. A NAME is bounded by what
 * can be read, never by how many beings a model decides for (`DeciderMarkRule`, the page's
 * catalog). Nearest first, a model's name is drawn over its mark where its being stands tall enough
 * on the screen to be worth naming, while the names cover no more than a stated share of the view
 * (what a name adds over its mark; the marks are no part of the share), and where it would cover no
 * name already drawn and nobody else's mark. Where any of the three fails the being wears the mark
 * alone, which is still its own and still a button, and pointing at it or reaching it by keyboard
 * gives the whole name at once (the page's stylesheet). So in a pile one keeps its name and the
 * others keep their marks, and no name stands where nobody can tell whose it is. The nearest being
 * a model decides for is named however small it stands, though not over somebody else's mark. A
 * mark alone over a being that stands lower on the screen than the rule's `dotUnderPx` is a DOT, the
 * same mark with no room for letters, so a crowd far off is a row of dots and not a smudge of
 * pills; it is still a button, and pointing at it opens the pill and the name. A
 * being that is picked, speaking or at a decision is named whatever stands by, outside the share,
 * and is said to be held on its node so the page draws it over the rest. A marked being no model
 * decides for (a game's player, a person's) has no shorter form: too small or beyond the share it
 * wears nothing. Every name not drawn is counted by why (`counts`, and `data-named` and
 * `data-unnamed` on the overlay's root), so a page can say how many more there are.
 *
 * The overlay is DOM, placed each frame by projecting world points, as the anchor overlay is
 * (`../anchor-overlay.ts`): nodes are kept and reused, a new one is made only when more marks are
 * in view than ever were before, and a frame that shows the same as the last writes nothing but
 * where each mark stands. The nodes are as many as the marked beings in view: the share of the view
 * bounds the names, not the marks. The marks stay readable by
 * a screen reader and checkable in the page. A line's words are set only as text: lines are written
 * by models and players and are never markup. A name is a button: clicking it picks its being as
 * aiming does.
 */

import * as pc from 'playcanvas';

/**
 * What a being's mark says, as the page decided it. `full` is the mark's words for a screen
 * reader; an AI's `name` is the model's whole served name, or for an AI agent from outside the
 * world (`outside`) the name it gave for itself; `from` is where a visitor this world's model runs
 * came from (a bridge's label). A person's mark (a being someone plays, or a line they said) draws
 * its `label` as the pill's word; `mine` says the viewer is the one playing.
 */
export type ThingMark =
  | { readonly kind: 'ai'; readonly name: string; readonly full: string; readonly outside?: true; readonly from?: string }
  | { readonly kind: 'from'; readonly label: string; readonly full: string }
  | { readonly kind: 'person'; readonly label: string; readonly full: string; readonly mine: boolean; readonly from?: string }
  /** Its own routine decides: worn only where the page hands it (the picked being), never by default. */
  | { readonly kind: 'routine'; readonly label: string; readonly full: string };

export interface MarkedSubject {
  /** What it wears always, or null for a being that wears nothing at rest (its routine decides). */
  readonly mark: ThingMark | null;
  /** What it wears only while it is the picked one, where it wears nothing at rest. */
  readonly picked?: ThingMark;
  /** The being's label beside its pill when its name shows ("knight"), or null. */
  readonly label: string | null;
  /** What a screen reader says for the mark, in the page's words; the mark's `full` without them. */
  readonly spoken?: string;
}

export interface ThingLine {
  readonly subjectId: string;
  /** The words, exactly as the state holds them. */
  readonly text: string;
  readonly mark: ThingMark;
  /** Who said it, in words: "knight · Qwen3 235B Instruct". */
  readonly header: string;
  /** What a screen reader says for the line's mark, in the page's words. */
  readonly spoken?: string;
}

/** What a decider chose, as the page words it, to open under the decider's name. */
export interface ThingDecision {
  readonly subjectId: string;
  /** What was chosen and what came of it, in the page's words. Plain text. */
  readonly chose: string;
  /** The decider's own stated words with its choice, where a decision serves any; else null. */
  readonly said?: string | null;
}

/**
 * What bounds the marks, as the page's catalog states it
 * (`assets/catalogs/thing-presentation/decider-marks.v2.json`): each a value with its class and
 * reason there, none a count of beings.
 */
export interface DeciderMarkRule {
  /** The model's name is never drawn in letters smaller than this, in CSS pixels. */
  readonly nameLeastPx: number;
  /** A name is drawn over a being that stands at least this tall on the screen, in CSS pixels. */
  readonly beingLeastPx: number;
  /**
   * A model's mark is a dot, and not the pill that says AI, over a being that stands lower than
   * this on the screen, in CSS pixels; 0 where the catalog states none, and then no mark is a dot.
   */
  readonly dotUnderPx: number;
  /** How much of the view's area names may cover, as a share of it, spent nearest first. */
  readonly screenShare: number;
  /** How many lines of speech are open at once. */
  readonly linesAtOnce: number;
  /** How long a line or a decision stays open: a base, more a character, and a most, in ms. */
  readonly lineBaseMs: number;
  readonly linePerCharacterMs: number;
  readonly lineMostMs: number;
}

/** How long a line of these words stays open, in seconds, by the rule. */
export const lineSeconds = (text: string, rule: DeciderMarkRule): number =>
  Math.min(rule.lineMostMs, rule.lineBaseMs + rule.linePerCharacterMs * [...text].length) / 1000;
/** The custom property the overlay states the floor of a name's letters in, for the page's stylesheet. */
export const NAME_LEAST_PROPERTY = '--thing-mark-name-least';
/** How far over its speaker's head a bubble stands where the speaker wears no mark, in CSS pixels. */
const LINE_LIFT_PX = 34;
/** How far over all its speaker wears a bubble stands, in CSS pixels: the gap between a mark's own rows. */
const LINE_GAP_PX = 3;
/** Two boxes that overlap by no more than this, in CSS pixels, only touch: neither covers the other. */
const TOUCH_PX = 1;
/** A point this far off screen, in CSS pixels, is not drawn. */
const SCREEN_MARGIN_PX = 40;

interface MarkNode {
  readonly root: HTMLDivElement;
  readonly pill: HTMLButtonElement;
  readonly pillWord: HTMLSpanElement;
  readonly pillName: HTMLSpanElement;
  /** Where a visitor a model runs came from, after the name, in the quieter weight. */
  readonly pillFrom: HTMLSpanElement;
  /** The name and where it came from, in the row over the mark; hidden where the mark has no name. */
  readonly plate: HTMLSpanElement;
  readonly label: HTMLSpanElement;
  /** The row that opens with the name at a decision: what was chosen, and the decider's own words. */
  readonly decision: HTMLDivElement;
  readonly chose: HTMLSpanElement;
  readonly said: HTMLSpanElement;
  subject: string | null;
  visible: boolean;
  /** The transform last written, so a mark that has not moved is not written again. */
  at: string;
  /** What it shows now, joined: the key its size is kept under. */
  words: string;
  /** Everything last written into it, joined, so a frame that shows the same writes nothing. */
  filled: string;
  /** Its size while a decision is open under it, and the words that size was read for. */
  open: { readonly words: string; readonly size: Size } | null;
}

interface Size { readonly width: number; readonly height: number }
interface Box { readonly left: number; readonly right: number; readonly top: number; readonly bottom: number }

/** A box of a size standing centred over a point of the screen, from `from` pixels over it up. */
const boxAt = (x: number, y: number, size: Size, from: number): Box =>
  ({ left: x - size.width / 2, right: x + size.width / 2, top: y - size.height, bottom: y - from });

/** A marked being in view this frame: where its head is on the screen, and its mark's box where a model's. */
interface Seen {
  readonly id: string;
  readonly subject: MarkedSubject;
  readonly mark: ThingMark;
  readonly held: boolean;
  readonly x: number;
  readonly y: number;
  readonly small: boolean;
  readonly behind: boolean;
  readonly alone: MarkContent | null;
  readonly size: Size | null;
  readonly box: Box | null;
}

/** What a mark node is to show, worked out before anything is written into it. */
interface MarkContent {
  readonly alone: boolean;
  /** Its being is picked, speaking or at a decision: it is drawn over every other mark. */
  readonly held: boolean;
  /** Its being is followed (picked, or played by the viewer) and something stands between: drawn as behind it. */
  readonly behind: boolean;
  /** The mark alone, over a being too low on the screen for the pill: drawn as a dot. */
  readonly dot: boolean;
  readonly pillClass: string;
  readonly kind: ThingMark['kind'];
  readonly word: string;
  readonly name: string | null;
  readonly from: string | null;
  readonly label: string | null;
  readonly chose: string | null;
  readonly said: string;
  readonly aria: string;
  /** What decides its size: the key its size is kept under. */
  readonly words: string;
}

/**
 * What a being's mark shows. `alone` is the mark with no name beside it: the name stays in the node
 * for a screen reader and for the pointer (the stylesheet shows it while the mark is pointed at or
 * focused), and takes no room, so the mark alone has one size whatever the name.
 */
function contentOf(
  subject: MarkedSubject, mark: ThingMark, held: boolean,
  decision: { readonly chose: string; readonly said: string | null } | null, alone: boolean, behind = false, dot = false,
): MarkContent {
  const ai = mark.kind === 'ai';
  // The model's whole name, always: never a word of it, never hidden for being far.
  const name = ai ? mark.name : null;
  const from = ai && mark.from !== undefined ? `· from ${mark.from}` : null;
  const word = ai ? 'AI' : mark.label;
  // The page's spoken words are for the mark worn at rest; one worn only while picked says its own.
  const spoken = mark === subject.mark ? subject.spoken ?? mark.full : mark.full;
  const chose = decision?.chose ?? null;
  const said = decision?.said ?? '';
  const named = subject.label === null ? spoken : `${subject.label}: ${spoken}`;
  const label = held ? subject.label : null;
  const classes = pillClass(mark);
  return {
    alone, held, behind, dot: alone && dot, pillClass: classes, kind: mark.kind, word, name, from, label, chose, said,
    aria: chose === null ? named : `${named}. ${[chose, said].filter((part) => part !== '').join(' ')}`,
    words: alone
      ? [dot ? 'dot' : 'alone', classes, word].join('\u0000')
      : ['name', classes, word, name ?? '', from ?? '', label ?? '', chose === null ? '' : `\u0001${chose}\u0001${said}`].join('\u0000'),
  };
}

/**
 * Why a marked being in view wears its mark alone this frame and not its name. A being a model
 * decides for is counted here and still drawn, as the small mark over its own head; any other
 * marked being too small to name is counted and not drawn.
 */
export interface UnnamedCounts {
  /** It stands too small on the screen to be worth naming. */
  readonly small: number;
  /** The names nearer the viewer already cover the share of the view names may. */
  readonly beyondShare: number;
  /** Its name would cover a name or a mark already standing over a nearer being, so nobody could tell whose it was. */
  readonly collides: number;
  /** Something of the world stands between the viewer and it: it wears nothing, mark or name. */
  readonly hidden: number;
}

/**
 * Whether a point of the world is seen from an eye, as the page answers it for the world drawn (a
 * town's plan of what stands at eye height). World metres.
 */
export type Sees = (eye: pc.Vec3, point: pc.Vec3) => boolean;

interface LineNode {
  readonly root: HTMLDivElement;
  readonly pill: HTMLSpanElement;
  readonly header: HTMLSpanElement;
  readonly text: HTMLDivElement;
  subject: string | null;
  until: number;
  visible: boolean;
  at: string;
}

const hide = (node: { root: HTMLElement; visible: boolean; at: string }) => {
  if (node.visible) {
    node.root.style.display = 'none';
    node.visible = false;
    node.at = '';
  }
};

/** The mark a being wears now: its own, or where it has none and is the picked one, the one for then. */
const worn = (subject: MarkedSubject, picked: boolean): ThingMark | null =>
  subject.mark ?? (picked ? subject.picked ?? null : null);

/** The pill's classes: its kind, and an outside agent's outline. */
const pillClass = (mark: ThingMark): string =>
  `thing-mark-pill thing-mark-${mark.kind}${mark.kind === 'ai' && mark.outside === true ? ' thing-mark-outside' : ''}`;

export class ThingMarks {
  readonly root: HTMLDivElement;
  private readonly marks: MarkNode[] = [];
  private readonly lines: LineNode[] = [];
  private subjects: ReadonlyMap<string, MarkedSubject> = new Map();
  /** The decision open under each being's name, and until when. */
  private readonly decisions = new Map<string, { readonly chose: string; readonly said: string | null; readonly until: number }>();
  /** The size of a mark by what it shows, read from the page once for each. */
  private readonly sizes = new Map<string, Size>();
  private unnamed: UnnamedCounts = { small: 0, beyondShare: 0, collides: 0, hidden: 0 };
  private named = 0;
  /** How tall all a being wears stands over its head this frame, in CSS pixels, for a line to stand over. */
  private readonly tops = new Map<string, number>();
  /** What the overlay last stated of its counts, so it is stated again only when it changes. */
  private said = '';
  private readonly viewProjection = new pc.Mat4();
  private readonly view = new pc.Mat4();
  private readonly point = new pc.Vec4();
  private readonly viewer = new pc.Vec3();

  constructor(
    parent: HTMLElement, private readonly onPick: (subjectId: string) => void, private readonly rule: DeciderMarkRule,
  ) {
    this.root = document.createElement('div');
    this.root.className = 'thing-marks';
    this.root.setAttribute('role', 'region');
    this.root.setAttribute('aria-label', 'Who decides for what you see');
    Object.assign(this.root.style, { position: 'absolute', inset: '0', pointerEvents: 'none', overflow: 'hidden' });
    // The floor for a name's letters is the rule's: stated here as data, which the page's stylesheet
    // takes the larger of with whatever size its shape gives a name (`--thing-mark-name-least`).
    this.root.style.setProperty(NAME_LEAST_PROPERTY, `${rule.nameLeastPx}px`);
    parent.appendChild(this.root);
    for (let i = 0; i < Math.max(1, Math.round(rule.linesAtOnce)); i += 1) this.lines.push(this.lineNode());
  }

  /** Who decides for each being, as the page decided it; a being it leaves out wears nothing. */
  setMarks(subjects: ReadonlyMap<string, MarkedSubject>): void {
    this.subjects = subjects;
  }

  /** The beings that wear a mark now (the picked one among them), and those whose line is shown. */
  wanted(nowMs: number, selected: string | null = null): Set<string> {
    const ids = this.speaking(nowMs);
    for (const [id, subject] of this.subjects) if (worn(subject, id === selected) !== null) ids.add(id);
    return ids;
  }

  /** Show a line over its speaker from `nowMs`, replacing the speaker's last one. */
  showLine(line: ThingLine, nowMs: number): void {
    const node = this.lines.find((one) => one.subject === line.subjectId)
      ?? this.lines.find((one) => one.subject === null || one.until <= nowMs)
      ?? this.lines.reduce((a, b) => (a.until <= b.until ? a : b));
    node.subject = line.subjectId;
    node.until = nowMs + lineSeconds(line.text, this.rule) * 1000;
    node.pill.className = pillClass(line.mark);
    node.pill.textContent = line.mark.kind === 'ai' ? 'AI' : line.mark.label;
    node.pill.setAttribute('aria-label', line.spoken ?? line.mark.full);
    node.header.textContent = line.header;
    node.text.textContent = line.text;
  }

  /**
   * Open a decision under its decider's name from `nowMs`, replacing that being's last one. It
   * stays as long as a line of speech of its words would, and shows only while the being is marked.
   */
  showDecision(decision: ThingDecision, nowMs: number): void {
    const said = decision.said == null || decision.said === '' ? null : decision.said;
    const words = said === null ? decision.chose : `${decision.chose} ${said}`;
    this.decisions.set(decision.subjectId, { chose: decision.chose, said, until: nowMs + lineSeconds(words, this.rule) * 1000 });
  }

  /** The beings speaking now: a line of theirs is shown. */
  speaking(nowMs: number): Set<string> {
    return new Set(this.lines.filter((line) => line.subject !== null && line.until > nowMs).map((line) => line.subject!));
  }

  /** The beings at a decision now: one of theirs is open. */
  deciding(nowMs: number): Set<string> {
    for (const [id, decision] of this.decisions) if (decision.until <= nowMs) this.decisions.delete(id);
    return new Set(this.decisions.keys());
  }

  /**
   * Once a frame, after everyone is posed: `anchors` is where each being's mark hangs in the world
   * (over its head) and `heights` how tall each stands, in metres, where the society drawn says. A
   * being that is selected, speaking or at a decision shows its label and is always named. `sees`
   * is the page's answer to whether a point is seen from the eye: a being it says is not seen wears
   * nothing and says nothing, and is counted; the one that is picked and one the viewer plays are
   * followed, and keep what they wear, marked as behind something. Absent, everything is seen.
   */
  update(
    camera: pc.Entity, anchors: ReadonlyMap<string, pc.Vec3>, selected: string | null, nowMs: number,
    heights: ReadonlyMap<string, number> = new Map(), sees: Sees | null = null,
  ): void {
    const component = camera.camera;
    if (!component) return;
    const canvas = component.system.app.graphicsDevice.canvas;
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    // The camera where it is now, not where the last render left it.
    this.view.copy(camera.getWorldTransform()).invert();
    this.viewProjection.mul2(component.projectionMatrix, this.view);
    this.viewer.copy(camera.getPosition());
    const speaking = this.speaking(nowMs);
    const deciding = this.deciding(nowMs);
    // How many CSS pixels a metre standing upright takes one metre ahead of the eye.
    const pixelsPerMetre = component.projectionMatrix.data[5]! * height / 2;
    const marked = [...this.subjects]
      .filter(([id, subject]) => worn(subject, id === selected) !== null && anchors.has(id))
      .map(([id, subject]) => ({
        id, subject, mark: worn(subject, id === selected)!, at: anchors.get(id)!, distance: anchors.get(id)!.distance(this.viewer),
        held: id === selected || speaking.has(id) || deciding.has(id),
      }))
      // Whoever is held first (the picked one, one speaking, one at a decision), then nearest first: a
      // held being and the nearest are always named, and after them a name is drawn only where it can
      // be tied to its being without doubt.
      .sort((a, b) => Number(b.held) - Number(a.held) || a.distance - b.distance || (a.id < b.id ? -1 : 1));
    const budget = this.rule.screenShare * width * height;
    let covered = 0;
    let used = 0;
    let named = 0;
    let nearest = true;
    const unnamed = { small: 0, beyondShare: 0, collides: 0, hidden: 0 };
    // First where everything stands: a model's mark is on its being's head whatever else is drawn,
    // so every one of them is known before any name is.
    const seen: Seen[] = [];
    let first = true;
    for (const one of marked) {
      const screen = this.project(one.at, width, height);
      // Only marks on screen are drawn: one behind the eye takes no name and is no name missed.
      if (screen === null) continue;
      // What the eye cannot see wears nothing. The picked one and one the viewer plays are followed:
      // they keep what they wear, said to be behind something.
      const behind = sees !== null && !sees(this.viewer, one.at);
      if (behind && one.id !== selected && !(one.mark.kind === 'person' && one.mark.mine)) {
        unnamed.hidden += 1;
        continue;
      }
      const tall = heights.get(one.id);
      // How tall it stands on the screen, where the society says how tall it stands at all.
      const stands = tall !== undefined && one.distance > 0 ? tall * pixelsPerMetre / one.distance : null;
      const small = !one.held && stands !== null && stands < this.rule.beingLeastPx;
      // A being a model decides for always wears its mark; anything else too small to name wears nothing.
      // Its mark alone is a dot where it stands lower than the pill is worth; the nearest and a held
      // one wear the pill however small they stand.
      const always = one.mark.kind === 'ai';
      const dot = always && !one.held && !first && stands !== null && stands < this.rule.dotUnderPx;
      if (always && !one.held) first = false;
      const alone = always ? contentOf(one.subject, one.mark, false, null, true, behind, dot) : null;
      if (small && alone === null) {
        unnamed.small += 1;
        continue;
      }
      // The mark is the same whatever is over it: its size is read once, from the mark alone.
      let mark: Size | null = alone === null ? null : this.sizes.get(alone.words) ?? null;
      if (alone !== null && mark === null) {
        const node = this.marks[0] ?? this.markNode();
        this.fill(node, one.id, alone);
        mark = this.sizeOf(node);
      }
      const [x, y] = screen;
      seen.push({ id: one.id, subject: one.subject, mark: one.mark, held: one.held, x, y, small, behind, alone, size: mark, box: mark === null ? null : boxAt(x, y, mark, 0) });
    }
    const names: Box[] = [];
    const overlap = (box: Box, other: Box): boolean =>
      box.right - other.left > TOUCH_PX && other.right - box.left > TOUCH_PX && box.bottom - other.top > TOUCH_PX && other.bottom - box.top > TOUCH_PX;
    this.tops.clear();
    // Then the names, the held first and then nearest first.
    for (const one of seen) {
      const node = this.marks[used] ?? this.markNode();
      const decision = deciding.has(one.id) ? this.decisions.get(one.id)! : null;
      // The whole of it, name and all, from what was read before where it was: nothing is written to learn it.
      const whole = contentOf(one.subject, one.mark, one.held, decision, false, one.behind);
      let size = decision === null ? this.sizes.get(whole.words) : undefined;
      if (size === undefined) {
        this.fill(node, one.id, whole);
        size = this.sizeOf(node);
      }
      // What a name adds: the rows over the mark, which are what the share is spent on and what must
      // cover nothing. A mark no model wears (a game's player, a person's) is all of it.
      const over = boxAt(one.x, one.y, size, one.size?.height ?? 0);
      const cost = (over.right - over.left) * (over.bottom - over.top);
      let why: keyof typeof unnamed | null = null;
      if (one.held) {
        // The picked one, one speaking and one at a decision are named whatever stands by.
      } else if (one.alone !== null) {
        // The nearest a model decides for is named however small it stands; like every other, only
        // where its name covers no name and nobody else's mark.
        if (one.small && !nearest) why = 'small';
        else if (covered + cost > budget) why = 'beyondShare';
        else if (names.some((other) => overlap(over, other)) || seen.some((other) => other !== one && other.box !== null && overlap(over, other.box))) why = 'collides';
        nearest = false;
      } else if (covered + cost > budget) {
        unnamed.beyondShare += 1;
        continue;
      }
      if (why !== null) {
        unnamed[why] += 1;
        this.fill(node, one.id, one.alone!);
        size = one.size!;
      } else {
        this.fill(node, one.id, whole);
        named += 1;
        if (!one.held) covered += cost;
        names.push(over);
      }
      this.tops.set(one.id, size.height);
      this.place(node, one.x, one.y);
      used += 1;
    }
    this.unnamed = unnamed;
    this.named = named;
    // Said on the overlay too, for a page that tells a person how many more there are: written only
    // when it changes, so a frame that draws the same writes nothing.
    const said = `${named} ${unnamed.small} ${unnamed.beyondShare} ${unnamed.collides} ${unnamed.hidden}`;
    if (said !== this.said) {
      this.said = said;
      this.root.dataset['named'] = String(named);
      this.root.dataset['unnamed'] = JSON.stringify(unnamed);
    }
    for (let i = used; i < this.marks.length; i += 1) {
      this.marks[i]!.subject = null;
      hide(this.marks[i]!);
    }
    for (const line of this.lines) {
      const at = line.subject === null || line.until <= nowMs ? undefined : anchors.get(line.subject);
      // A line is never drawn through what hides its speaker, followed or not.
      const screen = at === undefined || (sees !== null && !sees(this.viewer, at)) ? null : this.project(at, width, height);
      if (screen === null) {
        if (line.until <= nowMs) line.subject = null;
        hide(line);
        continue;
      }
      // Over all its speaker wears, or over its head where it wears nothing.
      const stands = this.tops.get(line.subject!);
      this.place(line, screen[0], screen[1] - (stands === undefined ? LINE_LIFT_PX : stands + LINE_GAP_PX));
    }
  }

  /**
   * How many marks, decisions and bubbles are drawn now, how many of the marks are an AI's and how
   * many show their name whole, and how many marked beings in view show no name this frame, by why.
   */
  get counts(): {
    readonly marks: number; readonly aiMarks: number; readonly named: number; readonly lines: number;
    readonly decisions: number; readonly unnamed: UnnamedCounts;
  } {
    const marks = this.marks.filter((node) => node.visible);
    return {
      marks: marks.length,
      aiMarks: marks.filter((node) => node.pill.dataset['mark'] === 'ai').length,
      named: this.named,
      lines: this.lines.filter((node) => node.visible).length,
      decisions: marks.filter((node) => !node.decision.hidden).length,
      unnamed: this.unnamed,
    };
  }

  destroy(): void {
    this.root.remove();
  }

  private project(at: pc.Vec3, width: number, height: number): readonly [number, number] | null {
    this.point.set(at.x, at.y, at.z, 1);
    this.viewProjection.transformVec4(this.point, this.point);
    if (this.point.w <= 1e-6) return null;
    const x = (this.point.x / this.point.w * 0.5 + 0.5) * width;
    const y = (1 - (this.point.y / this.point.w * 0.5 + 0.5)) * height;
    if (x < -SCREEN_MARGIN_PX || y < -SCREEN_MARGIN_PX || x > width + SCREEN_MARGIN_PX || y > height + SCREEN_MARGIN_PX) return null;
    return [x, y];
  }

  private show(node: { root: HTMLElement; visible: boolean }): void {
    if (!node.visible) {
      node.root.style.display = '';
      node.visible = true;
    }
  }

  private place(node: { root: HTMLElement; visible: boolean; at: string }, x: number, y: number): void {
    this.show(node);
    // Centred over the point, standing on it.
    const at = `translate3d(${x.toFixed(1)}px, ${y.toFixed(1)}px, 0) translate(-50%, -100%)`;
    if (at !== node.at) {
      node.root.style.transform = at;
      node.at = at;
    }
  }

  /**
   * A mark's size in CSS pixels, read from the page once for what it shows and kept by those words:
   * a node shown again with words read before is not measured again, so a frame reads no layout
   * unless a name never drawn before is. The sizes kept are as many as the names and labels the
   * society has; a mark with a decision open is kept on its own node only, for as long as it shows
   * those words, since a decision's words are new each time.
   */
  private sizeOf(node: MarkNode): Size {
    const measured = (): Size => {
      // Measured as it will be drawn: a node that is hidden has no size.
      const hidden = !node.visible;
      if (hidden) node.root.style.display = '';
      const size = { width: node.root.offsetWidth, height: node.root.offsetHeight };
      if (hidden) node.root.style.display = 'none';
      return size;
    };
    if (!node.decision.hidden) {
      if (node.open === null || node.open.words !== node.words) node.open = { words: node.words, size: measured() };
      return node.open.size;
    }
    node.open = null;
    let size = this.sizes.get(node.words);
    if (size === undefined) {
      size = measured();
      // A mark alone that is pointed at shows its name for as long: that size is not the mark's.
      if (!node.root.classList.contains('thing-mark-alone') || !node.root.matches(':hover, :focus-within')) this.sizes.set(node.words, size);
    }
    return size;
  }

  /** Write what a node shows, where it differs from what the node shows already. */
  private fill(node: MarkNode, id: string, content: MarkContent): void {
    const filled = [id, content.words, content.name ?? '', content.from ?? '', content.aria, content.held ? 'held' : '', content.behind ? 'behind' : ''].join('\u0000');
    node.subject = id;
    if (filled === node.filled) return;
    node.filled = filled;
    node.words = content.words;
    node.root.classList.toggle('thing-mark-alone', content.alone);
    node.root.classList.toggle('thing-mark-held', content.held);
    node.root.classList.toggle('thing-mark-behind', content.behind);
    node.root.classList.toggle('thing-mark-dot', content.dot);
    node.pill.className = content.pillClass;
    node.pill.dataset['form'] = content.dot ? 'dot' : content.alone ? 'mark' : 'name';
    node.pill.dataset['subject'] = id;
    node.pill.dataset['mark'] = content.kind;
    node.pillWord.textContent = content.word;
    node.pillName.textContent = content.name ?? '';
    node.pillName.hidden = content.name === null;
    node.pillFrom.textContent = content.from ?? '';
    node.pillFrom.hidden = content.from === null;
    node.plate.hidden = content.name === null;
    node.decision.hidden = content.chose === null;
    node.chose.textContent = content.chose ?? '';
    // The decider's own words: empty, hidden and taking no room unless a decision serves any.
    node.said.textContent = content.said;
    node.said.hidden = content.said === '';
    node.pill.setAttribute('aria-label', content.aria);
    node.label.textContent = content.label ?? '';
    node.label.hidden = content.label === null;
  }

  /** A new mark node, kept for reuse: made only when more names fit the view than ever did. */
  private markNode(): MarkNode {
    const root = document.createElement('div');
    root.className = 'thing-mark';
    Object.assign(root.style, { position: 'absolute', left: '0', top: '0', display: 'none', willChange: 'transform' });
    const pill = document.createElement('button');
    pill.type = 'button';
    pill.className = 'thing-mark-pill';
    pill.style.pointerEvents = 'auto';
    const pillWord = document.createElement('span');
    pillWord.className = 'thing-mark-word';
    const pillName = document.createElement('span');
    pillName.className = 'thing-mark-name';
    const pillFrom = document.createElement('span');
    pillFrom.className = 'thing-mark-origin';
    pillFrom.hidden = true;
    const plate = document.createElement('span');
    plate.className = 'thing-mark-plate';
    plate.append(pillName, pillFrom);
    pill.append(pillWord, plate);
    const label = document.createElement('span');
    label.className = 'thing-mark-label';
    const decision = document.createElement('div');
    decision.className = 'thing-mark-decision';
    decision.setAttribute('role', 'status');
    decision.hidden = true;
    const chose = document.createElement('span');
    chose.className = 'thing-mark-chose';
    const said = document.createElement('span');
    said.className = 'thing-mark-said';
    said.hidden = true;
    decision.append(chose, said);
    root.append(pill, label, decision);
    const node: MarkNode = { root, pill, pillWord, pillName, pillFrom, plate, label, decision, chose, said, subject: null, visible: false, at: '', words: '', filled: '', open: null };
    pill.addEventListener('click', () => {
      if (node.subject !== null) this.onPick(node.subject);
    });
    this.root.appendChild(root);
    this.marks.push(node);
    return node;
  }

  private lineNode(): LineNode {
    const root = document.createElement('div');
    root.className = 'thing-line';
    root.setAttribute('role', 'status');
    Object.assign(root.style, { position: 'absolute', left: '0', top: '0', display: 'none', willChange: 'transform' });
    const head = document.createElement('div');
    head.className = 'thing-line-head';
    const pill = document.createElement('span');
    pill.className = 'thing-mark-pill';
    const header = document.createElement('span');
    header.className = 'thing-line-speaker';
    head.append(pill, header);
    const text = document.createElement('div');
    text.className = 'thing-line-text';
    root.append(head, text);
    this.root.appendChild(root);
    return { root, pill, header, text, subject: null, until: 0, visible: false, at: '' };
  }
}

/** Where marked beings stand now: the society drawn (`AuthoredSociety.anchorOf`). */
export interface MarkAnchors {
  anchorOf(id: string, out: pc.Vec3): boolean;
  /** How tall the being stands as drawn, in metres, or null where the society drawn does not say. */
  heightOf?(id: string): number | null;
}

export interface AttachedMarksOptions {
  readonly app: pc.AppBase;
  readonly camera: pc.Entity;
  /** The element the world shows through, which the anchor overlay also writes into. */
  readonly parent: HTMLElement;
  /** The society drawn now, or null while none is. */
  readonly anchors: () => MarkAnchors | null;
  readonly selected: () => string | null;
  readonly onPick: (subjectId: string) => void;
  /** What bounds the marks, as the page's catalog states it. */
  readonly rule: DeciderMarkRule;
  /**
   * Whether a point is seen from the eye in the world drawn now, or null where the page has no
   * answer for it; absent or null, everything is seen (`ThingMarks.update`).
   */
  readonly sees?: () => Sees | null;
  /** Ask for a frame, so marks just set are placed. */
  readonly invalidate?: () => void;
  readonly now?: () => number;
}

/**
 * The marks over a drawn society, placed once a frame after everyone is posed: on the app's
 * `framerender`, which the engine fires every frame after the update in which the controls move the
 * camera and the crowd walks, and before anything is drawn.
 */
export class AttachedMarks {
  readonly overlay: ThingMarks;
  /** One point per marked being, reused frame to frame. */
  private readonly points = new Map<string, pc.Vec3>();
  private readonly found = new Map<string, pc.Vec3>();
  private readonly heights = new Map<string, number>();
  private readonly frame = (): void => this.step();
  private destroyed = false;

  constructor(private readonly options: AttachedMarksOptions) {
    this.overlay = new ThingMarks(options.parent, options.onPick, options.rule);
    options.app.on('framerender', this.frame);
  }

  private get nowMs(): number {
    return (this.options.now ?? (() => performance.now()))();
  }

  /** Who runs each being, as the page decided it (`ThingMarks.setMarks`). */
  set(subjects: ReadonlyMap<string, MarkedSubject>): void {
    this.overlay.setMarks(subjects);
    for (const id of this.points.keys()) if (!subjects.has(id)) this.points.delete(id);
    this.options.invalidate?.();
  }

  /** Show a line over its speaker now (`ThingMarks.showLine`). */
  showLine(line: ThingLine): void {
    this.overlay.showLine(line, this.nowMs);
    this.options.invalidate?.();
  }

  /** Open a decision under its decider's name now (`ThingMarks.showDecision`). */
  showDecision(decision: ThingDecision): void {
    this.overlay.showDecision(decision, this.nowMs);
    this.options.invalidate?.();
  }

  get counts(): ThingMarks['counts'] {
    return this.overlay.counts;
  }

  /** Place every mark and line where its being stands now. */
  step(): void {
    if (this.destroyed) return;
    const now = this.nowMs;
    const society = this.options.anchors();
    this.found.clear();
    this.heights.clear();
    if (society !== null) {
      for (const id of this.overlay.wanted(now, this.options.selected())) {
        let point = this.points.get(id);
        if (point === undefined) {
          point = new pc.Vec3();
          this.points.set(id, point);
        }
        if (!society.anchorOf(id, point)) continue;
        this.found.set(id, point);
        const tall = society.heightOf?.(id) ?? null;
        if (tall !== null) this.heights.set(id, tall);
      }
    }
    this.overlay.update(this.options.camera, this.found, this.options.selected(), now, this.heights, this.options.sees?.() ?? null);
  }

  destroy(): void {
    if (this.destroyed) return;
    this.destroyed = true;
    this.options.app.off('framerender', this.frame);
    this.overlay.destroy();
  }
}
