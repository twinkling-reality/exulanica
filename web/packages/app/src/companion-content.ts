/**
 * Companion presentation of existing `Intent.CONTENT` rows.
 *
 * The rows come from `selection.content` on a `POST /selection/ask` response, which answers a
 * confirmed place's CONTENT plan without a model. This module parses the same validated
 * ContentView the direct Selection controls return and says what each row is in plain words.
 * Identifiers stay in the parsed row for inspection and are never printed as the description.
 */

export interface CompanionContentRow {
  readonly resultKind: string;
  readonly originKind: string;
  readonly contentKind: string;
  readonly authoredRole: string | null;
  readonly placeRelationship: string;
  readonly matchReason: string;
  readonly memoryPlaceEntityId: string;
  readonly canonicalPlaceId: string | null;
  readonly worldId: string | null;
  readonly versionId: string | null;
  readonly sourceId: string;
  readonly lineageIds: readonly string[];
  readonly label: string | null;
  readonly availability: string;
  readonly personalVisitEvidence: boolean;
}

export interface CompanionContentSurface {
  readonly rows: readonly CompanionContentRow[];
  /** True when a confirmed place bridge existed and Selection ran. */
  readonly placeConfirmed: boolean;
  readonly totalMatched: number;
}

interface WireContentRow {
  readonly result_kind?: unknown;
  readonly origin_kind?: unknown;
  readonly content_kind?: unknown;
  readonly authored_role?: unknown;
  readonly place_relationship?: unknown;
  readonly match_reason?: unknown;
  readonly memory_place_entity_id?: unknown;
  readonly canonical_place_id?: unknown;
  readonly world_id?: unknown;
  readonly version_id?: unknown;
  readonly source_id?: unknown;
  readonly lineage_ids?: unknown;
  readonly label?: unknown;
  readonly availability?: unknown;
  readonly personal_visit_evidence?: unknown;
}

interface WireSelection {
  readonly content?: unknown;
  readonly total_matched?: unknown;
}

const textOrNull = (value: unknown): string | null =>
  typeof value === 'string' && value.length > 0 ? value : null;

const textOrAbsent = (value: unknown, absent: string): string =>
  typeof value === 'string' && value.length > 0 ? value : absent;

/**
 * Parse one ContentView row. Unknown or missing scalars become explicit absences rather than
 * invented defaults, except booleans which the wire always carries.
 */
export function parseContentRow(value: unknown): CompanionContentRow | null {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return null;
  const row = value as WireContentRow;
  const lineage = Array.isArray(row.lineage_ids)
    ? row.lineage_ids.filter((item): item is string => typeof item === 'string')
    : [];
  return Object.freeze({
    resultKind: textOrAbsent(row.result_kind, '(result kind not supplied)'),
    originKind: textOrAbsent(row.origin_kind, '(origin not supplied)'),
    contentKind: textOrAbsent(row.content_kind, '(content kind not supplied)'),
    authoredRole: textOrNull(row.authored_role),
    placeRelationship: textOrAbsent(row.place_relationship, '(place relationship not supplied)'),
    matchReason: textOrAbsent(row.match_reason, '(match reason not supplied)'),
    memoryPlaceEntityId: textOrAbsent(
      row.memory_place_entity_id,
      '(memory place not supplied)',
    ),
    canonicalPlaceId: textOrNull(row.canonical_place_id),
    worldId: textOrNull(row.world_id),
    versionId: textOrNull(row.version_id),
    sourceId: textOrAbsent(row.source_id, '(source not supplied)'),
    lineageIds: Object.freeze(lineage),
    label: textOrNull(row.label),
    availability: textOrAbsent(row.availability, '(availability not supplied)'),
    personalVisitEvidence: row.personal_visit_evidence === true,
  });
}

export function parseContentSurface(
  selection: unknown,
  options: { readonly placeConfirmed: boolean },
): CompanionContentSurface {
  if (typeof selection !== 'object' || selection === null || Array.isArray(selection)) {
    return Object.freeze({
      rows: Object.freeze([]),
      placeConfirmed: options.placeConfirmed,
      totalMatched: 0,
    });
  }
  const wire = selection as WireSelection;
  const raw = Array.isArray(wire.content) ? wire.content : [];
  const rows = Object.freeze(
    raw.map(parseContentRow).filter((row): row is CompanionContentRow => row !== null),
  );
  const totalMatched =
    typeof wire.total_matched === 'number' && Number.isFinite(wire.total_matched)
      ? wire.total_matched
      : rows.length;
  return Object.freeze({
    rows,
    placeConfirmed: options.placeConfirmed,
    totalMatched,
  });
}

/** What an unlabelled row is, by kind. Mirrors the server's own answer sentences. */
const UNLABELLED: Readonly<Record<string, string>> = {
  memory_capture: 'A photograph in your library',
  admitted_environment_source: 'An admitted source',
  admitted_environment_feature: 'A feature derived from an admitted source',
  authored_environment_instance: 'An authored addition',
  synthetic_inhabitant: 'An unnamed inhabitant',
  simulation_event: 'An unlabelled simulation event',
};

const KIND: Readonly<Record<string, string>> = {
  memory_capture: 'Your photograph',
  admitted_environment_source: 'Admitted source record',
  admitted_environment_feature: 'Feature from an admitted source',
  authored_environment_instance: 'Authored addition to a world',
  synthetic_inhabitant: 'Simulated inhabitant',
  simulation_event: 'Simulated event',
};

const ORIGIN: Readonly<Record<string, string>> = {
  personal: 'Your own photographs',
  imported: 'An admitted outside source',
  authored: 'Made in a world, not observed',
  simulated: 'The world simulation, not observed',
};

const RELATION: Readonly<Record<string, string>> = {
  captured_at: 'Taken at this place',
  admitted_for: 'Admitted for this place',
  derived_from: 'Made from this place’s source records',
  simulated_at: 'Simulated at this place',
};

const AVAILABILITY: Readonly<Record<string, string>> = {
  available: 'Available',
  unavailable_bytes: 'Recorded, but its file is missing',
  unknown: 'Not checked',
};

const ROLE: Readonly<Record<string, string>> = {
  fictional: 'invented for this world',
  personal: 'connected to something you experienced',
};

/**
 * Field lines for one CONTENT row, in plain words. Authored and simulated origins stay labelled
 * as such; they are never phrased as recovered personal memories, and only a memory capture is
 * said to count as a personal visit.
 */
export function contentRowFields(row: CompanionContentRow): readonly {
  readonly label: string;
  readonly value: string;
}[] {
  const kind = KIND[row.resultKind] ?? 'Related record';
  const role = row.authoredRole === null ? null : ROLE[row.authoredRole] ?? null;
  return Object.freeze([
    { label: 'Record', value: row.label ?? UNLABELLED[row.resultKind] ?? 'A related record' },
    { label: 'What it is', value: role === null ? kind : `${kind}, ${role}` },
    { label: 'Where it comes from', value: ORIGIN[row.originKind] ?? 'Not stated' },
    { label: 'This place', value: RELATION[row.placeRelationship] ?? 'Related to this place' },
    { label: 'Available', value: AVAILABILITY[row.availability] ?? 'Not available' },
    {
      label: 'Counts as a visit',
      value: row.personalVisitEvidence ? 'Yes, your own photograph from here' : 'No',
    },
  ]);
}
