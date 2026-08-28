import assert from "node:assert/strict";
import test from "node:test";
import { collectionUrlFromDeepLink } from "./deepLink.ts";

const collectionUrl = "https://example.com/courses/collection.json";

test("accepts stable, beta, and development collection install links", () => {
  for (const scheme of ["watchcraft", "watchcraft-beta", "watchcraft-dev", "watchcraft-smoke"]) {
    assert.equal(
      collectionUrlFromDeepLink(`${scheme}://install?url=${encodeURIComponent(collectionUrl)}`),
      collectionUrl,
    );
  }
});

test("rejects malformed commands and insecure collection URLs", () => {
  assert.equal(collectionUrlFromDeepLink("watchcraft://open?url=https://example.com/collection.json"), null);
  assert.equal(collectionUrlFromDeepLink("watchcraft://install/extra?url=https://example.com/collection.json"), null);
  assert.equal(collectionUrlFromDeepLink("watchcraft://install?url=http://example.com/collection.json"), null);
  assert.equal(collectionUrlFromDeepLink("watchcraft://install?url=https://user:secret@example.com/collection.json"), null);
  assert.equal(collectionUrlFromDeepLink("other-app://install?url=https://example.com/collection.json"), null);
});
