import { readdirSync, readFileSync } from 'node:fs';
import { join, relative } from 'node:path';
import { describe, expect, it } from 'vitest';

import { COPY } from '../src/ui/copy.js';
import { problemRecord, problemSentence, problemWords, REQUEST_REFUSALS } from '../src/ui/words/problems.js';
import { ApiError } from '@exulanica/graph-client';

/*
 * The interface's words keep the voice guide's rule that a code is never the message
 * (docs/interface-system.md section 5): no entry is left as placeholder words, the copy table
 * has no code slot, and no surface builds a sentence around a code.
 */

const SRC = new URL('../src/', import.meta.url).pathname;
const CATALOGS = new URL('../../../../assets/catalogs/', import.meta.url).pathname;

function files(dir: string, suffixes: readonly string[]): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return files(path, suffixes);
    return suffixes.some((suffix) => entry.name.endsWith(suffix)) ? [path] : [];
  });
}

describe('the interface’s words', () => {
  it('leaves no entry as placeholder words', () => {
    const marked = [...files(SRC, ['.ts']), ...files(CATALOGS, ['.json'])]
      .filter((path) => readFileSync(path, 'utf8').includes('Placeholder words'))
      .map((path) => relative(join(SRC, '..'), path));
    expect(marked).toEqual([]);
  });

  it('has no code slot in the copy table', () => {
    const slots = Object.entries(COPY).filter(([, text]) => /\{code\}/.test(text)).map(([key]) => key);
    expect(slots).toEqual([]);
  });

  it('builds no sentence around a code in the interface and its composition', () => {
    const builders: string[] = [];
    for (const path of files(join(SRC, 'ui'), ['.ts']).concat(files(join(SRC, 'composition'), ['.ts']))) {
      const lines = readFileSync(path, 'utf8').split('\n');
      lines.forEach((line, index) => {
        if (/^\s*(\/\/|\*)/.test(line) || /\.replace\(|startsWith\(|const prefix/.test(line)) return;
        if (/\(\$\{(code|error\.code|refusal|reason)\}\)|\$\{error\.code\}: /.test(line)) {
          builders.push(`${relative(SRC, path)}:${index + 1}`);
        }
      });
    }
    expect(builders).toEqual([]);
  });

  it('says a refusal as what happened and what to do next, keeping the code for the record', () => {
    const refused = new ApiError(429, 'workspace_capacity_exhausted', 'share spent');
    expect(problemWords(refused)).toBe(REQUEST_REFUSALS['workspace_capacity_exhausted']);
    expect(problemSentence(refused)).not.toContain('workspace_capacity_exhausted');
    expect(problemRecord(refused)).toEqual({ code: 'workspace_capacity_exhausted', status: 429, detail: 'share spent' });
    expect(problemSentence(new ApiError(500, 'a_new_code', 'x'))).not.toContain('a_new_code');
  });
});
