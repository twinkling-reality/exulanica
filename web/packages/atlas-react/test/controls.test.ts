// @vitest-environment happy-dom

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { atlasVec3, buildNavigationWorld, makeScene, type NavigationWorld } from '@exulanica/atlas-core';
import {
  cameraRelativeMovement,
  FirstPersonControls,
  FLY_FLOOR_M,
  FLY_SPEED,
} from '../src/playcanvas/controls.js';

describe('camera-relative movement intent', () => {
  it.each([
    ['forward', 0, 1, 0, 0, -1],
    ['backward', 0, -1, 0, 0, 1],
    ['left', -1, 0, 0, -1, 0],
    ['right', 1, 0, 0, 1, 0],
    ['forward at a quarter turn', 0, 1, Math.PI / 2, -1, 0],
    ['backward at a quarter turn', 0, -1, Math.PI / 2, 1, 0],
    ['forward at a half turn', 0, 1, Math.PI, 0, 1],
  ])('maps %s through camera yaw', (_label, right, forward, yaw, x, z) => {
    const movement = cameraRelativeMovement(right, forward, yaw);
    expect(movement.x).toBeCloseTo(x, 12);
    expect(movement.z).toBeCloseTo(z, 12);
  });

  it.each([
    [-1, -1],
    [-1, 1],
    [1, -1],
    [1, 1],
  ])('normalizes diagonal intent %s,%s', (right, forward) => {
    const movement = cameraRelativeMovement(right, forward, 0.73);
    expect(Math.hypot(movement.x, movement.z)).toBeCloseTo(1, 12);
  });
});

