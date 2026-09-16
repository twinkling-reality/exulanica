import type { SourceMediaCatalog, SourceMediaDescriptor } from '@exulanica/atlas-react/playcanvas';
import { PREVIEW_IDS as ID } from './preview-graph.js';

interface PreviewSource extends SourceMediaDescriptor {
  readonly assetPath: string | null;
}

const COURTYARD: Omit<PreviewSource, 'evidenceRef'> = Object.freeze({
  title: 'Glasshouse courtyard',
  capturedLabel: 'Date unresolved',
  url: '/fixtures/memory/glasshouse-courtyard.jpg',
  assetPath: 'fixtures/memory/glasshouse-courtyard.jpg',
  available: true,
  accent: '#ef7b5d',
  alt: 'Mara beside a blue bicycle in the wet glasshouse courtyard.',
});

const STUDIO: Omit<PreviewSource, 'evidenceRef'> = Object.freeze({
  title: 'Spring planting day',
  capturedLabel: 'Date unresolved',
  url: '/fixtures/memory/glasshouse-studio.jpg',
  assetPath: 'fixtures/memory/glasshouse-studio.jpg',
  available: true,
  accent: '#e9a875',
  alt: 'Mara repotting plants inside the glasshouse studio.',
});

const SHORE: Omit<PreviewSource, 'evidenceRef'> = Object.freeze({
  title: 'Kite at the lakeshore',
  capturedLabel: 'Date unresolved',
  url: '/fixtures/memory/lakeshore-kite.jpg',
  assetPath: 'fixtures/memory/lakeshore-kite.jpg',
  available: true,
  accent: '#e6c777',
  alt: 'Mara holding a paper kite beside the blue bicycle at the lakeshore.',
});

const ARCHIVE: Omit<PreviewSource, 'evidenceRef'> = Object.freeze({
  title: 'Unsent letter',
  capturedLabel: 'Date unresolved',
  url: null,
  assetPath: null,
  available: false,
  accent: '#8377bd',
  alt: 'The source for this memory is unavailable.',
});

const assignments: readonly [string, Omit<PreviewSource, 'evidenceRef'>][] = [
  [ID.spanCourtyardMara, COURTYARD],
  [ID.spanCourtyardPlace, COURTYARD],
  [ID.spanCourtyardBicycle, COURTYARD],
  [ID.spanStudioMara, STUDIO],
  [ID.spanStudioPlace, STUDIO],
  [ID.spanStudioChair, STUDIO],
  [ID.spanStudioEvent, STUDIO],
  [ID.spanShoreMara, SHORE],
  [ID.spanShoreBicycle, SHORE],
  [ID.spanShoreKite, SHORE],
  [ID.spanArchiveLetter, ARCHIVE],
];

export const PREVIEW_SOURCE_MEDIA: SourceMediaCatalog = new Map(
  assignments.map(([evidenceRef, source]) => [
    evidenceRef,
    Object.freeze({ ...source, evidenceRef }),
  ]),
);

export function previewSource(evidenceRef: string): PreviewSource | undefined {
  return PREVIEW_SOURCE_MEDIA.get(evidenceRef) as PreviewSource | undefined;
}
