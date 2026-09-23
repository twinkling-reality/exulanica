// @vitest-environment happy-dom
/**
 * What an appearance change and the Map do to the world, step by step.
 *
 * An art profile swap sets the clear colours, ambient light, fog and sun colour and switches the
 * composed world's profile layers; the Map swaps the clear colour, hides what the Map does not
 * show, moves the camera to the Map pose, locks walking and re-aims the fog at whatever sky is
 * then drawn. Leaving the Map puts back the ground pose. Each step's readings are pinned per
 * world kind, so a change to any of them, or to their order, is a diff to read.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import * as pc from 'playcanvas';
import { DAWN_THEME, ORIGIN_LANDSCAPE, SURVEY_RELIEF } from '@exulanica/presentation';
import type { AtlasBinding } from '../../src/playcanvas/atlas-binding.js';
import { buildBinding, record, type WorldKind } from './binding-harness.js';

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.replaceChildren();
});

const round = (value: number): number => Math.round(value * 1e6) / 1e6;
const colour = (c: pc.Color): readonly number[] => [c.r, c.g, c.b].map(round);

function readings(binding: AtlasBinding): Record<string, unknown> {
  const scene = binding.app.scene;
  const light = (binding.app.root.findByName('atlas-directional-light') as pc.Entity).light!;
  const internals = binding as unknown as { mapState: unknown; controls: { enabled: boolean } };
  const marker = binding.field.entity.findByName('atlas-map-user-marker') as pc.Entity | null;
  return {
    clear: colour(binding.camera.camera!.clearColor),
    fog: colour(scene.fog.color),
    ambient: colour(scene.ambientLight),
    sun: colour(light.color),
    profile: binding.composedWorld.profileId,
    layers: binding.composedWorld.entity.children.map((child) => `${child.name}:${(child as pc.Entity).enabled}`),
    skyHorizon: binding.composedWorld.skyHorizonColour()?.map(round) ?? null,
    map: internals.mapState !== null,
    mapMarker: marker?.enabled ?? null,
    regionMass: binding.regionMass.entity.enabled,
    regionRelief: binding.regionRelief.entity.enabled,
    overlayHidden: binding.overlay?.root.hidden ?? null,
    mapOverlayHidden: binding.mapOverlay?.root.hidden ?? null,
    controlsEnabled: internals.controls.enabled,
    pose: Object.fromEntries(Object.entries(binding.controls.state).map(([key, value]) => [key, round(value)])),
  };
}

async function walkThrough(kind: WorldKind): Promise<Record<string, unknown>> {
  const { binding } = await buildBinding(kind);
  try {
    binding.update(1 / 60, 10_000);
    const steps: Record<string, unknown> = { built: readings(binding) };
    binding.setMapMode(true);
    steps.mapOn = readings(binding);
    binding.update(1 / 60, 10_016);
    steps.mapFrame = readings(binding);
    binding.setMapMode(false);
    steps.mapOff = readings(binding);
    binding.setArtProfile(SURVEY_RELIEF);
    steps.surveyRelief = readings(binding);
    binding.setMapMode(true);
    steps.surveyReliefMapOn = readings(binding);
    binding.setMapMode(false);
    binding.setArtProfile(ORIGIN_LANDSCAPE);
    steps.originLandscape = readings(binding);
    return steps;
  } finally {
    binding.destroy();
  }
}

describe('appearance and the Map, step by step', () => {
  for (const kind of ['authored-endless', 'personal-regions', 'owned-district'] as const) {
    it(`changes ${kind} as pinned`, async () => {
      const steps = await walkThrough(kind);
      await expect(`${JSON.stringify(steps, null, 1)}\n`).toMatchFileSnapshot(`pins/appearance-${kind}.json`);
    });
  }

  it('aims the fog at the sky it draws, and at the clear colour where it draws none', async () => {
    const steps = await walkThrough('authored-endless') as Record<string, Record<string, unknown>>;
    // The origin landscape draws a sky, so fog meets the sky's eye-level colour.
    expect(steps.built!.skyHorizon).not.toBeNull();
    expect(steps.built!.fog).toEqual(steps.built!.skyHorizon);
    // The Map hides the sky, so the fog is the Map's clear colour.
    expect(steps.mapOn!.skyHorizon).toBeNull();
    expect(steps.mapOn!.fog).toEqual(steps.mapOn!.clear);
    expect(steps.mapOn!.clear).not.toEqual(steps.built!.clear);
    // Leaving the Map restores the ground pose, the clear colour and the fog on the sky.
    expect(steps.mapOff!.pose).toEqual(steps.built!.pose);
    expect(steps.mapOff!.clear).toEqual(steps.built!.clear);
    expect(steps.mapOff!.fog).toEqual(steps.built!.fog);
    // A profile with no sky of its own: the fog is its clear colour.
    expect(steps.surveyRelief!.skyHorizon).toBeNull();
    expect(steps.surveyRelief!.fog).toEqual(steps.surveyRelief!.clear);
    expect(steps.originLandscape!.fog).toEqual(steps.built!.fog);
  });

  it('passes a theme to every collaborator that draws in theme colours', async () => {
    const { binding } = await buildBinding('personal-regions');
    try {
      const log: string[] = [];
      record(log, binding.motes, 'motes', ['setTheme']);
      record(log, binding.field, 'field', ['setTheme']);
      record(log, binding.composedWorld, 'composedWorld', ['setTheme']);
      binding.setTheme(DAWN_THEME);
      expect(log).toEqual(['motes.setTheme', 'field.setTheme', 'composedWorld.setTheme']);
    } finally {
      binding.destroy();
    }
  });
});
