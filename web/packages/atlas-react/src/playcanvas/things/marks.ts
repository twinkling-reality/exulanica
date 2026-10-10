/**
 * Who decides for each being, marked over it in the world, what it chose, and the lines it says.
 *
 * Every being a model decides for wears the model's whole name over its head, never in letters
 * smaller than the rule's floor, with a small "AI" word before it; every line a model writes is
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
 * WHEN A DECISION IS TAKEN UP the page hands its words (`showDecision`): a second row opens under
 * the name, saying what was chosen, stays as long as a line of speech of that length would, and
 * closes. It has a place for the decider's own stated words, which stays empty and takes no room
 * until a decision serves any.
 *
 * WHAT IS DRAWN IS BOUNDED BY WHAT CAN BE READ, never by how many beings a model decides for
 * (`DeciderMarkRule`, the page's catalog): a name is drawn over a being that stands tall enough on
 * the screen to be worth naming, nearest first, until the names cover a stated share of the view.
 * Every name not drawn is counted (`counts`, and `data-named` and `data-unnamed` on the overlay's
 * root), so a page can say how many more there are. Each name stands over its own being, the
 * nearest lowest: one that would cover a nearer name stands just above it, so two beings side by
 * side are both named. A being that is picked, speaking or at a decision is named outside the share.
 *
 * The overlay is DOM, placed each frame by projecting world points, as the anchor overlay is
 * (`../anchor-overlay.ts`): nodes are kept and reused, and a new one is made only when more names
 * fit the view than ever did before, which the share of the view bounds. The marks stay readable by
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
 * (`assets/catalogs/thing-presentation/decider-marks.v1.json`): each a value with its class and
 * reason there, none a count of beings.
 */
export interface DeciderMarkRule {
  /** The model's name is never drawn in letters smaller than this, in CSS pixels. */
  readonly nameLeastPx: number;
  /** A name is drawn over a being that stands at least this tall on the screen, in CSS pixels. */
  readonly beingLeastPx: number;
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
/** How far over its speaker's mark a bubble stands, in CSS pixels. */
const LINE_LIFT_PX = 34;
/** A point this far off screen, in CSS pixels, is not drawn. */
const SCREEN_MARGIN_PX = 40;
/** The room between a pill and the nearer one it stands on, in CSS pixels. */
export const MARK_STACK_GAP_PX = 2;

interface MarkNode {
  readonly root: HTMLDivElement;
  readonly pill: HTMLButtonElement;
  readonly pillWord: HTMLSpanElement;
  readonly pillName: HTMLSpanElement;
  /** Where a visitor a model runs came from, after the name, in the quieter weight. */
  readonly pillFrom: HTMLSpanElement;
  readonly label: HTMLSpanElement;
  /** The row under the name that opens at a decision: what was chosen, and the decider's own words. */
  readonly decision: HTMLDivElement;
  readonly chose: HTMLSpanElement;
  readonly said: HTMLSpanElement;
  subject: string | null;
  visible: boolean;
  /** The transform last written, so a mark that has not moved is not written again. */
  at: string;
  /** What it shows now, joined: the key its size is kept under. */
  words: string;
  /** Its size while a decision is open under it, and the words that size was read for. */
  open: { readonly words: string; readonly size: Size } | null;
}

interface Size { readonly width: number; readonly height: number }

/** Why a marked being in view wears no name this frame. */
export interface UnnamedCounts {
  /** It stands too small on the screen to be worth naming. */
  readonly small: number;
  /** The names nearer the viewer already cover the share of the view names may. */
  readonly beyondShare: number;
}

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
  private unnamed: UnnamedCounts = { small: 0, beyondShare: 0 };
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
   * being that is selected, speaking or at a decision shows its label and is always named.
   */
  update(
    camera: pc.Entity, anchors: ReadonlyMap<string, pc.Vec3>, selected: string | null, nowMs: number,
    heights: ReadonlyMap<string, number> = new Map(),
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
      // Nearest first: the nearest name stays over its own being, and the share of the view is spent on the near.
      .sort((a, b) => a.distance - b.distance || (a.id < b.id ? -1 : 1));
    const budget = this.rule.screenShare * width * height;
    let covered = 0;
    let used = 0;
    const unnamed = { small: 0, beyondShare: 0 };
    const placed: { readonly left: number; readonly right: number; readonly top: number; readonly bottom: number }[] = [];
    for (const one of marked) {
      const screen = this.project(one.at, width, height);
      // Only marks on screen are drawn: one behind the eye takes no name and is no name missed.
      if (screen === null) continue;
      const tall = heights.get(one.id);
      if (!one.held && tall !== undefined && one.distance > 0 && tall * pixelsPerMetre / one.distance < this.rule.beingLeastPx) {
        unnamed.small += 1;
        continue;
      }
      const node = this.marks[used] ?? this.markNode();
      this.fillMark(node, one.id, one.subject, one.mark, one.held, deciding.has(one.id) ? this.decisions.get(one.id)! : null);
      const size = this.sizeOf(node);
      const x = screen[0];
      let y = screen[1];
      if (!one.held && covered + size.width * size.height > budget) {
        unnamed.beyondShare += 1;
        continue;
      }
      // Each name stands over its own being, the nearest lowest: one that would cover a name already
      // placed stands just above it, so two beings side by side are both named and neither is hidden.
      for (let moved = true; moved;) {
        moved = false;
        for (const box of placed) {
          if (x + size.width / 2 > box.left && x - size.width / 2 < box.right && y > box.top && y - size.height < box.bottom) {
            y = box.top - MARK_STACK_GAP_PX;
            moved = true;
          }
        }
      }
      if (!one.held) covered += size.width * size.height;
      placed.push({ left: x - size.width / 2, right: x + size.width / 2, top: y - size.height, bottom: y });
      this.place(node, x, y);
      used += 1;
    }
    this.unnamed = unnamed;
    // Said on the overlay too, for a page that tells a person how many more there are: written only
    // when it changes, so a frame that draws the same writes nothing.
    const said = `${used} ${unnamed.small} ${unnamed.beyondShare}`;
    if (said !== this.said) {
      this.said = said;
      this.root.dataset['named'] = String(used);
      this.root.dataset['unnamed'] = JSON.stringify(unnamed);
    }
    for (let i = used; i < this.marks.length; i += 1) {
      this.marks[i]!.subject = null;
      hide(this.marks[i]!);
    }
    for (const line of this.lines) {
      const at = line.subject === null || line.until <= nowMs ? undefined : anchors.get(line.subject);
      const screen = at === undefined ? null : this.project(at, width, height);
      if (screen === null) {
        if (line.until <= nowMs) line.subject = null;
        hide(line);
        continue;
      }
      this.place(line, screen[0], screen[1] - LINE_LIFT_PX);
    }
  }

