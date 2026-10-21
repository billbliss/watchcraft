import assert from "node:assert/strict";
import test from "node:test";
import { youtubeDuration } from "./playback.ts";

test("reads only positive finite duration from YouTube information events", () => {
  assert.equal(youtubeDuration(JSON.stringify({ event: "initialDelivery", info: { duration: 900 } })), 900);
  for (const duration of [0, -1, null, "900", Infinity, NaN]) {
    assert.equal(youtubeDuration({ event: "infoDelivery", info: { duration } }), null);
  }
  assert.equal(youtubeDuration({ event: "untrusted", info: { duration: 900 } }), null);
  assert.equal(youtubeDuration("invalid JSON"), null);
});
