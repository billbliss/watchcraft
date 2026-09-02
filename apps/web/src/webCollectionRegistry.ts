export interface SavedWebCollection {
  collectionId: string;
  title: string;
  url: string;
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

export function readWebCollections(raw: string | null): SavedWebCollection[] {
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
      unique.set(item.url, {
        collectionId: item.collectionId,
        title: item.title,
        url: item.url,
      });
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
  const next = collections.filter((candidate) => candidate.url !== collection.url);
  next.push(collection);
  return next.sort((left, right) => left.title.localeCompare(right.title, undefined, {
    sensitivity: "base",
  }));
}

export function removeWebCollection(
  collections: SavedWebCollection[],
  url: string,
): SavedWebCollection[] {
  return collections.filter((collection) => collection.url !== url);
}
