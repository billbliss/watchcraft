import { upsertCollectionRegistration } from "@watchcraft/catalog-core";

export interface SavedWebCollection {
  collectionId: string;
  title: string;
  url: string;
  revision?: number | null;
  contentHash?: string | null;
}

export const WEB_COLLECTIONS_KEY = "watchcraft.web.collections.v1";
export const WEB_LAST_COLLECTION_KEY = "watchcraft.web.lastCollection.v1";

export function readLastWebCollectionUrl(raw: string | null): string | null {
  const url = raw?.trim();
  if (!url) return null;
  try {
    return new URL(url).href;
  } catch {
    return null;
  }
}

export function isLegacyWebDemoUrl(rawUrl: string, appUrl: string): boolean {
  try {
    const url = new URL(rawUrl).href;
    return url === new URL("/demo/collection.json", appUrl).href
      || url === new URL("demo/collection.json", appUrl).href;
  } catch {
    return false;
  }
}

export function readWebCollections(
  raw: string | null,
  preferredUrl: string | null = null,
): SavedWebCollection[] {
  if (!raw) return [];
  try {
    const value: unknown = JSON.parse(raw);
    if (!Array.isArray(value)) return [];
    const unique = new Map<string, SavedWebCollection>();
    for (const candidate of value) {
      if (!candidate || typeof candidate !== "object") continue;
      const item = candidate as Partial<SavedWebCollection>;
      if (
        typeof item.collectionId !== "string"
        || typeof item.title !== "string"
        || typeof item.url !== "string"
      ) continue;
      const collection = {
        collectionId: item.collectionId,
        title: item.title,
        url: item.url,
        revision: Number.isInteger(item.revision) && Number(item.revision) > 0
          ? Number(item.revision)
          : null,
        contentHash: typeof item.contentHash === "string"
          && /^[a-f0-9]{64}$/.test(item.contentHash)
          ? item.contentHash
          : null,
      };
      if (!unique.has(collection.collectionId) || collection.url === preferredUrl) {
        unique.set(collection.collectionId, collection);
      }
    }
    return [...unique.values()];
  } catch {
    return [];
  }
}

export function saveWebCollection(
  collections: SavedWebCollection[],
  collection: SavedWebCollection,
): SavedWebCollection[] {
  const next = upsertCollectionRegistration(collections, collection);
  return next.sort((left, right) => left.title.localeCompare(right.title, undefined, {
    sensitivity: "base",
  }));
}

export function removeWebCollection(
  collections: SavedWebCollection[],
  collectionId: string,
): SavedWebCollection[] {
  return collections.filter((collection) => collection.collectionId !== collectionId);
}
