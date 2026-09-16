import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { inspectCharacterGlb, validateNativeCharacterDescriptor } from '../src/playcanvas/native-character.js';
import { createHash } from 'node:crypto';
const root = new URL('../../../../assets/characters/makehuman-parametric-v1/', import.meta.url);
describe('prepared editable human', () => {
  it('contains the declared rig, verified bytes and playable native motion', () => {
    const look = JSON.parse(readFileSync(new URL('default.look.json', root), 'utf8'));
    const bytes = readFileSync(new URL(look.file, root));
    expect(bytes.length).toBe(look.descriptor.asset.byteSize);
    expect(createHash('sha256').update(bytes).digest('hex')).toBe(look.descriptor.asset.contentSha256);
    const glb = inspectCharacterGlb(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength));
    expect(() => validateNativeCharacterDescriptor(look.descriptor, glb)).not.toThrow();
    expect(glb.clipNames).toEqual(expect.arrayContaining(['HumanIdle', 'HumanWalk', 'HumanRun']));
    expect(look.descriptor.unitScale * look.descriptor.standingHeight).toBeCloseTo(look.recipe.heightCm / 100);
    expect(look.descriptor.clips.run.metresPerSecond).toBeGreaterThan(look.descriptor.clips.walk.metresPerSecond);
  });
});
