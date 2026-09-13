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

interface EnvironmentProposalBase {
  readonly versionId: string;
  readonly baseStateSha256: string;
  readonly modelId: string | null;
  readonly promptVersion: string;
}

export interface PlaceEnvironmentProposal extends EnvironmentProposalBase {
  readonly operation: 'place_selected_feature';
  readonly instanceId: string;
  readonly admissionId: string;
  readonly renderAssetId: string;
  readonly publicationId: string;
  readonly featureId: string;
  readonly renderBatchId: number;
  readonly sourceAnchorFrameName: string;
  readonly sourceAnchorCoordinateScale: number;
  readonly sourceAnchorCoordinates: readonly [number, number];
  readonly regionId: string;
  readonly transform: TransformInput;
  readonly originRole: ObjectRole;
}

export interface RemoveEnvironmentProposal extends EnvironmentProposalBase {
  readonly operation: 'remove_selected_authored_instance';
  readonly instanceId: string;
}

export interface UndoEnvironmentProposal extends EnvironmentProposalBase {
  readonly operation: 'undo_latest_version_edit';
}

export type EnvironmentProposal =
  | PlaceEnvironmentProposal
  | RemoveEnvironmentProposal
  | UndoEnvironmentProposal;

export type EnvironmentProposalResult =
  | { readonly kind: 'proposed'; readonly proposal: EnvironmentProposal }
  | { readonly kind: 'refused'; readonly code: string; readonly detail: string };

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
  private queue: Promise<void> = Promise.resolve();

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
    return this.write(base.versionId, base.stateSha256,
      `/world/versions/${encodeURIComponent(base.versionId)}/environment-instances`, {
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
      base.versionId,
      base.stateSha256,
      `/world/versions/${encodeURIComponent(base.versionId)}/environment-instances/`
        + `${encodeURIComponent(instanceId)}/remove`,
      {},
    );
  }

  move(
    base: AlternateVersion,
    instanceId: string,
    transform: TransformInput,
  ): Promise<ObjectWriteResult> {
    return this.write(
      base.versionId,
      base.stateSha256,
      `/world/versions/${encodeURIComponent(base.versionId)}/environment-instances/`
        + `${encodeURIComponent(instanceId)}/move`,
      { transform: wireTransform(transform) },
    );
  }

  undo(base: AlternateVersion): Promise<ObjectWriteResult> {
    return this.write(
      base.versionId,
      base.stateSha256,
      `/world/versions/${encodeURIComponent(base.versionId)}/environment-instances/undo`,
      {},
    );
  }

  async propose(
    base: AlternateVersion,
    catalog: EnvironmentCatalog,
    request: EnvironmentPlacementRequest,
    utterance: string,
  ): Promise<EnvironmentProposalResult> {
    const response = record(await this.transport.postJson<unknown>('/selection/environment', {
      utterance,
      version_id: base.versionId,
      base_state_sha256: base.stateSha256,
      admission_id: catalog.admissionId,
      selected_feature_id: request.feature.id,
      region_id: request.regionId,
      transform: wireTransform(request.transform),
      origin_role: request.originRole,
    }), 'proposal');
    if (response['proposal'] === null) {
      const refusal = record(response['refusal'], 'proposal refusal');
      return Object.freeze({
        kind: 'refused' as const,
        code: text(refusal['code'], 'proposal refusal code'),
        detail: text(refusal['detail'], 'proposal refusal detail'),
      });
    }
    return Object.freeze({
      kind: 'proposed' as const,
      proposal: parseEnvironmentProposal(response['proposal']),
    });
  }

  deterministicPlace(
    base: AlternateVersion,
    catalog: EnvironmentCatalog,
    request: EnvironmentPlacementRequest,
  ): PlaceEnvironmentProposal {
    return Object.freeze({
      operation: 'place_selected_feature',
      versionId: base.versionId,
      baseStateSha256: base.stateSha256,
      instanceId: request.instanceId,
      admissionId: catalog.admissionId,
      renderAssetId: catalog.renderAssetId,
      publicationId: catalog.publicationId,
      featureId: request.feature.id,
      renderBatchId: request.feature.renderBatchId,
      sourceAnchorFrameName: catalog.frameName,
      sourceAnchorCoordinateScale: catalog.coordinateScale,
      sourceAnchorCoordinates: request.sourceAnchor,
      regionId: request.regionId,
      transform: request.transform,
      originRole: request.originRole,
      modelId: null,
      promptVersion: 'deterministic-environment-preview-1',
    });
  }

  apply(proposal: EnvironmentProposal): Promise<ObjectWriteResult> {
    const root = `/world/versions/${encodeURIComponent(proposal.versionId)}/environment-instances`;
    if (proposal.operation === 'remove_selected_authored_instance') {
      return this.write(
        proposal.versionId,
        proposal.baseStateSha256,
        `${root}/${encodeURIComponent(proposal.instanceId)}/remove`,
        {},
      );
    }
    if (proposal.operation === 'undo_latest_version_edit') {
      return this.write(proposal.versionId, proposal.baseStateSha256, `${root}/undo`, {});
    }
    return this.write(proposal.versionId, proposal.baseStateSha256, root, {
      instance_id: proposal.instanceId,
      admission_id: proposal.admissionId,
      render_asset_id: proposal.renderAssetId,
      publication_id: proposal.publicationId,
      selection: {
        kind: 'feature',
        feature_id: proposal.featureId,
        render_batch_id: proposal.renderBatchId,
      },
      source_anchor: {
        frame_name: proposal.sourceAnchorFrameName,
        coordinate_scale: proposal.sourceAnchorCoordinateScale,
        coordinates: [...proposal.sourceAnchorCoordinates],
      },
      region_id: proposal.regionId,
      transform: wireTransform(proposal.transform),
      origin_role: proposal.originRole,
    });
  }

  private write(
    versionId: string,
    baseStateSha256: string,
    path: string,
    body: Readonly<Record<string, unknown>>,
  ): Promise<ObjectWriteResult> {
    const run = async (): Promise<ObjectWriteResult> => {
      try {
        const version = parseVersion(await this.transport.postJson(path, {
          ...body,
          base_state_sha256: baseStateSha256,
        }));
        return Object.freeze({ kind: 'recorded' as const, version });
      } catch (error) {
        if (error instanceof ApiError &&
          (error.code === 'stale_structural_base' || error.code === 'stale_object_base')) {
          const current = parseVersion(await this.transport.getJson(
            `/world/versions/${encodeURIComponent(versionId)}`,
          ));
          return Object.freeze({ kind: 'stale' as const, current });
        }
        throw error;
      }
    };
    const result = this.queue.then(run, run);
    this.queue = result.then(() => undefined, () => undefined);
    return result;
  }
}

