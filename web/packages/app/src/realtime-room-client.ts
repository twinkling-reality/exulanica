/**
 * Real-time 20 Hz spatial room client & 60fps pose interpolator.
 *
 * Consumes `exulanica.realtime-delta-frame/v1` frames (over WebSocket `/realtime/stream`
 * or HTTP `POST /realtime/step`), maintains the client's Area-of-Interest (AOI) entity
 * table, smoothly interpolates `(x_mm, y_mm, z_mm, yaw_urad)` between 50ms server ticks
 * for 60fps rendering in PlayCanvas, and surfaces each being's active mind tier
 * (`tier0_reflex`, `tier1_routine`, `tier2_model`, `door_visitor`).
 */

export const REALTIME_DELTA_FRAME_PROFILE = 'exulanica.realtime-delta-frame/v1' as const;
export const SERVER_TICK_MS = 50 as const;
export const FULL_CIRCLE_URAD = 6_283_185 as const;
export const HALF_CIRCLE_URAD = 3_141_592 as const;

export type MindTier =
  | 'tier0_reflex'
  | 'tier1_routine'
  | 'tier2_model'
  | 'door_visitor';

export type RealtimeDeltaTuple = readonly [
  u16Id: number,
  xMm: number,
  yMm: number,
  zMm: number,
  yawUrad: number,
  motionState: string,
  activeTier: number,
];

export interface RealtimeWireEntity {
  readonly u16_id: number;
  readonly being_id: string;
  readonly label: string;
  readonly x_mm: number;
  readonly y_mm: number;
  readonly z_mm: number;
  readonly yaw_urad: number;
  readonly motion_state: string;
  readonly active_tier: number;
  readonly mind_tier: MindTier;
  readonly last_line?: string | null;
}

export interface RealtimeDeltaFrame {
  readonly profile: typeof REALTIME_DELTA_FRAME_PROFILE;
  readonly tick: number;
  readonly world_minute: number;
  readonly observer_cell: readonly [number, number];
  readonly radius_mm: number;
  readonly deltas: readonly RealtimeDeltaTuple[];
  readonly entities?: readonly RealtimeWireEntity[];
  readonly state_sha256?: string;
  readonly tier_summary?: Readonly<Record<string, number>>;
}

export interface PoseSample {
  readonly tick: number;
  readonly timestampMs: number;
  readonly xMm: number;
  readonly yMm: number;
  readonly zMm: number;
  readonly yawUrad: number;
}

export interface InterpolatedEntity {
  readonly u16Id: number;
  readonly beingId: string;
  readonly label: string;
  readonly xMm: number;
  readonly yMm: number;
  readonly zMm: number;
  readonly yawUrad: number;
  readonly xMeters: number;
  readonly yMeters: number;
  readonly zMeters: number;
  readonly yawRadians: number;
  readonly motionState: string;
  readonly activeTier: number;
  readonly mindTier: MindTier;
  readonly lastLine: string | null;
  readonly previousPose: PoseSample;
  readonly targetPose: PoseSample;
}

export interface RealtimeWebSocketLike {
  send(data: string): void;
  close(): void;
  onmessage: ((event: { readonly data: unknown }) => void) | null;
  onclose?: (() => void) | null;
}

interface InternalEntityRecord {
  u16Id: number;
  beingId: string;
  label: string;
  motionState: string;
  activeTier: number;
  mindTier: MindTier;
  lastLine: string | null;
  previousPose: PoseSample;
  targetPose: PoseSample;
}

export function classifyMindTier(
  activeTier: number,
  explicitMindTier?: string | null,
  cameBy?: string | null,
  deciderKind?: string | null,
): MindTier {
  if (
    explicitMindTier === 'tier0_reflex' ||
    explicitMindTier === 'tier1_routine' ||
    explicitMindTier === 'tier2_model' ||
    explicitMindTier === 'door_visitor'
  ) {
    return explicitMindTier;
  }
  if (cameBy === 'crossed' || deciderKind === 'external' || activeTier === 3) {
    return 'door_visitor';
  }
  if (activeTier >= 2 || deciderKind === 'model') {
    return 'tier2_model';
  }
  if (activeTier === 1) {
    return 'tier1_routine';
  }
  return 'tier0_reflex';
}

