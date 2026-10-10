// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';
import * as pc from 'playcanvas';
import {
  AttachedMarks,
  NAME_LEAST_PROPERTY,
  ThingMarks,
  lineSeconds,
  type DeciderMarkRule,
  type MarkedSubject,
  type ThingMark,
} from '../src/playcanvas/things/marks.js';

/*
 * Who decides for each being, marked over it. Expected screen points come from the camera's stated
 * field of view (90 degrees vertical, so a point d metres ahead and y up is y / d of the half
 * height from the centre, and a being h metres tall d metres ahead stands 300 h / d px on this 600
 * px frame), not from the overlay's matrices. The rule is written here, not read from the catalog,
 * so each expectation is arithmetic on these figures.
 */

const WIDTH = 800;
const HEIGHT = 600;

function setup() {
  const canvas = document.createElement('canvas');
  Object.defineProperty(canvas, 'clientWidth', { value: WIDTH });
  Object.defineProperty(canvas, 'clientHeight', { value: HEIGHT });
  const device = new pc.NullGraphicsDevice(canvas);
  const app = new pc.AppBase(canvas);
  const options = new pc.AppOptions();
  options.graphicsDevice = device;
  options.componentSystems = [pc.CameraComponentSystem];
  app.init(options);
  const camera = new pc.Entity('camera');
  camera.addComponent('camera', { fov: 90, nearClip: 0.1, farClip: 1000 });
  camera.camera!.aspectRatioMode = pc.ASPECT_MANUAL;
  camera.camera!.aspectRatio = WIDTH / HEIGHT;
  app.root.addChild(camera);
  const stage = document.createElement('div');
  document.body.appendChild(stage);
  return { app, camera, stage };
}

/** Where a point `ahead` metres in front of a camera at the origin facing -Z, `up` over it, is drawn. */
const screenOf = (ahead: number, up: number, across = 0): [number, number] => [
  (across / (ahead * (WIDTH / HEIGHT)) * 0.5 + 0.5) * WIDTH,
  (1 - (up / ahead * 0.5 + 0.5)) * HEIGHT,
];

const RULE: DeciderMarkRule = {
  nameLeastPx: 14, beingLeastPx: 22, dotUnderPx: 22, screenShare: 0.08, linesAtOnce: 4,
  lineBaseMs: 2000, linePerCharacterMs: 55, lineMostMs: 9000,
};
const NOTHING_UNNAMED = { small: 0, beyondShare: 0, collides: 0, hidden: 0 };

const AI: ThingMark = { kind: 'ai', name: 'Qwen3 235B Instruct', full: 'Qwen3 235B Instruct' };
const AGENT: ThingMark = { kind: 'ai', name: 'Scout', full: 'An outside AI agent, Scout', outside: true };
const BLOCK_GAME: ThingMark = { kind: 'from', label: 'from Block Game', full: 'A person playing Block Game' };
const ROUTINE: ThingMark = { kind: 'routine', label: 'Their own routine', full: 'Their own routine decides for them' };

const marked = (entries: [string, ThingMark | null, string | null, string?][]): Map<string, MarkedSubject> =>
  new Map(entries.map(([id, mark, label, spoken]) => [id, spoken === undefined ? { mark, label } : { mark, label, spoken }]));

function shown(stage: HTMLElement) {
  return Array.from(stage.querySelectorAll<HTMLElement>('.thing-mark'))
    .filter((node) => node.style.display !== 'none')
    .map((node) => {
      const pill = node.querySelector<HTMLButtonElement>('.thing-mark-pill')!;
      const name = node.querySelector<HTMLElement>('.thing-mark-name')!;
      const label = node.querySelector<HTMLElement>('.thing-mark-label')!;
      const origin = node.querySelector<HTMLElement>('.thing-mark-origin')!;
      const decision = node.querySelector<HTMLElement>('.thing-mark-decision')!;
      const said = node.querySelector<HTMLElement>('.thing-mark-said')!;
      return {
        subject: pill.dataset['subject'],
        // 'name' where the whole name shows beside the mark, 'mark' where the being wears the mark alone.
        form: pill.dataset['form'],
        word: node.querySelector('.thing-mark-word')!.textContent,
        name: name.hidden ? null : name.textContent,
        origin: origin.hidden ? null : origin.textContent,
        label: label.hidden ? null : label.textContent,
        chose: decision.hidden ? null : node.querySelector('.thing-mark-chose')!.textContent,
        said: decision.hidden || said.hidden ? null : said.textContent,
        classes: pill.className,
        aria: pill.getAttribute('aria-label'),
        transform: node.style.transform,
      };
    });
}

/**
 * This page lays nothing out, so every mark states the size a browser would give it: a model's mark
 * alone 26 by 24, as a dot 10 by 10, and with its name in the row over it 80 by 48 (so a name adds
 * 80 by 24); any other mark, one row, 80 by 24. `reads` counts how often a size is asked of the page.
 */
const layout = { reads: 0 };
function sized(): () => void {
  const width = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'offsetWidth');
  const height = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'offsetHeight');
  const is = (node: HTMLElement) => node.classList.contains('thing-mark');
  const dot = (node: HTMLElement) => node.classList.contains('thing-mark-dot');
  const wide = (node: HTMLElement) => (dot(node) ? 10 : node.classList.contains('thing-mark-alone') ? 26 : 80);
  const tall = (node: HTMLElement) =>
    (dot(node) ? 10 : node.querySelector('.thing-mark-ai') !== null && !node.classList.contains('thing-mark-alone') ? 48 : 24);
  Object.defineProperty(HTMLElement.prototype, 'offsetWidth', {
    configurable: true,
    get(this: HTMLElement) {
      layout.reads += 1;
      return is(this) ? wide(this) : 0;
    },
  });
  Object.defineProperty(HTMLElement.prototype, 'offsetHeight', { configurable: true, get(this: HTMLElement) { return is(this) ? tall(this) : 0; } });
  return () => {
    if (width) Object.defineProperty(HTMLElement.prototype, 'offsetWidth', width);
    if (height) Object.defineProperty(HTMLElement.prototype, 'offsetHeight', height);
  };
}

