import assert from "node:assert/strict";
import test from "node:test";
import {
  isAllowedPlayerCommand,
  isValidVideoId,
  youtubePlayerUrl,
} from "../site/youtube-player/player-bridge.mjs";

test("builds the nested YouTube URL with the HTTPS bridge as its origin", () => {
  assert.equal(
    youtubePlayerUrl("PjObX9XQvgI", "https://watchcraft.stream"),
    "https://www.youtube-nocookie.com/embed/PjObX9XQvgI?enablejsapi=1&origin=https%3A%2F%2Fwatchcraft.stream&playsinline=1&rel=0&widget_referrer=https%3A%2F%2Fwatchcraft.stream",
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