/**
 * Shortest-arc angular interpolation in integer microradians `[0, 6_283_185)`.
 */
export function interpolateYawUrad(startUrad: number, endUrad: number, alpha: number): number {
  const clamped = Math.max(0, Math.min(1, alpha));
  const a = ((Math.trunc(startUrad) % FULL_CIRCLE_URAD) + FULL_CIRCLE_URAD) % FULL_CIRCLE_URAD;
  const b = ((Math.trunc(endUrad) % FULL_CIRCLE_URAD) + FULL_CIRCLE_URAD) % FULL_CIRCLE_URAD;
  let diff = b - a;
  if (diff > HALF_CIRCLE_URAD) {
    diff -= FULL_CIRCLE_URAD;
  } else if (diff < -HALF_CIRCLE_URAD) {
    diff += FULL_CIRCLE_URAD;
  }
  const interpolated = Math.round(a + diff * clamped);
  return ((interpolated % FULL_CIRCLE_URAD) + FULL_CIRCLE_URAD) % FULL_CIRCLE_URAD;
}

export function lerpMillimeters(startMm: number, endMm: number, alpha: number): number {
  const clamped = Math.max(0, Math.min(1, alpha));
  return Math.round(startMm + (endMm - startMm) * clamped);
}

export class RealtimeRoomClient {
  private readonly entitiesByU16 = new Map<number, InternalEntityRecord>();
  private readonly u16ByBeingId = new Map<string, number>();
  private readonly tickDurationMs: number;
  private latestTick = 0;
  private latestWorldMinute = 0;
  private latestStateSha256: string | null = null;
  private lastFrameTimestampMs = 0;
  private socket: RealtimeWebSocketLike | null = null;
  private readonly frameListeners = new Set<(frame: RealtimeDeltaFrame) => void>();

  public constructor(options?: { readonly tickDurationMs?: number }) {
    this.tickDurationMs = options?.tickDurationMs ?? SERVER_TICK_MS;
  }

  public get tick(): number {
    return this.latestTick;
  }

  public get worldMinute(): number {
    return this.latestWorldMinute;
  }

  public get stateSha256(): string | null {
    return this.latestStateSha256;
  }

  public get entityCount(): number {
    return this.entitiesByU16.size;
  }

  public onFrame(listener: (frame: RealtimeDeltaFrame) => void): () => void {
    this.frameListeners.add(listener);
    return () => {
      this.frameListeners.delete(listener);
    };
  }

