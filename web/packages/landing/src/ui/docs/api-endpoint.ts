import { el } from '../dom.js';
import { codeBlock, p } from './elements.js';
import { API_SCHEMA } from '../../content/api-schema.js';
import type { Schema } from '../../content/api-types.js';

const descriptions: Record<string, string> = {
  recipe: 'Recipe key returned by GET /worlds/recipes.',
  title: 'The name shown for this saved world.',
  values: 'Recipe parameters. Read /worlds/specification for supported keys and ranges.',
  style_pack: 'Optional appearance pack, identified by its ID, version, and manifest digest.',
  base_state_sha256: 'The state_sha256 from the version you read. A changed base is refused.',
  saved_entry: 'Update the saved entry’s state digest and edit cursor together with the object edit.',
  object_id: 'A unique identifier for the object in this world.',
  asset_sha256: 'Content digest of an asset from the server’s catalog.',
  region_id: 'A region offered by the version’s capability descriptor.',
  transform: 'Position in millimeters, yaw in microradians, and scale in thousandths.',
  origin_role: 'Whether the object is authored fiction or belongs to the personal world.',
  behaviour: 'Optional behavior binding supported by this version.',
};
const resolve = (s: Schema): Schema => s.$ref ? API_SCHEMA.schemas[s.$ref.split('/').at(-1)!]! : s;
function type(s: Schema): string {
  if (s.$ref) return type(resolve(s));
  if (s.anyOf) return s.anyOf.map(type).join(' | ');
  if (s.enum) return s.enum.map(v => JSON.stringify(v)).join(' | ');
  return s.type === 'array' ? `${type(s.items ?? {})}[]` : s.format ?? s.type ?? 'value';
}
function fields(input: Schema, depth = 0, parents: string[] = []): HTMLElement {
  const schema = resolve(input);
  if (schema.type === 'array') return el('div', { class: 'api-fields' }, [p(`Array of ${type(schema.items ?? {})} values`), fields(schema.items ?? {}, depth, parents)]);
  const rows = Object.entries(schema.properties ?? {});
  if (!rows.length) return p(schema.description ?? (schema.type === 'object' ? 'An object with properties defined by the server.' : type(input)));
  return el('div', { class: 'api-fields' }, rows.map(([name, value]) => {
    const constraints = ['minLength', 'maxLength', 'minimum', 'maximum', 'pattern'].filter(k => value[k] !== undefined).map(k => `${k}: ${value[k]}`).join(', ');
    const nested = resolve(value.anyOf?.find(s => s.type !== 'null') ?? value);
    const children: Node[] = [el('div', { class: 'api-field-heading' }, [el('code', { text: name }), el('span', { text: type(value) }), ...(schema.required?.includes(name) ? [el('span', { class: 'api-required', text: 'required' })] : [])])];
    const description = value.description ?? (depth === 0 ? descriptions[name] : undefined);
    if (description) children.push(p(description));
    if (constraints) children.push(el('p', { class: 'api-constraints', text: constraints }));
    if (value.default !== undefined) children.push(el('p', { class: 'api-constraints', text: `Default: ${JSON.stringify(value.default)}` }));
    if ((nested.properties || nested.items) && depth < 3 && (!value.$ref || !parents.includes(value.$ref))) children.push(el('details', {}, [el('summary', { text: 'Show properties' }), fields(nested, depth + 1, [...parents, value.$ref ?? name])]));
    return el('div', { class: 'api-field' }, children);
  }));
}
export interface Endpoint { key: string; title: string; method: 'get' | 'post'; path: string; description: string; body?: string; note?: string }
export function endpoint(entry: Endpoint, includeDescription = true): Node[] {
  const operation = API_SCHEMA.paths[entry.path]![entry.method]!;
  const parameters = operation.parameters?.filter(p => p.in !== 'header') ?? [];
  const url = entry.path.replace(/\{([^}]+)\}/g, (_, name: string) => `$${name.toUpperCase()}`) + (parameters.some(p => p.name === 'world_id') ? '?world_id=$WORLD_ID' : '');
  const curl = `curl --fail-with-body${entry.method === 'post' ? ' -X POST' : ''} \\\n  "$EXULANICA_API_URL${url}" \\\n  -H "Authorization: Bearer $EXULANICA_TOKEN"${entry.body ? ` \\\n  -H "Content-Type: application/json" \\\n  -d '${entry.body}'` : ''}`;
  const pythonUrl = url.replace(/\$([A-Z_]+)/g, (_, name: string) => `{os.environ["${name}"]}`);
  const python = `import json
import os
import urllib.request

url = os.environ["EXULANICA_API_URL"] + f'${pythonUrl}'
headers = {
    "Authorization": "Bearer " + os.environ["EXULANICA_TOKEN"]
}${entry.body ? `
headers["Content-Type"] = "application/json"
body = ${entry.body}
data = json.dumps(body).encode()` : ''}
request = urllib.request.Request(
    url, ${entry.body ? 'data=data, ' : ''}headers=headers, method="${entry.method.toUpperCase()}"
)
with urllib.request.urlopen(request) as response:
    print(json.load(response))`;
  const response = Object.entries(operation.responses).find(([status]) => status.startsWith('2'))!;
  const responseSchema = response[1].content?.['application/json']?.schema;
  const bodySchema = operation.requestBody?.content['application/json']?.schema;
  return [
    el('div', { class: 'api-route' }, [el('span', { class: `api-method ${entry.method}`, text: entry.method.toUpperCase() }), el('code', { text: entry.path })]),
    el('div', { class: 'api-endpoint-grid' }, [
      el('div', { class: 'api-description' }, [...(includeDescription ? [p(entry.description)] : []),
        ...(entry.note ? [p(entry.note)] : []),
        ...(parameters.length ? [el('h3', { text: 'Parameters' }), ...parameters.map(parameter => el('div', { class: 'api-field' }, [el('div', { class: 'api-field-heading' }, [el('code', { text: parameter.name }), el('span', { text: `${parameter.in}, ${type(parameter.schema)}` }), el('span', { class: 'api-required', text: parameter.required ? 'required' : 'optional' })])]))] : []),
        ...(bodySchema ? [el('h3', { text: 'Request body' }), fields(bodySchema)] : []),
        el('section', { class: 'api-response-fields' }, [el('h3', { text: 'Response' }), el('div', { class: 'api-response-status' }, [el('span', { text: response[0] }), el('span', { text: 'application/json' })]), ...(responseSchema ? [fields(responseSchema)] : [p(response[1].description)])]),
      ]),
      el('div', { class: 'api-example' }, [requestTabs(entry.key, curl, python),
        ...(responseSchema ? [el('details', { class: 'api-response-example' }, [el('summary', { text: `${response[0]} Response structure` }), codeBlock('Response structure', JSON.stringify(responseShape(responseSchema), null, 2), 'json'), el('p', { class: 'api-example-note', text: 'Types and structure, not a live response. Expand properties for the complete field definitions.' })])] : []),
      ]),
    ]),
  ];
}

