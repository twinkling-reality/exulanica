/**
 * Who runs each being, marked over it in the world, and the lines it says.
 *
 * Every being a model runs wears a small "AI" pill over its head, and every line a model writes is
 * drawn in a bubble that starts with the same pill; an outside AI agent wears the AI pill outlined
 * as a visitor's, with the name it gave; a being a person runs from outside (a game's player)
 * wears that game's pill instead ("from Block Game"), and a visitor the world's own model runs wears
 * the AI pill with where it came from after the name, quieter ("AI Qwen3 · from Block Game");
 * everyone else wears nothing. What each mark says
 * is the page's to decide, from each being's decider, in the one function the card shares; this
 * overlay only draws what it is given (`setMarks`), so the world and the card never disagree.
 *
 * The overlay is DOM in a fixed pool of nodes, placed each frame by projecting world points, as the
 * anchor overlay is (`../anchor-overlay.ts`): no node is made during a frame, so it cannot grow,
 * and the marks stay readable by a screen reader and checkable in the page. The model's short name
 * shows beside the pill, with the being's label, for the selected being, a speaking one and the
 * three nearest marked beings within 12 m; farther ones show the pill alone, and none is drawn
 * beyond 60 m or off screen. A line's words are set only as text: lines are written by models and
 * players and are never markup. A pill is a button: clicking it picks its being as aiming does.
 */

import * as pc from 'playcanvas';

/**
 * What a being's mark says, as the page decided it. `full` is the mark's words for a screen
 * reader; `outside` is an AI agent from outside the world, `short` its name for itself; `from` is
 * where a visitor this world's model runs came from (a bridge's label).
 */
export type ThingMark =
  | { readonly kind: 'ai'; readonly short: string; readonly full: string; readonly outside?: true; readonly from?: string }
  | { readonly kind: 'from'; readonly label: string; readonly full: string };

export interface MarkedSubject {
  readonly mark: ThingMark | null;
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

/** At most this many pills: the measured budget's full places. */
export const MARKS_MAXIMUM = 64;
/** At most this many bubbles at once. */
export const LINES_MAXIMUM = 4;
/** Pills beyond this many metres are not drawn. */
export const MARK_RANGE_METRES = 60;
/** The short name shows over this many nearest marked beings within `NAME_RANGE_METRES`. */
export const NAMED_NEAREST = 3;
export const NAME_RANGE_METRES = 12;
/** How long a line stays: two seconds and 55 ms a character, at most nine seconds. */
export const lineSeconds = (text: string): number => Math.min(9, 2 + 0.055 * [...text].length);
/** How far over its speaker's mark a bubble stands, in CSS pixels. */
const LINE_LIFT_PX = 34;
/** A point this far off screen, in CSS pixels, is not drawn. */
const SCREEN_MARGIN_PX = 40;

interface MarkNode {
  readonly root: HTMLDivElement;
  readonly pill: HTMLButtonElement;
  readonly pillWord: HTMLSpanElement;
  readonly pillName: HTMLSpanElement;
  /** Where a visitor a model runs came from, after the name, in the quieter weight. */
  readonly pillFrom: HTMLSpanElement;
  readonly label: HTMLSpanElement;
  subject: string | null;
  visible: boolean;
  /** The transform last written, so a mark that has not moved is not written again. */
  at: string;
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

/** The pill's classes: its kind, and an outside agent's outline. */
const pillClass = (mark: ThingMark): string =>
  `thing-mark-pill thing-mark-${mark.kind}${mark.kind === 'ai' && mark.outside === true ? ' thing-mark-outside' : ''}`;

export class ThingMarks {
  readonly root: HTMLDivElement;
  private readonly marks: MarkNode[] = [];
  private readonly lines: LineNode[] = [];
  private subjects: ReadonlyMap<string, MarkedSubject> = new Map();
  private readonly viewProjection = new pc.Mat4();
  private readonly view = new pc.Mat4();
  private readonly point = new pc.Vec4();
  private readonly viewer = new pc.Vec3();

  constructor(parent: HTMLElement, private readonly onPick: (subjectId: string) => void) {
    this.root = document.createElement('div');
    this.root.className = 'thing-marks';
    this.root.setAttribute('role', 'region');
    this.root.setAttribute('aria-label', 'Who runs what you see');
    Object.assign(this.root.style, { position: 'absolute', inset: '0', pointerEvents: 'none', overflow: 'hidden' });
    parent.appendChild(this.root);
    for (let i = 0; i < MARKS_MAXIMUM; i += 1) this.marks.push(this.markNode());
    for (let i = 0; i < LINES_MAXIMUM; i += 1) this.lines.push(this.lineNode());
  }

  /** Who runs each being, as the page decided it; a being it leaves out wears nothing. */
  setMarks(subjects: ReadonlyMap<string, MarkedSubject>): void {
    this.subjects = subjects;
  }

  /** The beings that wear a mark now, and those whose line is shown. */
  wanted(nowMs: number): Set<string> {
    const ids = this.speaking(nowMs);
    for (const [id, subject] of this.subjects) if (subject.mark !== null) ids.add(id);
    return ids;
  }

  /** Show a line over its speaker from `nowMs`, replacing the speaker's last one. */
  showLine(line: ThingLine, nowMs: number): void {
    const node = this.lines.find((one) => one.subject === line.subjectId)
      ?? this.lines.find((one) => one.subject === null || one.until <= nowMs)
      ?? this.lines.reduce((a, b) => (a.until <= b.until ? a : b));
    node.subject = line.subjectId;
    node.until = nowMs + lineSeconds(line.text) * 1000;
    node.pill.className = pillClass(line.mark);
    node.pill.textContent = line.mark.kind === 'ai' ? 'AI' : line.mark.label;
    node.pill.setAttribute('aria-label', line.spoken ?? line.mark.full);
    node.header.textContent = line.header;
    node.text.textContent = line.text;
  }

