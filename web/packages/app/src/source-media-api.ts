/** Authenticated, provenance-checked source media for the renderer. */

import type { SourceMediaCatalog, SourceMediaDescriptor } from '@exulanica/atlas-react/playcanvas';
import { ApiError, Transport, type TransportOptions } from '@exulanica/graph-client';

export type SourceMediaIssueState =
  | 'unavailable_asset'
  | 'missing_evidence'
  | 'unauthorized'
  | 'error';

export interface SourceMediaIssue {
  readonly sourceId: string;
  readonly slotKey: string;
  readonly state: SourceMediaIssueState;
  readonly reason: string;
}

export interface SourceMediaSession {
  readonly catalog: SourceMediaCatalog;
  readonly issues: readonly SourceMediaIssue[];
  dispose(): void;
}

interface SourceMediaWire {
  readonly sourceId: string;
  readonly slotKey: string;
  readonly regionId: string | null;
  readonly captureIds: readonly string[];
  readonly state: 'available' | 'unavailable_asset' | 'missing_evidence';
  readonly reason: string | null;
  readonly evidenceSpanId: string | null;
  readonly evidencePath: string | null;
  readonly mediaType: string | null;
  readonly capturedAt: string | null;
  readonly assetReference: {
    readonly href: string;
    readonly authorization: 'workspace-bearer';
    readonly provenance: {
      readonly sourceId: string;
      readonly evidenceSpanId: string;
    };
  } | null;
}

export class SourceMediaClient {
  readonly #transport: Transport;
  readonly #createObjectUrl: (blob: Blob) => string;
  readonly #revokeObjectUrl: (url: string) => void;

  constructor(options: TransportOptions & {
    readonly createObjectURL?: (blob: Blob) => string;
    readonly revokeObjectURL?: (url: string) => void;
  }) {
    this.#transport = new Transport(options);
    this.#createObjectUrl = options.createObjectURL ?? URL.createObjectURL.bind(URL);
    this.#revokeObjectUrl = options.revokeObjectURL ?? URL.revokeObjectURL.bind(URL);
  }

  async load(accent: string): Promise<SourceMediaSession> {
    const values = parseSourceList(
      await this.#transport.getJson<unknown>('/world/source-media'),
    );
    const catalog = new Map<string, SourceMediaDescriptor>();
    const issues: SourceMediaIssue[] = [];
    const held: string[] = [];
    for (const source of values) {
      const title = humanize(source.slotKey);
      const key = source.evidenceSpanId ?? source.sourceId;
      const unavailable = (state: SourceMediaIssueState, reason: string): void => {
        const descriptor = Object.freeze({
          evidenceRef: key,
          regionId: source.regionId,
          captureIds: source.captureIds,
          title,
          capturedLabel: source.capturedAt?.slice(0, 10) ?? 'Capture date unavailable',
          url: null,
          available: false,
          accent,
          alt: `${title} source is unavailable: ${reason}`,
        });
        installDescriptor(catalog, source, descriptor);
        issues.push(Object.freeze({
          sourceId: source.sourceId,
          slotKey: source.slotKey,
          state,
          reason,
        }));
      };
      if (source.state !== 'available') {
        unavailable(source.state, source.reason ?? (
          source.state === 'missing_evidence'
            ? 'No source evidence was recorded.'
            : 'The authorized source bytes are not available.'
        ));
        continue;
      }
      if (source.mediaType === null || !source.mediaType.startsWith('image/')) {
        unavailable('unavailable_asset', 'This source is not a supported image asset.');
        continue;
      }
      const reference = source.assetReference;
      if (
        reference === null ||
        reference.authorization !== 'workspace-bearer' ||
        source.evidenceSpanId === null ||
        source.evidencePath !== reference.href ||
        reference.provenance.sourceId !== source.sourceId ||
        reference.provenance.evidenceSpanId !== source.evidenceSpanId ||
        !safeEvidencePath(reference.href)
      ) {
        unavailable('error', 'The source asset reference failed its provenance check.');
        continue;
      }
      try {
        const response = await this.#transport.getBytes(reference.href);
        const blob = await response.blob();
        if (!blob.type.startsWith('image/')) {
          unavailable('error', 'The authorized source response was not an image.');
          continue;
        }
        const url = this.#createObjectUrl(blob);
        held.push(url);
        installDescriptor(catalog, source, Object.freeze({
          evidenceRef: source.evidenceSpanId,
          regionId: source.regionId,
          captureIds: source.captureIds,
          title,
          capturedLabel: source.capturedAt?.slice(0, 10) ?? 'Capture date unavailable',
          url,
          available: true,
          accent,
          alt: `${title} source evidence`,
        }));
      } catch (error) {
        unavailable(
          error instanceof ApiError && error.isUnauthenticated ? 'unauthorized' : 'error',
          sourceFailure(error),
        );
      }
    }
    let disposed = false;
    return Object.freeze({
      catalog,
      issues: Object.freeze(issues),
      dispose: () => {
        if (disposed) return;
        disposed = true;
        for (const url of held) this.#revokeObjectUrl(url);
        catalog.clear();
      },
    });
  }
}

