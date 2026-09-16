// @vitest-environment happy-dom

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { buildNavigationWorld, makeScene } from '@exulanica/atlas-core';
import {
  cameraRelativeMovement,
  FirstPersonControls,
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
   * `atlasLandscapeSurface` samples everywhere and never returns null, so an unconditional snap
   * also caught the deliberate aerial poses: the Google-tiles overview at y = 95 landed near the
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
      { groundStart: false },
    );
    expect(controls.state.y).toBe(95);
    expect(controls.state.pitch).toBe(-0.48);
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
