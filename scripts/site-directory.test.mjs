import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  collectionDeepLink,
  newestRelease,
  visibleCollections,
} from "../site/directory.mjs";

test("selects the newest published release instead of trusting API order", () => {
  const releases = [
    { tag_name: "v0.1.0-beta.9", draft: false, prerelease: true, published_at: "2026-08-28T01:21:41Z" },
    { tag_name: "v0.1.0-beta.10", draft: false, prerelease: true, published_at: "2026-08-28T03:33:59Z" },
    { tag_name: "v0.1.0", draft: false, prerelease: false, published_at: "2026-08-27T01:00:00Z" },
  ];

  assert.equal(newestRelease(releases, true)?.tag_name, "v0.1.0-beta.10");
  assert.equal(newestRelease(releases, false)?.tag_name, "v0.1.0");
});

test("omits archived collections from the public directory", () => {
  const collections = [
    { collection_id: "hello", archived: true },
    { collection_id: "course" },
  ];

  assert.deepEqual(visibleCollections(collections), [{ collection_id: "course" }]);
});

test("builds stable public collection install links", () => {
  const manifestUrl = "https://example.com/courses/collection.json";
  const encoded = "https%3A%2F%2Fexample.com%2Fcourses%2Fcollection.json";

  assert.equal(
    collectionDeepLink(manifestUrl),
    `watchcraft://install?url=${encoded}`,
  );
});

test("loads the public directory from the blocker-resistant endpoint", () => {
  const app = readFileSync(new URL("../site/app.js", import.meta.url), "utf8");

  assert.match(app, /https:\/\/collections\.watchcraft\.stream\/directory\.json/);
  assert.doesNotMatch(app, /collections\.watchcraft\.stream\/collections\.json/);
});
