import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { displayCollectionSource } from "./collectionSource.ts";

function collection(sourceType: "folder" | "url", sourceLabel: string) {
  return { sourceType, sourceLabel };
}

test("hides the Windows extended-length prefix from local folder labels", () => {
  assert.equal(
    displayCollectionSource(collection("folder", String.raw`\\?\C:\Users\Bill\Courses`)),
    String.raw`C:\Users\Bill\Courses`,
  );
});

test("renders extended UNC paths as ordinary UNC paths", () => {
  assert.equal(
    displayCollectionSource(collection("folder", String.raw`\\?\UNC\server\share\Courses`)),
    String.raw`\\server\share\Courses`,
  );
});

test("does not alter URLs or ordinary folder paths", () => {
  assert.equal(
    displayCollectionSource(collection("url", "https://example.com/course.watchcraft")),
    "https://example.com/course.watchcraft",
  );
  assert.equal(
    displayCollectionSource(collection("folder", String.raw`C:\Users\Bill\Courses`)),
    String.raw`C:\Users\Bill\Courses`,
  );
});

test("labels remote delivery as Web Video in Settings", () => {
  const settings = readFileSync(
    new URL("./CollectionSettings.tsx", import.meta.url),
    "utf8",
  );

  assert.match(settings, /remote: "Web Video"/);
  assert.doesNotMatch(settings, /Remote media/);
});