  /**
   * Ingest a 20 Hz `exulanica.realtime-delta-frame/v1` payload.
   */
  public ingestDeltaFrame(frame: RealtimeDeltaFrame, receivedAtMs?: number): void {
    if (frame.profile !== REALTIME_DELTA_FRAME_PROFILE) {
      throw new Error(`Unsupported realtime delta frame profile: ${String(frame.profile)}`);
    }
    const timestampMs =
      receivedAtMs ??
      (this.lastFrameTimestampMs > 0
        ? this.lastFrameTimestampMs +
          Math.max(1, frame.tick - this.latestTick) * this.tickDurationMs
        : frame.tick * this.tickDurationMs);

    const sampleAtNow = this.samplePosesAt(timestampMs);
    const currentByU16 = new Map<number, InterpolatedEntity>();
    for (const sampled of sampleAtNow) {
      currentByU16.set(sampled.u16Id, sampled);
    }

    this.latestTick = frame.tick;
    this.latestWorldMinute = frame.world_minute;
    if (typeof frame.state_sha256 === 'string') {
      this.latestStateSha256 = frame.state_sha256;
    }
    this.lastFrameTimestampMs = timestampMs;

    const wireEntitiesByU16 = new Map<number, RealtimeWireEntity>();
    if (Array.isArray(frame.entities)) {
      for (const wireEntity of frame.entities) {
        wireEntitiesByU16.set(wireEntity.u16_id, wireEntity);
      }
    }

    for (const tuple of frame.deltas) {
      const [u16Id, xMm, yMm, zMm, yawUrad, motionState, activeTier] = tuple;
      const wireMeta = wireEntitiesByU16.get(u16Id);
      const existing = this.entitiesByU16.get(u16Id);
      const sampledCurrent = currentByU16.get(u16Id);

      const newTargetPose: PoseSample = {
        tick: frame.tick,
        timestampMs,
        xMm,
        yMm,
        zMm,
        yawUrad,
      };

      const previousPose: PoseSample = sampledCurrent
        ? {
            tick: existing?.targetPose.tick ?? frame.tick,
            timestampMs: timestampMs - this.tickDurationMs,
            xMm: sampledCurrent.xMm,
            yMm: sampledCurrent.yMm,
            zMm: sampledCurrent.zMm,
            yawUrad: sampledCurrent.yawUrad,
          }
        : newTargetPose;

      const beingId = wireMeta?.being_id ?? existing?.beingId ?? `being-${String(u16Id)}`;
      const label = wireMeta?.label ?? existing?.label ?? beingId;
      const mindTier = classifyMindTier(
        activeTier,
        wireMeta?.mind_tier ??
          (existing?.mindTier === 'door_visitor' ? 'door_visitor' : null),
      );
      const lastLine =
        wireMeta?.last_line !== undefined ? wireMeta.last_line : (existing?.lastLine ?? null);

      const record: InternalEntityRecord = {
        u16Id,
        beingId,
        label,
        motionState,
        activeTier,
        mindTier,
        lastLine,
        previousPose,
        targetPose: newTargetPose,
      };
      this.entitiesByU16.set(u16Id, record);
      this.u16ByBeingId.set(beingId, u16Id);
    }

    for (const listener of this.frameListeners) {
      listener(frame);
    }
  }

  /**
   * Sample all AOI entities at `renderTimestampMs` for 60fps PlayCanvas rendering.
   * When `alpha` is provided directly in `[0, 1]`, interpolates at that exact fraction
   * between the previous 50ms tick pose and the latest 50ms tick pose.
   */
  public samplePosesAt(renderTimestampMs: number, explicitAlpha?: number): InterpolatedEntity[] {
    const results: InterpolatedEntity[] = [];
    const sortedU16 = [...this.entitiesByU16.keys()].sort((a, b) => a - b);

    for (const u16Id of sortedU16) {
      const rec = this.entitiesByU16.get(u16Id);
      if (!rec) {
        continue;
      }
      results.push(this.interpolateRecord(rec, renderTimestampMs, explicitAlpha));
    }
    return results;
  }

  public sampleEntity(
    beingIdOrU16: string | number,
    renderTimestampMs: number,
    explicitAlpha?: number,
  ): InterpolatedEntity | null {
    const u16Id =
      typeof beingIdOrU16 === 'number'
        ? beingIdOrU16
        : this.u16ByBeingId.get(beingIdOrU16);
    if (u16Id === undefined) {
      return null;
    }
    const rec = this.entitiesByU16.get(u16Id);
    if (!rec) {
      return null;
    }
    return this.interpolateRecord(rec, renderTimestampMs, explicitAlpha);
  }

  public tierCounts(): Readonly<Record<MindTier, number>> {
    const counts: Record<MindTier, number> = {
      tier0_reflex: 0,
      tier1_routine: 0,
      tier2_model: 0,
      door_visitor: 0,
    };
    for (const rec of this.entitiesByU16.values()) {
      counts[rec.mindTier] += 1;
    }
    return counts;
  }

