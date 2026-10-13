/** Essays interpret a recorded result. No invented publication dates. */
export interface JournalSection { id: string; title: string; paragraphs: readonly string[]; evidence?: { caption: string; headers: string[]; rows: string[][] } }
export interface JournalSource { title: string; detail: string; path?: string; href?: string }
export interface JournalPost {
  slug: string; title: string; subject: string; description: string;
  opening: string; sections: readonly JournalSection[];
  sources: readonly JournalSource[];
}

/** Empty. The homepage, product page, and About already say what Exulanica is. */
export const JOURNAL: readonly JournalPost[] = [];
