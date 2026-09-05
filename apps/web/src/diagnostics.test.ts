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

const { formatDiagnosticEntry, WebDiagnosticsService } = await import("./diagnostics.ts");

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
