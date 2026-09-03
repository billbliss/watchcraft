import assert from "node:assert/strict";
import test from "node:test";
import {
  isLegacyWebDemoUrl,
  readLastWebCollectionUrl,
  readWebCollections,
  removeWebCollection,
  saveWebCollection,
} from "./webCollectionRegistry.ts";

test("reads only absolute URLs for the most recently opened collection", () => {
  assert.equal(
    readLastWebCollectionUrl("https://example.com/course.json"),
    "https://example.com/course.json",
  );
  assert.equal(readLastWebCollectionUrl("/course.json"), null);
  assert.equal(readLastWebCollectionUrl("not a URL"), null);
  assert.equal(readLastWebCollectionUrl(null), null);
});

test("recognizes the retired bundled demo without hiding unrelated collections", () => {
  const appUrl = "https://watchcraft.stream/app/";

  assert.equal(
    isLegacyWebDemoUrl("https://watchcraft.stream/app/demo/collection.json", appUrl),
    true,
  );
  assert.equal(
    isLegacyWebDemoUrl("https://example.com/demo/collection.json", appUrl),
    false,
  );
});

test("reads only valid saved browser collections and de-duplicates URLs", () => {
  const collections = readWebCollections(JSON.stringify([
    { collectionId: "old", title: "Old title", url: "https://example.com/course.json" },
    { collectionId: "new", title: "New title", url: "https://example.com/course.json" },
    { title: "Incomplete", url: "https://example.com/incomplete.json" },
  ]));

  assert.deepEqual(collections, [
    { collectionId: "new", title: "New title", url: "https://example.com/course.json" },
  ]);
});

test("saving updates an existing URL and sorts collection titles", () => {
  const collections = saveWebCollection([
    { collectionId: "z", title: "Zulu", url: "https://example.com/z.json" },
    { collectionId: "a-old", title: "Archived", url: "https://example.com/a.json" },
  ], {
    collectionId: "a-new",
    title: "Alpha",
    url: "https://example.com/a.json",
  });

  assert.deepEqual(collections, [
    { collectionId: "a-new", title: "Alpha", url: "https://example.com/a.json" },
    { collectionId: "z", title: "Zulu", url: "https://example.com/z.json" },
  ]);
});

test("removing a collection leaves the other registrations intact", () => {
  const collections = removeWebCollection([
    { collectionId: "a", title: "Alpha", url: "https://example.com/a.json" },
    { collectionId: "b", title: "Beta", url: "https://example.com/b.json" },
  ], "https://example.com/a.json");

  assert.deepEqual(collections, [
    { collectionId: "b", title: "Beta", url: "https://example.com/b.json" },
  ]);
});
