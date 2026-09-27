// The page's words for a world edit are keyed by exactly the edit kinds the server states.
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { EDIT_WORDS } from '../src/composition/objects.js';

/** The repository, from the web workspace vitest runs in, as the other page tests read it. */
const EDIT_KINDS = `${process.cwd()}/../exulanica/world/edit_kinds.py`;

describe('the words for a world edit', () => {
  it('name exactly the edit kinds the server states', () => {
    const source = readFileSync(EDIT_KINDS, 'utf8');
    const stated = [...source.matchAll(/EditKind\(\s*"([a-z_]+)"/g)].map((match) => match[1]!);
    // A positive control: kinds the server is known to state are found by the same reading.
    expect(stated).toEqual(expect.arrayContaining(['add_object', 'set_object_behaviour', 'remove_point_map']));
    expect(Object.keys(EDIT_WORDS).sort()).toEqual([...stated].sort());
  });
});
