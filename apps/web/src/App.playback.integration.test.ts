import assert from "node:assert/strict";
import { after, afterEach, test } from "node:test";
import { createElement } from "react";
import { JSDOM } from "jsdom";
import type { CatalogRepository, CollectionManifest, VideoAnalysis } from "@watchcraft/catalog-core";
import { App } from "./App.tsx";

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "https://watchcraft.example/" });
for (const [key, value] of Object.entries({ window: dom.window, document: dom.window.document,
  localStorage: dom.window.localStorage, navigator: dom.window.navigator, HTMLElement: dom.window.HTMLElement,
  HTMLMediaElement: dom.window.HTMLMediaElement, MediaError: { MEDIA_ERR_ABORTED: 1 }, IS_REACT_ACT_ENVIRONMENT: true })) {
  Object.defineProperty(globalThis, key, { configurable: true, value, writable: true });
}
const { act, cleanup, fireEvent, render, waitFor } = await import("@testing-library/react");
Object.defineProperty(dom.window.HTMLMediaElement.prototype, "play", { configurable: true, value: () => Promise.resolve() });
Object.defineProperty(dom.window.HTMLMediaElement.prototype, "load", { configurable: true, value: () => undefined });
afterEach(() => { cleanup(); localStorage.clear(); dom.window.history.replaceState(null, "", "/"); });
after(() => dom.window.close());

const analysis: VideoAnalysis = { schema_version: 2, video: "Yeb7zft_79k.youtube", title: "Under the Hood", summary: "", topics: [],
  sections: [{ title: "Hood release and initial safety", start: "00:27:06", end: "01:04:00", concepts: [], description: "Safety" },
    { title: "Wrap-up", start: "14:24:00", end: "14:59:00", concepts: [], description: "Finish" }] };
function repository(youtube: boolean): CatalogRepository {
  const item = { item_id: "video", title: "Under the Hood", media: youtube ? [{ type: "youtube", video_id: "Yeb7zft_79k" }] : [{ type: "local-file", relative_path: "lesson.mp4", delivery: "referenced-local" }],
    analysis: { path: "analysis.json" }, summary: "", locations: [], topic_ids: [], family_ids: [], topic_sections: {}, chapter_count: 2 };
  const manifest = { kind: "watchcraft.collection", schema_version: 4, title: "Mechanics", collection_id: "mechanics", revision: 1, content_hash: "test", topic_scope: "collection",
    root: { type: "group", group_id: "root", title: "Mechanics", children: [{ type: "video", item_id: "video" }] }, topics: {}, topic_families: {}, items: { video: item }, stats: { video_count: 1, topic_count: 0, topic_family_count: 0 } } as CollectionManifest;
  return { manifestLocation: "collection.json", loadCollection: async () => manifest, loadAnalysis: async () => analysis,
    mediaUrl: () => youtube ? "https://www.youtube-nocookie.com/embed/Yeb7zft_79k?enablejsapi=1" : "stream://localhost/lesson.mp4",
    openInDefaultPlayer: async () => true, openExternalMedia: async () => true };
}

test("YouTube chapter seeks wait for trusted duration and correct the reported MM:SS:ff timestamps", async () => {
  const view = render(createElement(App, { repository: repository(true) }));
  const chapter = await view.findByRole("button", { name: /Hood release and initial safety/ });
  const frame = view.container.querySelector("iframe")!;
  const commands: string[] = [];
  frame.contentWindow!.postMessage = (data: unknown) => { commands.push(String(data)); };
  fireEvent.click(chapter);
  assert.equal(commands.length, 0);
  const deliver = (origin: string, source: Window | null) => fireEvent(dom.window, new dom.window.MessageEvent("message", {
    origin, source, data: JSON.stringify({ event: "infoDelivery", info: { duration: 900 } }),
  }));
  deliver("https://untrusted.example", frame.contentWindow);
  deliver("https://www.youtube-nocookie.com", dom.window);
  assert.equal(commands.length, 0);
  deliver("https://www.youtube-nocookie.com", frame.contentWindow);
  await waitFor(() => assert.ok(commands.some(data => JSON.parse(data).func === "seekTo")));
  assert.deepEqual(JSON.parse(commands.find(data => JSON.parse(data).func === "seekTo")!).args, [27.06, true]);
  assert.equal(view.queryByRole("button", { name: /YouTube/ }), null);
  assert.equal(view.container.querySelector(".player-footer"), null);
});

test("local chapter requests before metadata keep only the latest requested chapter", async () => {
  const view = render(createElement(App, { repository: repository(false) }));
  fireEvent.click(await view.findByRole("button", { name: /Hood release and initial safety/ }));
  fireEvent.click(view.getByRole("button", { name: /Wrap-up/ }));
  const video = view.container.querySelector("video")!;
  Object.defineProperty(video, "duration", { configurable: true, value: 900 });
  Object.defineProperty(video, "readyState", { configurable: true, value: 1 });
  fireEvent.loadedMetadata(video);
  await waitFor(() => assert.equal(video.currentTime, 864));
  fireEvent.click(view.getByRole("button", { name: /Hood release and initial safety/ }));
  assert.equal(video.currentTime, 27.06);
  assert.ok(view.getByRole("button", { name: /Open video|Open in default player/ }));
});

test("a playback failure can inspect only the selected file and explain a disconnected drive", async () => {
  const repo = repository(false);
  let inspected = 0;
  repo.inspectMedia = async item => {
    inspected++;
    assert.equal(item.item_id, "video");
    return { status: "folder-unavailable", message: "Reconnect the drive, then retry.", path: "/Volumes/Drive/lesson.mp4" };
  };
  const view = render(createElement(App, { repository: repo, onOpenSettings: () => undefined }));
  await view.findByRole("button", { name: /Hood release/ });
  assert.equal(inspected, 0);
  const video = view.container.querySelector("video")!;
  fireEvent.error(video);
  assert.ok(view.getByText("Video playback interrupted. Retrying…"));
  await act(async () => fireEvent.click(view.getByRole("button", { name: "Check video file" })));
  assert.equal(inspected, 1);
  assert.ok(view.getByText("Reconnect the drive, then retry."));
  assert.ok(view.getByRole("button", { name: "Video folder settings" }));
  assert.ok(view.getByText("/Volumes/Drive/lesson.mp4"));
  fireEvent.canPlay(video);
  assert.equal(view.queryByRole("button", { name: "Check video file" }), null);
});

test("a scheduled retry is cancelled after playback recovers", async () => {
  const view = render(createElement(App, { repository: repository(false) }));
  await view.findByRole("button", { name: /Hood release/ });
  const video = view.container.querySelector("video")!;
  const schedule = dom.window.setTimeout;
  const cancel = dom.window.clearTimeout;
  const cancelled: number[] = [];
  dom.window.setTimeout = (() => 42) as typeof dom.window.setTimeout;
  dom.window.clearTimeout = id => { if (id !== undefined) cancelled.push(id); };
  try {
    fireEvent.error(video);
    fireEvent.canPlay(video);
    assert.ok(cancelled.includes(42));
    assert.equal(view.queryByText("Video playback interrupted. Retrying…"), null);
  } finally {
    dom.window.setTimeout = schedule;
    dom.window.clearTimeout = cancel;
  }
});
