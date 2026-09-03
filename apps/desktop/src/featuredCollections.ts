import {
  PUBLIC_COLLECTION_DIRECTORY_URL,
  readPublicCollectionDirectory,
  type PublicCollectionDirectoryEntry,
} from "@watchcraft/catalog-core";

export const FEATURED_COLLECTION_DIRECTORY_URL = PUBLIC_COLLECTION_DIRECTORY_URL;

export const FALLBACK_FEATURED_COLLECTIONS: PublicCollectionDirectoryEntry[] = [
  {
    collectionId: "essence-of-linear-algebra",
    title: "Essence of linear algebra",
    url: "https://collections.watchcraft.stream/collections/essence-of-linear-algebra/collection.json",
    category: "Mathematics",
    videoCount: 16,
    mediaModes: ["remote"],
  },
];

export function readFeaturedCollections(value: unknown): PublicCollectionDirectoryEntry[] {
  return readPublicCollectionDirectory(value);
}
