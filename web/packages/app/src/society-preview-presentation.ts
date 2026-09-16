import { parseSociety, type SocietySnapshot } from './society-api.js';

export interface RecordedSocietyPreview {
  readonly status:string;
  readonly frames: readonly {
    readonly snapshot: SocietySnapshot;
    readonly change: string | null;
    readonly authored_objects: readonly unknown[];
  }[];
  readonly events: readonly {
    readonly event_id: string;
    readonly subject_id: string;
    readonly tick: number;
    readonly document: { readonly summary: string; readonly branch_id: string };
  }[];
}

/** Only the explicitly labeled development recording uses this shape; it is not an API. */
export function parseRecordedSocietyPreview(
  value: unknown,
  districtDigest: string,
): RecordedSocietyPreview {
  const row = value as Record<string, unknown> | null;
  if (
    !row ||
    row['profile'] !== 'exulanica.living-world-preview-fixture/v1' ||
    row['district_document_sha256'] !== districtDigest ||
    !Array.isArray(row['frames']) ||
    !Array.isArray(row['events'])
  )
    throw new Error('Recorded society fixture does not match this district');
  const frames = row['frames'].map((raw: Record<string, unknown>) => ({
    snapshot: parseSociety(raw['snapshot']),
    change: typeof raw['change'] === 'string' ? raw['change'] : null,
    authored_objects: Array.isArray(raw['authored_objects'])
      ? raw['authored_objects']
      : [],
  }));
  if (
    !frames.length ||
    frames.some(
      (f, i) =>
        f.snapshot.state.profile !== 'exulanica-society/v2' ||
        f.snapshot.currentTick !== i ||
        f.snapshot.societyId !== frames[0]!.snapshot.societyId ||
        f.snapshot.versionId !== frames[0]!.snapshot.versionId,
    )
  )
    throw new Error('Recorded society fixture has discontinuous history');
  const events = row['events'].map((raw: Record<string, unknown>) => {
    const doc = raw['document'] as Record<string, unknown> | null;
    if (
      !doc ||
      typeof raw['event_id'] !== 'string' ||
      typeof raw['subject_id'] !== 'string' ||
      !Number.isSafeInteger(raw['tick']) ||
      typeof doc['summary'] !== 'string' ||
      doc['branch_id'] !== frames[0]!.snapshot.versionId ||
      doc['subject_id'] !== raw['subject_id'] ||
      doc['tick'] !== raw['tick']
    )
      throw new Error('Recorded society event binding is invalid');
    return {
      event_id: raw['event_id'],
      subject_id: raw['subject_id'],
      tick: raw['tick'] as number,
      document: {
        summary: doc['summary'],
        branch_id: doc['branch_id'] as string,
      },
    };
  });
  return { frames, events, status:typeof row['status']==='string'?row['status']:'Recorded preview, not persistence evidence.' };
}
