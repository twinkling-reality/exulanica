import type { CapabilityConcept } from './product.js';

/** Particle volumes share one material system and vary through motion and color. */
export const CAPABILITY_SCENES = {
  world: { motion: 'organization', color: '#7294aa', accent: '#7294aa' },
  agents: { motion: 'flow', color: '#659b98', accent: '#659b98' },
  model: { motion: 'reconfiguration', color: '#9185b0', accent: '#9185b0' },
  comparison: { motion: 'divergence', color: '#7294aa', accent: '#ac83a0' },
  connection: { motion: 'convergence', color: '#b38699', accent: '#7294aa' },
} as const satisfies Record<CapabilityConcept, { motion: string; color: string; accent: string }>;

export const CAPABILITY_PARTICLES = Object.freeze({
  width: 440,
  height: 320,
  count: 288,
  bands: 9,
  radius: 112,
  cameraDistance: 460,
  depthLayers: 8,
  dotRadius: 1.25,
  depthRadius: 2.6,
  pointerRadius: 74,
  pointerDisplacement: 15,
  pointerTilt: .22,
});
