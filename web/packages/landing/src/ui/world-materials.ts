/** Shared colors for the CSS fallback and the optical renderer. */
export const ORBIT_PALETTES = [
  ['#e2f8fc', '#89bade', '#797dc2'],
  ['#e4f5d0', '#93c8b3', '#548eaa'],
  ['#fff2cf', '#e8b391', '#ba85ae'],
  ['#efe4fb', '#b5acd9', '#7998cc'],
  ['#f7f9c4', '#c5d78d', '#81b7a6'],
  ['#ffe9df', '#e3acc6', '#a098d1'],
] as const;

export const orbitMaterial = (index: number): number => (index * 5 + Math.floor(index / 6)) % ORBIT_PALETTES.length;
export function orbitGradient(index: number): string {
  const [light, middle, shade] = ORBIT_PALETTES[orbitMaterial(index) % ORBIT_PALETTES.length]!;
  return `radial-gradient(ellipse at ${20 + index % 5 * 12}% 14%, ${light}, transparent 72%), linear-gradient(${125 + index * 17}deg, ${middle} 15%, ${shade})`;
}
