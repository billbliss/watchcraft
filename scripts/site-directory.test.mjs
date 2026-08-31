import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  collectionCategories,
  collectionDeepLink,
  collectionsInCategory,
  newestRelease,
  visibleCollections,
  withFallbackCategories,
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

test("lists and filters collection categories while ignoring archived entries", () => {
  const collections = [
    { collection_id: "guitar", category: "Music" },
    { collection_id: "cooking", category: "Cooking" },
    { collection_id: "archived", category: "Examples", archived: true },
    { collection_id: "legacy" },
  ];

  assert.deepEqual(collectionCategories(collections), ["Cooking", "Music"]);
  assert.deepEqual(
    collectionsInCategory(collections, "Music"),
    [{ collection_id: "guitar", category: "Music" }],
  );
  assert.deepEqual(
    collectionsInCategory(collections, ""),
    collections.slice(0, 2).concat(collections[3]),
  );
});

test("fills categories missing from an older directory without overriding published values", () => {
  const collections = [
    { collection_id: "legacy" },
    { collection_id: "published", category: "Published Category" },
    { collection_id: "unknown" },
  ];

  assert.deepEqual(
    withFallbackCategories(collections, {
      legacy: "Fallback Category",
      published: "Wrong Category",
    }),
    [
      { collection_id: "legacy", category: "Fallback Category" },
      { collection_id: "published", category: "Published Category" },
      { collection_id: "unknown" },
    ],
  );
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

test("describes platform signing accurately", () => {
  const page = readFileSync(new URL("../site/index.html", import.meta.url), "utf8");

  assert.match(page, /macOS beta is signed and notarized by Apple/);
  assert.match(page, /Windows builds are currently unsigned/);
  assert.doesNotMatch(page, /macOS Gatekeeper and Windows SmartScreen/);
});

test("publishes a screenshot gallery and social sharing metadata", () => {
  const page = readFileSync(new URL("../site/index.html", import.meta.url), "utf8");
  const app = readFileSync(new URL("../site/app.js", import.meta.url), "utf8");
  const gallery = readFileSync(new URL("../site/gallery.html", import.meta.url), "utf8");
  const workflow = readFileSync(
    new URL("../.github/workflows/pages.yml", import.meta.url),
    "utf8",
  );

  assert.match(page, /href="gallery\.html"/);
  assert.match(page, /property="og:image"/);
  assert.match(page, /name="twitter:card" content="summary_large_image"/);
  assert.match(page, /class="carousel-arrow previous"/);
  assert.match(page, /class="carousel-dots"/);
  assert.match(app, /function setupGalleryCarousel\(\)/);
  assert.match(gallery, /<h1>Gallery<\/h1>/);
  assert.match(gallery, /class="caption-divider"/);
  assert.doesNotMatch(gallery, /figure \+ figure/);
  assert.match(app, /track\.prepend\(lastClone\)/);
  assert.match(app, /track\.append\(firstClone\)/);
  assert.match(gallery, /watchcraft-premiere-pro-beginner-tutorial\.png/);
  assert.match(workflow, /cp -R site\/gallery _site\/gallery/);
});
