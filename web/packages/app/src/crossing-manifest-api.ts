/**
 * What came across with a visitor and what stayed behind, from its crossing's translation manifest
 * (`GET /door/crossings/{arrival_id}/manifest?world_id=`, the stored
 * `exulanica.translation-manifest/v2` byte for byte): each field the game's mapping accounted for,
 * in the game's own words, with its reason in words wherever it did not cross exactly. The page
 * holds no words of any game: every line comes from the manifest.
 *
 * A manifest of the first profile states no words, so it gives no rows; any other shape is refused.
 */
import type { Credentials } from './config.js';

export const MANIFEST_PROFILE_WITH_WORDS = 'exulanica.translation-manifest/v2';

/** One line of the card: what it was and became, in the game's words, and why where it changed. */
export interface CrossedLine {
  readonly words: string;
  /** Why, in the game's words; null for what crossed exactly. */
  readonly reason: string | null;
}

/** What stayed behind for one reason: the fields it covers, in words, and the reason once. */
export interface StayedGroup {
  readonly words: readonly string[];
  readonly reason: string;
}

export interface CrossingRows {
  /** What came across: exactly, then approximated with its reason, each in the manifest's order. */
  readonly came: readonly CrossedLine[];
  /** What stayed behind (dropped, or kept by the program it came from), grouped by shared reason. */
  readonly stayed: readonly StayedGroup[];
}

export interface CrossingManifest {
  readonly manifestSha256: string;
  readonly from: { readonly bridge: string; readonly label: string; readonly ai: boolean };
  /** Null for a manifest of the first profile, which states no words. */
  readonly rows: CrossingRows | null;
}

const invalid = (what: string): never => { throw new Error(`Invalid crossing manifest: ${what}`); };
const object = (value: unknown, what: string): Record<string, unknown> =>
  value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : invalid(what);
const text = (value: unknown, what: string): string => (typeof value === 'string' && value.trim() !== '' ? value : invalid(what));

const DISPOSITIONS = ['exact', 'approximated', 'dropped', 'opaque'] as const;
type Disposition = typeof DISPOSITIONS[number];

/** The manifest's fields as the card's rows. */
export function crossingRows(manifest: unknown): CrossingRows | null {
  const held = object(manifest, 'document');
  if (held['profile'] !== MANIFEST_PROFILE_WITH_WORDS) {
    if (held['profile'] === 'exulanica.translation-manifest/v1') return null;
    invalid('profile');
  }
  const fields = Array.isArray(held['fields']) ? held['fields'] : invalid('fields');
  const came: CrossedLine[] = [];
  const approximated: CrossedLine[] = [];
  const stayed = new Map<string, string[]>();
  for (const raw of fields) {
    const field = object(raw, 'field');
    const disposition = field['disposition'];
    if (!(DISPOSITIONS as readonly unknown[]).includes(disposition)) invalid('disposition');
    const words = text(field['words'], 'field words');
    switch (disposition as Disposition) {
      case 'exact':
        came.push({ words, reason: null });
        break;
      case 'approximated':
        approximated.push({ words, reason: text(field['reason'], 'approximated reason') });
        break;
      case 'dropped':
      case 'opaque': {
        const reason = text(field['reason'], 'reason');
        stayed.set(reason, [...stayed.get(reason) ?? [], words]);
        break;
      }
    }
  }
  return { came: [...came, ...approximated], stayed: [...stayed].map(([reason, words]) => ({ words, reason })) };
}

/** The route's answer as the card reads it. */
export function readCrossingManifest(value: unknown): CrossingManifest {
  const body = object(value, 'answer');
  const sha256 = text(body['manifest_sha256'], 'digest');
  if (!/^[0-9a-f]{64}$/u.test(sha256)) invalid('digest');
  const from = object(body['from'], 'from');
  const ai = from['ai'];
  if (typeof ai !== 'boolean') return invalid('from ai');
  return {
    manifestSha256: sha256,
    from: { bridge: text(from['bridge'], 'bridge'), label: text(from['label'], 'label'), ai },
    rows: crossingRows(body['manifest']),
  };
}

export async function fetchCrossingManifest(
  access: Credentials, worldId: string, arrivalId: string, fetcher: typeof fetch = fetch,
): Promise<CrossingManifest> {
  const response = await fetcher(
    `${access.baseUrl}/door/crossings/${encodeURIComponent(arrivalId)}/manifest?world_id=${encodeURIComponent(worldId)}`,
    { headers: { Authorization: `Bearer ${access.token}` }, credentials: 'same-origin' },
  );
  if (!response.ok) throw new Error(`What came across with this visitor is unavailable: HTTP ${response.status}`);
  return readCrossingManifest(await response.json());
}
