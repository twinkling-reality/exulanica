// No words a person reads call a person, a day or a minute simulated, or what happens a simulation
// (DESIGN's J34 and J35): people are invented for this world, and a moment is the world's own, said by
// its clock or its minute. This reads every string the app's source and the world workspace's own
// modules write, and holds the prose among them (two words or more) to that; a code such as
// 'simulated' or 'data-simulated' is not prose.
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const SOURCES = [new URL('../src/', import.meta.url), new URL('../../../../tools/previews/world-workspace/', import.meta.url)];

function files(folder: URL): URL[] {
  return readdirSync(folder).flatMap((name) => {
    const path = new URL(name, folder);
    if (statSync(path).isDirectory()) return files(new URL(`${name}/`, folder));
    return /\.(ts|mjs)$/u.test(name) && !name.startsWith('verify-') ? [path] : [];
  });
}

/** The strings a module writes: its quoted and template literals, comments left out. */
function strings(source: string): string[] {
  const code = source.replace(/\/\*[\s\S]*?\*\//gu, '').replace(/^\s*\/\/.*$/gmu, '');
  return [...code.matchAll(/'(?:[^'\\\n]|\\.)*'|"(?:[^"\\\n]|\\.)*"|`(?:[^`\\]|\\.)*`/gu)].map((found) => found[0].slice(1, -1));
}

/** Two words or more; a hole reads as a word (`${who} (simulated) waits`). */
const prose = (text: string) => /[A-Za-z]+[ ,:()·]+[A-Za-z]/u.test(text.replace(/\$\{[^}]*\}/gu, 'x'));
/** The words themselves, never part of a code's name ('companion-simulated', 'simulated_minute', 'onSimulation'). */
const saysSimulated = (text: string) => /(?<![-\w])simulat(?:ed|ion)(?![-\w])/iu.test(text);

describe('words a person reads', () => {
  const written = SOURCES.flatMap(files).map((path) => ({ path: path.pathname, said: strings(readFileSync(path, 'utf8')).filter(prose) }));

  it('never call anyone, any moment or what happens simulated, or a simulation', () => {
    // The positive control: the scan reads the app's own sentences and the workspace's.
    const all = written.flatMap((file) => file.said);
    expect(all).toContain('Bring people into this world');
    expect(written.some((file) => file.path.includes('/tools/previews/world-workspace/') && file.said.length > 0)).toBe(true);
    const simulated = written.flatMap((file) => file.said.filter(saysSimulated).map((text) => `${file.path}: ${text}`));
    expect(simulated).toEqual([]);
  });

  it('would see a sentence that says it', () => {
    expect(strings("const hint = 'Bring simulated people into this world';").filter(prose).filter(saysSimulated))
      .toEqual(['Bring simulated people into this world']);
    expect(strings("el('p', { class: 'companion-name companion-simulated', 'data-simulated': kind });").filter(prose).filter(saysSimulated)).toEqual([]);
    expect(strings("['Plane / origin', 'Simulation · synthetic']").filter(prose).filter(saysSimulated)).toEqual(['Simulation · synthetic']);
    expect(strings('const line = `${who} (simulated) waits`;').filter(prose).filter(saysSimulated)).toEqual(['${who} (simulated) waits']);
  });
});
