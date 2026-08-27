import assert from "node:assert/strict";
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