const wireTransform = (value: TransformInput): Readonly<Record<string, number>> => ({
  x_mm: value.xMm,
  y_mm: value.yMm,
  z_mm: value.zMm,
  yaw_microradians: value.yawMicroradians,
  scale_milli: value.scaleMilli,
});

function parseEnvironmentProposal(value: unknown): EnvironmentProposal {
  const row = record(value, 'typed proposal');
  const operation = text(row['operation'], 'proposal operation');
  const common = {
    versionId: text(row['version_id'], 'proposal version'),
    baseStateSha256: digest(row['base_state_sha256'], 'proposal base state'),
    modelId: row['model_id'] === null ? null : text(row['model_id'], 'proposal model'),
    promptVersion: text(row['prompt_version'], 'proposal prompt version'),
  };
  if (operation === 'undo_latest_version_edit') {
    return Object.freeze({ operation, ...common });
  }
  if (operation === 'remove_selected_authored_instance') {
    return Object.freeze({
      operation,
      instanceId: text(row['instance_id'], 'proposal instance'),
      ...common,
    });
  }
  if (operation !== 'place_selected_feature') throw invalid('proposal operation');
  const anchor = row['source_anchor_coordinates'];
  if (!Array.isArray(anchor) || anchor.length !== 2) throw invalid('proposal source anchor');
  const role = text(row['origin_role'], 'proposal origin role');
  if (role !== 'fictional' && role !== 'personal') throw invalid('proposal origin role');
  const transform = record(row['transform'], 'proposal transform');
  return Object.freeze({
    operation,
    instanceId: text(row['instance_id'], 'proposal instance'),
    admissionId: text(row['admission_id'], 'proposal admission'),
    renderAssetId: text(row['render_asset_id'], 'proposal render asset'),
    publicationId: text(row['publication_id'], 'proposal publication'),
    featureId: text(row['feature_id'], 'proposal feature'),
    renderBatchId: integer(row['render_batch_id'], 'proposal render batch'),
    sourceAnchorFrameName: text(row['source_anchor_frame_name'], 'proposal anchor frame'),
    sourceAnchorCoordinateScale: integer(
      row['source_anchor_coordinate_scale'], 'proposal anchor scale',
    ),
    sourceAnchorCoordinates: [
      integer(anchor[0], 'proposal anchor x'), integer(anchor[1], 'proposal anchor y'),
    ] as const,
    regionId: text(row['region_id'], 'proposal region'),
    transform: {
      xMm: integer(transform['x_mm'], 'proposal transform x'),
      yMm: integer(transform['y_mm'], 'proposal transform y'),
      zMm: integer(transform['z_mm'], 'proposal transform z'),
      yawMicroradians: integer(transform['yaw_microradians'], 'proposal transform yaw'),
      scaleMilli: integer(transform['scale_milli'], 'proposal transform scale'),
    },
    originRole: role,
    ...common,
  });
}
