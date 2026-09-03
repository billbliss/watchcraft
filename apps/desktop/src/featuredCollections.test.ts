import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  FALLBACK_FEATURED_COLLECTIONS,
  FEATURED_COLLECTION_DIRECTORY_URL,
  readFeaturedCollections,
} from "./featuredCollections.ts";

test("desktop featured collections include every supported media mode", () => {
  const featured = readFeaturedCollections({ collections: [
    {
      collection_id: "managed",
      title: "Managed collection",
      manifest_url: "https://example.com/managed/collection.json",
      media_modes: ["managed-local"],
    },
    {
      collection_id: "web",
      title: "Web collection",
      manifest_url: "https://example.com/web/collection.json",
      media_modes: ["remote"],
    },
  ] });

  assert.deepEqual(featured.map((collection) => collection.mediaModes), [
    ["managed-local"],
    ["remote"],
  ]);
});

test("desktop featured collections have a resilient starter fallback", () => {
  assert.equal(FEATURED_COLLECTION_DIRECTORY_URL, "https://collections.watchcraft.stream/directory.json");
  assert.equal(FALLBACK_FEATURED_COLLECTIONS[0]?.title, "Essence of linear algebra");
});

test("desktop content security policy permits the public directory origin", () => {
  const config = JSON.parse(readFileSync(
    new URL("../src-tauri/tauri.conf.json", import.meta.url),
    "utf8",
  )) as { app: { security: { csp: { "connect-src": string }; devCsp: { "connect-src": string } } } };

  assert.match(config.app.security.csp["connect-src"], /https:\/\/collections\.watchcraft\.stream/);
  assert.match(config.app.security.devCsp["connect-src"], /https:\/\/collections\.watchcraft\.stream/);
});
