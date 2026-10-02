import {
  PRESENTATION_THEMES,
  type PresentationTheme,
  type WorldArtProfile,
} from '@exulanica/presentation';
import { resolvedAppearance, type AtlasPreferences } from './preferences.js';

export function themeForPreferences(
  preferences: AtlasPreferences,
  systemDark: boolean,
): PresentationTheme {
  return PRESENTATION_THEMES[resolvedAppearance(preferences.appearance, systemDark)];
}

/** The small DOM adapter; the theme definition itself remains engine and browser neutral. */
export function applyDocumentTheme(
  theme: PresentationTheme,
  root: HTMLElement = document.documentElement,
): void {
  root.dataset['theme'] = theme.name;
  root.style.colorScheme = theme.colorScheme;
}

/**
 * Apply the complete semantic UI language owned by the active world profile. Components use only
 * these roles, so changing world identity can change palette, type, texture, blur, and motion
 * without changing component selectors or markup. Control geometry is deliberately absent: the
 * same commands keep the same silhouettes, hit areas, placement, and reading order in every world.
 */
export function applyDocumentWorldStyle(
  profile: WorldArtProfile,
  root: HTMLElement = document.documentElement,
): WorldArtProfile {
  const { colors, chromatic, typography, material, texture, motion } = profile.ui;
  root.dataset['worldStyle'] = profile.profileId;
  root.dataset['uiTexture'] = texture.kind;

  // Earlier profile versions could write these inline. Clear that legacy authority so the fixed
  // system tokens in tokens.css are the only source of component shape after a live update/HMR.
  for (const property of [
    '--radius-label',
    '--radius-control',
    '--radius-panel',
    '--radius-pill',
    '--ui-choice-radius',
    '--ui-speech-radius',
  ]) root.style.removeProperty(property);

  const properties: Readonly<Record<string, string>> = {
    '--ground': colors.ground,
    '--surface': colors.surface,
    '--raised': colors.raised,
    '--ink': colors.ink,
    '--ink-soft': colors.body,
    '--ink-faint': colors.muted,
    '--accent': colors.accent,
    '--accent-soft': colors.secondary,
    '--focus': colors.focus,
    '--warning': colors.warning,
    '--error': colors.error,
    '--user': colors.user,
    '--capture': colors.capture,
    '--inference': colors.inference,
    '--external': colors.external,
    '--user-mark': colors.userMark,
    '--capture-mark': colors.captureMark,
    '--inference-mark': colors.inferenceMark,
    '--external-mark': colors.externalMark,
    '--ui-companion-surface': colors.companionSurface,
    '--ui-companion-surface-hover': colors.companionSurfaceHover,
    '--ui-companion-text': colors.companionText,
    '--ui-companion-accent': colors.companionAccent,
    '--ui-companion-secondary': colors.companionSecondary,
    '--ui-companion-ink': colors.companionInk,
    '--ui-companion-unavailable': colors.companionUnavailable,
    '--ui-shadow': colors.shadow,
    '--ui-vignette': colors.vignette,
    '--ui-spectrum-rose': chromatic.rose,
    '--ui-spectrum-orange': chromatic.orange,
    '--ui-spectrum-violet': chromatic.violet,
    '--ui-spectrum-blue': chromatic.blue,
    '--ui-spectrum-green': chromatic.green,
    '--ui-chromatic-ink': chromatic.ink,
    '--ui-chromatic-paper': chromatic.paper,
    '--ui-chromatic-accent': chromatic.accent,
    '--ui-font-body': typography.body,
    '--ui-font-display': typography.display,
    '--ui-font-utility': typography.utility,
    '--ui-font-companion': typography.companion,
    '--profile-blur-world': `${material.worldBlur}px`,
    '--profile-blur-system': `${material.systemBlur}px`,
    '--profile-ui-companion-blur': `${material.companionBlur}px`,
    '--saturation-world': String(material.worldSaturation),
    '--saturation-system': String(material.systemSaturation),
    '--ui-companion-saturation': String(material.companionSaturation),
    '--profile-grain-opacity': String(material.textureOpacity),
    '--grain-blend': texture.blendMode,
    '--motion-quick': `${motion.quickMs}ms`,
    '--motion-standard': `${motion.standardMs}ms`,
    '--motion-deliberate': `${motion.deliberateMs}ms`,
    '--motion-idle-cycle': `${motion.idleCycleMs}ms`,
    '--motion-working-cycle': `${motion.workingCycleMs}ms`,
    '--motion-stagger': `${motion.staggerMs}ms`,
    '--motion-easing': motion.easing,
  };
  for (const [name, value] of Object.entries(properties)) root.style.setProperty(name, value);
  return profile;
}

/** Apply every document-level appearance decision together so surfaces cannot drift. */
export function applyDocumentAppearance(
  preferences: AtlasPreferences,
  systemDark: boolean,
  root: HTMLElement = document.documentElement,
): PresentationTheme {
  const theme = themeForPreferences(preferences, systemDark);
  applyDocumentTheme(theme, root);
  root.dataset['uiScheme'] = preferences.scheme;
  root.dataset['contrast'] = preferences.contrast;
  root.dataset['transparency'] = preferences.transparency;
  return theme;
}
