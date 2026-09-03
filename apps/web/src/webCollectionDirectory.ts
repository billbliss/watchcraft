export interface FeaturedWebCollection {
  collectionId: string;
  title: string;
  url: string;
  category: string | null;
  videoCount: number | null;
}

export const WEB_COLLECTION_DIRECTORY_URL =
  "https://collections.watchcraft.stream/directory.json";

export const FALLBACK_FEATURED_WEB_COLLECTIONS: FeaturedWebCollection[] = [
  {
    collectionId: "essence-of-linear-algebra",
    title: "Essence of linear algebra",
    url: "https://collections.watchcraft.stream/collections/essence-of-linear-algebra/collection.json",
    category: "Mathematics",
    videoCount: 16,
  },
];

export function readFeaturedWebCollections(value: unknown): FeaturedWebCollection[] {
  if (!value || typeof value !== "object") return [];
  const collections = (value as { collections?: unknown }).collections;
  if (!Array.isArray(collections)) return [];

  const unique = new Map<string, FeaturedWebCollection>();
  for (const candidate of collections) {
    if (!candidate || typeof candidate !== "object") continue;
    const item = candidate as Record<string, unknown>;
    if (
      item.archived === true
      || typeof item.collection_id !== "string"
      || typeof item.title !== "string"
      || typeof item.manifest_url !== "string"
      || !Array.isArray(item.media_modes)
      || !item.media_modes.includes("remote")
    ) continue;
    try {
      const url = new URL(item.manifest_url);
      if (url.protocol !== "https:") continue;
      unique.set(url.href, {
        collectionId: item.collection_id,
        title: item.title,
        url: url.href,
        category: typeof item.category === "string" ? item.category : null,
        videoCount: Number.isInteger(item.video_count) ? item.video_count as number : null,
      });
    } catch {
      // Ignore malformed public directory entries.
    }
  }
  return [...unique.values()];
}
