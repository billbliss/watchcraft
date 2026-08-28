import assert from "node:assert/strict";
import test from "node:test";
import {
  DesktopCatalogRepository,
  joinLocalPath,
  localMediaRoot,
  type DesktopLibraryLocation,
} from "./desktopCatalogRepository.ts";

const localLocation: DesktopLibraryLocation = {
  selectedRoot: "/user/course",
  collectionId: "mixed-media",
  manifestPath: "/private/collection.json",
  metadataRoot: "/private",
  mediaRoot: "/user/course",
  managedMediaRoot: "/private/managed-media",
  mediaExpected: 2,
  mediaFound: 2,
  mediaExtra: 0,
};

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

test("selects the correct local root for each delivery mode", () => {
  assert.equal(localMediaRoot(localLocation, "managed-local"), "/private/managed-media");
  assert.equal(localMediaRoot(localLocation, "referenced-local"), "/user/course");
  assert.equal(localMediaRoot(localLocation), "/user/course");
});

test("routes desktop YouTube playback through the HTTPS player bridge", () => {
  const location: DesktopLibraryLocation = {
    selectedRoot: "/collection",
    collectionId: "youtube-pilot",
    manifestPath: "/collection/collection.json",
    metadataRoot: "/collection",
    mediaRoot: null,
    managedMediaRoot: null,
    mediaExpected: 0,
    mediaFound: 0,
    mediaExtra: 0,
  };
  const repository = new DesktopCatalogRepository(
    location,
    "https://watchcraft.stream/youtube-player/",
  );
  const mediaUrl = repository.mediaUrl({
    item_id: "video",
    title: "YouTube lesson",
    media: [{ type: "youtube", video_id: "PjObX9XQvgI" }],
    analysis: { path: "analysis/video.json" },
    summary: "",
    locations: [],
    topic_ids: [],
    family_ids: [],
    topic_sections: {},
    chapter_count: 0,
  });

  assert.equal(
    mediaUrl,
    "https://watchcraft.stream/youtube-player/?video=PjObX9XQvgI",
  );
});
