import { ApiError, Transport, type TransportOptions } from '@exulanica/graph-client';
import type { NYCSemanticFeature, SemanticFootprint } from '@exulanica/atlas-react/playcanvas';
import {
  parseVersion,
  type AlternateVersion,
  type ObjectRole,
  type ObjectWriteResult,
  type TransformInput,
} from './world-objects-api.js';

export interface EnvironmentCatalog {
  readonly admissionId: string;
  readonly publicationId: string;
  readonly placeId: string;
  readonly renderAssetId: string;
  readonly coordinateScale: number;
  readonly frameName: string;
  readonly receiptSha256: string;
  readonly sourceSha256: string;
  readonly sourceReceiptSha256: string;
  readonly renderSha256: string;
  readonly renderReceiptSha256: string;
  readonly indexSha256: string;
  readonly indexReceiptSha256: string;
  readonly features: readonly NYCSemanticFeature[];
  readonly attribution: string;
}

export interface EnvironmentPlacementRequest {
  readonly instanceId: string;
  readonly feature: NYCSemanticFeature;
  readonly sourceAnchor: readonly [number, number];
  readonly regionId: string;
  readonly transform: TransformInput;
  readonly originRole: ObjectRole;
}

const invalid = (label: string): Error => new Error(`Invalid environment ${label} response`);
const record = (value: unknown, label: string): Readonly<Record<string, unknown>> => {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) throw invalid(label);
  return value as Readonly<Record<string, unknown>>;
};
const text = (value: unknown, label: string): string => {
  if (typeof value !== 'string' || value.length === 0) throw invalid(label);
  return value;
};
const digest = (value: unknown, label: string): string => {
  const held = text(value, label);
  if (!/^[0-9a-f]{64}$/.test(held)) throw invalid(label);
  return held;
};
const integer = (value: unknown, label: string): number => {
  if (!Number.isSafeInteger(value)) throw invalid(label);
  return value as number;
};

function footprint(value: unknown): SemanticFootprint {
  const geometry = record(value, 'feature footprint');
  if (geometry['type'] !== 'MultiPolygon' || !Array.isArray(geometry['coordinates'])) {
    throw invalid('feature footprint');
  }
  const coordinates = geometry['coordinates'] as unknown[];
  return coordinates.map((polygon) => {
    if (!Array.isArray(polygon)) throw invalid('feature footprint');
    return polygon.map((ring) => {
      if (!Array.isArray(ring)) throw invalid('feature footprint');
      return ring.map((point) => {
        if (!Array.isArray(point) || point.length !== 2) throw invalid('feature footprint');
        return [
          integer(point[0], 'feature longitude'),
          integer(point[1], 'feature latitude'),
        ] as const;
      });
    });
  });
}

export function parseEnvironmentCatalog(value: unknown): EnvironmentCatalog {
  const row = record(value, 'catalog');
  const receipt = record(row['receipt'], 'publication receipt');
  const frame = record(row['geographic_frame'], 'geographic frame');
  if (!Array.isArray(row['features'])) throw invalid('feature list');
  const features = row['features'].map((held) => {
    const feature = record(held, 'feature');
    const properties = record(feature['semantic_properties'], 'semantic properties');
    const bbox = feature['bbox'];
    if (!Array.isArray(bbox) || bbox.length !== 4) throw invalid('feature bbox');
    const providerFeatureId = text(feature['provider_feature_id'], 'provider feature id');
    if (!/^doitt_id:[1-9][0-9]*$/.test(providerFeatureId)) throw invalid('DOITT_ID');
    const bin = properties['bin'];
    const name = properties['name'];
    return Object.freeze({
      id: text(feature['id'], 'feature id'),
      providerFeatureId,
      bbox: bbox.map((axis) => integer(axis, 'feature bbox')) as
        unknown as readonly [number, number, number, number],
      footprint: footprint(feature['footprint']),
      renderBatchId: integer(feature['render_batch_id'], 'render batch'),
      name: name === null ? null : text(name, 'feature name'),
      bin: bin === null ? null : text(bin, 'feature BIN'),
    });
  });
  return Object.freeze({
    admissionId: text(row['admission_id'], 'admission id'),
    publicationId: text(row['publication_id'], 'publication id'),
    placeId: text(row['place_id'], 'place id'),
    renderAssetId: text(row['render_asset_id'], 'render asset id'),
    coordinateScale: integer(row['coordinate_scale'], 'coordinate scale'),
    frameName: text(frame['name'], 'frame name'),
    receiptSha256: digest(row['receipt_sha256'], 'publication receipt digest'),
    sourceSha256: digest(receipt['source_sha256'], 'source digest'),
    sourceReceiptSha256: digest(receipt['source_receipt_sha256'], 'source receipt digest'),
    renderSha256: digest(receipt['render_sha256'], 'render digest'),
    renderReceiptSha256: digest(receipt['render_receipt_sha256'], 'render receipt digest'),
    indexSha256: digest(receipt['index_sha256'], 'index digest'),
    indexReceiptSha256: digest(receipt['index_receipt_sha256'], 'index receipt digest'),
    features: Object.freeze(features),
    attribution: 'NYC Open Data, Office of Technology and Innovation, BUILDING dataset 5zhs-2jue',
  });
}