describe('first-person keyboard ownership', () => {
  beforeEach(() => {
    document.body.replaceChildren();
    Object.defineProperty(document, 'pointerLockElement', {
      configurable: true,
      writable: true,
      value: null,
    });
  });

  it('stops residual velocity as soon as pointer lock is released', () => {
    const canvas = document.createElement('canvas');
    document.body.append(canvas);
    const controls = new FirstPersonControls(canvas, {
      x: 0,
      y: 1.62,
      z: 0,
      yaw: 0,
      pitch: 0,
    });
    Object.defineProperty(document, 'pointerLockElement', {
      configurable: true,
      value: canvas,
      writable: true,
    });
    document.dispatchEvent(new Event('pointerlockchange'));
    window.dispatchEvent(new KeyboardEvent('keydown', { code: 'KeyW' }));
    controls.update(0.2);
    const movedZ = controls.state.z;
    expect(movedZ).toBeLessThan(0);

    Object.defineProperty(document, 'pointerLockElement', {
      configurable: true,
      value: null,
      writable: true,
    });
    document.dispatchEvent(new Event('pointerlockchange'));
    controls.update(0.2);
    expect(controls.state.z).toBe(movedZ);
    controls.destroy();
  });

  it('never swallows native button activation', () => {
    const canvas = document.createElement('canvas');
    const button = document.createElement('button');
    document.body.append(canvas, button);
    const controls = new FirstPersonControls(canvas, { x: 0, y: 1.62, z: 0, yaw: 0, pitch: 0 });
    const interact = vi.fn();
    controls.onInteract = interact;

    const event = new KeyboardEvent('keydown', { code: 'Enter', key: 'Enter', bubbles: true, cancelable: true });
    button.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(false);
    expect(interact).not.toHaveBeenCalled();
    controls.destroy();
  });

  it('does not summon behind a disabled system surface', () => {
    const canvas = document.createElement('canvas');
    document.body.append(canvas);
    const controls = new FirstPersonControls(canvas, { x: 0, y: 1.62, z: 0, yaw: 0, pitch: 0 });
    const summon = vi.fn();
    controls.onSummon = summon;
    controls.setEnabled(false);

    window.dispatchEvent(new KeyboardEvent('keydown', { code: 'KeyX', key: 'x' }));
    expect(summon).not.toHaveBeenCalled();
    controls.destroy();
  });

  it('gives an active system surface exclusive ownership of WASD', () => {
    const canvas = document.createElement('canvas');
    document.body.append(canvas);
    const requestPointerLock = vi.fn();
    canvas.requestPointerLock = requestPointerLock;
    const controls = new FirstPersonControls(canvas, { x: 0, y: 1.62, z: 0, yaw: 0, pitch: 0 });
    controls.setConversationActive(true);

    canvas.dispatchEvent(new MouseEvent('mousedown', { button: 0, bubbles: true }));
    expect(requestPointerLock).not.toHaveBeenCalled();
    window.dispatchEvent(new KeyboardEvent('keydown', { code: 'KeyW' }));
    controls.update(0.2);
    expect(controls.state.z).toBe(0);
    controls.destroy();
  });

  it('clears held movement when a system surface opens and closes', () => {
    const canvas = document.createElement('canvas');
    document.body.append(canvas);
    const controls = new FirstPersonControls(canvas, {
      x: 0,
      y: 1.62,
      z: 0,
      yaw: 0,
      pitch: 0,
    });
    canvas.focus();
    window.dispatchEvent(new KeyboardEvent('keydown', { code: 'KeyW' }));
    controls.update(0.05);
    const stopped = controls.state.z;
    expect(controls.movementHeading).toBeCloseTo(0, 12);

    controls.setConversationActive(true);
    expect(controls.movementHeading).toBeNull();
    controls.setConversationActive(false);
    controls.update(0.05);
    expect(controls.state.z).toBe(stopped);
    controls.destroy();
  });

  it('keeps left click for camera look and requires a keyboard interaction gesture', () => {
    const canvas = document.createElement('canvas');
    document.body.append(canvas);
    const controls = new FirstPersonControls(canvas, { x: 0, y: 1.62, z: 0, yaw: 0, pitch: 0 });
    const interact = vi.fn();
    controls.onInteract = interact;
    Object.defineProperty(document, 'pointerLockElement', {
      configurable: true,
      value: canvas,
      writable: true,
    });
    document.dispatchEvent(new Event('pointerlockchange'));

    canvas.dispatchEvent(new MouseEvent('mousedown', { button: 0, bubbles: true }));
    expect(interact).not.toHaveBeenCalled();

    window.dispatchEvent(new KeyboardEvent('keydown', { code: 'KeyE', key: 'e' }));
    expect(interact).toHaveBeenCalledOnce();
    controls.destroy();
  });

  describe('a click on the world before looking around', () => {
    const press = (canvas: HTMLCanvasElement, x: number, y: number) =>
      canvas.dispatchEvent(new MouseEvent('mousedown', { button: 0, bubbles: true, clientX: x, clientY: y }));
    const move = (x: number, y: number) => document.dispatchEvent(new MouseEvent('mousemove', { clientX: x, clientY: y }));
    const release = (x: number, y: number) => document.dispatchEvent(new MouseEvent('mouseup', { button: 0, clientX: x, clientY: y }));
    function setup(picks: boolean) {
      const canvas = document.createElement('canvas');
      document.body.append(canvas);
      const requestPointerLock = vi.fn();
      canvas.requestPointerLock = requestPointerLock;
      const controls = new FirstPersonControls(canvas, { x: 0, y: 1.62, z: 0, yaw: 0, pitch: 0 });
      const pick = vi.fn((_x: number, _y: number) => picks);
      controls.onPointerPick = pick;
      return { canvas, controls, pick, requestPointerLock };
    }

    it('opens what it hits and leaves the pointer free', () => {
      const { canvas, controls, pick, requestPointerLock } = setup(true);
      press(canvas, 100, 100);
      release(102, 101);
      expect(pick).toHaveBeenCalledWith(102, 101);
      expect(requestPointerLock).not.toHaveBeenCalled();
      controls.destroy();
    });

    it('looks around as before when it misses, drags or is held', () => {
      vi.useFakeTimers();
      try {
        const missed = setup(false);
        press(missed.canvas, 100, 100);
        release(100, 100);
        expect(missed.pick).toHaveBeenCalledOnce();
        expect(missed.requestPointerLock).toHaveBeenCalledOnce();
        missed.controls.destroy();
        // A press that drags is looking around from the moment it moves past the slop, never a pick.
        const dragged = setup(true);
        press(dragged.canvas, 100, 100);
        move(110, 100);
        expect(dragged.requestPointerLock).toHaveBeenCalledOnce();
        release(110, 100);
        expect(dragged.pick).not.toHaveBeenCalled();
        dragged.controls.destroy();
        // A press held longer than a click is looking around too.
        const held = setup(true);
        press(held.canvas, 100, 100);
        vi.advanceTimersByTime(301);
        release(100, 100);
        expect(held.pick).not.toHaveBeenCalled();
        expect(held.requestPointerLock).toHaveBeenCalledOnce();
        held.controls.destroy();
      } finally {
        vi.useRealTimers();
      }
    });

    it('never picks from a press made while a person types in a field', () => {
      const { canvas, controls, pick, requestPointerLock } = setup(true);
      const field = document.createElement('input');
      document.body.append(field);
      field.focus();
      press(canvas, 100, 100);
      release(100, 100);
      expect(pick).not.toHaveBeenCalled();
      expect(requestPointerLock).toHaveBeenCalledOnce();
      controls.destroy();
    });
  });

  it('uses X as the one keyboard summon contract', () => {
    const canvas = document.createElement('canvas');
    document.body.append(canvas);
    const controls = new FirstPersonControls(canvas, { x: 0, y: 1.62, z: 0, yaw: 0, pitch: 0 });
    const summon = vi.fn();
    controls.onSummon = summon;

    window.dispatchEvent(new KeyboardEvent('keydown', { code: 'KeyC', key: 'c' }));
    expect(summon).not.toHaveBeenCalled();
    window.dispatchEvent(new KeyboardEvent('keydown', { code: 'KeyX', key: 'x' }));
    expect(summon).toHaveBeenCalledOnce();
    controls.destroy();
  });

  it('publishes recovery once after returning from outside the resident field', () => {
    const canvas = document.createElement('canvas');
    document.body.append(canvas);
    const world = buildNavigationWorld(makeScene([], 1, 1));
    const controls = new FirstPersonControls(
      canvas,
      { x: 1_000, y: 1.62, z: 0, yaw: 0, pitch: 0 },
      undefined,
      world,
    );
    controls.update(0.016);
    expect(controls.consumeRecoveryReason()).toBe('outside-field');
    expect(controls.consumeRecoveryReason()).toBeNull();
    controls.destroy();
  });

  /*
   * `flatNavigationSurface` samples everywhere and never returns null, so an unconditional snap
   * also caught the deliberate aerial poses: a city overview at y = 95 landed near the
   * ground with its downward pitch intact. Grounding is now something a caller asks for.
   */
  it('leaves a declared aerial start pose alone and still seeds recovery on the ground', () => {
    const canvas = document.createElement('canvas');
    document.body.append(canvas);
    const world = buildNavigationWorld(makeScene([], 1, 1), {
      sample: () => ({ height: -1.31, normal: { x: 0, y: 1, z: 0 } }),
    });
    const controls = new FirstPersonControls(
      canvas,
      { x: -45, y: 95, z: -380, yaw: Math.PI, pitch: -0.48 },
      undefined,
      world,
      { hold: 'altitude' },
    );
    expect(controls.state.y).toBe(95);
    expect(controls.state.pitch).toBe(-0.48);
    controls.destroy();
  });

  it('holds a view at altitude on every frame after, and pans no farther than it was framed from', () => {
    const canvas = document.createElement('canvas');
    document.body.append(canvas);
    const world = buildNavigationWorld(makeScene([], 1, 1), {
      sample: () => ({ height: 0, normal: { x: 0, y: 1, z: 0 } }),
    });
    const controls = new FirstPersonControls(canvas, { x: 0, y: 1.62, z: 0, yaw: 0, pitch: 0 }, undefined, world);
    controls.setView({ x: 0, y: 95, z: 300, yaw: 0, pitch: -0.4 }, 'altitude');
    for (let frame = 0; frame < 30; frame += 1) controls.update(1 / 60);
    expect(controls.state).toMatchObject({ x: 0, y: 95, z: 300 });
    // Forward (yaw 0 faces the field) pans toward it at the same height; backing away stops at the
    // distance the view was framed from.
    canvas.focus();
    window.dispatchEvent(new KeyboardEvent('keydown', { code: 'KeyW' }));
    for (let frame = 0; frame < 60; frame += 1) controls.update(1 / 60);
    window.dispatchEvent(new KeyboardEvent('keyup', { code: 'KeyW' }));
    expect(controls.state.y).toBe(95);
    expect(controls.state.z).toBeLessThan(295);
    window.dispatchEvent(new KeyboardEvent('keydown', { code: 'KeyS' }));
    for (let frame = 0; frame < 240; frame += 1) controls.update(1 / 60);
    window.dispatchEvent(new KeyboardEvent('keyup', { code: 'KeyS' }));
    expect(controls.state.y).toBe(95);
    expect(Math.hypot(controls.state.x, controls.state.z)).toBeCloseTo(300, 9);
    // A ground view stands on the surface at once and stays there.
    controls.setView({ x: 3, y: 40, z: 4, yaw: 0, pitch: 0 }, 'ground');
    expect(controls.hold).toBe('ground');
    expect(controls.state.y).toBeCloseTo(world.eyeHeight, 12);
    controls.update(1 / 60);
    expect(controls.state).toMatchObject({ x: 3, z: 4 });
    controls.destroy();
  });

  it('grounds the initial pose and seeds a safe position from the surface', () => {
    const canvas = document.createElement('canvas');
    document.body.append(canvas);
    const world = buildNavigationWorld(makeScene([], 1, 1), {
      sample: (x, z) => ({
        height: x * 0.2 + z * 0.1 + 3,
        normal: { x: -0.2, y: 1, z: -0.1 },
      }),
    });
    const controls = new FirstPersonControls(
      canvas,
      { x: 2, y: 40, z: 4, yaw: 0, pitch: 0 },
      undefined,
      world,
    );
    expect(controls.state.y).toBeCloseTo(3 + 0.4 + 0.4 + world.eyeHeight, 12);
    controls.destroy();
  });
});

