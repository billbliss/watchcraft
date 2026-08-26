import assert from "node:assert/strict";
import test from "node:test";
import {
  DesktopCatalogRepository,
  joinLocalPath,
  type DesktopLibraryLocation,
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

test("identifies the actual desktop page origin to the YouTube API", () => {
  const location: DesktopLibraryLocation = {
    selectedRoot: "/collection",
    collectionId: "youtube-pilot",
    manifestPath: "/collection/collection.json",
    metadataRoot: "/collection",
    mediaRoot: null,
    mediaExpected: 0,
    mediaFound: 0,
    mediaExtra: 0,
  };
  const repository = new DesktopCatalogRepository(location, "http://127.0.0.1:1420");
  const mediaUrl = repository.mediaUrl({
    item_id: "video",
    title: "YouTube lesson",
    media: [{ type: "youtube", video_id: "PjObX9XQvgI" }],
    transcript: {},
    analysis: { path: "analysis/video.json" },
    summary: "",
    locations: [],
    topic_ids: [],
    family_ids: [],
    topic_sections: {},
    chapter_count: 0,
  });

  assert.match(mediaUrl ?? "", /origin=http%3A%2F%2F127\.0\.0\.1%3A1420/);
});
