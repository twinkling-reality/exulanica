// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';
import * as pc from 'playcanvas';
import {
  AttachedMarks,
  MARKS_MAXIMUM,
  ThingMarks,
  lineSeconds,
  type MarkedSubject,
  type ThingMark,
} from '../src/playcanvas/things/marks.js';

/*
 * Who runs each being, marked over it. Expected screen points come from the camera's stated field
 * of view (90 degrees vertical, so a point d metres ahead and y up is y / d of the half height
 * from the centre), not from the overlay's matrices.
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

const AI: ThingMark = { kind: 'ai', short: 'Qwen3', full: 'Qwen3 235B Instruct' };
const AGENT: ThingMark = { kind: 'ai', short: 'Scout', full: 'An outside AI agent, Scout', outside: true };
const BLOCK_GAME: ThingMark = { kind: 'from', label: 'from Block Game', full: 'A person playing Block Game' };

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
      return {
        subject: pill.dataset['subject'],
        word: node.querySelector('.thing-mark-word')!.textContent,
        name: name.hidden ? null : name.textContent,
        origin: origin.hidden ? null : origin.textContent,
        label: label.hidden ? null : label.textContent,
        classes: pill.className,
        aria: pill.getAttribute('aria-label'),
        transform: node.style.transform,
      };
    });
}

describe('marks over the beings a model or someone outside runs', () => {
  it('hangs each mark over its being, and nothing over one nobody outside its routine runs', () => {
    const { camera, stage } = setup();
    const overlay = new ThingMarks(stage, () => undefined);
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
    // A game's player wears the game's pill; an AI the AI pill, both with their words for a screen reader.
    expect(marks.find((one) => one.subject === 'visitor')).toMatchObject({ word: 'from Block Game', name: null, aria: 'A person playing Block Game' });
    // The page's words for a screen reader where it gives them, the mark's full words where not.
    expect(marks.find((one) => one.subject === 'knight')).toMatchObject({ word: 'AI', aria: 'knight: run by an AI model, Qwen3 235B Instruct' });
    expect(overlay.counts).toEqual({ marks: 2, aiMarks: 1, lines: 0 });
  });

  it('names the three nearest within 12 m, the selected one and a speaking one, and draws none beyond 60 m or behind the eye', () => {
    const { camera, stage } = setup();
    const overlay = new ThingMarks(stage, () => undefined);
    const ids = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'far', 'behind'];
    overlay.setMarks(marked(ids.map((id) => [id, AI, `kind ${id}`])));
    const anchors = new Map<string, pc.Vec3>([
      ['a', new pc.Vec3(0, 1, -3)], ['b', new pc.Vec3(0.5, 1, -4)], ['c', new pc.Vec3(-0.5, 1, -5)],
      ['d', new pc.Vec3(0, 1, -6)], ['e', new pc.Vec3(0, 1, -20)], ['f', new pc.Vec3(0, 1, -30)],
      ['g', new pc.Vec3(0, 1, -40)], ['far', new pc.Vec3(0, 1, -61)], ['behind', new pc.Vec3(0, 1, 5)],
    ]);
    overlay.showLine({ subjectId: 'f', text: 'Who goes there?', mark: AI, header: 'kind f · Qwen3 235B Instruct' }, 0);
    overlay.update(camera, anchors, 'e', 0);
    const marks = shown(stage);
    expect(marks.map((one) => one.subject).sort()).toEqual(['a', 'b', 'c', 'd', 'e', 'f', 'g']);
    const named = marks.filter((one) => one.name !== null).map((one) => one.subject).sort();
    // The three nearest (d at 6 m is fourth), the selected e and the speaking f.
    expect(named).toEqual(['a', 'b', 'c', 'e', 'f']);
    expect(marks.find((one) => one.subject === 'a')).toMatchObject({ name: 'Qwen3', label: 'kind a' });
    expect(marks.find((one) => one.subject === 'd')).toMatchObject({ name: null, label: null });
  });

  it('draws where a visitor the world\'s model runs came from inside its AI pill, near or far, and nowhere else', () => {
    const { camera, stage } = setup();
    const overlay = new ThingMarks(stage, () => undefined);
    const RUN_HERE: ThingMark = { kind: 'ai', short: 'Qwen3', full: 'Qwen3 235B Instruct', from: 'Block Game' };
    overlay.setMarks(marked([['near', RUN_HERE, null], ['far', RUN_HERE, null], ['knight', AI, null], ['player', BLOCK_GAME, null]]));
    const anchors = new Map([
      ['near', new pc.Vec3(0, 1, -4)], ['far', new pc.Vec3(0, 1, -30)],
      ['knight', new pc.Vec3(1, 1, -5)], ['player', new pc.Vec3(-1, 1, -5)],
    ]);
    overlay.update(camera, anchors, null, 0);
    const marks = shown(stage);
    // One pill: AI, the model's short name where names show, then where it came from, always.
    expect(marks.find((one) => one.subject === 'near')).toMatchObject({ word: 'AI', name: 'Qwen3', origin: '· from Block Game' });
    expect(marks.find((one) => one.subject === 'far')).toMatchObject({ word: 'AI', name: null, origin: '· from Block Game' });
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
    expect(shown(stage).find((one) => one.subject === 'near')).toMatchObject({ word: 'from Block Game', origin: null });
  });

  it('outlines an outside agent\'s AI pill and picks a being when its pill is clicked', () => {
    const { camera, stage } = setup();
    const onPick = vi.fn();
    const overlay = new ThingMarks(stage, onPick);
    overlay.setMarks(marked([['agent', AGENT, null]]));
    overlay.update(camera, new Map([['agent', new pc.Vec3(0, 1, -4)]]), null, 0);
    const [mark] = shown(stage);
    expect(mark!.classes.split(' ').sort()).toEqual(['thing-mark-ai', 'thing-mark-outside', 'thing-mark-pill']);
    expect(mark).toMatchObject({ word: 'AI', name: 'Scout', aria: 'An outside AI agent, Scout' });
    stage.querySelector<HTMLButtonElement>('.thing-mark-pill[data-subject="agent"]')!.click();
    expect(onPick).toHaveBeenCalledWith('agent');
  });

  it('writes a line as text over its speaker, for as long as its length allows', () => {
    const { camera, stage } = setup();
    const overlay = new ThingMarks(stage, () => undefined);
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
    // Two seconds and 55 ms a character: 34 characters stay 3.87 s.
    expect(lineSeconds(words)).toBeCloseTo(2 + 0.055 * 34, 9);
    overlay.update(camera, anchors, null, 1000 + 3869);
    expect(overlay.counts.lines).toBe(1);
    overlay.update(camera, anchors, null, 1000 + 3871);
    expect(overlay.counts.lines).toBe(0);
    expect(overlay.speaking(1000 + 3871).size).toBe(0);
  });

  it('never makes a node while drawing, however many beings are marked', () => {
    const { camera, stage } = setup();
    const overlay = new ThingMarks(stage, () => undefined);
    const nodes = stage.querySelectorAll('*').length;
    const ids = Array.from({ length: 200 }, (_, i) => `p${String(i).padStart(3, '0')}`);
    overlay.setMarks(marked(ids.map((id) => [id, AI, null])));
    overlay.update(camera, new Map(ids.map((id, i) => [id, new pc.Vec3((i % 20) - 10, 1, -5 - Math.floor(i / 20))])), null, 0);
    expect(stage.querySelectorAll('*').length).toBe(nodes);
    expect(overlay.counts.marks).toBe(MARKS_MAXIMUM);
  });

  it('places the marks in every engine frame where the society stands them, and stops when destroyed', () => {
    const { app, camera, stage } = setup();
    // Frames are run by the engine's own tick; nothing is drawn (the null device has nothing to draw to).
    app.autoRender = false;
    let now = 0;
    const at = new Map([['knight', new pc.Vec3(0, 1, -5)]]);
    const asked: string[] = [];
    const attached = new AttachedMarks({
      app, camera, parent: stage, now: () => now, selected: () => null, onPick: () => undefined,
      anchors: () => ({
        anchorOf(id, out) {
          asked.push(id);
          const point = at.get(id);
          if (point === undefined) return false;
          out.copy(point);
          return true;
        },
      }),
    });
    attached.set(marked([['knight', AI, null], ['indoors', AI, null]]));
    app.tick(16);
    expect(asked.sort()).toEqual(['indoors', 'knight']);
    expect(attached.counts.marks).toBe(1);
    at.get('knight')!.set(0, 1, -10);
    now = 16;
    app.tick(32);
    const [x, y] = screenOf(10, 1);
    expect(shown(stage)[0]!.transform).toContain(`translate3d(${x.toFixed(1)}px, ${y.toFixed(1)}px, 0)`);
    attached.destroy();
    asked.length = 0;
    app.tick(48);
    expect(asked).toEqual([]);
    expect(stage.querySelector('.thing-marks')).toBeNull();
    app.destroy();
  });
});
