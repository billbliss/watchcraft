import assert from "node:assert/strict";
import test from "node:test";
import { joinLocalPath } from "./desktopCatalogRepository.ts";

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
