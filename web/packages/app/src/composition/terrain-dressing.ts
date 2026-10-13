import {prepareTerrainDressing, type TerrainDressing, type PreparedDressing} from '@exulanica/atlas-react/generated-site';
import {fetchVerifiedObjectAsset} from '@exulanica/atlas-react/playcanvas';
import type {IslandId} from '@exulanica/atlas-core';
import {accessHeaders, type Credentials} from '../config.js';

/** Resolve each source key before fetching its pinned bytes. Current component kind is proved by the backend drawing and leased source proof. */
export async function loadTerrainDressing(access: Credentials, dressing: TerrainDressing): Promise<PreparedDressing> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30_000);
  const files = new Map<string, ArrayBuffer>(); let admittedBytes = 0;
  try {
    return await prepareTerrainDressing(dressing, async (source, signal) => {
      const response = await fetch(`${access.baseUrl}/world/assets/${encodeURIComponent(source.asset_key)}`, {
        headers: {...accessHeaders(access), Accept: 'application/json'}, credentials: 'same-origin', cache: 'no-store', signal,
      });
      if (!response.ok) throw new Error('A terrain component is unavailable.');
      const row = await response.json() as Record<string, unknown>;
      if (row['asset_key'] !== source.asset_key || row['content_sha256'] !== source.content_sha256
        || row['media_type'] !== 'model/gltf-binary' || row['availability'] !== 'available'
        || typeof row['byte_size'] !== 'number' || !Number.isSafeInteger(row['byte_size']) || row['byte_size'] <= 0 || row['byte_size'] > 32 * 1024 * 1024) {
        throw new Error('A terrain component no longer matches its source.');
      }
      const byteSize = row['byte_size'];
      const cached = files.get(source.content_sha256);
      if (cached !== undefined) {if (cached.byteLength !== byteSize) throw new Error('A terrain component byte count changed.'); return cached;}
      admittedBytes += byteSize;
      if (admittedBytes > 32 * 1024 * 1024) throw new Error('Terrain component content exceeds the aggregate budget.');
      // Preserve the existing verifier, while refusing an oversized stream before arrayBuffer allocation.
      const boundedFetch: typeof fetch = async (input, init) => {
        const result = await fetch(input, {...init, cache: 'no-store'});
        if (!result.ok || result.body === null) return result;
        const reader = result.body.getReader(), chunks: Uint8Array[] = []; let size = 0;
        try {
          while (true) {
            const next = await reader.read(); if (next.done) break;
            size += next.value.byteLength;
            if (size > byteSize || signal.aborted) throw new Error('Terrain component byte stream differs from its source.');
            chunks.push(next.value);
          }
        } finally {await reader.cancel(); reader.releaseLock();}
        const bytes = new Uint8Array(size); let at = 0;
        for (const chunk of chunks) {bytes.set(chunk, at); at += chunk.byteLength;}
        return new Response(bytes, {status: result.status, headers: result.headers});
      };
      const bytes = await fetchVerifiedObjectAsset('region:generated' as IslandId, {assetKey: source.asset_key, contentSha256: source.content_sha256,
        mediaType: 'model/gltf-binary', byteSize}, signal, {...access, fetch: boundedFetch});
      files.set(source.content_sha256, bytes); return bytes;
    }, controller.signal);
  } finally {clearTimeout(timeout); controller.abort();}
}
