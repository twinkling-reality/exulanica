import { describe,expect,it } from 'vitest';
import { lensMotions,LiquidMotionState } from '../src/ui/liquid-motion.js';
import type { OrbitPose } from '../src/ui/world-orbit-geometry.js';
const orb=(x:number,y=0):OrbitPose=>({x,y,ax:20,ay:0,bx:0,by:20,material:0});
describe('motion-driven liquid lenses',()=>{
  it('follows travel direction and leaves stationary lenses calm',()=>{
    expect(lensMotions([orb(0)],[orb(0)],.1)[0]!.strength).toBe(0);
    const forward=lensMotions([orb(0)],[orb(2)],.1)[0]!;
    const reverse=lensMotions([orb(0)],[orb(-2)],.1)[0]!;
    expect(forward.x).toBe(1); expect(reverse.x).toBe(-1);
    expect(forward.strength).toBe(reverse.strength);
  });
  it('keeps at most two lenses active during a smooth change of motion',()=>{
    const state=new LiquidMotionState();
    const first=[0,1,2,3].map(index=>({index,strength:index<2?1:.2,x:1,y:0}));
    for(let i=0;i<60;i++) state.update(first,1/60,false);
    const second=first.map(m=>({...m,strength:m.index<2?.2:1}));
    state.update(second,1/60,false);
    expect(state.active[0]!.index).toBe(0);
    for(let i=0;i<180;i++) {
      state.update(second,1/60,false);
      const active=state.active.filter(m=>m.strength>0);
      expect(active.length).toBeLessThanOrEqual(2);
      expect(new Set(active.map(m=>m.index)).size).toBe(active.length);
    }
    expect(state.active.map(m=>m.index).sort()).toEqual([2,3]);
  });
  it('settles deformation when the field rests or reduced motion is enabled',()=>{
    const state=new LiquidMotionState();
    for(let i=0;i<60;i++) state.update([{index:0,strength:1,x:1,y:0}],1/60,false);
    for(let i=0;i<180;i++) state.update([],1/60,true);
    expect(state.active.every(m=>m.index===-1 && m.strength===0)).toBe(true);
  });
});
