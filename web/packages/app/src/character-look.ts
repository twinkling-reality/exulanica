/**
 * The rules a catalog look obeys, kept out of the views.
 *
 * A view builds controls and hands back choices; the look those choices mean, and whether it is a
 * whole valid look over one body, is decided here. That is also why no view module imports the
 * renderer: this is the layer that speaks to it.
 */
import { designedLook, validateLook, type CharacterCatalog, type CharacterLook, type DesignedLooks } from '@exulanica/atlas-react/playcanvas';

/** The catalog's own designed looks, named for the views that may not reach the renderer. */
export { designedLook } from '@exulanica/atlas-react/playcanvas';

/** Two looks name the same choices, whatever order their fields were written in. */
export function sameLook(a: CharacterLook, b: CharacterLook): boolean {
  return JSON.stringify(canonical(a)) === JSON.stringify(canonical(b));
}

function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.keys(value).sort().map((key) => [key, canonical((value as Record<string, unknown>)[key])]));
  }
  return value;
}

/** The same person over another body: shared choices kept, the rest from that body's default. */
export function lookOverBase(catalog: CharacterCatalog, looks: DesignedLooks, look: CharacterLook, baseId: string): CharacterLook {
  if (look.baseId === baseId) return look;
  const family = catalog.families.find((candidate) => candidate.familyId === look.familyId)!;
  const from = family.bases.find((candidate) => candidate.baseId === look.baseId)!;
  const to = family.bases.find((candidate) => candidate.baseId === baseId);
  const fallback = designedLook(looks, looks.defaults.bases[baseId] ?? '');
  if (!to) throw new TypeError(`Unknown base ${baseId}`);
  const parts: Record<string, string | null> = {};
  for (const slot of family.slots.filter((candidate) => candidate.kind === 'part')) {
    const chosen = look.parts[slot.slot] ?? null;
    if (chosen === null) {
      parts[slot.slot] = slot.optional ? null : fallback.parts[slot.slot] ?? null;
      continue;
    }
    const twin = `${baseId}${chosen.slice(chosen.indexOf('/'))}`;
    parts[slot.slot] = to.parts.some((part) => part.partId === twin && part.slot === slot.slot) ? twin : fallback.parts[slot.slot] ?? null;
  }
  const materials: Record<string, string> = {};
  for (const slot of family.slots.filter((candidate) => candidate.kind === 'material')) {
    const index = (from.materials[slot.slot] ?? []).indexOf(look.materials[slot.slot]!);
    const options = to.materials[slot.slot] ?? [];
    materials[slot.slot] = index >= 0 && index < options.length ? options[index]! : fallback.materials[slot.slot]!;
  }
  const parameters: Record<string, number> = {};
  for (const parameter of family.parameters) {
    const value = look.parameters[parameter.key]!;
    const bounds = parameter.unit === 'mm' ? to.heightMillimetres : parameter;
    parameters[parameter.key] = Math.max(bounds.min, Math.min(bounds.max, value));
  }
  const next: CharacterLook = { ...look, baseId, parts, materials, colours: { ...look.colours }, parameters };
  validateLook(catalog, next);
  return next;
}

/** A look is only ever handed on after the catalog has agreed to it. */
export function checkedLook(catalog: CharacterCatalog, look: CharacterLook): CharacterLook {
  validateLook(catalog, look);
  return look;
}