describe('player keyboard fallback and camera switch', () => {
  it('moves at pedestrian speed without pointer lock and stops while typing', () => {
    document.body.replaceChildren();
    Object.defineProperty(document, 'pointerLockElement', {configurable:true,value:null});
    const canvas=document.createElement('canvas'), input=document.createElement('input'); document.body.append(canvas,input);
    const controls=new FirstPersonControls(canvas,{x:0,y:1.62,z:0,yaw:0,pitch:0},{sensitivity:.0022,moveSpeed:1.65,sprintMultiplier:2.7,accelTime:.16,eyeHeight:1.62});
    canvas.focus(); canvas.dispatchEvent(new KeyboardEvent('keydown',{code:'KeyW',bubbles:true}));
    for(let i=0;i<60;i++) controls.update(1/60);
    expect(-controls.state.z).toBeGreaterThan(1.3); expect(-controls.state.z).toBeLessThan(1.65);
    input.focus(); const stopped=controls.state.z;
    input.dispatchEvent(new KeyboardEvent('keydown',{code:'KeyW',bubbles:true})); controls.update(1/60);
    expect(controls.state.z).toBe(stopped);
    const toggle=vi.fn(); controls.onCameraToggle=toggle;
    input.dispatchEvent(new KeyboardEvent('keydown',{code:'KeyC',bubbles:true})); expect(toggle).not.toHaveBeenCalled();
    canvas.focus(); canvas.dispatchEvent(new KeyboardEvent('keydown',{code:'KeyC',bubbles:true})); expect(toggle).toHaveBeenCalledOnce();
    controls.destroy();
  });
});