  /**
   * Attach to a WebSocket stream (`/world/versions/{version_id}/realtime/stream`).
   */
  public attachWebSocket(socket: RealtimeWebSocketLike): void {
    this.socket = socket;
    socket.onmessage = (event: { readonly data: unknown }): void => {
      const raw =
        typeof event.data === 'string'
          ? (JSON.parse(event.data) as Record<string, unknown>)
          : (event.data as Record<string, unknown>);
      if (raw && raw['profile'] === REALTIME_DELTA_FRAME_PROFILE) {
        this.ingestDeltaFrame(raw as unknown as RealtimeDeltaFrame);
      }
    };
  }

  public sendPlayerMove(command: {
    readonly beingId: string;
    readonly targetXMm: number;
    readonly targetYMm: number;
    readonly targetZMm?: number;
    readonly line?: string;
  }): void {
    if (!this.socket) {
      throw new Error('WebSocket is not attached');
    }
    this.socket.send(
      JSON.stringify({
        type: 'player_move',
        being_id: command.beingId,
        target_x_mm: Math.trunc(command.targetXMm),
        target_y_mm: Math.trunc(command.targetYMm),
        target_z_mm: Math.trunc(command.targetZMm ?? 0),
        line: command.line ?? null,
      }),
    );
  }

  public sendTier2Proposal(proposal: {
    readonly requestId: string;
    readonly chosenLabel: string;
    readonly line?: string | null;
    readonly latencyMs?: number;
    readonly modelId?: string;
  }): void {
    if (!this.socket) {
      throw new Error('WebSocket is not attached');
    }
    this.socket.send(
      JSON.stringify({
        type: 'tier2_proposal',
        request_id: proposal.requestId,
        chosen_label: proposal.chosenLabel,
        line: proposal.line ?? null,
        latency_ms: Math.trunc(proposal.latencyMs ?? 0),
        model_id: proposal.modelId ?? null,
      }),
    );
  }

  public disconnect(): void {
    if (this.socket) {
      this.socket.close();
      this.socket = null;
    }
  }

  private interpolateRecord(
    rec: InternalEntityRecord,
    renderTimestampMs: number,
    explicitAlpha?: number,
  ): InterpolatedEntity {
    let alpha: number;
    if (explicitAlpha !== undefined) {
      alpha = Math.max(0, Math.min(1, explicitAlpha));
    } else {
      const spanMs = rec.targetPose.timestampMs - rec.previousPose.timestampMs;
      if (spanMs <= 0) {
        alpha = 1;
      } else {
        // Render 1 server tick (50ms) behind latest target timestamp for smooth 60fps interpolation
        const elapsedMs = renderTimestampMs - rec.previousPose.timestampMs;
        alpha = Math.max(0, Math.min(1, elapsedMs / spanMs));
      }
    }

    const xMm = lerpMillimeters(rec.previousPose.xMm, rec.targetPose.xMm, alpha);
    const yMm = lerpMillimeters(rec.previousPose.yMm, rec.targetPose.yMm, alpha);
    const zMm = lerpMillimeters(rec.previousPose.zMm, rec.targetPose.zMm, alpha);
    const yawUrad = interpolateYawUrad(rec.previousPose.yawUrad, rec.targetPose.yawUrad, alpha);

    return {
      u16Id: rec.u16Id,
      beingId: rec.beingId,
      label: rec.label,
      xMm,
      yMm,
      zMm,
      yawUrad,
      xMeters: xMm / 1000,
      yMeters: yMm / 1000,
      zMeters: zMm / 1000,
      yawRadians: yawUrad / 1_000_000,
      motionState: rec.motionState,
      activeTier: rec.activeTier,
      mindTier: rec.mindTier,
      lastLine: rec.lastLine,
      previousPose: rec.previousPose,
      targetPose: rec.targetPose,
    };
  }
}
