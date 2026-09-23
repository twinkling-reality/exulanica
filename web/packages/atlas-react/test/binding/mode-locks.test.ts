// @vitest-environment happy-dom
/**
 * How the binding's movement locks compose.
 *
 * Walking is on only while the application allows it, the Map is closed, no direct navigation is
 * travelling and no inspection holds the camera. Each lock is released by its own owner and no
 * lock can switch another back on: closing the Map under an application lock leaves walking off,
 * and an application that allows walking during a journey does not cut the journey short. The
 * free cursor is separate: it keeps walking while a surface owns the pointer.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { islandId } from '@exulanica/atlas-core';
import type { AtlasBinding } from '../../src/playcanvas/atlas-binding.js';
import { buildBinding, record } from './binding-harness.js';

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.replaceChildren();
});

const walking = (binding: AtlasBinding): boolean =>
  (binding.controls as unknown as { enabled: boolean }).enabled;

describe('the movement locks', () => {
  it('lets no lock re-enable walking while another holds it', async () => {
    const { binding } = await buildBinding('authored-endless');
    try {
      const calls: string[] = [];
      record(calls, binding.controls, 'controls', ['setEnabled']);
      expect(walking(binding)).toBe(true);
      binding.setControlsEnabled(false);
      expect(walking(binding)).toBe(false);
      binding.setMapMode(true);
      binding.setMapMode(false);
      expect(walking(binding)).toBe(false);
      binding.setControlsEnabled(true);
      expect(walking(binding)).toBe(true);
      binding.setMapMode(true);
      binding.setControlsEnabled(true);
      expect(walking(binding)).toBe(false);
      binding.setMapMode(false);
      expect(walking(binding)).toBe(true);
      // Every change went through the one place that composes the locks.
      expect(calls).toEqual(Array(7).fill('controls.setEnabled'));
    } finally {
      binding.destroy();
    }
  });

  it('holds walking off for a journey and gives it back on arrival, unless the application took it', async () => {
    const { binding } = await buildBinding('personal-regions');
    try {
      const arrived: string[] = [];
      binding.onNavigationArrive = (target) => { arrived.push(target.kind); };
      binding.update(1 / 60, 10_000);
      const resolution = binding.navigateToIsland(islandId('region:second'));
      expect(resolution.ok).toBe(true);
      expect(walking(binding)).toBe(false);
      binding.setControlsEnabled(true);
      expect(walking(binding)).toBe(false);
      for (let frame = 0; frame < 600 && arrived.length === 0; frame += 1) binding.update(1 / 60, 10_016 + frame * 16);
      expect(arrived).toEqual(['island']);
      expect(walking(binding)).toBe(true);

      binding.navigateToIsland(islandId('region:first'));
      binding.setControlsEnabled(false);
      for (let frame = 0; frame < 600 && arrived.length === 1; frame += 1) binding.update(1 / 60, 30_000 + frame * 16);
      expect(arrived).toEqual(['island', 'island']);
      expect(walking(binding)).toBe(false);
    } finally {
      binding.destroy();
    }
  });

  it('keeps walking with a free cursor, through the conversation switch, not the lock', async () => {
    const { binding } = await buildBinding('authored-endless');
    try {
      const calls: string[] = [];
      record(calls, binding.controls, 'controls', ['setEnabled', 'setConversationActive']);
      binding.setFreeCursorActive(true);
      binding.setFreeCursorActive(false);
      expect(calls).toEqual(['controls.setConversationActive', 'controls.setConversationActive']);
      expect(walking(binding)).toBe(true);
    } finally {
      binding.destroy();
    }
  });
});
