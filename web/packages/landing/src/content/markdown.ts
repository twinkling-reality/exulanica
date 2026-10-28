import type { DocumentPage } from '../ui/docs/elements.js';
import type { JournalPost, JournalSource } from './journal.js';

const escapeCell = (text: string): string => text.replace(/\|/g, '\\|').replace(/\n/g, ' ');
/** Serialize the content tree, excluding controls. Exports and copy use this same function. */
export function nodeMarkdown(node: Node): string {
  if (node.nodeType === 3) return node.textContent ?? '';
  if (node.nodeType !== 1) return '';
  const element = node as HTMLElement;
  if (element.matches('button, input, kbd, [role="tablist"], [role="status"], [aria-hidden="true"], .docs-code-toolbar')) return '';
  if (element.matches('.docs-paths a')) return `- [${element.querySelector('span')?.textContent}](${element.getAttribute('href')}): ${element.querySelector('p')?.textContent}\n\n`;
  if (element.matches('a.docs-index-link')) return `- [${element.querySelector('strong')?.textContent}](${element.getAttribute('href')}): ${element.querySelector('span')?.textContent}\n\n`;
  if (element.matches('.api-operation-index a')) return `[${Array.from(element.children).map(child => child.textContent).join(' · ')}](${element.getAttribute('href')})`;
  if (element.classList.contains('api-field-heading')) return Array.from(element.children).map(child => nodeMarkdown(child)).join(' · ') + '\n\n';
  if (element.classList.contains('api-route')) return Array.from(element.children).map(child => nodeMarkdown(child)).join(' ') + '\n\n';
  const children = () => Array.from(element.childNodes).map(nodeMarkdown).join('');
  const text = element.textContent ?? '';
  switch (element.tagName.toLowerCase()) {
    case 'pre': return `\n\n\`\`\`${element.dataset.language ?? ''}\n${text.trimEnd()}\n\`\`\`\n\n`;
    case 'code': return `\`${text}\``;
    case 'p': case 'figcaption': return `${children()}\n\n`;
    case 'h2': return `\n## ${text}\n\n`;
    case 'h3': return `\n### ${text}\n\n`;
    case 'h4': return `\n#### ${text}\n\n`;
    case 'a': return `[${children()}](${element.getAttribute('href')})`;
    case 'img': return `\n![${element.getAttribute('alt') ?? ''}](${element.getAttribute('src')})\n\n`;
    case 'strong': return `**${children()}**`;
    case 'nav': return Array.from(element.children).map(child => nodeMarkdown(child)).join('\n\n') + '\n\n';
    case 'summary': return `\n**${children()}**\n\n`;
    case 'ul': return `\n${Array.from(element.children).map(li => `- ${nodeMarkdown(li).trim()}\n`).join('')}\n`;
    case 'ol': return `\n${Array.from(element.children).map((li, i) => `${i + 1}. ${nodeMarkdown(li).trim()}\n`).join('')}\n`;
    case 'table': {
      const rows = Array.from(element.querySelectorAll('tr')).map(row => `| ${Array.from(row.children).map(cell => escapeCell(nodeMarkdown(cell).trim())).join(' | ')} |`);
      rows.splice(1, 0, `| ${Array.from(element.querySelectorAll('thead th')).map(() => '---').join(' | ')} |`);
      return `\n${rows.join('\n')}\n\n`;
    }
    case 'dt': return `\n**${children()}**\n\n`;
    case 'dd': return `${children()}\n\n`;
    default: return children();
  }
}
export function documentMarkdown(page: DocumentPage): string {
  return `# ${page.title}\n\n${page.introduction}\n\n${page.chapters.map(chapter => `## ${chapter.title}\n\n${chapter.nodes.map(nodeMarkdown).join('')}`).join('\n')}`.split(/(```[\s\S]*?```)/g).map((part, index) => index % 2 ? part : part.replace(/\n{3,}/g, '\n\n')).join('').trim() + '\n';
}
const sourceHref = (item: JournalSource): string => item.href ?? `https://github.com/twinkling-reality/exulanica/blob/main/${item.path}`;
export function articleMarkdown(post: JournalPost): string {
  const sources = post.sources.length === 0 ? '' : `\n\n## Sources\n\n${post.sources.map(item => `- [${item.title}](${sourceHref(item)}): ${item.detail}`).join('\n')}`;
  return `# ${post.title}\n\n${post.description}\n\n${post.opening}\n\n${post.sections.map(section => `## ${section.title}\n\n${section.paragraphs.join('\n\n')}${section.evidence ? '\n\n| ' + section.evidence.headers.join(' | ') + ' |\n| ' + section.evidence.headers.map(() => '---').join(' | ') + ' |\n' + section.evidence.rows.map(row => '| ' + row.join(' | ') + ' |').join('\n') + '\n\n' + section.evidence.caption : ''}`).join('\n\n')}${sources}\n`;
}