export class EnvironmentSelectionClient {
  private readonly transport: Transport;

  constructor(options: TransportOptions) {
    this.transport = new Transport(options);
  }

  async catalog(admissionId: string): Promise<EnvironmentCatalog> {
    return parseEnvironmentCatalog(await this.transport.getJson<unknown>(
      `/environment-resources/sources/${encodeURIComponent(admissionId)}/features`,
    ));
  }

  async add(
    base: AlternateVersion,
    catalog: EnvironmentCatalog,
    request: EnvironmentPlacementRequest,
  ): Promise<ObjectWriteResult> {
    return this.write(base, `/world/versions/${encodeURIComponent(base.versionId)}/environment-instances`, {
      instance_id: request.instanceId,
      admission_id: catalog.admissionId,
      render_asset_id: catalog.renderAssetId,
      publication_id: catalog.publicationId,
      selection: {
        kind: 'feature',
        feature_id: request.feature.id,
        render_batch_id: request.feature.renderBatchId,
      },
      source_anchor: {
        frame_name: catalog.frameName,
        coordinate_scale: catalog.coordinateScale,
        coordinates: [...request.sourceAnchor],
      },
      region_id: request.regionId,
      transform: {
        x_mm: request.transform.xMm,
        y_mm: request.transform.yMm,
        z_mm: request.transform.zMm,
        yaw_microradians: request.transform.yawMicroradians,
        scale_milli: request.transform.scaleMilli,
      },
      origin_role: request.originRole,
    });
  }

  remove(base: AlternateVersion, instanceId: string): Promise<ObjectWriteResult> {
    return this.write(
      base,
      `/world/versions/${encodeURIComponent(base.versionId)}/environment-instances/`
        + `${encodeURIComponent(instanceId)}/remove`,
      {},
    );
  }

  undo(base: AlternateVersion): Promise<ObjectWriteResult> {
    return this.write(
      base,
      `/world/versions/${encodeURIComponent(base.versionId)}/environment-instances/undo`,
      {},
    );
  }

  private async write(
    base: AlternateVersion,
    path: string,
    body: Readonly<Record<string, unknown>>,
  ): Promise<ObjectWriteResult> {
    try {
      const version = parseVersion(await this.transport.postJson(path, {
        ...body,
        base_state_sha256: base.stateSha256,
      }));
      return Object.freeze({ kind: 'recorded' as const, version });
    } catch (error) {
      if (error instanceof ApiError &&
        (error.code === 'stale_structural_base' || error.code === 'stale_object_base')) {
        const current = parseVersion(await this.transport.getJson(
          `/world/versions/${encodeURIComponent(base.versionId)}`,
        ));
        return Object.freeze({ kind: 'stale' as const, current });
      }
      throw error;
    }
  }
}
