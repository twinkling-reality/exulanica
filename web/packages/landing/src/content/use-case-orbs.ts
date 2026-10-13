import { USE_CASES } from './use-cases.js';

export const ORB_MATERIALS = ['satin', 'halftone'] as const;
export type OrbMaterial = typeof ORB_MATERIALS[number];

/** Decorative category materials. They do not represent agent status or run data. */
export const USE_CASE_ORBS = {
  'model-comparison': { material: 'satin', palette: 0, phase: 2.4, fallback: ['#edf5f8', '#9dbecb', '#678ba8'] },
  worldbuilding: { material: 'satin', palette: 1, phase: 6.8, fallback: ['#f1f6e7', '#aec9b1', '#779f94'] },
  'agent-development': { material: 'halftone', palette: 2, phase: 11.2, fallback: ['#f5eaf1', '#c7a9bc', '#a47e9e'] },
} as const satisfies Record<typeof USE_CASES[number]['key'], { material: OrbMaterial; palette: number; phase: number; fallback: readonly string[] }>;