function installDescriptor(
  catalog: Map<string, SourceMediaDescriptor>,
  source: SourceMediaWire,
  descriptor: SourceMediaDescriptor,
): void {
  catalog.set(source.sourceId, descriptor);
  if (source.evidenceSpanId !== null) catalog.set(source.evidenceSpanId, descriptor);
}

function parseSourceList(value: unknown): readonly SourceMediaWire[] {
  if (!Array.isArray(value)) throw new TypeError('The server returned an invalid source media list.');
  return Object.freeze(value.map((item) => {
    const source = asRecord(item, 'source media item');
    const state = source['state'];
    if (state !== 'available' && state !== 'unavailable_asset' && state !== 'missing_evidence') {
      throw new TypeError('The server returned an unknown source media state.');
    }
    const asset = source['asset_reference'];
    let assetReference: SourceMediaWire['assetReference'] = null;
    if (asset !== null) {
      const reference = asRecord(asset, 'source asset reference');
      const provenance = asRecord(reference['provenance'], 'source asset provenance');
      if (reference['authorization'] !== 'workspace-bearer') {
        throw new TypeError('The server returned an unknown source authorization mode.');
      }
      assetReference = Object.freeze({
        href: requiredText(reference['href'], 'source href'),
        authorization: 'workspace-bearer',
        provenance: Object.freeze({
          sourceId: requiredText(provenance['source_id'], 'source provenance ID'),
          evidenceSpanId: requiredText(provenance['evidence_span_id'], 'evidence provenance ID'),
        }),
      });
    }
    return Object.freeze({
      sourceId: requiredText(source['source_id'], 'source ID'),
      slotKey: requiredText(source['slot_key'], 'source slot'),
      regionId: optionalText(source['region_id'], 'source region ID'),
      captureIds: source['capture_ids'] === undefined ? [] : parseCaptureIds(source['capture_ids']),
      state,
      reason: optionalText(source['reason'], 'source reason'),
      evidenceSpanId: optionalText(source['evidence_span_id'], 'evidence span ID'),
      evidencePath: optionalText(source['evidence_path'], 'evidence path'),
      mediaType: optionalText(source['media_type'], 'source media type'),
      capturedAt: optionalText(source['captured_at'], 'source capture time'),
      assetReference,
    });
  }));
}

function parseCaptureIds(value: unknown): readonly string[] {
  if (!Array.isArray(value) || value.some((item) => typeof item !== 'string' || item.length === 0)) {
    throw new TypeError('The server returned invalid source capture IDs.');
  }
  return Object.freeze([...new Set(value as string[])]);
}

function safeEvidencePath(value: string): boolean {
  return value.startsWith('/evidence/') && !value.includes('://') && !value.includes('?') && !value.includes('#');
}

function humanize(value: string): string {
  const words = value.replace(/[-_]+/g, ' ').trim();
  return words.length === 0 ? 'Source memory' : words[0]!.toUpperCase() + words.slice(1);
}

function sourceFailure(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.isUnauthenticated) return 'This session is not authorized to load the source.';
    if (error.code === 'unavailable_asset') return 'The authorized source bytes are unavailable.';
    return `${error.code}: ${error.message.replace(`${error.code}: `, '')}`;
  }
  return error instanceof Error ? error.message : 'The source request failed.';
}

function asRecord(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new TypeError(`The server returned an invalid ${label}.`);
  }
  return value as Record<string, unknown>;
}

function requiredText(value: unknown, label: string): string {
  if (typeof value !== 'string' || value.length === 0) throw new TypeError(`Invalid ${label}.`);
  return value;
}

function optionalText(value: unknown, label: string): string | null {
  return value === null ? null : requiredText(value, label);
}
