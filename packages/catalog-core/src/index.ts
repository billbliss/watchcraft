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
  date?: {
    display?: string;
    iso?: string;
    precision?: string;
    confidence?: number;
    basis?: string;
  } | string | null;
  locations: Array<{
    name?: string;
    confidence?: number;
    basis?: string;
  } | string>;
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
  readonly canOpenInDefaultPlayer?: boolean;
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

export type TimelineClockMode = "hours-minutes-seconds" | "minutes-seconds-fraction";

export function clockSeconds(
  value: string,
  mode: TimelineClockMode = "hours-minutes-seconds",
): number {
  const rawParts = value.split(":");
  const parts = rawParts.map(Number);
  if ((parts.length !== 2 && parts.length !== 3) || parts.some(Number.isNaN)) {
    return 0;
  }
  if (parts.length === 2) return parts[0] * 60 + parts[1];
  if (mode === "minutes-seconds-fraction") {
    const fractionDigits = rawParts[2].replace(/\D/g, "");
    const fraction = fractionDigits ? Number(`0.${fractionDigits}`) : 0;
    return parts[0] * 60 + parts[1] + fraction;
  }
  return parts[0] * 3600 + parts[1] * 60 + parts[2];
}

export function inferTimelineClockMode(
  sections: AnalysisSection[],
  durationSeconds: number | null,
): TimelineClockMode {
  if (!Number.isFinite(durationSeconds) || !durationSeconds || sections.length === 0) {
    return "hours-minutes-seconds";
  }
  const finalClock = [...sections].reverse().find((section) => section.end)?.end;
  if (!finalClock || finalClock.split(":").length !== 3) {
    return "hours-minutes-seconds";
  }
  const standardEnd = clockSeconds(finalClock, "hours-minutes-seconds");
  const shiftedEnd = clockSeconds(finalClock, "minutes-seconds-fraction");
  const standardDistance = Math.abs(durationSeconds - standardEnd);
  const shiftedDistance = Math.abs(durationSeconds - shiftedEnd);
  const meaningfulDifference = Math.max(2, durationSeconds * 0.01);
  return shiftedDistance + meaningfulDifference < standardDistance
    ? "minutes-seconds-fraction"
    : "hours-minutes-seconds";
}

export function displayClock(
  value: string,
  mode: TimelineClockMode = "hours-minutes-seconds",
): string {
  const seconds = Math.max(0, Math.floor(clockSeconds(value, mode)));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainder = seconds % 60;
  return hours
    ? `${hours}:${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`
    : `${minutes}:${String(remainder).padStart(2, "0")}`;
}
