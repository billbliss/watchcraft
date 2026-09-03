import assert from "node:assert/strict";
import test from "node:test";
import { DEFAULT_WEB_COLLECTION_URL } from "./catalog/httpCatalogRepository.ts";

test("defaults to the published Essence of linear algebra web-video collection", () => {
  assert.equal(
    DEFAULT_WEB_COLLECTION_URL,
    "https://collections.watchcraft.stream/collections/essence-of-linear-algebra/collection.json",
  );
});
