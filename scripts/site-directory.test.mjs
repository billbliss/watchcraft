import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  collectionBrowseCopy,
  collectionCategories,
  collectionDeepLink,
  collectionSupportsWeb,
  collectionWebLink,
  collectionsInCategory,
  developerInfoEnabled,
  newestRelease,
  videoCountLabel,
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

test("describes the number of visible featured collections", () => {
  const collections = [
    { collection_id: "one" },
    { collection_id: "two" },
    { collection_id: "archived", archived: true },
  ];

  assert.equal(
    collectionBrowseCopy(collections),
    "Browse 2 featured collections below, or open any compatible collection by URL.",
  );
  assert.equal(
    collectionBrowseCopy([{ collection_id: "one" }]),
    "Browse 1 featured collection below, or open any compatible collection by URL.",
  );
});

test("shows developer information only when the debug parameter is present", () => {
  assert.equal(developerInfoEnabled(""), false);
  assert.equal(developerInfoEnabled("?category=Music"), false);
  assert.equal(developerInfoEnabled("?debug"), true);
  assert.equal(developerInfoEnabled("?debug=1"), true);
});

test("formats directory video counts", () => {
  assert.equal(videoCountLabel(1), "1 video");
  assert.equal(videoCountLabel(12), "12 videos");
  assert.equal(videoCountLabel(undefined), "Video count unavailable");
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

test("builds browser links only for collections with web video", () => {
  const manifestUrl = "https://example.com/courses/collection.json";

  assert.equal(collectionSupportsWeb({ media_modes: ["remote"] }), true);
  assert.equal(collectionSupportsWeb({ media_modes: ["managed-local"] }), false);
  assert.equal(collectionSupportsWeb({}), false);
  assert.equal(
    collectionWebLink(manifestUrl),
    `https://watchcraft.stream/app/?catalog=${encodeURIComponent(manifestUrl)}`,
  );
});

test("loads the public directory from the blocker-resistant endpoint", () => {
  const app = readFileSync(new URL("../site/app.js", import.meta.url), "utf8");

  assert.match(app, /https:\/\/collections\.watchcraft\.stream\/directory\.json/);
  assert.doesNotMatch(app, /collections\.watchcraft\.stream\/collections\.json/);
  assert.match(app, /developerInfoEnabled\(window\.location\.search\)/);
  assert.match(app, /videoCountLabel\(collection\.video_count\)/);
  assert.match(app, /collectionWebLink\(collection\.manifest_url\)/);
  assert.match(app, /Continue in Watchcraft/);
  assert.match(app, /remote: "Web Video"/);
  assert.doesNotMatch(app, /Remote media/);
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
  assert.match(workflow, /npm run build --workspace @watchcraft\/web/);
  assert.match(workflow, /cp -R apps\/web\/dist _site\/app/);
});

test("links the public homepage to the web reader and desktop downloads", () => {
  const page = readFileSync(new URL("../site/index.html", import.meta.url), "utf8");

  assert.match(page, /data-web-app-link href="app\/"/);
  assert.match(page, /Get the desktop app/);
  assert.match(page, /Web-video collections can open in your browser/);
});
