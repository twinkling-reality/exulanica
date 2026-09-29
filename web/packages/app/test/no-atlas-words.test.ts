import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';
import { describe, expect, it } from 'vitest';

/**
 * "Atlas" is the runtime's internal name, never a word a person reads. The page's words are its
 * string literals, so this reads every string literal and template text in the app's source as
 * the TypeScript parser does, and refuses the word "Atlas" in any of them. Module names are not
 * words a person reads: an import or export specifier is skipped, and a lowercase package name
 * (`@exulanica/atlas-react`) or an identifier (`AtlasBinding`) never matches the word itself.
 */

const SOURCE = fileURLToPath(new URL('../src', import.meta.url));
const WORD = /\bAtlas\b/u;

function* sources(directory: string): Generator<string> {
  for (const name of readdirSync(directory)) {
    const path = join(directory, name);
    if (statSync(path).isDirectory()) yield* sources(path);
    else if (path.endsWith('.ts')) yield path;
  }
}

/** Every string a file's code holds that says the word, with its line. */
function saidIn(path: string, text: string): string[] {
  const file = ts.createSourceFile(path, text, ts.ScriptTarget.Latest, true);
  const found: string[] = [];
  const visit = (node: ts.Node): void => {
    const literal = ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)
      || ts.isTemplateHead(node) || ts.isTemplateMiddle(node) || ts.isTemplateTail(node);
    const parent = node.parent as ts.Node | undefined;
    const specifier = parent !== undefined && (
      ts.isImportDeclaration(parent) || ts.isExportDeclaration(parent) || ts.isExternalModuleReference(parent)
      || (ts.isCallExpression(parent) && parent.expression.kind === ts.SyntaxKind.ImportKeyword)
    );
    if (literal && !specifier && WORD.test((node as ts.LiteralLikeNode).text)) {
      const { line } = file.getLineAndCharacterOfPosition(node.getStart(file));
      found.push(`${path.slice(SOURCE.length + 1)}:${line + 1}: ${(node as ts.LiteralLikeNode).text}`);
    }
    ts.forEachChild(node, visit);
  };
  visit(file);
  return found;
}

describe('the page never says Atlas', () => {
  it('finds the word where code says it, and not in a comment or a module name', () => {
    // A positive control: the scan sees a string and a template, and leaves the rest alone.
    const planted = [
      "// The Atlas binding",
      "import { AtlasBinding } from '@exulanica/atlas-react/playcanvas';",
      "const a = 'Opening the Atlas';",
      'const b = `This ${kind} Atlas`;',
    ].join('\n');
    expect(saidIn(join(SOURCE, 'planted.ts'), planted)).toEqual([
      'planted.ts:3: Opening the Atlas',
      'planted.ts:4:  Atlas',
    ]);
  });

  it('says it in no string of the app', () => {
    const said = [...sources(SOURCE)].flatMap((path) => saidIn(path, readFileSync(path, 'utf8')));
    expect(said).toEqual([]);
  });
});
