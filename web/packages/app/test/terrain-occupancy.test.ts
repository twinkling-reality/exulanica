import {afterEach,expect,it,vi} from 'vitest';
import {holdTerrainOccupancy,TERRAIN_PROOF_LEASE_MS,TERRAIN_PROOF_REFRESH_MS,TERRAIN_PROOF_TIMEOUT_MS} from '../src/composition/terrain-occupancy.js';
import type {TerrainOccupancyProof} from '@exulanica/atlas-core';
const proof:TerrainOccupancyProof={status:'verified',worldId:'world:terrain',versionId:'11111111-1111-1111-1111-111111111111',receiptSha256:'a'.repeat(64),geometrySha256:'b'.repeat(64),contactSha256:'c'.repeat(64),authoredStateSha256:'d'.repeat(64)};
afterEach(()=>vi.useRealTimers());
function clock(){vi.useFakeTimers({toFake:['setTimeout','clearTimeout','performance']});}
it('expires synchronously even when no background timer ran and never revives on attachment',async()=>{
 clock();const read=vi.fn(async()=>proof),lease=await holdTerrainOccupancy(read,()=>true);
 expect(lease.read().status).toBe('verified');await vi.advanceTimersByTimeAsync(TERRAIN_PROOF_LEASE_MS);
 expect(lease.read().status).toBe('unavailable');const stop=lease.attach();await vi.advanceTimersByTimeAsync(10000);
 expect(read).toHaveBeenCalledTimes(1);expect(lease.read().status).toBe('unavailable');stop();expect(vi.getTimerCount()).toBe(0);
});
it('renews only while mounted and stops its bounded refresh after disposal',async()=>{
 clock();const read=vi.fn(async()=>proof),lease=await holdTerrainOccupancy(read,()=>true),stop=lease.attach();
 await vi.advanceTimersByTimeAsync(6000);expect(read).toHaveBeenCalledTimes(4);expect(lease.read().status).toBe('verified');
 stop();stop();expect(vi.getTimerCount()).toBe(0);await vi.advanceTimersByTimeAsync(5000);expect(lease.read().status).toBe('unavailable');
});
it('revokes at timeout, aborts transport and ignores a late valid response through relook',async()=>{
 clock();let resolve!:(p:TerrainOccupancyProof)=>void;let signal!:AbortSignal;
 const read=vi.fn(async(s:AbortSignal)=>{signal=s;return read.mock.calls.length===1?proof:new Promise<TerrainOccupancyProof>(r=>{resolve=r;});});
 const lease=await holdTerrainOccupancy(read,()=>true),stop=lease.attach();await vi.advanceTimersByTimeAsync(TERRAIN_PROOF_REFRESH_MS);
 expect(lease.read().status).toBe('verified');await vi.advanceTimersByTimeAsync(TERRAIN_PROOF_TIMEOUT_MS);
 expect(signal.aborted).toBe(true);expect(lease.read().status).toBe('unavailable');resolve(proof);await Promise.resolve();stop();const stopRelook=lease.attach();
 await vi.advanceTimersByTimeAsync(10000);expect(read).toHaveBeenCalledTimes(2);expect(lease.read().status).toBe('unavailable');stopRelook();expect(vi.getTimerCount()).toBe(0);
});
it('disposal aborts an in-flight refresh without leaving a timer or accepting its late result',async()=>{
 clock();let resolve!:(p:TerrainOccupancyProof)=>void;let signal!:AbortSignal;
 const read=vi.fn(async(s:AbortSignal)=>{signal=s;return read.mock.calls.length===1?proof:new Promise<TerrainOccupancyProof>(r=>{resolve=r;});});
 const lease=await holdTerrainOccupancy(read,()=>true),stop=lease.attach();await vi.advanceTimersByTimeAsync(2000);stop();
 expect(signal.aborted).toBe(true);await Promise.resolve();expect(vi.getTimerCount()).toBe(0);resolve(proof);await Promise.resolve();
 await vi.advanceTimersByTimeAsync(3000);expect(lease.read().status).toBe('unavailable');
});
it('failed refresh and local source change both permanently withdraw held contact',async()=>{
 clock();let current=true;const read=vi.fn(async()=>proof),lease=await holdTerrainOccupancy(read,()=>current),stop=lease.attach();
 current=false;expect(lease.read().status).toBe('unavailable');current=true;await vi.advanceTimersByTimeAsync(5000);expect(lease.read().status).toBe('unavailable');stop();
 const remote=await holdTerrainOccupancy(vi.fn().mockResolvedValueOnce(proof).mockRejectedValue(new Error('offline')),()=>true),stopRemote=remote.attach();
 await vi.advanceTimersByTimeAsync(2000);expect(remote.read().status).toBe('unavailable');stopRemote();expect(vi.getTimerCount()).toBe(0);
});
it('bounds the initial proof request even if transport ignores abort',async()=>{
 clock();let signal!:AbortSignal;
 const pending=holdTerrainOccupancy(async(s)=>{signal=s;return new Promise<TerrainOccupancyProof>(()=>undefined);},()=>true);
 await vi.advanceTimersByTimeAsync(1500);const lease=await pending;
 expect(signal.aborted).toBe(true);expect(lease.read().status).toBe('unavailable');expect(vi.getTimerCount()).toBe(0);
});
