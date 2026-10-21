import assert from "node:assert/strict";
import test from "node:test";
import {
  isAllowedPlayerCommand,
  isValidVideoId,
  youtubePlayerFrameUrl,
  youtubePlayerUrl,
} from "../site/youtube-player/player-bridge.mjs";

test("builds the nested YouTube URL with the HTTPS bridge as its origin", () => {
  assert.equal(
    youtubePlayerUrl("PjObX9XQvgI", "https://watchcraft.stream"),
    "https://www.youtube-nocookie.com/embed/PjObX9XQvgI?enablejsapi=1&origin=https%3A%2F%2Fwatchcraft.stream&playsinline=1&rel=0&widget_referrer=https%3A%2F%2Fwatchcraft.stream",
  );
});

test("stages the YouTube player through the HTTPS bridge origin", () => {
  assert.equal(
    youtubePlayerFrameUrl(
      "PjObX9XQvgI",
      "https://watchcraft.stream/youtube-player/?video=PjObX9XQvgI",
    ),
    "https://watchcraft.stream/youtube-player/player-frame.html?video=PjObX9XQvgI",
  );
});

test("accepts YouTube IDs and only the player commands Watchcraft uses", () => {
  assert.equal(isValidVideoId("PjObX9XQvgI"), true);
  assert.equal(isValidVideoId("not a video id"), false);
  assert.equal(
    isAllowedPlayerCommand({ event: "command", func: "seekTo", args: [42, true] }),
    true,
  );
  assert.equal(
    isAllowedPlayerCommand({ event: "command", func: "loadVideoByUrl", args: [] }),
    false,
  );
});

test("permits the readiness handshake needed to receive YouTube duration", () => {
  assert.equal(isAllowedPlayerCommand({ event: "listening", id: "watchcraft" }), true);
  assert.equal(isAllowedPlayerCommand({ event: "command", func: "loadVideoByUrl" }), false);
  assert.equal(isAllowedPlayerCommand({ event: "infoDelivery" }), false);
});

test("desktop bridge forwards listening and returns duration only from its YouTube frame", async () => {
  const { JSDOM } = await import("jsdom");
  const { startBridge, youtubeOrigin } = await import("../site/youtube-player/player-bridge.mjs");
  const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "https://watchcraft.stream/youtube-player/?video=Yeb7zft_79k" });
  const previousWindow = globalThis.window;
  const previousDocument = globalThis.document;
  globalThis.window = dom.window;
  globalThis.document = dom.window.document;
  const returned = [];
  const parent = { postMessage: (...args) => returned.push(args) };
  Object.defineProperty(dom.window, "parent", { value: parent });
  try {
    startBridge();
    const frame = dom.window.document.querySelector("iframe");
    const forwarded = [];
    frame.contentWindow.postMessage = (...args) => forwarded.push(args);
    dom.window.dispatchEvent(new dom.window.MessageEvent("message", { source: parent, data: JSON.stringify({ event: "listening", id: "watchcraft" }) }));
    assert.deepEqual(forwarded, [[JSON.stringify({ event: "listening", id: "watchcraft" }), youtubeOrigin]]);
    const data = JSON.stringify({ event: "infoDelivery", info: { duration: 900 } });
    dom.window.dispatchEvent(new dom.window.MessageEvent("message", { source: frame.contentWindow, origin: "https://untrusted.example", data }));
    assert.equal(returned.length, 0);
    dom.window.dispatchEvent(new dom.window.MessageEvent("message", { source: frame.contentWindow, origin: youtubeOrigin, data }));
    assert.deepEqual(returned, [[data, "*"]]);
  } finally {
    dom.window.close();
    globalThis.window = previousWindow;
    globalThis.document = previousDocument;
  }
});
