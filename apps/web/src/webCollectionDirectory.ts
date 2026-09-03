import {
  PUBLIC_COLLECTION_DIRECTORY_URL,
  readPublicCollectionDirectory,
} from "@watchcraft/catalog-core";

export interface FeaturedWebCollection {
  collectionId: string;
  title: string;
  url: string;
  category: string | null;
  videoCount: number | null;
}

export const WEB_COLLECTION_DIRECTORY_URL =
  PUBLIC_COLLECTION_DIRECTORY_URL;

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
  return readPublicCollectionDirectory(value)
    .filter((collection) => collection.mediaModes.includes("remote"))
    .map(({ collectionId, title, url, category, videoCount }) => ({
      collectionId,
      title,
      url,
      category,
      videoCount,
    }));
}
