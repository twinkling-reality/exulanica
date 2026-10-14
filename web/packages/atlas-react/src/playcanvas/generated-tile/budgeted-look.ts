import type { RenderCaps } from '@exulanica/atlas-core';
import { isRenderLook, type TileLook } from './look.js';

/**
 * A look drawn within a scene form's render budget (`render-budget.ts` in atlas-core): each of its
 * sun shadow and contact shadowing values lowered to its cap, never raised. A look within every cap
 * is returned as it is, the same object, so a budget at the look's ceilings changes nothing at all.
 *
 * Presentation only. Pure: the look is not changed; a lowered look is a new frozen one.
 */
export function budgetedLook(look: TileLook, caps: RenderCaps): TileLook {
  const shadow = look.sun.shadow;
  const contact = look.contactShadow;
  const cascades = Math.min(shadow.cascades, caps.sunShadowCascades);
  const resolution = Math.min(shadow.resolution, caps.sunShadowResolutionPx);
  const distanceM = Math.min(shadow.distanceM, caps.sunShadowDistanceM);
  const samples = Math.min(contact.samples, caps.contactShadowSamples);
  const scale = Math.min(contact.scale, caps.contactShadowScale);
  const shadowWithin = cascades === shadow.cascades && resolution === shadow.resolution && distanceM === shadow.distanceM;
  const contactWithin = samples === contact.samples && scale === contact.scale;
  if (shadowWithin && contactWithin) return look;
  const lowered = { cascades, resolution, distanceM };
  const contactShadow = contactWithin ? contact : Object.freeze({ ...contact, samples, scale });
  // Each descriptor's sun is its own shape, so each is copied as itself.
  if (isRenderLook(look)) {
    const sun = shadowWithin ? look.sun : Object.freeze({ ...look.sun, shadow: Object.freeze({ ...look.sun.shadow, ...lowered }) });
    return Object.freeze({ ...look, sun, contactShadow });
  }
  const sun = shadowWithin ? look.sun : Object.freeze({ ...look.sun, shadow: Object.freeze({ ...look.sun.shadow, ...lowered }) });
  return Object.freeze({ ...look, sun, contactShadow });
}
