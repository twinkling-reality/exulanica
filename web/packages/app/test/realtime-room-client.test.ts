import { describe, expect, it, vi } from 'vitest';
import {
  FULL_CIRCLE_URAD,
  REALTIME_DELTA_FRAME_PROFILE,
  RealtimeRoomClient,
  type RealtimeDeltaFrame,
  type RealtimeWebSocketLike,
  classifyMindTier,
  interpolateYawUrad,
} from '../src/realtime-room-client.js';

describe('RealtimeRoomClient & 60fps pose interpolator', () => {
  it('assembles AOI delta frames, tracks state_sha256, and surfaces all four mind tiers', () => {
    const client = new RealtimeRoomClient();

    const frame1: RealtimeDeltaFrame = {
      profile: REALTIME_DELTA_FRAME_PROFILE,
      tick: 1,
      world_minute: 0,
      observer_cell: [0, 0],
      radius_mm: 24_000,
      state_sha256: 'a'.repeat(64),
      deltas: [
        [1, 1_000, 2_000, 0, 0, 'walking', 0],
        [2, 3_000, 4_000, 0, 1_570_796, 'walking', 1],
        [3, 5_000, 6_000, 0, 3_141_592, 'talking', 2],
        [4, 7_000, 8_000, 0, 4_712_388, 'walking', 2],
      ],
      entities: [
        {
          u16_id: 1,
          being_id: 'being-reflex',
          label: 'Reflex Guard',
          x_mm: 1_000,
          y_mm: 2_000,
          z_mm: 0,
          yaw_urad: 0,
          motion_state: 'walking',
          active_tier: 0,
          mind_tier: 'tier0_reflex',
        },
        {
          u16_id: 2,
          being_id: 'being-routine',
          label: 'Baker Ivo',
          x_mm: 3_000,
          y_mm: 4_000,
          z_mm: 0,
          yaw_urad: 1_570_796,
          motion_state: 'walking',
          active_tier: 1,
          mind_tier: 'tier1_routine',
        },
        {
          u16_id: 3,
          being_id: 'being-model',
          label: 'Teo (Nemotron 120B)',
          x_mm: 5_000,
          y_mm: 6_000,
          z_mm: 0,
          yaw_urad: 3_141_592,
          motion_state: 'talking',
          active_tier: 2,
          mind_tier: 'tier2_model',
          last_line: 'Morning! Fresh loaves are out.',
        },
        {
          u16_id: 4,
          being_id: 'visitor-kael',
          label: 'Kael (Door Visitor)',
          x_mm: 7_000,
          y_mm: 8_000,
          z_mm: 0,
          yaw_urad: 4_712_388,
          motion_state: 'walking',
          active_tier: 2,
          mind_tier: 'door_visitor',
        },
      ],
    };

    client.ingestDeltaFrame(frame1, 50);

    expect(client.tick).toBe(1);
    expect(client.entityCount).toBe(4);
    expect(client.stateSha256).toBe('a'.repeat(64));
    expect(client.tierCounts()).toEqual({
      tier0_reflex: 1,
      tier1_routine: 1,
      tier2_model: 1,
      door_visitor: 1,
    });

    const teo = client.sampleEntity('being-model', 50);
    expect(teo).not.toBeNull();
    expect(teo?.mindTier).toBe('tier2_model');
    expect(teo?.lastLine).toBe('Morning! Fresh loaves are out.');
    expect(teo?.xMeters).toBeCloseTo(5.0);
    expect(teo?.yMeters).toBeCloseTo(6.0);

    const kael = client.sampleEntity('visitor-kael', 50);
    expect(kael?.mindTier).toBe('door_visitor');
  });

  it('smoothly interpolates (x_mm, y_mm, z_mm, yaw_urad) at 60fps sub-frames between 50ms server ticks', () => {
    const client = new RealtimeRoomClient({ tickDurationMs: 50 });

    // Tick 1 at t = 100ms: entity #1 at (1000, 2000, 0), yaw = 6_100_000 urad (near 2*pi)
    client.ingestDeltaFrame(
      {
        profile: REALTIME_DELTA_FRAME_PROFILE,
        tick: 1,
        world_minute: 0,
        observer_cell: [0, 0],
        radius_mm: 24_000,
        deltas: [[1, 1_000, 2_000, 0, 6_100_000, 'walking', 1]],
        entities: [
          {
            u16_id: 1,
            being_id: 'walker-1',
            label: 'Walker One',
            x_mm: 1_000,
            y_mm: 2_000,
            z_mm: 0,
            yaw_urad: 6_100_000,
            motion_state: 'walking',
            active_tier: 1,
            mind_tier: 'tier1_routine',
          },
        ],
      },
      100,
    );

    // Tick 2 at t = 150ms: entity #1 moves to (2000, 4000, 300), yaw wraps across 0 to 200_000 urad
    client.ingestDeltaFrame(
      {
        profile: REALTIME_DELTA_FRAME_PROFILE,
        tick: 2,
        world_minute: 0,
        observer_cell: [0, 0],
        radius_mm: 24_000,
        deltas: [[1, 2_000, 4_000, 300, 200_000, 'walking', 2]],
      },
      150,
    );

    // Sample 3 intermediate 60fps frames (~16.67ms apart) between t=100ms (previous) and t=150ms (target)
    const atStart = client.sampleEntity('walker-1', 100, 0.0)!;
    const atOneThird = client.sampleEntity('walker-1', 116.67, 1 / 3)!;
    const atMid = client.sampleEntity('walker-1', 125, 0.5)!;
    const atTwoThirds = client.sampleEntity('walker-1', 133.33, 2 / 3)!;
    const atEnd = client.sampleEntity('walker-1', 150, 1.0)!;

    expect(atStart.xMm).toBe(1_000);
    expect(atStart.yMm).toBe(2_000);
    expect(atStart.zMm).toBe(0);

    expect(atMid.xMm).toBe(1_500);
    expect(atMid.yMm).toBe(3_000);
    expect(atMid.zMm).toBe(150);

    expect(atOneThird.xMm).toBeGreaterThan(atStart.xMm);
    expect(atTwoThirds.xMm).toBeGreaterThan(atMid.xMm);

    expect(atEnd.xMm).toBe(2_000);
    expect(atEnd.yMm).toBe(4_000);
    expect(atEnd.zMm).toBe(300);
    expect(atEnd.mindTier).toBe('tier2_model');

    // Verify shortest-arc yaw wrap-around across 0 / 2*pi (6_100_000 -> 200_000 is +383_185 urad)
    const expectedMidYaw = (6_100_000 + Math.round(383_185 * 0.5)) % FULL_CIRCLE_URAD;
    expect(atMid.yawUrad).toBe(expectedMidYaw);
    expect(interpolateYawUrad(100_000, FULL_CIRCLE_URAD - 100_000, 0.5)).toBe(0);
  });

  it('consumes WebSocket stream messages and dispatches outbound player_move and tier2_proposal frames', () => {
    const client = new RealtimeRoomClient();
    const sent: string[] = [];
    const mockSocket: RealtimeWebSocketLike = {
      onmessage: null,
      send(data: string) {
        sent.push(data);
      },
      close: vi.fn(),
    };

    client.attachWebSocket(mockSocket);

    const framePayload: RealtimeDeltaFrame = {
      profile: REALTIME_DELTA_FRAME_PROFILE,
      tick: 5,
      world_minute: 0,
      observer_cell: [1, 1],
      radius_mm: 24_000,
      deltas: [[7, 16_500, 18_000, 0, 1_000_000, 'walking', 0]],
    };
    mockSocket.onmessage?.({ data: JSON.stringify(framePayload) });

    expect(client.tick).toBe(5);
    const sampled = client.sampleEntity(7, 250);
    expect(sampled?.xMm).toBe(16_500);
    expect(sampled?.mindTier).toBe('tier0_reflex');

    client.sendPlayerMove({
      beingId: 'being-7',
      targetXMm: 20_000,
      targetYMm: 22_000,
      line: 'On my way!',
    });
    expect(JSON.parse(sent[0]!)).toEqual({
      type: 'player_move',
      being_id: 'being-7',
      target_x_mm: 20_000,
      target_y_mm: 22_000,
      target_z_mm: 0,
      line: 'On my way!',
    });

    client.sendTier2Proposal({
      requestId: 'req:w1:being-7:5:0',
      chosenLabel: 'go to town square bench, 4 m away',
      latencyMs: 520,
      modelId: 'nvidia/Nemotron-3-Super-120B',
    });
    expect(JSON.parse(sent[1]!)).toEqual({
      type: 'tier2_proposal',
      request_id: 'req:w1:being-7:5:0',
      chosen_label: 'go to town square bench, 4 m away',
      line: null,
      latency_ms: 520,
      model_id: 'nvidia/Nemotron-3-Super-120B',
    });

    expect(classifyMindTier(0, null, 'crossed', 'external')).toBe('door_visitor');
    expect(classifyMindTier(1, null, 'populated', 'routine')).toBe('tier1_routine');
    expect(classifyMindTier(2, null, 'populated', 'model')).toBe('tier2_model');

    client.disconnect();
    expect(mockSocket.close).toHaveBeenCalledOnce();
  });
});
