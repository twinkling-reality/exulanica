/**
 * The authored-objects surface's words for an edit and a motion, and a placed record's saved pose.
 *
 * Pure functions of their arguments, read by `objects.ts`, which re-exports `EDIT_WORDS`.
 */

import { BEHAVIOUR_REGISTRY, BOUNDED_PATH_KEY, BOUNDED_PATH_VERSION } from '@exulanica/atlas-core';
import { MM_PER_METRE, type RegionPose } from '@exulanica/atlas-react/playcanvas';

import type { MotionAxisKey, MotionDraft } from '../ui/object-placement.js';
import type { AuthoredObject, ObjectBehaviour } from '../world-objects-api.js';

/**
 * A world edit in words, by every edit kind the server states (`EDIT_KINDS` in
 * exulanica/world/edit_kinds.py, held to it by edit-words-parity.test.ts), `undo` aside.
 */
export const EDIT_WORDS: Readonly<Record<string, string>> = {
  add_object: 'an object you added',
  move_object: 'a move',
  remove_object: 'a removal',
  set_object_behaviour: 'a change to an object’s motion',
  suppress_element: 'a part of the world you hid',
  transform_element: 'a part of the world you moved',
  add_environment: 'an environment you added',
  move_environment: 'an environment you moved',
  remove_environment: 'an environment you removed',
  add_point_map: 'a photograph’s points you placed',
  move_point_map: 'a photograph’s points you moved',
  remove_point_map: 'a photograph’s points you removed',
  add_thing: 'a thing you placed',
  move_thing: 'a thing you moved',
  remove_thing: 'a thing you removed',
};

export const poseOf = (record: AuthoredObject): RegionPose => Object.freeze({
  xMm: record.transform.xMm,
  yMm: record.transform.yMm,
  zMm: record.transform.zMm,
  yawMicroradians: record.transform.yawMicroradians,
  scaleMilli: record.transform.scaleMilli,
});

export function axisWords(axis: MotionAxisKey): string {
  return { x: 'side to side', y: 'up and down', z: 'forward and back' }[axis] ?? String(axis);
}

/** The reviewed behaviour a motion draft names, in the registry's own parameter names. */
export function boundedPath(motion: MotionDraft): ObjectBehaviour {
  return {
    behaviourKey: BOUNDED_PATH_KEY,
    behaviourVersion: BOUNDED_PATH_VERSION,
    parameters: {
      axis: motion.axis,
      easing: motion.easing,
      travel_mm: motion.travelMm,
      period_milliseconds: motion.periodMilliseconds,
    },
  };
}

export function motionWords(motion: MotionDraft): string {
  return `${axisWords(motion.axis)}, ${(motion.travelMm / MM_PER_METRE).toFixed(2)} m out and `
    + `back every ${(motion.periodMilliseconds / 1000).toFixed(1)} s, `
    + (motion.easing === 'linear' ? 'at an even pace' : 'easing in and out');
}

/** The stored motion in the panel's own controls, or null when they cannot show it exactly. */
export function storedMotionOf(record: AuthoredObject): MotionDraft | null {
  const behaviour = record.behaviour;
  if (behaviour === null || behaviour.behaviourKey !== BOUNDED_PATH_KEY
    || behaviour.behaviourVersion !== BOUNDED_PATH_VERSION) return null;
  const read = BEHAVIOUR_REGISTRY.readParameters(
    behaviour.behaviourKey, behaviour.behaviourVersion, behaviour.parameters,
  );
  if (!read.ok || read.clamped.length > 0) return null;
  return Object.freeze({
    axis: String(read.parameters['axis']),
    easing: String(read.parameters['easing']),
    travelMm: Number(read.parameters['travel_mm']),
    periodMilliseconds: Number(read.parameters['period_milliseconds']),
  });
}

export function editWords(kind: string): string {
  return EDIT_WORDS[kind] ?? 'a change the page has no words for';
}

export function offsetWords(record: AuthoredObject, pose: RegionPose): string {
  const saved = poseOf(record);
  const moved = Math.hypot(pose.xMm - saved.xMm, pose.yMm - saved.yMm, pose.zMm - saved.zMm);
  return moved === 0 ? '' : `, about ${(moved / MM_PER_METRE).toFixed(2)} of a step from where it is saved`;
}