  /** The beings speaking now: a line of theirs is shown. */
  speaking(nowMs: number): Set<string> {
    return new Set(this.lines.filter((line) => line.subject !== null && line.until > nowMs).map((line) => line.subject!));
  }

  /**
   * Once a frame, after everyone is posed: `anchors` is where each being's mark hangs in the world
   * (over its head); the selected being shows its name.
   */
  update(camera: pc.Entity, anchors: ReadonlyMap<string, pc.Vec3>, selected: string | null, nowMs: number): void {
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
    const marked = [...this.subjects]
      .filter(([id, subject]) => subject.mark !== null && anchors.has(id))
      .map(([id, subject]) => ({ id, subject, at: anchors.get(id)!, distance: anchors.get(id)!.distance(this.viewer) }))
      .filter((one) => one.distance <= MARK_RANGE_METRES)
      .sort((a, b) => a.distance - b.distance || (a.id < b.id ? -1 : 1));
    // Only marks on screen are drawn, and only drawn ones are named: one behind the eye takes no name.
    const drawn: { readonly id: string; readonly subject: MarkedSubject; readonly distance: number; readonly screen: readonly [number, number] }[] = [];
    for (const one of marked) {
      if (drawn.length >= this.marks.length) break;
      const screen = this.project(one.at, width, height);
      if (screen !== null) drawn.push({ ...one, screen });
    }
    const named = new Set(drawn.filter((one) => one.distance <= NAME_RANGE_METRES).slice(0, NAMED_NEAREST).map((one) => one.id));
    let used = 0;
    for (const one of drawn) {
      const node = this.marks[used]!;
      used += 1;
      this.fillMark(node, one.id, one.subject, named.has(one.id) || one.id === selected || speaking.has(one.id));
      this.place(node, one.screen[0], one.screen[1]);
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

  /** How many pills and bubbles are drawn now, and how many of the pills are an AI's. */
  get counts(): { readonly marks: number; readonly aiMarks: number; readonly lines: number } {
    const marks = this.marks.filter((node) => node.visible);
    return {
      marks: marks.length,
      aiMarks: marks.filter((node) => node.pill.dataset['mark'] === 'ai').length,
      lines: this.lines.filter((node) => node.visible).length,
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

  private place(node: { root: HTMLElement; visible: boolean; at: string }, x: number, y: number): void {
    if (!node.visible) {
      node.root.style.display = '';
      node.visible = true;
    }
    // Centred over the point, standing on it.
    const at = `translate3d(${x.toFixed(1)}px, ${y.toFixed(1)}px, 0) translate(-50%, -100%)`;
    if (at !== node.at) {
      node.root.style.transform = at;
      node.at = at;
    }
  }

  private fillMark(node: MarkNode, id: string, subject: MarkedSubject, withName: boolean): void {
    const mark = subject.mark!;
    node.subject = id;
    node.pill.className = pillClass(mark);
    node.pill.dataset['subject'] = id;
    node.pill.dataset['mark'] = mark.kind;
    if (mark.kind === 'ai') {
      node.pillWord.textContent = 'AI';
      node.pillName.textContent = withName ? mark.short : '';
      node.pillName.hidden = !withName;
      node.pillFrom.textContent = mark.from === undefined ? '' : `· from ${mark.from}`;
      node.pillFrom.hidden = mark.from === undefined;
    } else {
      node.pillWord.textContent = mark.label;
      node.pillName.textContent = '';
      node.pillName.hidden = true;
      node.pillFrom.textContent = '';
      node.pillFrom.hidden = true;
    }
    const spoken = subject.spoken ?? mark.full;
    node.pill.setAttribute('aria-label', subject.label === null ? spoken : `${subject.label}: ${spoken}`);
    const label = withName ? subject.label : null;
    node.label.textContent = label ?? '';
    node.label.hidden = label === null;
  }

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
    root.append(pill, label);
    const node: MarkNode = { root, pill, pillWord, pillName, pillFrom, label, subject: null, visible: false, at: '' };
    pill.addEventListener('click', () => {
      if (node.subject !== null) this.onPick(node.subject);
    });
    this.root.appendChild(root);
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
  private readonly frame = (): void => this.step();
  private destroyed = false;

  constructor(private readonly options: AttachedMarksOptions) {
    this.overlay = new ThingMarks(options.parent, options.onPick);
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

  get counts(): ThingMarks['counts'] {
    return this.overlay.counts;
  }

  /** Place every mark and line where its being stands now. */
  step(): void {
    if (this.destroyed) return;
    const now = this.nowMs;
    const society = this.options.anchors();
    this.found.clear();
    if (society !== null) {
      for (const id of this.overlay.wanted(now)) {
        let point = this.points.get(id);
        if (point === undefined) {
          point = new pc.Vec3();
          this.points.set(id, point);
        }
        if (society.anchorOf(id, point)) this.found.set(id, point);
      }
    }
    this.overlay.update(this.options.camera, this.found, this.options.selected(), now);
  }

  destroy(): void {
    if (this.destroyed) return;
    this.destroyed = true;
    this.options.app.off('framerender', this.frame);
    this.overlay.destroy();
  }
}
