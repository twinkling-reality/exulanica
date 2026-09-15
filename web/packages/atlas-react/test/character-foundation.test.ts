import { describe, it, expect } from 'vitest';
import { buildPlayerSculpt } from '../src/playcanvas/player-sculpt.js';
import { CharacterMotion } from '../src/playcanvas/character-motion.js';
import {
  BASE_DIMENSIONS,
  syntheticCharacterStyle,
} from '../src/playcanvas/character-shape.js';
import {
  deformPlayer,
  playerSkinWeights,
} from '../src/playcanvas/player-rig.js';

describe('continuous shared character foundation', () => {
  it('quickly turns toward camera-relative forward travel', () => {
    const motion = new CharacterMotion();
    motion.update({ x: 0, z: 0, yaw: 0, dx: 0, dz: 0, dt: 1 / 60, reduced: false });
    let pose = motion.update({
      x: -1 / 60, z: 0, yaw: Math.PI / 2, dx: -1 / 60, dz: 0, dt: 1 / 60, reduced: false,
    });
    for (let frame = 1; frame < 12; frame++) {
      pose = motion.update({
        x: -(frame + 1) / 60, z: 0, yaw: Math.PI / 2, dx: -1 / 60, dz: 0, dt: 1 / 60, reduced: false,
      });
    }
    expect(Math.abs(pose.facing - Math.PI / 2)).toBeLessThan(0.03);
  });
  it('produces a single closed connected skin with finite normals at both detail levels', () => {
    for (const detail of [0.018, 0.035]) {
      const sculpt = buildPlayerSculpt(detail),
        adjacency = new Map<number, Set<number>>(),
        edges = new Map<string, number>();
      for (let i = 0; i < sculpt.indices.length; i += 3)
        for (let k = 0; k < 3; k++) {
          const a = sculpt.indices[i + k]!,
            b = sculpt.indices[i + ((k + 1) % 3)]!,
            key = a < b ? `${a}:${b}` : `${b}:${a}`;
          edges.set(key, (edges.get(key) ?? 0) + 1);
          if (!adjacency.has(a)) adjacency.set(a, new Set());
          adjacency.get(a)!.add(b);
        }
      expect([...edges.values()].every((count) => count === 2)).toBe(true);
      const seen = new Set<number>(),
        queue = [0];
      while (queue.length) {
        const i = queue.pop()!;
        if (seen.has(i)) continue;
        seen.add(i);
        queue.push(...(adjacency.get(i) ?? []));
      }
      expect(seen.size).toBe(sculpt.positions.length / 3);
      expect([...sculpt.normals].every(Number.isFinite)).toBe(true);
      expect(buildPlayerSculpt(detail)).toBe(sculpt);
    }
  });
  it('keeps contact ankles fixed in world space through acceleration, curves, running and stopping across body presets', () => {
    for (const body of [
      BASE_DIMENSIONS,
      syntheticCharacterStyle('short').body,
      syntheticCharacterStyle('broad').body,
    ]) {
      const rig = new CharacterMotion(body);
      let x = 0,
        z = 0,
        previous: ReturnType<CharacterMotion['update']> | null = null,
        contacts = 0,
        maxDrift = 0;
      for (let frame = 0; frame < 720; frame++) {
        const speed =
          frame < 120
            ? (1.65 * frame) / 120
            : frame < 360
              ? 1.65
              : frame < 540
                ? 4.4
                : frame < 600
                  ? (4.4 * (600 - frame)) / 60
                  : 0;
        const yaw = frame < 180 ? 0 : (((frame - 180) / 540) * Math.PI) / 2,
          dx = (-Math.sin(yaw) * speed) / 60,
          dz = (-Math.cos(yaw) * speed) / 60;
        x += dx;
        z += dz;
        const pose = rig.update({
          x,
          z,
          yaw,
          dx,
          dz,
          dt: 1 / 60,
          reduced: false,
        });
        if (previous)
          for (let foot = 0; foot < 2; foot++)
            if (pose.stance[foot] && previous.stance[foot]) {
              contacts++;
              maxDrift = Math.max(
                maxDrift,
                Math.hypot(
                  ...pose.worldFeet[foot]!.map(
                    (v, i) => v - previous!.worldFeet[foot]![i]!,
                  ),
                ),
              );
            }
        expect(
          pose.bones.flatMap((b) => [...b.a, ...b.b]).every(Number.isFinite),
        ).toBe(true);
        previous = pose;
      }
      expect(contacts).toBeGreaterThan(100);
      expect(maxDrift).toBeLessThan(0.000001);
    }
  });
  it('keeps deformed foot soles finite and near ground when stopped', () => {
    const sculpt = buildPlayerSculpt(0.035),
      skin = playerSkinWeights(sculpt.positions),
      motion = new CharacterMotion();
    const pose = motion.update({
      x: 0,
      z: 0,
      yaw: 0,
      dx: 0,
      dz: 0,
      dt: 1 / 60,
      reduced: true,
    });
    const positions = new Float32Array(sculpt.positions.length),
      normals = new Float32Array(positions.length);
    deformPlayer(
      sculpt.positions,
      sculpt.normals,
      skin,
      pose.bones,
      positions,
      normals,
    );
    const heights = Array.from(
      { length: positions.length / 3 },
      (_, i) => positions[i * 3 + 1]!,
    );
    expect(Math.min(...heights)).toBeGreaterThan(-0.015);
    expect(Math.min(...heights)).toBeLessThan(0.015);
    expect([...positions, ...normals].every(Number.isFinite)).toBe(true);
  });
  it('keeps synthetic presets stable under sorting and population capping', () => {
    const ids = ['inhabitant:1', 'inhabitant:2', 'inhabitant:3'];
    const before = ids.map(syntheticCharacterStyle);
    for (const id of [...ids].reverse())
      expect(syntheticCharacterStyle(id)).toEqual(before[ids.indexOf(id)]);
  });
});
