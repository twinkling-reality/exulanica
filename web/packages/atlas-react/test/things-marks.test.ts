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
  nameLeastPx: 14, beingLeastPx: 22, screenShare: 0.08, linesAtOnce: 4,
  lineBaseMs: 2000, linePerCharacterMs: 55, lineMostMs: 9000,
};
const NOTHING_UNNAMED = { small: 0, beyondShare: 0 };

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

/** This page lays nothing out, so every mark states the size a browser would give it: 80 by 24. */
function sized(): () => void {
  const width = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'offsetWidth');
  const height = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'offsetHeight');
  const is = (node: HTMLElement) => node.classList.contains('thing-mark');
  Object.defineProperty(HTMLElement.prototype, 'offsetWidth', { configurable: true, get(this: HTMLElement) { return is(this) ? 80 : 0; } });
  Object.defineProperty(HTMLElement.prototype, 'offsetHeight', { configurable: true, get(this: HTMLElement) { return is(this) ? 24 : 0; } });
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
    expect(overlay.counts).toEqual({ marks: 2, aiMarks: 1, lines: 0, decisions: 0, unnamed: NOTHING_UNNAMED });
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

  it('names a being that stands tall enough on the screen, counts the ones that do not, and always names a held one', () => {
    const { camera, stage } = setup();
    const overlay = new ThingMarks(stage, () => undefined, RULE);
    const ids = ['a', 'b', 'c', 'd', 'unmeasured', 'behind'];
    overlay.setMarks(marked(ids.map((id) => [id, AI, `kind ${id}`])));
    const anchors = new Map<string, pc.Vec3>([
      ['a', new pc.Vec3(-6, 1, -5)], ['b', new pc.Vec3(-2, 1, -20)], ['c', new pc.Vec3(4, 1, -23.5)],
      ['d', new pc.Vec3(10, 1, -40)], ['unmeasured', new pc.Vec3(-20, 1, -40)], ['behind', new pc.Vec3(0, 1, 5)],
    ]);
    // Each 1.7 m tall where the society says: 102 px at 5 m, 25.5 px at 20 m, 21.7 px at 23.5 m
    // and 12.75 px at 40 m. The floor is 22 px.
    const tall = new Map(['a', 'b', 'c', 'd', 'behind'].map((id) => [id, 1.7]));
    overlay.update(camera, anchors, null, 0, tall);
    // A being whose height the society does not state is named: nothing says it is small.
    expect(shown(stage).map((one) => one.subject).sort()).toEqual(['a', 'b', 'unmeasured']);
    // One behind the eye takes no name and is not a name missed.
    expect(overlay.counts.unnamed).toEqual({ small: 2, beyondShare: 0 });
    // The picked one and a speaking one are named however small they stand, with their labels.
    overlay.showLine({ subjectId: 'd', text: 'Who goes there?', mark: AI, header: 'kind d · Qwen3 235B Instruct' }, 0);
    overlay.update(camera, anchors, 'c', 0, tall);
    const marks = shown(stage);
    expect(marks.map((one) => one.subject).sort()).toEqual(['a', 'b', 'c', 'd', 'unmeasured']);
    expect(marks.find((one) => one.subject === 'c')).toMatchObject({ name: 'Qwen3 235B Instruct', label: 'kind c' });
    expect(marks.find((one) => one.subject === 'd')).toMatchObject({ label: 'kind d' });
    expect(marks.find((one) => one.subject === 'a')).toMatchObject({ label: null });
    expect(overlay.counts.unnamed.small).toBe(0);
  });

  it('stands a name that would cover a nearer one just above it, so two beings side by side are both named', () => {
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
      // Over its own being the traveller's name would cover the spirit's (both 80 wide at x 400, 13 px apart).
      expect(Math.abs(ty - sy)).toBeLessThan(24);
      // All three are named: the nearest stays over its being, and the traveller's stands over its
      // own being too, just above the spirit's, 2 px clear. Neither is hidden.
      expect(shown(stage).map((one) => one.subject).sort()).toEqual(['knight', 'spirit', 'traveller']);
      expect(overlay.counts.unnamed).toEqual(NOTHING_UNNAMED);
      expect(placedAt(stage, 'spirit')).toEqual([Number(sx.toFixed(1)), Number(sy.toFixed(1))]);
      expect(placedAt(stage, 'traveller')).toEqual([Number(tx.toFixed(1)), Number((sy - 24 - 2).toFixed(1))]);
      const [kx, ky] = screenOf(9, 1, 4);
      expect(placedAt(stage, 'knight')).toEqual([Number(kx.toFixed(1)), Number(ky.toFixed(1))]);
      // Two on one bench, 0.6 m apart 5 m off (36 px on the screen): each name is centred over its
      // own being, one above the other.
      overlay.setMarks(marked([['left', AI, null], ['right', AI, null]]));
      overlay.update(camera, new Map([['left', new pc.Vec3(-0.3, 1, -5)], ['right', new pc.Vec3(0.3, 1, -5.01)]]), null, 0);
      const [lx, ly] = screenOf(5, 1, -0.3);
      const [rx] = screenOf(5.01, 1, 0.3);
      expect(placedAt(stage, 'left')).toEqual([Number(lx.toFixed(1)), Number(ly.toFixed(1))]);
      expect(placedAt(stage, 'right')).toEqual([Number(rx.toFixed(1)), Number((ly - 24 - 2).toFixed(1))]);
    } finally {
      restore();
    }
  });

  it('spends a share of the view on names, nearest first, and counts every name beyond it', () => {
    const restore = sized();
    try {
      const { camera, stage } = setup();
      const overlay = new ThingMarks(stage, () => undefined, RULE);
      // Thirty beings in thirty directions, 3 m apart across and 1 m apart up at 10 m ahead (90 px
      // by 30 px between names of 80 by 24, so none covers another), each 5 cm farther from the eye
      // than the one before along its own direction, which leaves it where it is on the screen.
      const ids = Array.from({ length: 30 }, (_, i) => `p${String(i).padStart(2, '0')}`);
      overlay.setMarks(marked(ids.map((id) => [id, AI, null])));
      const anchors = new Map(ids.map((id, i) => {
        const toward = new pc.Vec3(-12 + 3 * (i % 9), -1 + Math.floor(i / 9), -10).normalize();
        return [id, toward.mulScalar(10 + 0.05 * i)];
      }));
      overlay.update(camera, anchors, null, 0);
      // The view is 800 by 600 and the share 0.08: 38,400 px of it, which is twenty names of 1,920 px.
      const drawn = shown(stage).map((one) => one.subject).sort();
      expect(drawn).toEqual(ids.slice(0, 20));
      expect(overlay.counts).toMatchObject({ marks: 20, unnamed: { small: 0, beyondShare: 10 } });
      // The overlay says the same on its root, for a page that tells a person how many more there are.
      const root = stage.querySelector<HTMLElement>('.thing-marks')!;
      expect([root.dataset['named'], JSON.parse(root.dataset['unnamed']!)]).toEqual(['20', { small: 0, beyondShare: 10 }]);
      // The picked one is named outside the share, and takes none of it from the near.
      overlay.update(camera, anchors, 'p29', 0);
      expect(shown(stage).map((one) => one.subject).sort()).toEqual([...ids.slice(0, 20), 'p29']);
      expect(overlay.counts.unnamed.beyondShare).toBe(9);
      expect([root.dataset['named'], JSON.parse(root.dataset['unnamed']!).beyondShare]).toEqual(['21', 9]);
      // Picked among the nearest, it still takes none of the share: twenty others are named with it.
      overlay.update(camera, anchors, 'p00', 0);
      expect(shown(stage).map((one) => one.subject).sort()).toEqual(ids.slice(0, 21));
    } finally {
      restore();
    }
  });

  it('makes a node only when more names fit the view than ever did, and none to draw the same again', () => {
    const restore = sized();
    try {
      const { camera, stage } = setup();
      const overlay = new ThingMarks(stage, () => undefined, RULE);
      const ids = Array.from({ length: 200 }, (_, i) => `p${String(i).padStart(3, '0')}`);
      overlay.setMarks(marked(ids.map((id) => [id, AI, null])));
      const anchors = new Map(ids.map((id, i) => [id, new pc.Vec3((i % 20) - 10, 1, -5 - Math.floor(i / 20))]));
      overlay.update(camera, anchors, null, 0);
      const { marks, unnamed } = overlay.counts;
      // Every marked being on the screen (within the overlay's 40 px margin) is either named or
      // counted, and the share bounds the named.
      const onScreen = ids.filter((_, i) => {
        const [x, y] = screenOf(5 + Math.floor(i / 20), 1, (i % 20) - 10);
        return x >= -40 && x <= WIDTH + 40 && y >= -40 && y <= HEIGHT + 40;
      }).length;
      expect(onScreen).toBeGreaterThan(100);
      expect(marks).toBeGreaterThan(0);
      expect(marks).toBeLessThanOrEqual(20);
      expect(marks + unnamed.small + unnamed.beyondShare).toBe(onScreen);
      // No more nodes than the names drawn and the one last tried.
      expect(stage.querySelectorAll('.thing-mark').length).toBeLessThanOrEqual(marks + 1);
      const nodes = stage.querySelectorAll('*').length;
      overlay.update(camera, anchors, null, 16);
      expect(stage.querySelectorAll('*').length).toBe(nodes);
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

  it('places the marks in every engine frame where the society stands them, by how tall it says they stand, and stops when destroyed', () => {
    const { app, camera, stage } = setup();
    // Frames are run by the engine's own tick; nothing is drawn (the null device has nothing to draw to).
    app.autoRender = false;
    let now = 0;
    const at = new Map([['knight', new pc.Vec3(0, 1, -5)], ['speck', new pc.Vec3(10, 1, -40)], ['baker', new pc.Vec3(-3, 1, -6)]]);
    const asked: string[] = [];
    let picked: string | null = null;
    const attached = new AttachedMarks({
      app, camera, parent: stage, now: () => now, selected: () => picked, onPick: () => undefined, rule: RULE,
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
    expect(shown(stage).map((one) => one.subject).sort()).toEqual(['baker', 'knight']);
    picked = null;
    asked.length = 0;
    app.tick(16);
    expect(asked.sort()).toEqual(['indoors', 'knight', 'speck']);
    // The one the society does not draw wears nothing; the one too small to name is counted.
    expect(attached.counts).toMatchObject({ marks: 1, unnamed: { small: 1, beyondShare: 0 } });
    attached.showDecision({ subjectId: 'knight', chose: 'Chose “wait”.' });
    at.get('knight')!.set(0, 1, -10);
    now = 16;
    app.tick(32);
    const [x, y] = screenOf(10, 1);
    expect(shown(stage)[0]!.transform).toContain(`translate3d(${x.toFixed(1)}px, ${y.toFixed(1)}px, 0)`);
    expect(shown(stage)[0]!.chose).toBe('Chose “wait”.');
    attached.destroy();
    asked.length = 0;
    app.tick(48);
    expect(asked).toEqual([]);
    expect(stage.querySelector('.thing-marks')).toBeNull();
    app.destroy();
  });
});
