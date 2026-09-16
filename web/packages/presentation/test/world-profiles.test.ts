import { describe, expect, it } from 'vitest';
import { BLUE_HOUR_THEME, DAWN_THEME } from '../src/system.js';
import {
  DEFAULT_WORLD_ART_PROFILE,
  ORIGIN_LANDSCAPE,
  SURVEY_RELIEF,
  WORLD_ART_PROFILES,
  contrastRatio,
  deriveWorldUiColors,
  mixHex,
  perceptualColour,
  resolveWorldStyleParameters,
  worldStyleControls,
  worldArtProfile,
} from '../src/world-profiles.js';
import { validateWorldStyleControlManifest } from '../src/world-style-capabilities.js';

describe('world art profiles', () => {
  it('offers materially different worlds over one protected topology contract', () => {
    expect(ORIGIN_LANDSCAPE.geometry.expansion).not.toBe(SURVEY_RELIEF.geometry.expansion);
    expect(ORIGIN_LANDSCAPE.field).not.toEqual(SURVEY_RELIEF.field);
    // No profile authors an orientation register or evidence silhouette any more: the renderer
    // drew invented shapes from those tokens, and a region with no recorded register shows none.
    for (const profile of [ORIGIN_LANDSCAPE, SURVEY_RELIEF]) {
      expect(profile.geometry).not.toHaveProperty('landmark');
      expect(profile.geometry).not.toHaveProperty('evidence');
      expect(profile.geometry).not.toHaveProperty('landmarkHeight');
      expect(profile.geometry).not.toHaveProperty('landmarkWidth');
    }
    expect(ORIGIN_LANDSCAPE.compatibilityKey).toBe(SURVEY_RELIEF.compatibilityKey);
    expect(ORIGIN_LANDSCAPE.semanticChannels).toEqual(SURVEY_RELIEF.semanticChannels);
    expect(ORIGIN_LANDSCAPE.palette.sky).not.toBe(ORIGIN_LANDSCAPE.palette.terrain);
  });

  it('derives a coherent interface language from each world without replacing topology', () => {
    expect(ORIGIN_LANDSCAPE.ui.colors).not.toEqual(SURVEY_RELIEF.ui.colors);
    expect(ORIGIN_LANDSCAPE.ui.typography).not.toEqual(SURVEY_RELIEF.ui.typography);
    expect(ORIGIN_LANDSCAPE.ui).not.toHaveProperty('geometry');
    expect(SURVEY_RELIEF.ui).not.toHaveProperty('geometry');
    expect(ORIGIN_LANDSCAPE.ui.material.companionBlur).toBeGreaterThan(
      SURVEY_RELIEF.ui.material.companionBlur,
    );
    expect(ORIGIN_LANDSCAPE.ui.texture.kind).toBe('paper-grain');
    expect(SURVEY_RELIEF.ui.texture.kind).toBe('contour-grid');
    expect(ORIGIN_LANDSCAPE.ui.motion).not.toEqual(SURVEY_RELIEF.ui.motion);
    expect(ORIGIN_LANDSCAPE.compatibilityKey).toBe(SURVEY_RELIEF.compatibilityKey);
  });

  it('does not accept an independently authored interface palette and guarantees readable roles', () => {
    expect(ORIGIN_LANDSCAPE.ui.colors)
      .toEqual(deriveWorldUiColors(ORIGIN_LANDSCAPE.palette, ORIGIN_LANDSCAPE.interfacePalette));
    expect(SURVEY_RELIEF.ui.colors)
      .toEqual(deriveWorldUiColors(SURVEY_RELIEF.palette, SURVEY_RELIEF.interfacePalette));
    // Survey Relief authors no interface roots, so it must still resolve from its scene alone.
    expect(SURVEY_RELIEF.interfacePalette).toBeUndefined();
    expect(SURVEY_RELIEF.ui.colors).toEqual(deriveWorldUiColors(SURVEY_RELIEF.palette));
    expect(contrastRatio(
      ORIGIN_LANDSCAPE.ui.colors.ink,
      ORIGIN_LANDSCAPE.ui.colors.raised,
    )).toBeGreaterThanOrEqual(7);
    expect(contrastRatio(
      ORIGIN_LANDSCAPE.ui.colors.body,
      ORIGIN_LANDSCAPE.ui.colors.surface,
    )).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(
      ORIGIN_LANDSCAPE.ui.colors.companionText,
      ORIGIN_LANDSCAPE.ui.colors.companionSurface,
    )).toBeGreaterThanOrEqual(7);
  });

  it('spends hue only where hue means something', () => {
    // Reading text, panel material, shadow and the Companion's own surface say nothing by being
    // coloured. They were all darkened world hues, so the type, the rules, the focus ring and the
    // speech band were tinted and none of that tint carried information. Provenance, caution and
    // error are the roles where hue is the message, plus one accent.
    const aeroheart = ORIGIN_LANDSCAPE.ui.colors;
    const structure = [
      'ground', 'surface', 'raised', 'ink', 'body', 'muted', 'shadow', 'vignette',
      'companionSurface', 'companionText', 'companionAccent', 'companionSecondary',
    ] as const;
    for (const role of structure) {
      expect(perceptualColour(aeroheart[role]).chroma).toBeLessThanOrEqual(0.016);
    }
    const meaning = ['accent', 'focus', 'user', 'inference', 'external', 'warning', 'error'] as const;
    for (const role of meaning) {
      expect(perceptualColour(aeroheart[role]).chroma).toBeGreaterThan(0.05);
    }
    // The cap is a ceiling, not a conversion to grey: a world's own cast still reaches structure,
    // and a world that authors no hue at all stays exactly as drab as it wrote itself.
    // `error` is anchored to a red literal on purpose and stays red in every world, because a
    // world's taste does not get to decide how a failure looks.
    const survey = SURVEY_RELIEF.ui.colors;
    for (const role of [...structure, ...meaning].filter((name) => name !== 'error')) {
      expect(perceptualColour(survey[role]).chroma).toBeLessThan(0.08);
    }
  });

  it('uses contrast as a floor rather than as the thing that chooses a colour', () => {
    // Every role once landed within 0.06 of its own minimum, so thirteen roles occupied two
    // values and no component could build a hierarchy on top of them. Reading text must clear its
    // floor with room to spare, and the reading ladder must actually descend.
    const { ink, body, muted, raised, surface } = ORIGIN_LANDSCAPE.ui.colors;
    expect(contrastRatio(ink, raised)).toBeGreaterThan(9);
    expect(contrastRatio(ink, surface)).toBeGreaterThan(contrastRatio(body, surface));
    expect(contrastRatio(body, surface)).toBeGreaterThan(contrastRatio(muted, surface));
    expect(contrastRatio(muted, surface)).toBeGreaterThanOrEqual(4.5);
  });

  it('leaves the reading roles enough margin to survive a real reading surface', () => {
    // `surface` is the lightest ground a world has. A role corrected to exactly 4.5 against it is
    // below 4.5 on the paper a held plate is actually made of, which took ninety labels in the
    // Index to 3.97 while this suite stayed green.
    for (const profile of [ORIGIN_LANDSCAPE, SURVEY_RELIEF]) {
      const colors = profile.ui.colors;
      const plate = mixHex(colors.raised, colors.ink, 0.07);
      const reading = [
        'body', 'muted', 'accent', 'secondary', 'warning', 'error', 'user',
        'capture', 'inference', 'external',
      ] as const;
      for (const role of reading) {
        expect(contrastRatio(colors[role], plate)).toBeGreaterThanOrEqual(4.5);
      }
    }
  });

  it('separates the provenance triad by hue and not only by shape', () => {
    // interaction-model.md 6.1 shows the three marks side by side in one row. While `brass` was
    // the only root with chroma left, user provenance was red and the other two were the same
    // grey as the body text.
    const { user, capture, inference, surface } = ORIGIN_LANDSCAPE.ui.colors;
    const separation = (left: string, right: string): number => {
      const delta = Math.abs(perceptualColour(left).hue - perceptualColour(right).hue);
      return Math.min(delta, Math.PI * 2 - delta);
    };
    expect(separation(user, capture)).toBeGreaterThan(0.7);
    expect(separation(capture, inference)).toBeGreaterThan(0.7);
    expect(separation(inference, user)).toBeGreaterThan(0.7);
    for (const mark of [user, capture, inference]) {
      expect(perceptualColour(mark).chroma).toBeGreaterThan(0.025);
      expect(contrastRatio(mark, surface)).toBeGreaterThanOrEqual(4.5);
    }
  });

  it('lets a mark keep the light the world put in it', () => {
    // A dot, a band rule and a callout edge are graphical objects, so 3:1 is the requirement.
    // Correcting them to the reading floor shipped `#f96858` as `#be2f25`: same hue, no light.
    const colors = ORIGIN_LANDSCAPE.ui.colors;
    const pairs = [
      ['user', 'userMark'], ['capture', 'captureMark'],
      ['inference', 'inferenceMark'], ['external', 'externalMark'],
    ] as const;
    for (const [text, mark] of pairs) {
      expect(contrastRatio(colors[mark], colors.surface)).toBeGreaterThanOrEqual(3);
      expect(contrastRatio(colors[text], colors.surface)).toBeGreaterThanOrEqual(4.5);
      // The mark is the brighter of the two, or the world authored something already dark.
      expect(contrastRatio(colors[mark], colors.surface))
        .toBeLessThanOrEqual(contrastRatio(colors[text], colors.surface) + 0.01);
    }
    // The world's one bright colour reaches the interface as a bright colour.
    expect(perceptualColour(colors.userMark).chroma)
      .toBeGreaterThanOrEqual(perceptualColour(ORIGIN_LANDSCAPE.palette.brass).chroma * 0.9);
  });

  it('keeps caution and user-provided provenance apart', () => {
    // They were the same hex while one root carried the entire interface, which made "you said
    // this" and "be careful" the same mark.
    expect(ORIGIN_LANDSCAPE.ui.colors.warning).not.toBe(ORIGIN_LANDSCAPE.ui.colors.user);
    expect(SURVEY_RELIEF.ui.colors.warning).not.toBe(SURVEY_RELIEF.ui.colors.user);
  });

  it('keeps exposure and art profile as orthogonal axes', () => {
    const combinations = [DAWN_THEME, BLUE_HOUR_THEME].flatMap((theme) =>
      Object.values(WORLD_ART_PROFILES).map((profile) => ({ theme: theme.name, profile: profile.profileId })),
    );
    expect(combinations).toEqual([
      { theme: 'dawn', profile: 'origin-landscape' },
      { theme: 'dawn', profile: 'survey-relief' },
      { theme: 'blue-hour', profile: 'origin-landscape' },
      { theme: 'blue-hour', profile: 'survey-relief' },
    ]);
  });

  it('uses a deterministic safe fallback for unknown or removed profiles', () => {
    expect(worldArtProfile('missing')).toBe(DEFAULT_WORLD_ART_PROFILE);
    expect(worldArtProfile('survey-relief', 99)).toBe(DEFAULT_WORLD_ART_PROFILE);
    expect(worldArtProfile('survey-relief')).toBe(SURVEY_RELIEF);
  });

  it('gives each style its own capability-backed controls and resolves dynamic Aeroheart values', () => {
    expect(worldStyleControls('origin-landscape').map((control) => control.capability)).toContain('material.transmission');
    expect(worldStyleControls('origin-landscape').map((control) => control.capability)).toContain('surface.finish');
    expect(worldStyleControls('origin-landscape').map((control) => control.capability)).toContain('motion.tempo');
    expect(worldStyleControls('survey-relief').map((control) => control.capability)).toContain('detail.contours');
    expect(worldStyleControls('origin-landscape')).not.toEqual(worldStyleControls('survey-relief'));

    const defaults = resolveWorldStyleParameters('origin-landscape');
    const tuned = worldArtProfile('origin-landscape', 1, {
      ...defaults,
      vitality: 0.1,
      glass: 0.2,
      'garden-density': 0.1,
      'surface-finish': 'clear-lens',
      'world-tempo': 1.25,
    });
    expect(tuned.palette.terrain).not.toBe(ORIGIN_LANDSCAPE.palette.terrain);
    expect(tuned.material.gloss).toBeLessThan(ORIGIN_LANDSCAPE.material.gloss);
    expect(tuned.geometry.detailCount).toBeLessThan(ORIGIN_LANDSCAPE.geometry.detailCount);
    expect(tuned.ui.colors).not.toEqual(ORIGIN_LANDSCAPE.ui.colors);
    expect(tuned.ui.colors).toEqual(deriveWorldUiColors(tuned.palette, tuned.interfacePalette));
    // Exactly one module owns each output. The field controls move the field and leave the
    // interface alone; the interface controls do the reverse. Two writers on one value is how a
    // later module silently wins and a control stops meaning what its label says.
    expect(tuned.palette).not.toEqual(ORIGIN_LANDSCAPE.palette);
    expect(tuned.interfacePalette).toEqual(ORIGIN_LANDSCAPE.interfacePalette);
    const resting = worldArtProfile('origin-landscape', 1, defaults);
    const recoloured = worldArtProfile('origin-landscape', 1, { ...defaults, 'source-hue': 0.1 });
    expect(recoloured.interfacePalette).not.toEqual(resting.interfacePalette);
    expect(recoloured.palette).toEqual(resting.palette);
    // Reading a recipe with no parameters and reading it at its own defaults are the same world.
    expect(resting.palette).toEqual(ORIGIN_LANDSCAPE.palette);
    expect(resting.interfacePalette).toEqual(ORIGIN_LANDSCAPE.interfacePalette);
    expect(tuned.ui.texture.kind).toBe('none');
    expect(tuned.ui.material.textureOpacity).toBe(0);
    expect(tuned.ui.motion.idleCycleMs).toBe(4_160);
    expect(worldArtProfile('origin-landscape', 1, defaults)).toEqual(
      worldArtProfile('origin-landscape', 1, defaults),
    );
  });

  it('rejects model-authored controls that invent bindings or widen safe capability ranges', () => {
    expect(validateWorldStyleControlManifest([{
      key: 'magic', capability: 'renderer.execute-code', kind: 'range', group: 'world',
      label: 'Magic', description: 'Unsafe invented binding.', min: 0, max: 1, step: 0.1,
      defaultValue: 0.5,
    }])).toContainEqual(expect.objectContaining({ key: 'magic' }));
    expect(validateWorldStyleControlManifest([{
      key: 'vitality', capability: 'world.vitality', kind: 'range', group: 'world',
      label: 'Vitality', description: 'Too broad.', min: -4, max: 4, step: 0.1,
      defaultValue: 0.5,
    }])).toContainEqual(expect.objectContaining({ key: 'vitality' }));
    expect(validateWorldStyleControlManifest(worldStyleControls('origin-landscape'))).toEqual([]);
    expect(validateWorldStyleControlManifest([{
      key: 'finish', capability: 'surface.finish', kind: 'choice', group: 'material',
      label: 'Finish', description: 'Unsupported remote material.',
      options: [
        { value: 'source-paper', label: 'Source paper' },
        { value: 'remote-css', label: 'Remote CSS' },
      ],
      defaultValue: 'source-paper',
    }])).toContainEqual(expect.objectContaining({ key: 'finish' }));
    expect(validateWorldStyleControlManifest([{
      key: 'tempo', capability: 'motion.tempo', kind: 'range', group: 'motion',
      label: 'Tempo', description: 'Invalid generated default.', min: 0.75, max: 1.25,
      step: 0.05, defaultValue: 8,
    }])).toContainEqual(expect.objectContaining({ key: 'tempo' }));
  });
});
