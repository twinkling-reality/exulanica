import { existsSync, readdirSync } from 'node:fs';
import { isAbsolute, join, relative } from 'node:path';

const within = (parent: string, child: string): boolean => {
  const path = relative(parent, child);
  return path === '' || (!path.startsWith('..') && !isAbsolute(path));
};

/**
 * Why `out` may not receive a dataset, or null. `root` is the repository root: dataset bytes go
 * outside it or under its ignored `.exulanica/` directory, never where git could take them, and
 * each export gets an empty directory of its own.
 */
export function outputProblem(root: string, out: string): string | null {
  if (within(root, out) && !within(join(root, '.exulanica'), out)) {
    return `${out} is inside the repository; dataset bytes go outside it or under .exulanica/`;
  }
  if (existsSync(out) && readdirSync(out).length > 0) {
    return `${out} is not empty; each export gets a directory of its own`;
  }
  return null;
}
