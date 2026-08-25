import assert from "node:assert/strict";
import test from "node:test";
import {
  isCatalogMetadataFolder,
  joinLocalPath,
  localPathName,
  parentLocalPath,
} from "./desktopCatalogRepository.ts";

test("joins portable catalog paths on macOS", () => {
  assert.equal(
    joinLocalPath("/Users/example/Courses", "Part 1/video.mp4"),
    "/Users/example/Courses/Part 1/video.mp4",
  );
});

test("joins portable catalog paths on Windows", () => {
  assert.equal(
    joinLocalPath("C:\\Courses", "Part 1/video.mp4"),
    "C:\\Courses\\Part 1\\video.mp4",
  );
});

test("finds the manifest parent on both path styles", () => {
  assert.equal(
    parentLocalPath("/Courses/Video Catalog/collection.json"),
    "/Courses/Video Catalog",
  );
  assert.equal(
    parentLocalPath("C:\\Courses\\Video Catalog\\collection.json"),
    "C:\\Courses\\Video Catalog",
  );
});

test("recognizes a selected catalog metadata folder on both path styles", () => {
  assert.equal(localPathName("/Courses/Video Catalog/"), "Video Catalog");
  assert.equal(localPathName("C:\\Courses\\Video Catalog\\"), "Video Catalog");
  assert.equal(isCatalogMetadataFolder("/Courses/Video Catalog"), true);
  assert.equal(isCatalogMetadataFolder("C:\\Courses\\video catalog\\"), true);
  assert.equal(isCatalogMetadataFolder("/Courses"), false);
});
