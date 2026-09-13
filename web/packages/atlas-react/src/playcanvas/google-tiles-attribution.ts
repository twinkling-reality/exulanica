interface GltfAsset {
  readonly copyright?: unknown;
}

interface EmbeddedGltf {
  readonly asset?: GltfAsset;
  readonly buffers?: readonly { readonly uri?: unknown }[];
  readonly images?: readonly { readonly uri?: unknown }[];
}

export interface GoogleGltfMetadata {
  readonly copyright: readonly string[];
}

/** Read only the glTF container metadata needed for admission and attribution. */
export function googleGltfMetadata(bytes: ArrayBuffer): GoogleGltfMetadata {
  if (bytes.byteLength < 20) throw new Error('Unsupported Google tile content');
  const view = new DataView(bytes);
  if (view.getUint32(0, true) !== 0x46546c67 ||
      view.getUint32(4, true) !== 2 ||
      view.getUint32(8, true) !== bytes.byteLength) {
    throw new Error('Unsupported Google tile content');
  }
  const jsonLength = view.getUint32(12, true);
  if (jsonLength < 2 || jsonLength > 4 * 1024 * 1024 ||
      20 + jsonLength > bytes.byteLength ||
      view.getUint32(16, true) !== 0x4e4f534a) {
    throw new Error('Unsupported Google tile content');
  }
  let gltf: EmbeddedGltf;
  try {
    const json = new TextDecoder().decode(new Uint8Array(bytes, 20, jsonLength)).trim();
    gltf = JSON.parse(json) as EmbeddedGltf;
  } catch {
    throw new Error('Unsupported Google tile content');
  }
  if (gltf.buffers?.some((buffer) => buffer.uri !== undefined) ||
      gltf.images?.some((image) => image.uri !== undefined)) {
    throw new Error('External Google tile resources are not admitted');
  }
  const value = gltf.asset?.copyright;
  const copyright = typeof value === 'string'
    ? value.split(';').map((part) => part.trim()).filter((part) => part.length > 0)
    : [];
  return Object.freeze({ copyright: Object.freeze(copyright) });
}

export class GoogleAttributionLedger {
  private sequence = 0;
  private readonly firstVisible = new Map<string, number>();
  private readonly visible = new Map<string, readonly string[]>();

  setVisible(tileId: string, values: readonly string[], visible: boolean): void {
    if (!visible) {
      this.visible.delete(tileId);
      return;
    }
    if (!this.firstVisible.has(tileId)) this.firstVisible.set(tileId, this.sequence++);
    this.visible.set(tileId, Object.freeze([...values]));
  }

  remove(tileId: string): void {
    this.visible.delete(tileId);
    this.firstVisible.delete(tileId);
  }

  values(): readonly string[] {
    const seen = new Set<string>();
    const result: string[] = [];
    const tiles = [...this.visible].sort((left, right) =>
      (this.firstVisible.get(left[0]) ?? 0) - (this.firstVisible.get(right[0]) ?? 0));
    for (const [, values] of tiles) {
      for (const value of values) {
        const normalized = value.trim();
        if (normalized.length > 0 && !seen.has(normalized)) {
          seen.add(normalized);
          result.push(normalized);
        }
      }
    }
    return Object.freeze(result);
  }

  clear(): void {
    this.visible.clear();
    this.firstVisible.clear();
  }
}

export class GoogleAttributionSurface {
  readonly root: HTMLElement;
  private readonly copyright: HTMLElement;

  constructor(parent: HTMLElement) {
    const document = parent.ownerDocument;
    this.root = document.createElement('aside');
    this.root.className = 'google-tiles-attribution';
    this.root.setAttribute('aria-label', 'Google Maps attribution');
    this.root.hidden = true;

    const provider = document.createElement('span');
    provider.textContent = 'Google Maps';
    this.copyright = document.createElement('span');
    this.copyright.className = 'google-tiles-copyright';
    const navigation = document.createElement('span');
    navigation.textContent = ' · Visual reference only; movement uses Atlas navigation, not Google street collision.';

    const terms = document.createElement('a');
    terms.href = 'https://maps.google.com/help/terms_maps/';
    terms.target = '_blank';
    terms.rel = 'noopener noreferrer';
    terms.textContent = 'Terms';

    const privacy = document.createElement('a');
    privacy.href = 'https://policies.google.com/privacy';
    privacy.target = '_blank';
    privacy.rel = 'noopener noreferrer';
    privacy.textContent = 'Privacy';

    this.root.append(provider, this.copyright, navigation, terms, privacy);
    parent.append(this.root);
  }

  update(visible: boolean, values: readonly string[]): void {
    this.root.hidden = !visible;
    this.copyright.textContent = values.length === 0 ? '' : ` · ${values.join(' · ')}`;
  }

  destroy(): void {
    this.root.remove();
  }
}
