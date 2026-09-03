import assert from "node:assert/strict";
import test from "node:test";
import {
  FALLBACK_FEATURED_WEB_COLLECTIONS,
  readFeaturedWebCollections,
} from "./webCollectionDirectory.ts";

test("keeps only public web-video collections from the directory", () => {
  assert.deepEqual(readFeaturedWebCollections({ collections: [
    {
      collection_id: "web",
      title: "Web collection",
      manifest_url: "https://example.com/web/collection.json",
      category: "Examples",
      video_count: 3,
      media_modes: ["remote"],
    },
    {
      collection_id: "local",
      title: "Local collection",
      manifest_url: "https://example.com/local/collection.json",
      media_modes: ["managed-local"],
    },
    {
      collection_id: "archived",
      title: "Archived collection",
      manifest_url: "https://example.com/archived/collection.json",
      media_modes: ["remote"],
      archived: true,
    },
  ] }), [
    {
      collectionId: "web",
      title: "Web collection",
      url: "https://example.com/web/collection.json",
      category: "Examples",
      videoCount: 3,
    },
  ]);
});

test("retains linear algebra as the resilient featured fallback", () => {
  assert.deepEqual(FALLBACK_FEATURED_WEB_COLLECTIONS, [
    {
      collectionId: "essence-of-linear-algebra",
      title: "Essence of linear algebra",
      url: "https://collections.watchcraft.stream/collections/essence-of-linear-algebra/collection.json",
      category: "Mathematics",
      videoCount: 16,
    },
  ]);
});