  /**
   * How many names, decisions and bubbles are drawn now, how many of the names are an AI's, and
   * how many marked beings in view wear no name this frame, by why.
   */
  get counts(): {
    readonly marks: number; readonly aiMarks: number; readonly lines: number; readonly decisions: number;
    readonly unnamed: UnnamedCounts;
  } {
    const marks = this.marks.filter((node) => node.visible);
    return {
      marks: marks.length,
      aiMarks: marks.filter((node) => node.pill.dataset['mark'] === 'ai').length,
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
      this.sizes.set(node.words, size);
    }
    return size;
  }

  private fillMark(
    node: MarkNode, id: string, subject: MarkedSubject, mark: ThingMark, withLabel: boolean,
    decision: { readonly chose: string; readonly said: string | null } | null,
  ): void {
    node.subject = id;
    node.pill.className = pillClass(mark);
    node.pill.dataset['subject'] = id;
    node.pill.dataset['mark'] = mark.kind;
    if (mark.kind === 'ai') {
      // The model's whole name, always: never a word of it, never hidden for being far.
      node.pillWord.textContent = 'AI';
      node.pillName.textContent = mark.name;
      node.pillName.hidden = false;
      node.pillFrom.textContent = mark.from === undefined ? '' : `· from ${mark.from}`;
      node.pillFrom.hidden = mark.from === undefined;
    } else {
      node.pillWord.textContent = mark.label;
      node.pillName.textContent = '';
      node.pillName.hidden = true;
      node.pillFrom.textContent = '';
      node.pillFrom.hidden = true;
    }
    // The page's spoken words are for the mark worn at rest; one worn only while picked says its own.
    const spoken = mark === subject.mark ? subject.spoken ?? mark.full : mark.full;
    const chose = decision?.chose ?? '';
    const said = decision?.said ?? '';
    node.decision.hidden = decision === null;
    node.chose.textContent = chose;
    // The decider's own words: empty, hidden and taking no room unless a decision serves any.
    node.said.textContent = said;
    node.said.hidden = said === '';
    const named = subject.label === null ? spoken : `${subject.label}: ${spoken}`;
    node.pill.setAttribute('aria-label', decision === null ? named : `${named}. ${[chose, said].filter((part) => part !== '').join(' ')}`);
    const label = withLabel ? subject.label : null;
    node.label.textContent = label ?? '';
    node.label.hidden = label === null;
    // What it shows decides its size: the key its size is kept under.
    node.words = [node.pill.className, node.pillWord.textContent, node.pillName.hidden ? '' : node.pillName.textContent,
      node.pillFrom.hidden ? '' : node.pillFrom.textContent, label ?? '', decision === null ? '' : `\u0001${chose}\u0001${said}`].join('\u0000');
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
    pill.append(pillWord, pillName, pillFrom);
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
    const node: MarkNode = { root, pill, pillWord, pillName, pillFrom, label, decision, chose, said, subject: null, visible: false, at: '', words: '', open: null };
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
    this.overlay.update(this.options.camera, this.found, this.options.selected(), now, this.heights);
  }

  destroy(): void {
    if (this.destroyed) return;
    this.destroyed = true;
    this.options.app.off('framerender', this.frame);
    this.overlay.destroy();
  }
}