describe('explicit movement assistance',()=>{
 it('uses ordinary movement and stops when typing or the window loses focus',()=>{
  const canvas=document.createElement('canvas'),input=document.createElement('input');document.body.append(canvas,input);
  const controls=new FirstPersonControls(canvas,{x:0,y:1.62,z:0,yaw:0,pitch:0});
  controls.setWalkAssist('walk');for(let i=0;i<60;i++)controls.update(1/60);expect(controls.state.z).toBeLessThan(-1);
  input.focus();for(let i=0;i<120;i++)controls.update(1/60);const stopped=controls.state.z;controls.update(1/60);expect(Math.abs(controls.state.z-stopped)).toBeLessThan(.00001);
  controls.setWalkAssist('run');window.dispatchEvent(new Event('blur'));controls.update(1/60);expect(controls.state.z).toBeCloseTo(stopped,4);controls.destroy();
 });
});

describe('flying (F)', () => {
  beforeEach(() => {
    document.body.replaceChildren();
    Object.defineProperty(document, 'pointerLockElement', { configurable: true, writable: true, value: null });
  });

  /** A flat world with a round wall 3 m ahead of where a person starts (north is -z). */
  const walled = (): NavigationWorld => ({ ...buildNavigationWorld(makeScene([], 1, 1)), obstacles: [{ id: 'wall', centre: atlasVec3(0, 0, -6), radius: 2 }] });
  const start = { x: 0, y: 1.62, z: 0, yaw: 0, pitch: 0 };
  const key = (code: string, type: 'keydown' | 'keyup' = 'keydown', target: EventTarget = window) =>
    target.dispatchEvent(new KeyboardEvent(type, { code, bubbles: true }));
  const setUp = (world: NavigationWorld | null = walled()) => {
    const canvas = document.createElement('canvas');
    document.body.append(canvas);
    const controls = new FirstPersonControls(canvas, { ...start }, undefined, world);
    canvas.focus();
    const changes: boolean[] = [];
    controls.onFlyChange = (flying) => changes.push(flying);
    return { canvas, controls, changes };
  };
  const run = (controls: FirstPersonControls, seconds: number) => { for (let t = 0; t < seconds; t += 0.05) controls.update(0.05); };

  it('takes off with F, passes through a wall walking stops at, and lands on open ground with F again', () => {
    const walking = setUp();
    key('KeyW');
    run(walking.controls, 2);
    // Walking stops at the wall's edge.
    expect(walking.controls.state.z).toBeGreaterThan(-4);
    walking.controls.destroy();
    document.body.replaceChildren();

    const { controls, changes } = setUp();
    key('KeyF');
    expect(controls.flying).toBe(true);
    key('KeyW');
    run(controls, 1);
    // Flying passes through it.
    expect(controls.state.z).toBeLessThan(-8);
    key('KeyW', 'keyup');
    key('KeyF');
    expect(controls.flying).toBe(false);
    expect(controls.hold).toBe('ground');
    expect(controls.state.y).toBeCloseTo(1.62, 5);
    expect(changes).toEqual([true, false]);
    controls.destroy();
  });

  it('lands beside a wall it is over rather than inside it', () => {
    const { controls } = setUp();
    controls.setView({ ...start, z: -6, y: 20 }, 'fly');
    key('KeyF');
    expect(controls.hold).toBe('ground');
    expect(Math.hypot(controls.state.x, controls.state.z + 6)).toBeGreaterThanOrEqual(2);
    controls.destroy();
  });

  it('rises with Space and descends with C, without Space interacting or C toggling the camera, and never under the ground', () => {
    const { controls } = setUp();
    let interacted = 0, toggled = 0;
    controls.onInteract = () => { interacted += 1; };
    controls.onCameraToggle = () => { toggled += 1; };
    key('KeyF');
    key('Space');
    run(controls, 1);
    const high = controls.state.y;
    expect(high).toBeGreaterThan(5);
    key('Space', 'keyup');
    key('KeyC');
    run(controls, 5);
    expect(controls.state.y).toBeCloseTo(FLY_FLOOR_M, 5);
    expect([interacted, toggled]).toEqual([0, 0]);
    // On the ground again, Space interacts and C toggles the camera as before.
    key('KeyC', 'keyup');
    key('KeyF');
    key('Space');
    key('KeyC');
    expect([interacted, toggled]).toEqual([1, 1]);
    controls.destroy();
  });

  it('sets its speed with the scroll wheel, within its least and most, and only while flying', () => {
    const { canvas, controls } = setUp();
    const wheel = (deltaY: number) => canvas.dispatchEvent(new WheelEvent('wheel', { deltaY, cancelable: true }));
    wheel(-100);
    expect(controls.flyingSpeed).toBe(FLY_SPEED.start);
    key('KeyF');
    wheel(-100);
    expect(controls.flyingSpeed).toBeCloseTo(FLY_SPEED.start * FLY_SPEED.step, 9);
    for (let n = 0; n < 60; n += 1) wheel(-100);
    expect(controls.flyingSpeed).toBe(FLY_SPEED.most);
    for (let n = 0; n < 60; n += 1) wheel(100);
    expect(controls.flyingSpeed).toBe(FLY_SPEED.least);
    controls.destroy();
  });

  it('ignores F typed into a field, and stops flying when a view is set', () => {
    const { controls, changes } = setUp();
    const field = document.createElement('input');
    document.body.append(field);
    key('KeyF', 'keydown', field);
    expect(controls.flying).toBe(false);
    key('KeyF');
    controls.setView({ ...start, x: 3 }, 'ground');
    expect(controls.flying).toBe(false);
    expect(changes).toEqual([true, false]);
    controls.destroy();
  });
});
