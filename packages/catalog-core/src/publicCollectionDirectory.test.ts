import assert from "node:assert/strict";
import test from "node:test";
import { readPublicCollectionDirectory } from "./index.ts";

test("reads installable public collections and preserves known media modes", () => {
  assert.deepEqual(readPublicCollectionDirectory({ collections: [
    {
      collection_id: "mixed",
      title: "Mixed collection",
      manifest_url: "https://example.com/mixed/collection.json",
      category: "Examples",
      video_count: 4,
      media_modes: ["remote", "referenced-local", "future-mode"],
    },
    {
      collection_id: "archived",
      title: "Archived collection",
      manifest_url: "https://example.com/archived/collection.json",
      media_modes: ["managed-local"],
      archived: true,
    },
    {
      collection_id: "insecure",
      title: "Insecure collection",
      manifest_url: "http://example.com/insecure/collection.json",
      media_modes: ["remote"],
    },
  ] }), [
    {
      collectionId: "mixed",
      title: "Mixed collection",
      url: "https://example.com/mixed/collection.json",
      category: "Examples",
      videoCount: 4,
      mediaModes: ["remote", "referenced-local"],
    },
  ]);
});