/** A type view, deliberately not invented response data. */
function responseShape(input: Schema, depth = 0): unknown {
  const s = resolve(input);
  if (depth > 2) return type(input);
  if (s.anyOf) return s.anyOf.map(part => type(part)).join(' | ');
  if (s.type === 'array') return [responseShape(s.items ?? {}, depth + 1)];
  if (s.properties) return Object.fromEntries(Object.entries(s.properties).map(([name, value]) => [name, responseShape(value, depth + 1)]));
  return type(s);
}
function requestTabs(key: string, curl: string, python: string): HTMLElement {
  const root = el('div', { class: 'api-request' });
  const panels = [codeBlock('cURL request', curl, 'bash'), codeBlock('Python request', python, 'python')];
  const tabs = ['cURL', 'Python'].map((label, index) => el('button', { type: 'button', role: 'tab', id: `request-${key}-tab-${index}`, 'aria-controls': `request-${key}-panel-${index}`, 'aria-selected': String(index === 0), tabindex: index === 0 ? '0' : '-1', text: label }));
  const select = (index: number) => tabs.forEach((tab, n) => { tab.setAttribute('aria-selected', String(n === index)); tab.tabIndex = n === index ? 0 : -1; panels[n]!.hidden = n !== index; });
  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => select(index));
    tab.addEventListener('keydown', event => { if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return; event.preventDefault(); const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length; select(next); tabs[next]!.focus(); });
    // Feedback occupies a row below the tabs, leaving the example unobscured.
    panels[index]!.querySelector('pre')!.before(panels[index]!.querySelector('.docs-copy-status')!);
    panels[index]!.id = `request-${key}-panel-${index}`;
    panels[index]!.setAttribute('role', 'tabpanel'); panels[index]!.setAttribute('aria-labelledby', tab.id);
  });
  select(0);
  root.append(el('div', { class: 'api-request-tabs', role: 'tablist', 'aria-label': 'Request language' }, tabs), ...panels);
  return root;
}