const placedAt = (stage: HTMLElement, id: string): number[] =>
  /translate3d\(([-\d.]+)px, ([-\d.]+)px/.exec(shown(stage).find((one) => one.subject === id)!.transform)!.slice(1).map(Number);

describe('marks over the beings a model or someone outside decides for', () => {
  it('hangs each mark over its being, and nothing over one nobody outside its routine runs', () => {
    const { camera, stage } = setup();
    const overlay = new ThingMarks(stage, () => undefined, RULE);
    overlay.setMarks(marked([['knight', AI, 'knight', 'run by an AI model, Qwen3 235B Instruct'], ['villager', null, null], ['visitor', BLOCK_GAME, null]]));
    const anchors = new Map([
      ['knight', new pc.Vec3(0, 1, -5)],
      ['villager', new pc.Vec3(1, 1, -5)],
      ['visitor', new pc.Vec3(2, 0.5, -10)],
    ]);
    overlay.update(camera, anchors, null, 0);
    const marks = shown(stage);
    expect(marks.map((one) => one.subject).sort()).toEqual(['knight', 'visitor']);
    const [x, y] = screenOf(5, 1);
    expect(marks.find((one) => one.subject === 'knight')!.transform).toBe(`translate3d(${x.toFixed(1)}px, ${y.toFixed(1)}px, 0) translate(-50%, -100%)`);
    const [vx, vy] = screenOf(10, 0.5, 2);
    expect(marks.find((one) => one.subject === 'visitor')!.transform).toContain(`translate3d(${vx.toFixed(1)}px, ${vy.toFixed(1)}px, 0)`);
    // A game's player wears the game's pill; an AI the AI word, both with their words for a screen reader.
    expect(marks.find((one) => one.subject === 'visitor')).toMatchObject({ word: 'from Block Game', name: null, aria: 'A person playing Block Game' });
    // The page's words for a screen reader where it gives them, the mark's full words where not.
    expect(marks.find((one) => one.subject === 'knight')).toMatchObject({ word: 'AI', aria: 'knight: run by an AI model, Qwen3 235B Instruct' });
    expect(overlay.counts).toEqual({ marks: 2, aiMarks: 1, named: 2, lines: 0, decisions: 0, unnamed: NOTHING_UNNAMED });
  });

  it('writes a model\'s whole name over its being, never under the floor, without its being picked or near', () => {
    const { camera, stage } = setup();
    const overlay = new ThingMarks(stage, () => undefined, RULE);
    overlay.setMarks(marked([['near', AI, 'knight'], ['far', AI, 'knight']]));
    // 3 m and 55 m off, well apart on the screen.
    overlay.update(camera, new Map([['near', new pc.Vec3(-1, 1, -3)], ['far', new pc.Vec3(20, 1, -55)]]), null, 0);
    const marks = shown(stage);
    for (const id of ['near', 'far']) {
      const mark = marks.find((one) => one.subject === id)!;
      // The whole served name, not its first word; the being's own label only when it is picked.
      expect(mark).toMatchObject({ word: 'AI', name: 'Qwen3 235B Instruct', label: null });
    }
    // The floor for a name's letters is stated on the overlay, in the rule's pixels, for the page's
    // stylesheet to take the larger of.
    expect(NAME_LEAST_PROPERTY).toBe('--thing-mark-name-least');
    expect(stage.querySelector<HTMLElement>('.thing-marks')!.style.getPropertyValue('--thing-mark-name-least')).toBe('14px');
  });

  it('names a being that stands tall enough on the screen, leaves a smaller one a model decides for its mark as a dot, and always names a held one and the nearest', () => {
    const { camera, stage } = setup();
    const overlay = new ThingMarks(stage, () => undefined, RULE);
    const ids = ['a', 'b', 'c', 'd', 'unmeasured', 'behind'];
    overlay.setMarks(new Map<string, MarkedSubject>([
      ...marked(ids.map((id) => [id, AI, `kind ${id}`])),
      // A game's player, as small as d: its pill has no shorter form, so it wears nothing.
      ...marked([['player', BLOCK_GAME, null]]),
    ]));
    const anchors = new Map<string, pc.Vec3>([
      ['a', new pc.Vec3(-6, 1, -5)], ['b', new pc.Vec3(-2, 1, -20)], ['c', new pc.Vec3(4, 1, -23.5)],
      ['d', new pc.Vec3(10, 1, -40)], ['unmeasured', new pc.Vec3(-20, 1, -40)], ['behind', new pc.Vec3(0, 1, 5)],
      ['player', new pc.Vec3(20, 1, -40)],
    ]);
    // Each 1.7 m tall where the society says: 102 px at 5 m, 25.5 px at 20 m, 21.7 px at 23.5 m
    // and 12.75 px at 40 m. The floor is 22 px.
    const tall = new Map(['a', 'b', 'c', 'd', 'behind', 'player'].map((id) => [id, 1.7]));
    overlay.update(camera, anchors, null, 0, tall);
    const formOf = () => Object.fromEntries(shown(stage).map((one) => [one.subject, one.form]));
    // A being whose height the society does not state is named: nothing says it is small. The two
    // too small to name still wear their mark, on their own heads, as a dot (under the 22 px a pill is
    // worth); the player too small wears nothing.
    expect(formOf()).toEqual({ a: 'name', b: 'name', unmeasured: 'name', c: 'dot', d: 'dot' });
    const dots = Array.from(stage.querySelectorAll<HTMLElement>('.thing-mark-dot')).filter((node) => node.style.display !== 'none');
    expect(dots.map((node) => node.querySelector<HTMLElement>('.thing-mark-pill')!.dataset['subject']).sort()).toEqual(['c', 'd']);
    // A dot is a mark alone, so the page's stylesheet opens its name when it is pointed at.
    expect(dots.every((node) => node.classList.contains('thing-mark-alone'))).toBe(true);
    const [dx, dy] = screenOf(40, 1, 10);
    expect(shown(stage).find((one) => one.subject === 'd')).toMatchObject({
      word: 'AI', transform: `translate3d(${dx.toFixed(1)}px, ${dy.toFixed(1)}px, 0) translate(-50%, -100%)`,
      // The name is still the mark's, for a screen reader and for the pointer.
      name: 'Qwen3 235B Instruct', aria: 'kind d: Qwen3 235B Instruct',
    });
    // One behind the eye takes no name and is not a name missed.
    expect(overlay.counts).toMatchObject({ marks: 5, named: 3, unnamed: { small: 3, beyondShare: 0, collides: 0 } });
    // The picked one and a speaking one are named however small they stand, with their labels.
    overlay.showLine({ subjectId: 'd', text: 'Who goes there?', mark: AI, header: 'kind d · Qwen3 235B Instruct' }, 0);
    overlay.update(camera, anchors, 'c', 0, tall);
    const marks = shown(stage);
    expect(formOf()).toEqual({ a: 'name', b: 'name', unmeasured: 'name', c: 'name', d: 'name' });
    expect(marks.find((one) => one.subject === 'c')).toMatchObject({ name: 'Qwen3 235B Instruct', label: 'kind c' });
    expect(marks.find((one) => one.subject === 'd')).toMatchObject({ label: 'kind d' });
    expect(marks.find((one) => one.subject === 'a')).toMatchObject({ label: null });
    expect(overlay.counts.unnamed.small).toBe(1);
    // Where everyone a model decides for is small, the nearest of them is named all the same.
    anchors.delete('a');
    anchors.delete('b');
    anchors.delete('unmeasured');
    overlay.update(camera, anchors, null, 10_000, tall);
    expect(formOf()).toEqual({ c: 'name', d: 'dot' });
    expect(stage.querySelectorAll('.thing-mark-dot').length).toBe(1);
    // The height a mark is a dot under is the rule's own, apart from the height a name is drawn at:
    // at 16 px the one that stands 21.7 px wears the pill and the one at 12.75 px the dot; where the
    // rule states none (0, the catalog's first version) nothing is a dot.
    anchors.set('a', new pc.Vec3(-6, 1, -5));
    const apart = new ThingMarks(stage, () => undefined, { ...RULE, dotUnderPx: 16 });
    apart.setMarks(marked(['a', 'c', 'd'].map((id) => [id, AI, null])));
    apart.update(camera, anchors, null, 0, tall);
    const formsIn = (overlay: ThingMarks) => Object.fromEntries(Array.from(overlay.root.querySelectorAll<HTMLElement>('.thing-mark'))
      .filter((node) => node.style.display !== 'none')
      .map((node) => node.querySelector<HTMLElement>('.thing-mark-pill')!).map((pill) => [pill.dataset['subject'], pill.dataset['form']]));
    expect(formsIn(apart)).toEqual({ a: 'name', c: 'mark', d: 'dot' });
    const none = new ThingMarks(stage, () => undefined, { ...RULE, dotUnderPx: 0 });
    none.setMarks(marked(['a', 'c', 'd'].map((id) => [id, AI, null])));
    none.update(camera, anchors, null, 0, tall);
    expect(formsIn(none)).toEqual({ a: 'name', c: 'mark', d: 'mark' });
  });

  it('draws a crowd far off as a row of dots that do not cover each other, where pills would', () => {
    const restore = sized();
    try {
      const { camera, stage } = setup();
      // Five people 1.7 m tall 40 m off (12.75 px on this frame), 2 m apart across: 15 px between
      // heads. A walker 5 m off is the nearest and is named.
      const ids = ['p0', 'p1', 'p2', 'p3', 'p4'];
      const anchors = new Map<string, pc.Vec3>([['walker', new pc.Vec3(-4, 1, -5)], ...ids.map((id, i) => [id, new pc.Vec3(2 * i, 1, -40)] as [string, pc.Vec3])]);
      const tall = new Map([...anchors.keys()].map((id) => [id, 1.7]));
      const boxes = (overlay: ThingMarks) => ids.map((id) => {
        const node = Array.from(overlay.root.querySelectorAll<HTMLElement>('.thing-mark'))
          .find((one) => one.style.display !== 'none' && one.querySelector<HTMLElement>('.thing-mark-pill')!.dataset['subject'] === id)!;
        const [x] = /translate3d\(([-\d.]+)px/.exec(node.style.transform)!.slice(1).map(Number) as [number];
        return [x - node.offsetWidth / 2, x + node.offsetWidth / 2] as const;
      });
      const overlapping = (spans: readonly (readonly [number, number])[]) => spans.filter((span, i) => i > 0 && span[0] < spans[i - 1]![1]).length;
      const dotted = new ThingMarks(stage, () => undefined, RULE);
      dotted.setMarks(marked([...anchors.keys()].map((id) => [id, AI, null])));
      dotted.update(camera, anchors, null, 0, tall);
      // Every one of the five wears its mark, as a dot 10 px wide on its own head, 15 px from the next.
      expect(dotted.counts).toMatchObject({ marks: 6, named: 1, unnamed: { small: 5 } });
      expect(dotted.root.querySelectorAll('.thing-mark-dot').length).toBe(5);
      expect(overlapping(boxes(dotted))).toBe(0);
      const [x0] = screenOf(40, 1, 0);
      expect(boxes(dotted)[0]).toEqual([Number(x0.toFixed(1)) - 5, Number(x0.toFixed(1)) + 5]);
      // The same five as pills 26 px wide (a rule that states no such height) cover each other.
      const pills = new ThingMarks(stage, () => undefined, { ...RULE, dotUnderPx: 0 });
      pills.setMarks(marked([...anchors.keys()].map((id) => [id, AI, null])));
      pills.update(camera, anchors, null, 0, tall);
      expect(overlapping(boxes(pills))).toBe(4);
      const formsIn = (overlay: ThingMarks) => Object.fromEntries(Array.from(overlay.root.querySelectorAll<HTMLElement>('.thing-mark'))
        .filter((node) => node.style.display !== 'none')
        .map((node) => node.querySelector<HTMLElement>('.thing-mark-pill')!).map((pill) => [pill.dataset['subject'], pill.dataset['form']]));
      // A dot takes a dot's room, not a pill's. A guard 10 m off stands 51 px; someone far off on a
      // roof is 30 px over the guard's head on the screen and 44 px to the side. Their dot, 10 px
      // wide, ends a pixel inside the guard's name (80 wide), which only touches it: the guard is
      // named. A pill there, 26 px wide, would be 9 px into the name and the guard would lose it.
      const roomy = new ThingMarks(stage, () => undefined, RULE);
      roomy.setMarks(marked([['near', AI, null], ['guard', AI, null], ['roof', AI, null]]));
      const roof = new Map([['near', new pc.Vec3(-6, 1, -5)], ['guard', new pc.Vec3(0, 1, -10)], ['roof', new pc.Vec3(5.8667, 8, -40)]]);
      const [gx, gy] = screenOf(10, 1);
      const [rx, ry] = screenOf(40, 8, 5.8667);
      expect([Math.round(rx - gx), Math.round(gy - ry)]).toEqual([44, 30]);
      roomy.update(camera, roof, null, 0, new Map([['near', 1.7], ['guard', 1.7], ['roof', 1.7]]));
      expect(formsIn(roomy)).toEqual({ near: 'name', guard: 'name', roof: 'dot' });
      // The nearest wears the pill however small it stands, named or not. Here the nearest stands
      // 21.7 px, and someone on a roof behind has their dot in the row its name would take: it
      // wears its mark alone, as a pill, and the one behind a dot.
      const first = new ThingMarks(stage, () => undefined, RULE);
      first.setMarks(marked([['front', AI, null], ['behind', AI, null]]));
      const pair = new Map([['front', new pc.Vec3(4, 1, -23.5)], ['behind', new pc.Vec3(6.8, 5.7, -40)]]);
      first.update(camera, pair, null, 0, new Map([['front', 1.7], ['behind', 1.7]]));
      expect(formsIn(first)).toEqual({ front: 'mark', behind: 'dot' });
      expect(first.counts.unnamed).toMatchObject({ collides: 1, small: 1 });
    } finally {
      restore();
    }
  });

  it('keeps the nearer name where two would cover each other and leaves the other its mark alone, on its own head', () => {
    const restore = sized();
    try {
      const { camera, stage } = setup();
      const overlay = new ThingMarks(stage, () => undefined, RULE);
      overlay.setMarks(marked([['spirit', AI, 'lantern spirit'], ['traveller', AI, 'traveller'], ['knight', AI, 'knight']]));
      // The traveller stands in the gate 4 m behind the spirit, in line from the camera; the knight is well aside.
      const anchors = new Map([
        ['spirit', new pc.Vec3(0, 1, -5)],
        ['traveller', new pc.Vec3(0, 1.4, -9)],
        ['knight', new pc.Vec3(4, 1, -9)],
      ]);
      overlay.update(camera, anchors, null, 0);
      const [sx, sy] = screenOf(5, 1);
      const [tx, ty] = screenOf(9, 1.4);
      const [kx, ky] = screenOf(9, 1, 4);
      const at = (x: number, y: number) => [Number(x.toFixed(1)), Number(y.toFixed(1))];
      const formOf = () => Object.fromEntries(shown(stage).map((one) => [one.subject, one.form]));
      // Over its own being the traveller's name would cover the spirit's (both 80 by 24 at x 400, in
      // the row over each one's mark, 13 px apart).
      expect(Math.abs(ty - sy)).toBeLessThan(24);
      // The nearer keeps its name. The traveller keeps its mark, and nothing is lifted: every one
      // of the three stands on its own being's head.
      expect(formOf()).toEqual({ spirit: 'name', traveller: 'mark', knight: 'name' });
      expect(placedAt(stage, 'spirit')).toEqual(at(sx, sy));
      expect(placedAt(stage, 'traveller')).toEqual(at(tx, ty));
      expect(placedAt(stage, 'knight')).toEqual(at(kx, ky));
      expect(overlay.counts).toMatchObject({ marks: 3, aiMarks: 3, named: 2, unnamed: { small: 0, beyondShare: 0, collides: 1 } });
      const root = stage.querySelector<HTMLElement>('.thing-marks')!;
      expect([root.dataset['named'], JSON.parse(root.dataset['unnamed']!)]).toEqual(['2', { small: 0, beyondShare: 0, collides: 1, hidden: 0 }]);
      // The mark alone is marked so on its node, which is what the page's stylesheet hides the name by.
      const alone = Array.from(stage.querySelectorAll<HTMLElement>('.thing-mark-alone')).filter((node) => node.style.display !== 'none');
      expect(alone.map((node) => node.querySelector<HTMLElement>('.thing-mark-pill')!.dataset['subject'])).toEqual(['traveller']);
      // Picked, the traveller is named whatever stands by, on its own head still, and drawn over the
      // rest; the spirit's name would cover the picked one's now, so the spirit wears its mark alone.
      overlay.update(camera, anchors, 'traveller', 0);
      expect(formOf()).toEqual({ spirit: 'mark', traveller: 'name', knight: 'name' });
      expect(placedAt(stage, 'traveller')).toEqual(at(tx, ty));
      expect(overlay.counts.unnamed).toEqual({ small: 0, beyondShare: 0, collides: 1, hidden: 0 });
      const held = Array.from(stage.querySelectorAll<HTMLElement>('.thing-mark-held')).filter((node) => node.style.display !== 'none');
      expect(held.map((node) => node.querySelector<HTMLElement>('.thing-mark-pill')!.dataset['subject'])).toEqual(['traveller']);
      // One sits on a bench and one stands just behind, 30 cm taller: the stander's mark is in the
      // row a name over the sitter would take (14 px up the screen, 11 px across). A name is never
      // drawn over somebody else's mark, the nearest's no more than another's: the sitter wears the
      // mark alone and the stander, whose name covers nothing, is the one named.
      overlay.setMarks(marked([['sitter', AI, null], ['stander', AI, null]]));
      const pair = new Map([['sitter', new pc.Vec3(0, 1, -5)], ['stander', new pc.Vec3(0.2, 1.3, -5.3)]]);
      overlay.update(camera, pair, null, 0);
      const [, sitY] = screenOf(5, 1);
      const [standX, standY] = screenOf(5.3, 1.3, 0.2);
      expect([Math.round(sitY - standY), Math.round(standX - 400)]).toEqual([14, 11]);
      expect(formOf()).toEqual({ sitter: 'mark', stander: 'name' });
      expect(overlay.counts).toMatchObject({ marks: 2, named: 1, unnamed: { collides: 1 } });
      // Three near a bench 5 m off. The middle one's name would cover the nearest's, so it wears the
      // mark alone (26 by 24, on its head). The third sits 20 cm lower, 12 px down the screen: its
      // name (from x 426) clears the nearest's name (to x 422) and would cover only the middle
      // one's mark (to x 431, and 12 px into its row). A mark is its being's too, so the third
      // wears the mark alone as well.
      overlay.setMarks(marked([['left', AI, null], ['middle', AI, null], ['right', AI, null]]));
      const bench = new Map([['left', new pc.Vec3(-0.3, 1, -5)], ['middle', new pc.Vec3(0.3, 1, -5.01)], ['right', new pc.Vec3(1.1, 0.8, -5.02)]]);
      overlay.update(camera, bench, null, 0);
      const [lx, ly] = screenOf(5, 1, -0.3);
      const [mx, my] = screenOf(5.01, 1, 0.3);
      const [rx, ry] = screenOf(5.02, 0.8, 1.1);
      expect([lx + 40, mx + 13, rx - 40, ry - my].map((v) => Math.round(v))).toEqual([422, 431, 426, 12]);
      expect(formOf()).toEqual({ left: 'name', middle: 'mark', right: 'mark' });
      expect(placedAt(stage, 'left')).toEqual(at(lx, ly));
      expect(placedAt(stage, 'middle')).toEqual(at(mx, my));
      expect(placedAt(stage, 'right')).toEqual(at(rx, ry));
      expect(overlay.counts.unnamed.collides).toBe(2);
      // Sitting as high as the others, its name stands in the row over the marks and covers none of
      // them: three in a row wear three marks side by side and two names.
      bench.get('right')!.set(1.1, 1, -5.02);
      overlay.update(camera, bench, null, 0);
      expect(formOf()).toEqual({ left: 'name', middle: 'mark', right: 'name' });
    } finally {
      restore();
    }
  });

  it('spends a share of the view on names, nearest first, and leaves every being beyond it its mark alone, counted', () => {
    const restore = sized();
    try {
      const { camera, stage } = setup();
      const overlay = new ThingMarks(stage, () => undefined, RULE);
      // Thirty beings in thirty directions, 3 m apart across and 2 m apart up at 10 m ahead (90 px
      // by 60 px between marks 26 by 24 with names 80 by 24 over them, so no name covers a name or
      // a mark), each 5 cm farther from the eye than the one before along its own direction, which
      // leaves it where it is on the screen.
      const ids = Array.from({ length: 30 }, (_, i) => `p${String(i).padStart(2, '0')}`);
      overlay.setMarks(marked(ids.map((id) => [id, AI, null])));
      const anchors = new Map(ids.map((id, i) => {
        const toward = new pc.Vec3(-12 + 3 * (i % 9), -3 + 2 * Math.floor(i / 9), -10).normalize();
        return [id, toward.mulScalar(10 + 0.05 * i)];
      }));
      overlay.update(camera, anchors, null, 0);
      const names = () => shown(stage).filter((one) => one.form === 'name').map((one) => one.subject).sort();
      // The view is 800 by 600 and the share 0.08: 38,400 px of it, which is twenty names of 1,920 px
      // (what a name adds over its mark; the marks themselves are no part of the share).
      // All thirty wear their mark; the nearest twenty their name with it.
      expect(shown(stage).map((one) => one.subject).sort()).toEqual(ids);
      expect(names()).toEqual(ids.slice(0, 20));
      expect(overlay.counts).toMatchObject({ marks: 30, named: 20, unnamed: { small: 0, beyondShare: 10, collides: 0 } });
      // The overlay says the same on its root, for a page that tells a person how many more there are.
      const root = stage.querySelector<HTMLElement>('.thing-marks')!;
      expect([root.dataset['named'], JSON.parse(root.dataset['unnamed']!)]).toEqual(['20', { small: 0, beyondShare: 10, collides: 0, hidden: 0 }]);
      // The picked one is named outside the share, and takes none of it from the near.
      overlay.update(camera, anchors, 'p29', 0);
      expect(names()).toEqual([...ids.slice(0, 20), 'p29']);
      expect(overlay.counts.unnamed.beyondShare).toBe(9);
      expect([root.dataset['named'], JSON.parse(root.dataset['unnamed']!).beyondShare]).toEqual(['21', 9]);
      // Picked among the nearest, it still takes none of the share: twenty others are named with it.
      overlay.update(camera, anchors, 'p00', 0);
      expect(names()).toEqual(ids.slice(0, 21));
      // A game's player beyond the share has no shorter form: it wears nothing and is counted.
      overlay.setMarks(new Map([...marked(ids.map((id) => [id, AI, null])), ...marked([['player', BLOCK_GAME, null]])]));
      anchors.set('player', new pc.Vec3(-12, 4.5, -10).normalize().mulScalar(12));
      overlay.update(camera, anchors, null, 0);
      expect(shown(stage).some((one) => one.subject === 'player')).toBe(false);
      expect(overlay.counts).toMatchObject({ marks: 30, named: 20, unnamed: { beyondShare: 11 } });
    } finally {
      restore();
    }
  });

  it('makes a node only when more marks are in view than ever were, and writes and reads nothing to draw the same again', () => {
    const restore = sized();
    try {
      const { camera, stage } = setup();
      const overlay = new ThingMarks(stage, () => undefined, RULE);
      const ids = Array.from({ length: 200 }, (_, i) => `p${String(i).padStart(3, '0')}`);
      overlay.setMarks(marked(ids.map((id) => [id, AI, null])));
      const anchors = new Map(ids.map((id, i) => [id, new pc.Vec3((i % 20) - 10, 1, -5 - Math.floor(i / 20))]));
      layout.reads = 0;
      overlay.update(camera, anchors, null, 0);
      const { marks, named, unnamed } = overlay.counts;
      // Every marked being on the screen (within the overlay's 40 px margin) wears its mark, each
      // is either named or counted, and the share bounds the named.
      const onScreen = ids.filter((_, i) => {
        const [x, y] = screenOf(5 + Math.floor(i / 20), 1, (i % 20) - 10);
        return x >= -40 && x <= WIDTH + 40 && y >= -40 && y <= HEIGHT + 40;
      }).length;
      expect(onScreen).toBeGreaterThan(100);
      expect(marks).toBe(onScreen);
      expect(named).toBeGreaterThan(0);
      expect(named).toBeLessThanOrEqual(20);
      expect(named + unnamed.small + unnamed.beyondShare + unnamed.collides).toBe(onScreen);
      // A node for each, and no more.
      expect(stage.querySelectorAll('.thing-mark').length).toBe(marks);
      // One mark alone and one with its name were measured: two sizes, however many wear them.
      expect(layout.reads).toBe(2);
      const nodes = stage.querySelectorAll('*').length;
      // The same frame again: no node made, no size read, and nothing written into a mark (every
      // write of a mark's words sets its spoken words too).
      const written = vi.spyOn(HTMLElement.prototype, 'setAttribute');
      overlay.update(camera, anchors, null, 16);
      expect(stage.querySelectorAll('*').length).toBe(nodes);
      expect(layout.reads).toBe(2);
      expect(written.mock.calls.length).toBe(0);
      written.mockRestore();
    } finally {
      restore();
    }
  });

  it('draws where a visitor the world\'s model runs came from after the model\'s whole name, near or far, and nowhere else', () => {
    const { camera, stage } = setup();
    const overlay = new ThingMarks(stage, () => undefined, RULE);
    const RUN_HERE: ThingMark = { kind: 'ai', name: 'Qwen3 235B Instruct', full: 'Qwen3 235B Instruct', from: 'Block Game' };
    overlay.setMarks(marked([['near', RUN_HERE, null], ['far', RUN_HERE, null], ['knight', AI, null], ['player', BLOCK_GAME, null]]));
    const anchors = new Map([
      ['near', new pc.Vec3(0, 1, -4)], ['far', new pc.Vec3(8, 1, -30)],
      ['knight', new pc.Vec3(1, 1, -5)], ['player', new pc.Vec3(-1, 1, -5)],
    ]);
    overlay.update(camera, anchors, null, 0);
    const marks = shown(stage);
    for (const id of ['near', 'far']) {
      expect(marks.find((one) => one.subject === id)).toMatchObject({ word: 'AI', name: 'Qwen3 235B Instruct', origin: '· from Block Game' });
    }
    expect(marks.find((one) => one.subject === 'knight')).toMatchObject({ origin: null });
    expect(marks.find((one) => one.subject === 'player')).toMatchObject({ word: 'from Block Game', origin: null });
    // A node marked again keeps nothing of its last origin, whichever mark it now wears.
    overlay.setMarks(marked([['near', AI, null]]));
    overlay.update(camera, anchors, null, 0);
    expect(shown(stage).find((one) => one.subject === 'near')).toMatchObject({ origin: null });
    overlay.setMarks(marked([['near', RUN_HERE, null]]));
    overlay.update(camera, anchors, null, 0);
    overlay.setMarks(marked([['near', BLOCK_GAME, null]]));
    overlay.update(camera, anchors, null, 0);
    expect(shown(stage).find((one) => one.subject === 'near')).toMatchObject({ word: 'from Block Game', name: null, origin: null });
  });

  it('outlines an outside agent\'s AI pill with the name it gave, and picks a being when its pill is clicked', () => {
    const { camera, stage } = setup();
    const onPick = vi.fn();
    const overlay = new ThingMarks(stage, onPick, RULE);
    overlay.setMarks(marked([['agent', AGENT, null]]));
    overlay.update(camera, new Map([['agent', new pc.Vec3(0, 1, -4)]]), null, 0);
    const [mark] = shown(stage);
    expect(mark!.classes.split(' ').sort()).toEqual(['thing-mark-ai', 'thing-mark-outside', 'thing-mark-pill']);
    expect(mark).toMatchObject({ word: 'AI', name: 'Scout', aria: 'An outside AI agent, Scout' });
    stage.querySelector<HTMLButtonElement>('.thing-mark-pill[data-subject="agent"]')!.click();
    expect(onPick).toHaveBeenCalledWith('agent');
  });

  it('marks a being a person plays with the person pill, never an AI\'s, and opens their lines with Person', () => {
    const { camera, stage } = setup();
    const overlay = new ThingMarks(stage, () => undefined, RULE);
    // The words agreed with lane UI for Play this one: "You" to the one playing, "Played" to others.
    const YOU: ThingMark = { kind: 'person', mine: true, label: 'You', full: 'Played by you' };
    const PLAYED: ThingMark = { kind: 'person', mine: false, label: 'Played', full: 'Played by another person' };
    overlay.setMarks(marked([['knight', YOU, 'knight'], ['spirit', PLAYED, 'lantern spirit']]));
    const anchors = new Map([['knight', new pc.Vec3(0, 1, -5)], ['spirit', new pc.Vec3(1, 1, -5)]]);
    overlay.update(camera, anchors, null, 0);
    const marks = shown(stage);
    expect(marks.find((one) => one.subject === 'knight')).toMatchObject({ word: 'You', name: null, origin: null, aria: 'knight: Played by you' });
    expect(marks.find((one) => one.subject === 'knight')!.classes.split(' ').sort()).toEqual(['thing-mark-person', 'thing-mark-pill']);
    expect(marks.find((one) => one.subject === 'spirit')).toMatchObject({ word: 'Played', aria: 'lantern spirit: Played by another person' });
    expect(overlay.counts).toMatchObject({ marks: 2, aiMarks: 0, lines: 0 });
    const line: ThingMark = { kind: 'person', mine: false, label: 'Person', full: 'Played by a person' };
    overlay.showLine({ subjectId: 'knight', text: 'Could I borrow your sword?', mark: line, header: 'knight · played by a person', spoken: 'Played by a person' }, 0);
    overlay.update(camera, anchors, null, 0);
    const pill = stage.querySelector<HTMLElement>('.thing-line .thing-mark-pill')!;
    expect([pill.textContent, pill.getAttribute('aria-label')]).toEqual(['Person', 'Played by a person']);
    expect(pill.className.split(' ').sort()).toEqual(['thing-mark-person', 'thing-mark-pill']);
  });

  it('says a being\'s own routine decides only while that being is the picked one', () => {
    const { camera, stage } = setup();
    const overlay = new ThingMarks(stage, () => undefined, RULE);
    const routine = (label: string): MarkedSubject => ({ mark: null, picked: ROUTINE, label });
    overlay.setMarks(new Map<string, MarkedSubject>([
      ['baker', routine('baker')], ['miller', routine('miller')], ['knight', { mark: AI, label: 'knight', spoken: 'run by an AI model, Qwen3 235B Instruct' }],
    ]));
    const anchors = new Map([['baker', new pc.Vec3(-2, 1, -5)], ['miller', new pc.Vec3(2, 1, -5)], ['knight', new pc.Vec3(0, 1, -8)]]);
    // At rest the routine's people wear nothing, and are not asked after.
    overlay.update(camera, anchors, null, 0);
    expect(shown(stage).map((one) => one.subject)).toEqual(['knight']);
    expect([...overlay.wanted(0)].sort()).toEqual(['knight']);
    expect([...overlay.wanted(0, 'baker')].sort()).toEqual(['baker', 'knight']);
    overlay.update(camera, anchors, 'baker', 0);
    const marks = shown(stage);
    expect(marks.map((one) => one.subject).sort()).toEqual(['baker', 'knight']);
    const baker = marks.find((one) => one.subject === 'baker')!;
    expect(baker).toMatchObject({ word: 'Their own routine', name: null, label: 'baker', aria: 'baker: Their own routine decides for them' });
    expect(baker.classes.split(' ').sort()).toEqual(['thing-mark-pill', 'thing-mark-routine']);
    // It is no AI's mark, and it goes when another is picked.
    expect(overlay.counts).toMatchObject({ marks: 2, aiMarks: 1 });
    overlay.update(camera, anchors, 'knight', 0);
    expect(shown(stage).map((one) => one.subject)).toEqual(['knight']);
  });

  it('opens what the decider chose under its name, for as long as its words allow, with a place for its own words that takes no room', () => {
    const { camera, stage } = setup();
    const overlay = new ThingMarks(stage, () => undefined, RULE);
    overlay.setMarks(marked([['knight', AI, 'knight', 'run by an AI model, Qwen3 235B Instruct'], ['baker', null, 'baker']]));
    const anchors = new Map([['knight', new pc.Vec3(0, 1, -5)], ['baker', new pc.Vec3(3, 1, -5)]]);
    overlay.update(camera, anchors, null, 0);
    expect(shown(stage)[0]).toMatchObject({ chose: null, said: null, label: null });
    const chose = 'Chose “<b>walk</b> to the well”.';
    overlay.showDecision({ subjectId: 'knight', chose }, 1000);
    // A decision for a being that wears no mark opens nothing.
    overlay.showDecision({ subjectId: 'baker', chose: 'Chose “rest”.' }, 1000);
    overlay.update(camera, anchors, null, 1000);
    const [open] = shown(stage);
    expect(shown(stage).length).toBe(1);
    // Its words are text, never markup; the being's label shows while it is at a decision.
    expect(open).toMatchObject({ subject: 'knight', chose, said: null, label: 'knight' });
    expect(stage.querySelector('.thing-mark-decision b')).toBeNull();
    expect(open!.aria).toBe(`knight: run by an AI model, Qwen3 235B Instruct. ${chose}`);
    const said = stage.querySelector<HTMLElement>('.thing-mark[style*="translate3d"] .thing-mark-said')!;
    expect([said.hidden, said.textContent]).toEqual([true, '']);
    expect(overlay.counts.decisions).toBe(1);
    // Two seconds and 55 ms a character: 32 characters stay 3.76 s.
    expect([...chose].length).toBe(32);
    overlay.update(camera, anchors, null, 1000 + 3759);
    expect(shown(stage)[0]!.chose).toBe(chose);
    overlay.update(camera, anchors, null, 1000 + 3761);
    expect(shown(stage)[0]).toMatchObject({ chose: null, label: null, aria: 'knight: run by an AI model, Qwen3 235B Instruct' });
    expect(overlay.counts.decisions).toBe(0);
    // Where a decision serves the decider's own words, they follow what it chose.
    overlay.showDecision({ subjectId: 'knight', chose: 'Chose “rest”.', said: 'It said: my legs ache.' }, 5000);
    overlay.update(camera, anchors, null, 5000);
    expect(shown(stage)[0]).toMatchObject({ chose: 'Chose “rest”.', said: 'It said: my legs ache.' });
    expect(shown(stage)[0]!.aria).toBe('knight: run by an AI model, Qwen3 235B Instruct. Chose “rest”. It said: my legs ache.');
  });

  it('writes a line as text over its speaker, for as long as its length allows', () => {
    const { camera, stage } = setup();
    const overlay = new ThingMarks(stage, () => undefined, RULE);
    overlay.setMarks(marked([['knight', AI, 'knight']]));
    const anchors = new Map([['knight', new pc.Vec3(0, 1, -5)]]);
    const words = '<img src=x onerror=alert(1)> Halt!';
    overlay.showLine({ subjectId: 'knight', text: words, mark: AI, header: 'knight · Qwen3 235B Instruct' }, 1000);
    overlay.update(camera, anchors, null, 1000);
    const line = stage.querySelector<HTMLElement>('.thing-line')!;
    expect(line.style.display).toBe('');
    expect(line.querySelector('.thing-line-text')!.textContent).toBe(words);
    expect(line.querySelector('img')).toBeNull();
    expect(line.querySelector('.thing-line-speaker')!.textContent).toBe('knight · Qwen3 235B Instruct');
    expect(line.querySelector('.thing-mark-pill')!.textContent).toBe('AI');
    // Two seconds and 55 ms a character: 34 characters stay 3.87 s; never longer than nine.
    expect(lineSeconds(words, RULE)).toBeCloseTo(2 + 0.055 * 34, 9);
    expect(lineSeconds('x'.repeat(400), RULE)).toBe(9);
    overlay.update(camera, anchors, null, 1000 + 3869);
    expect(overlay.counts.lines).toBe(1);
    overlay.update(camera, anchors, null, 1000 + 3871);
    expect(overlay.counts.lines).toBe(0);
    expect(overlay.speaking(1000 + 3871).size).toBe(0);
    // As many lines are open at once as the rule states, the next taking the place of the oldest.
    for (let i = 0; i < 6; i += 1) overlay.showLine({ subjectId: `s${i}`, text: 'Hello.', mark: AI, header: `s${i}` }, 9000 + i);
    expect(stage.querySelectorAll('.thing-line').length).toBe(4);
    expect([...overlay.speaking(9010)].sort()).toEqual(['s2', 's3', 's4', 's5']);
  });

  it('leaves a being the eye cannot see unmarked and unheard, counted, and marks a followed one as behind something', () => {
    const restore = sized();
    try {
      const { camera, stage } = setup();
      const overlay = new ThingMarks(stage, () => undefined, RULE);
      const YOU: ThingMark = { kind: 'person', mine: true, label: 'You', full: 'Played by you' };
      const PLAYED: ThingMark = { kind: 'person', mine: false, label: 'Played', full: 'Played by another person' };
      overlay.setMarks(marked([
        ['open', AI, 'knight'], ['walled', AI, 'baker'], ['mine', YOU, 'squire'], ['theirs', PLAYED, 'page'], ['near', AI, null],
      ]));
      // A wall stands across the view 8 m ahead: everything farther is behind it. The page's answer
      // is asked with the eye and the point over each being's head.
      const asked: [number, number][] = [];
      const sees = (eye: pc.Vec3, point: pc.Vec3): boolean => {
        asked.push([eye.z, point.z]);
        return point.z > -8;
      };
      const anchors = new Map([
        ['open', new pc.Vec3(-3, 1, -5)], ['walled', new pc.Vec3(0, 1, -12)], ['mine', new pc.Vec3(3, 1, -12)],
        ['theirs', new pc.Vec3(-3, 1, -12)],
        // In line with the hidden one and 5 px under it on the screen: the hidden one's mark is not
        // there to be covered, so this one is named.
        ['near', new pc.Vec3(0, 1.2, -6)],
      ]);
      overlay.update(camera, anchors, null, 0, new Map(), sees);
      const worn = () => Object.fromEntries(shown(stage).map((one) => [one.subject, one.form]));
      const behind = () => Array.from(stage.querySelectorAll<HTMLElement>('.thing-mark-behind'))
        .filter((node) => node.style.display !== 'none').map((node) => node.querySelector<HTMLElement>('.thing-mark-pill')!.dataset['subject']);
      // Behind the wall: the model's being and the one another person plays wear nothing. The one
      // the viewer plays is followed: it keeps its pill, said to be behind something.
      expect(worn()).toEqual({ open: 'name', near: 'name', mine: 'name' });
      expect(behind()).toEqual(['mine']);
      expect(overlay.counts.unnamed).toEqual({ small: 0, beyondShare: 0, collides: 0, hidden: 2 });
      expect(JSON.parse(stage.querySelector<HTMLElement>('.thing-marks')!.dataset['unnamed']!).hidden).toBe(2);
      expect(asked.every(([eyeZ]) => eyeZ === 0)).toBe(true);
      // Picked, the model's being behind the wall is followed too, with its name and its word.
      overlay.update(camera, anchors, 'walled', 0, new Map(), sees);
      expect(worn()).toMatchObject({ walled: 'name', mine: 'name' });
      expect(behind().sort()).toEqual(['mine', 'walled']);
      expect(shown(stage).find((one) => one.subject === 'walled')).toMatchObject({ name: 'Qwen3 235B Instruct', label: 'baker' });
      expect(overlay.counts.unnamed.hidden).toBe(1);
      // A line of speech is never drawn through the wall, not even the picked one's; one in the open is.
      overlay.showLine({ subjectId: 'walled', text: 'Bread!', mark: AI, header: 'baker' }, 0);
      overlay.showLine({ subjectId: 'open', text: 'Halt!', mark: AI, header: 'knight' }, 0);
      overlay.update(camera, anchors, 'walled', 0, new Map(), sees);
      const heard = Array.from(stage.querySelectorAll<HTMLElement>('.thing-line')).filter((node) => node.style.display !== 'none')
        .map((node) => node.querySelector('.thing-line-speaker')!.textContent);
      expect(heard).toEqual(['knight']);
      // Seen again, it is behind nothing; and with no answer from the page everything is seen.
      anchors.get('walled')!.set(0, 1, -7.5);
      overlay.update(camera, anchors, 'walled', 0, new Map(), sees);
      expect(behind()).toEqual(['mine']);
      overlay.update(camera, anchors, null, 10_000);
      expect(behind()).toEqual([]);
      expect(Object.keys(worn()).sort()).toEqual(['mine', 'near', 'open', 'theirs', 'walled']);
      expect(overlay.counts.unnamed.hidden).toBe(0);
    } finally {
      restore();
    }
  });

  it('stands a line of speech over all its speaker wears, and over the head of a speaker who wears nothing', () => {
    const restore = sized();
    try {
      const { camera, stage } = setup();
      const overlay = new ThingMarks(stage, () => undefined, RULE);
      overlay.setMarks(marked([['knight', AI, 'knight'], ['baker', null, 'baker']]));
      const anchors = new Map([['knight', new pc.Vec3(0, 1, -5)], ['baker', new pc.Vec3(3, 1, -5)]]);
      overlay.showLine({ subjectId: 'knight', text: 'Halt!', mark: AI, header: 'knight · Qwen3 235B Instruct' }, 0);
      overlay.showLine({ subjectId: 'baker', text: 'Bread!', mark: ROUTINE, header: 'baker' }, 0);
      overlay.update(camera, anchors, null, 0);
      const lines = Array.from(stage.querySelectorAll<HTMLElement>('.thing-line')).filter((node) => node.style.display !== 'none');
      const at = (header: string) => /translate3d\(([-\d.]+)px, ([-\d.]+)px/
        .exec(lines.find((node) => node.querySelector('.thing-line-speaker')!.textContent === header)!.style.transform)!.slice(1).map(Number);
      const [kx, ky] = screenOf(5, 1);
      const [bx, by] = screenOf(5, 1, 3);
      // The knight speaks, so it is held and named: mark and name stand 48 px, and the line 3 px over them.
      expect(at('knight · Qwen3 235B Instruct')).toEqual([Number(kx.toFixed(1)), Number((ky - 48 - 3).toFixed(1))]);
      // The baker wears nothing: its line stands 34 px over its head.
      expect(at('baker')).toEqual([Number(bx.toFixed(1)), Number((by - 34).toFixed(1))]);
    } finally {
      restore();
    }
  });

  it('places the marks in every engine frame where the society stands them, by how tall it says they stand, and stops when destroyed', () => {
    const { app, camera, stage } = setup();
    // Frames are run by the engine's own tick; nothing is drawn (the null device has nothing to draw to).
    app.autoRender = false;
    let now = 0;
    const at = new Map([['knight', new pc.Vec3(0, 1, -5)], ['speck', new pc.Vec3(10, 1, -40)], ['baker', new pc.Vec3(-3, 1, -6)]]);
    const asked: string[] = [];
    let picked: string | null = null;
    let hides = false;
    const attached = new AttachedMarks({
      app, camera, parent: stage, now: () => now, selected: () => picked, onPick: () => undefined, rule: RULE,
      sees: () => (hides ? () => false : null),
      anchors: () => ({
        anchorOf(id, out) {
          asked.push(id);
          const point = at.get(id);
          if (point === undefined) return false;
          out.copy(point);
          return true;
        },
        // Everyone drawn stands 1.7 m: 102 px at 5 m and 12.75 px at 40 m.
        heightOf: (id) => (at.has(id) ? 1.7 : null),
      }),
    });
    attached.set(new Map<string, MarkedSubject>([
      ...marked([['knight', AI, null], ['indoors', AI, null], ['speck', AI, null]]),
      // Its own routine decides for the baker: asked after, and marked, only while it is the picked one.
      ['baker', { mark: null, picked: ROUTINE, label: 'baker' }],
    ]));
    picked = 'baker';
    app.tick(8);
    expect(asked.sort()).toEqual(['baker', 'indoors', 'knight', 'speck']);
    // The one 40 m off stands 12.75 px: too small to name, and it wears its mark as a dot.
    expect(shown(stage).map((one) => [one.subject, one.form]).sort()).toEqual([['baker', 'name'], ['knight', 'name'], ['speck', 'dot']]);
    picked = null;
    asked.length = 0;
    app.tick(16);
    expect(asked.sort()).toEqual(['indoors', 'knight', 'speck']);
    // The one the society does not draw wears nothing; the one too small to name is counted.
    expect(attached.counts).toMatchObject({ marks: 2, named: 1, unnamed: { small: 1, beyondShare: 0, collides: 0, hidden: 0 } });
    attached.showDecision({ subjectId: 'knight', chose: 'Chose “wait”.' });
    at.get('knight')!.set(0, 1, -10);
    now = 16;
    app.tick(32);
    const [x, y] = screenOf(10, 1);
    expect(shown(stage)[0]!.transform).toContain(`translate3d(${x.toFixed(1)}px, ${y.toFixed(1)}px, 0)`);
    expect(shown(stage)[0]!.chose).toBe('Chose “wait”.');
    // The page's answer to what the eye sees is asked each frame and handed on: with everything
    // behind something, only what is followed would be drawn, and nothing here is.
    hides = true;
    app.tick(40);
    expect(shown(stage)).toEqual([]);
    expect(attached.counts.unnamed.hidden).toBe(2);
    hides = false;
    attached.destroy();
    asked.length = 0;
    app.tick(48);
    expect(asked).toEqual([]);
    expect(stage.querySelector('.thing-marks')).toBeNull();
    app.destroy();
  });
});
