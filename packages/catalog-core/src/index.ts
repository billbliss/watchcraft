export interface CollectionStats {
  video_count: number;
  topic_count: number;
  topic_family_count: number;
}

export interface CollectionGroup {
  type: "group";
  group_id: string;
  title: string;
  children: Array<CollectionGroup | CollectionVideoReference>;
}

export interface CollectionVideoReference {
  type: "video";
  item_id: string;
}

export interface Topic {
  topic_id: string;
  canonical_key: string;
  label: string;
  aliases: string[];
  video_count: number;
  family_ids: string[];
  related_topic_ids: string[];
}

export interface TopicFamily {
  family_id: string;
  canonical_key: string;
  label: string;
  description: string;
  topic_ids: string[];
  video_count: number;
}

export interface MediaReference {
  type: "local-file" | "url";
  relative_path: string;
  url?: string;
}

export interface CatalogItem {
  item_id: string;
  title: string;
  media: MediaReference[];
  transcript: {
    subtitles?: string;
    text?: string;
    segments?: string;
  };
  analysis: {
    path: string;
    schema_version?: number | null;
    model?: string | null;
  };
  summary: string;
  date?: { display?: string } | string | null;
  locations: Array<{ name?: string } | string>;
  topic_ids: string[];
  family_ids: string[];
  topic_sections: Record<string, number[]>;
  chapter_count: number;
}

export interface CollectionManifest {
  schema_version: 2;
  collection_id: string;
  title: string;
  description?: string;
  topic_scope: "collection";
  root: CollectionGroup;
  topics: Record<string, Topic>;
  topic_families: Record<string, TopicFamily>;
  items: Record<string, CatalogItem>;
  stats: CollectionStats;
  revision: number;
  content_hash: string;
}

export interface AnalysisSection {
  start: string;
  end: string;
  title: string;
  concepts: string[];
  description: string;
}

export interface VideoAnalysis {
  schema_version: number;
  video: string;
  title: string;
  summary: string;
  topics: string[];
  sections: AnalysisSection[];
  featured_techniques?: Array<{
    technique: string;
    timestamp: string;
    confidence: number;
  }>;
}

export interface CatalogRepository {
  readonly manifestLocation: string;
  loadCollection(): Promise<CollectionManifest>;
  loadAnalysis(item: CatalogItem): Promise<VideoAnalysis>;
  mediaUrl(item: CatalogItem): string | null;
  openInDefaultPlayer(item: CatalogItem): Promise<boolean>;
}

export interface OrderedCatalogItem {
  item: CatalogItem;
  path: string[];
}

export function orderedItems(manifest: CollectionManifest): OrderedCatalogItem[] {
  const result: OrderedCatalogItem[] = [];

  function visit(group: CollectionGroup, path: string[]): void {
    for (const child of group.children) {
      if (child.type === "group") {
        visit(child, [...path, child.title]);
        continue;
      }
      const item = manifest.items[child.item_id];
      if (item) result.push({ item, path });
    }
  }

  visit(manifest.root, []);
  return result;
}

export function clockSeconds(value: string): number {
  const parts = value.split(":").map(Number);
  if (parts.length !== 3 || parts.some(Number.isNaN)) return 0;
  return parts[0] * 3600 + parts[1] * 60 + parts[2];
}

export function displayClock(value: string): string {
  const seconds = Math.max(0, Math.floor(clockSeconds(value)));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainder = seconds % 60;
  return `${hours}:${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
}
