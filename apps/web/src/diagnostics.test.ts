import assert from "node:assert/strict";
import test from "node:test";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>", {
  url: "https://watchcraft.example/app/",
});
for (const [key, value] of Object.entries({
  window: dom.window,
  navigator: dom.window.navigator,
  localStorage: dom.window.localStorage,
})) {
  Object.defineProperty(globalThis, key, { configurable: true, value, writable: true });
}

const {
  formatDiagnosticEntry,
  readablePercentEscapes,
  WebDiagnosticsService,
} = await import("./diagnostics.ts");

test("formats URL escapes readably without creating forged log lines", () => {
  assert.equal(
    readablePercentEscapes("Video%20Catalog%2FLesson%20%231%25.mp4"),
    "Video Catalog/Lesson #1%.mp4",
  );
  assert.equal(readablePercentEscapes("caf%C3%A9%0Aerror"), "café\\nerror");
  assert.equal(readablePercentEscapes("nested%2520catalog"), "nested catalog");
  assert.equal(readablePercentEscapes("invalid%E2%80"), "invalid%E2%80");
});

test("web diagnostics persist browser events and can be cleared", async () => {
  localStorage.clear();
  const diagnostics = new WebDiagnosticsService();
  diagnostics.record({
    level: "error",
    category: "playback",
    event: "media.error",
    message: "Codec unsupported",
    fields: { mediaErrorCode: 4 },
  });

  const restored = new WebDiagnosticsService();
  const snapshot = await restored.snapshot();
  assert.equal(snapshot.enabled, true);
  assert.equal(snapshot.entries.some((entry) => entry.message === "Codec unsupported"), true);
  assert.match(formatDiagnosticEntry(snapshot.entries.at(-2)!), /ERROR \[playback\] media\.error/);

  await restored.clear();
  assert.deepEqual((await restored.snapshot()).entries, []);
  assert.equal(localStorage.getItem("watchcraftDiagnostics"), null);
});
