/** Small decorative vectors. Accessible names belong to their enclosing controls. */
export function icon(name: 'chevron' | 'github' | 'twinkling' | 'arrow' | 'copy' | 'check' | 'document' | 'download' | 'search' | 'close' | 'sun' | 'moon'): SVGSVGElement {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', name === 'twinkling' ? '0 0 256 256' : name === 'chevron' ? '0 0 14 14' : '0 0 24 24');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('focusable', 'false');
  svg.classList.add('icon', `icon-${name}`);
  const paths: Record<typeof name, readonly string[]> = {
    chevron: ['M3.5 5.25L7 8.75L10.5 5.25'],
    arrow: ['M5 12h14M13 6l6 6-6 6'],
    copy: ['M9 9h11v12H9z', 'M15 9V3H3v12h6'],
    check: ['M5 12l4 4L19 6'],
    document: ['M14 2H4v20h16V8z', 'M14 2v6h6', 'M8 13h8M8 17h6'],
    download: ['M12 3v12m-4-4 4 4 4-4', 'M4 16v5h16v-5'],
    search: ['M10.5 3a7.5 7.5 0 1 0 0 15 7.5 7.5 0 0 0 0-15', 'M16 16l5 5'],
    close: ['M6 6l12 12M6 18 18 6'],
    sun: ['M16 12a4 4 0 1 0-8 0a4 4 0 0 0 8 0', 'M12 2v2M12 20v2M2 12h2M20 12h2M4.93 4.93l1.42 1.42M17.65 17.65l1.42 1.42M4.93 19.07l1.42-1.42M17.65 6.35l1.42-1.42'],
    moon: ['M20.5 13A8.5 8.5 0 0 1 11 3.5A8.5 8.5 0 1 0 20.5 13Z'],
    github: ['M12 .3a12 12 0 0 0-3.8 23.4c.6.1.8-.3.8-.6v-2.2c-3.3.7-4-1.4-4-1.4-.5-1.4-1.3-1.8-1.3-1.8-1.1-.7.1-.7.1-.7 1.2.1 1.8 1.2 1.8 1.2 1.1 1.8 2.8 1.3 3.4 1 .1-.8.4-1.3.8-1.6-2.7-.3-5.5-1.3-5.5-5.9 0-1.3.5-2.4 1.2-3.2-.1-.3-.5-1.5.1-3.2 0 0 1-.3 3.3 1.2a11.5 11.5 0 0 1 6 0c2.3-1.5 3.3-1.2 3.3-1.2.6 1.7.2 2.9.1 3.2.7.8 1.2 1.9 1.2 3.2 0 4.6-2.8 5.6-5.5 5.9.4.4.8 1.1.8 2.2v3.3c0 .3.2.7.8.6A12 12 0 0 0 12 .3Z'],
    // Twinkling Reality's small-size mark, from its public inline SVG.
    twinkling: [
      'M123 20 C124 80 106 115 69 148 C122 129 157 122 235 115 C170 135 139 165 117 236 C107 173 86 156 20 146 C84 123 108 91 123 20Z',
      'M153 22 C169 70 190 81 236 88 C193 91 166 99 126 118 C151 84 156 52 153 22Z',
    ],
  };
  const stroked = ['chevron', 'arrow', 'copy', 'check', 'document', 'download', 'search', 'close', 'sun', 'moon'].includes(name);
  svg.setAttribute('fill', stroked ? 'none' : 'currentColor');
  if (stroked) {
    svg.setAttribute('stroke', 'currentColor');
    svg.setAttribute('stroke-width', name === 'chevron' ? '1.16667' : '1.5');
    svg.setAttribute('stroke-linecap', 'round');
    svg.setAttribute('stroke-linejoin', 'round');
  }
  for (const d of paths[name]) {
    const path = document.createElementNS(svg.namespaceURI, 'path');
    path.setAttribute('d', d);
    svg.append(path);
  }
  return svg;
}
