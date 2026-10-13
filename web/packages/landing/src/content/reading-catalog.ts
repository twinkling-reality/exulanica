import { DOCUMENTS } from '../ui/docs/catalog.js';
import { JOURNAL } from './journal.js';
import { documentMarkdown, articleMarkdown } from './markdown.js';

/** Requires a DOM for the existing content builders; no page shell or interactions run. */
export function readingFiles(): Map<string, string> {
  const files = new Map<string, string>();
  for (const entry of DOCUMENTS) files.set(`${entry.href}.md`, documentMarkdown(entry.build()));
  for (const post of JOURNAL) files.set(`/blog/${post.slug}.md`, articleMarkdown(post));
  const index = '# Exulanica\n\n> Open-source virtual worlds for AI agents.\n\nThe guides describe self-hosted software. A public hosted API is not advertised. World capability descriptors and the schema on a running server describe that installation.\n\n## Documentation\n\n' + DOCUMENTS.map(entry => `- [${entry.label}](${entry.href}.md)`).join('\n') + '\n\n## Blog\n\n' + JOURNAL.map(post => `- [${post.title}](/blog/${post.slug}.md): ${post.description}`).join('\n') + '\n\n## API\n\n- [OpenAPI schema](/openapi.json): Full checked-in API contract.\n';
  files.set('/llms.txt', index);
  files.set('/llms-full.txt', index + '\n' + Array.from(files.values()).filter(value => value !== index).join('\n---\n\n'));
  return files;
}
