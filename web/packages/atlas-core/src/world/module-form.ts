import type { WorldModuleRole } from './module-role.js';

/**
 * What a world module is built as, declared by the catalog rather than decided in a renderer.
 *
 * `world-memory-model.md` section 5.1 permits procedural construction and forbids unrecorded
 * procedural meaning: a grammar may emit thousands of vertices, but its identity, version,
 * parameters and declared semantics have to be written down somewhere durable. Section 11.6 says
 * the same thing as an acceptance rule, that no visual work counts if its meaning exists only in
 * entity names or mesh-generation loops. A form declared here satisfies both, because the module
 * key and version that carry it are already pinned in the topology digest.
 *
 * This vocabulary lives in atlas-core because atlas-core is the base package: the renderer and
 * `@exulanica/presentation` both depend on it, and a shared name can only avoid drifting if it has
 * one home below everything that uses it. `@exulanica/presentation` still declares its own copy for
 * world style profiles; `world-module-form.test.ts` fails when the two disagree, which is the check
 * that was missing when the style registry and the presentation package silently diverged.
 */
export type WorldLandmarkFormKind = 'aero-beacon' | 'survey-strata';
export type WorldEvidenceFormKind = 'memory-lens' | 'indexed-bays';
export type WorldExpansionFormKind = 'living-buds' | 'survey-stakes';

export type WorldModuleFormKind =
  | WorldLandmarkFormKind
  | WorldEvidenceFormKind
  | WorldExpansionFormKind;

export const WORLD_LANDMARK_FORM_KINDS: readonly WorldLandmarkFormKind[] =
  Object.freeze(['aero-beacon', 'survey-strata']);
export const WORLD_EVIDENCE_FORM_KINDS: readonly WorldEvidenceFormKind[] =
  Object.freeze(['memory-lens', 'indexed-bays']);
export const WORLD_EXPANSION_FORM_KINDS: readonly WorldExpansionFormKind[] =
  Object.freeze(['living-buds', 'survey-stakes']);

/**
 * Registered names that no renderer draws.
 *
 * `memory-lens` and `indexed-bays` are implemented nowhere: evidence bodies come from the
 * source-first grove when a real photograph exists, and section 8.3 of the interaction model is
 * why nothing decorative stands in when one does not.
 *
 * `aero-beacon` and `survey-strata` are drawn by nothing either. No builder draws these kinds: the
 * renderer loops that used to stand a beacon or a set of survey ribs at a region were invented
 * shapes and were deleted. A landmark will come from a grammar record, not from a renderer form.
 *
 * All four stay registered so a name can still be checked, and they stay out of
 * `WORLD_FORM_KINDS_BY_ROLE` so no module can promise a shape that will never appear.
 *
 * This list exists because the first version of this file asserted all six were drawn. The test
 * compared two hand-written lists, both wrong in the same way, and passed.
 */
export const WORLD_UNRENDERED_FORM_KINDS: readonly WorldModuleFormKind[] =
  Object.freeze([...WORLD_EVIDENCE_FORM_KINDS, ...WORLD_LANDMARK_FORM_KINDS]);

/**
 * Which forms each role may declare.
 *
 * A role absent from this table has no declarable vocabulary and must declare no form, so a module
 * cannot promise a shape the renderer has never agreed to draw. Adding a role here is a deliberate
 * act with a renderer obligation attached, and `world-module-form.test.ts` discharges it by
 * building the form and looking for geometry rather than by consulting another list.
 *
 * Every absent role is absent for a checked reason, not an oversight:
 *
 * - `navigation-field`, `region-foundation` and `relationship-path` are drawn by the continuous
 *   world field shader, which takes region bodies and confirmed traces as uniforms. A per-instance
 *   form has nothing to select there.
 * - `landmark` draws nothing. Its two registered forms were invented renderer shapes, and a
 *   landmark will be a grammar record; until one exists a landmark module declares no form.
 * - `evidence-assembly` draws nothing decorative on purpose. Evidence bodies come from the
 *   source-first grove when a real photograph exists, and nothing stands in when one does not.
 * - `reconstruction-assembly` realizes admitted reconstruction artifacts, so its appearance is
 *   owned by the evidence it has rather than by a catalog choice.
 */
export const WORLD_FORM_KINDS_BY_ROLE: ReadonlyMap<WorldModuleRole, readonly WorldModuleFormKind[]> =
  new Map<WorldModuleRole, readonly WorldModuleFormKind[]>([
    ['expansion-point', WORLD_EXPANSION_FORM_KINDS],
  ]);

/** Every form a module may actually declare, across all roles. */
export const WORLD_DECLARABLE_FORM_KINDS: readonly WorldModuleFormKind[] = Object.freeze(
  [...WORLD_FORM_KINDS_BY_ROLE.values()].flat(),
);

export const WORLD_MODULE_FORM_KINDS: readonly WorldModuleFormKind[] = Object.freeze([
  ...WORLD_LANDMARK_FORM_KINDS,
  ...WORLD_EVIDENCE_FORM_KINDS,
  ...WORLD_EXPANSION_FORM_KINDS,
]);

/** Parameter names a form may carry. Bounded so a catalog cannot smuggle arbitrary renderer state. */
const PARAMETER_KEY = /^[a-z][a-zA-Z0-9]{0,31}$/;
const MAXIMUM_PARAMETERS = 8;

export interface WorldModuleForm {
  readonly kind: WorldModuleFormKind;
  /**
   * Grammar parameters, recorded rather than merely emitted.
   *
   * Absent keys mean the world style still decides that dimension, so declaring a form states what
   * a module is without seizing how the current style renders it.
   */
  readonly parameters: Readonly<Record<string, number>>;
}

/** Why this form is not declarable by a module in this role, or null when it is. */
export function moduleFormFailure(
  role: WorldModuleRole,
  form: WorldModuleForm | null,
): string | null {
  const permitted = WORLD_FORM_KINDS_BY_ROLE.get(role);
  if (form === null) return null;
  if (permitted === undefined) return `role ${role} has no registered form vocabulary`;
  if (!permitted.includes(form.kind)) {
    return `form ${form.kind} is not one of ${permitted.join(', ')} for role ${role}`;
  }
  const entries = Object.entries(form.parameters);
  if (entries.length > MAXIMUM_PARAMETERS) {
    return `form ${form.kind} declares more than ${MAXIMUM_PARAMETERS} parameters`;
  }
  for (const [key, value] of entries) {
    if (!PARAMETER_KEY.test(key)) return `form parameter ${key} is not a stable name`;
    if (!Number.isFinite(value) || value < 0) return `form parameter ${key} must be finite and non-negative`;
  }
  return null;
}
