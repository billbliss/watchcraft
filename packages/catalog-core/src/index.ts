export interface CollectionStats {
  video_count: number;
  topic_count: number;
  topic_family_count: number;
}

export type CollectionMediaMode = "managed-local" | "referenced-local" | "remote";

export interface PublicCollectionDirectoryEntry {
  collectionId: string;
  title: string;
  url: string;
  category: string | null;
  videoCount: number | null;
  mediaModes: CollectionMediaMode[];
}

export const PUBLIC_COLLECTION_DIRECTORY_URL =
  "https://collections.watchcraft.stream/directory.json";

export function readPublicCollectionDirectory(
  value: unknown,
): PublicCollectionDirectoryEntry[] {
  if (!value || typeof value !== "object") return [];
  const collections = (value as { collections?: unknown }).collections;
  if (!Array.isArray(collections)) return [];

  const knownModes = new Set<CollectionMediaMode>([
    "managed-local",
    "referenced-local",
    "remote",
  ]);
  const unique = new Map<string, PublicCollectionDirectoryEntry>();
  for (const candidate of collections) {
    if (!candidate || typeof candidate !== "object") continue;
    const item = candidate as Record<string, unknown>;
    if (
      item.archived === true
      || typeof item.collection_id !== "string"
      || typeof item.title !== "string"
      || typeof item.manifest_url !== "string"
      || !Array.isArray(item.media_modes)
    ) continue;
    const mediaModes = item.media_modes.filter(
      (mode): mode is CollectionMediaMode => typeof mode === "string"
        && knownModes.has(mode as CollectionMediaMode),
    );
    if (mediaModes.length === 0) continue;
    try {
      const url = new URL(item.manifest_url);
      if (url.protocol !== "https:") continue;
      unique.set(url.href, {
        collectionId: item.collection_id,
        title: item.title,
        url: url.href,
        category: typeof item.category === "string" ? item.category : null,
        videoCount: Number.isInteger(item.video_count) && (item.video_count as number) >= 0
          ? item.video_count as number
          : null,
        mediaModes,
      });
    } catch {
      // Ignore malformed public directory entries.
    }
  }
  return [...unique.values()];
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

export interface LocalFileMediaReference {
  type: "local-file";
  delivery?: "managed-local" | "referenced-local";
  relative_path: string;
}

export interface YouTubeMediaReference {
  type: "youtube";
  delivery?: "remote";
  video_id: string;
  url?: string;
}

export const DEFAULT_YOUTUBE_BRIDGE_URL = "https://watchcraft.stream/youtube-player/";

export function youtubeBridgeUrl(
  videoId: string,
  bridgeUrl = DEFAULT_YOUTUBE_BRIDGE_URL,
): string {
  const url = new URL(bridgeUrl);
  url.searchParams.set("video", videoId);
  return url.toString();
}

export function youtubeEmbedUrl(videoId: string, clientOrigin?: string): string {
  const encoded = encodeURIComponent(videoId);
  const parameters = new URLSearchParams({
    enablejsapi: "1",
    playsinline: "1",
    rel: "0",
  });
  if (clientOrigin) {
    parameters.set("origin", clientOrigin);
    parameters.set("widget_referrer", clientOrigin);
  }
  return `https://www.youtube-nocookie.com/embed/${encoded}?${parameters}`;
}

export function youtubeWatchUrl(videoId: string): string {
  const url = new URL("https://www.youtube.com/watch");
  url.searchParams.set("v", videoId);
  return url.toString();
}

export function topicPassesFrequencyFilter(
  topicVideoCount: number,
  collectionVideoCount: number,
  maximumPercentage: number,
): boolean {
  if (collectionVideoCount < 5) return true;
  const percentage = (topicVideoCount * 100) / collectionVideoCount;
  return topicVideoCount > 1 && percentage <= maximumPercentage;
}

export interface HttpVideoMediaReference {
  type: "http-video";
  delivery?: "remote";
  url: string;
}

export type MediaReference =
  | LocalFileMediaReference
  | YouTubeMediaReference
  | HttpVideoMediaReference;

export interface CatalogItem {
  item_id: string;
  title: string;
  media: MediaReference[];
  /** @deprecated Legacy schema-v4 data; new collections omit transcript references. */
  transcript?: {
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
  kind: "watchcraft.collection";
  schema_version: 4;
  collection_id: string;
  title: string;
  description?: string;
  media_root_hint?: string;
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
  defaultPlayerName?(item: CatalogItem): Promise<string | null>;
  openInDefaultPlayer(item: CatalogItem): Promise<boolean>;
  openExternalMedia?(item: CatalogItem): Promise<boolean>;
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
