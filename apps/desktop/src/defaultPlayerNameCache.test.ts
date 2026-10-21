import assert from "node:assert/strict";
import test from "node:test";
import { DefaultPlayerNameCache } from "./defaultPlayerNameCache.ts";

test("rapid navigation among videos of the same type shares one OS lookup", async () => {
  let complete!: (name: string) => void;
  let calls = 0;
  const cache = new DefaultPlayerNameCache();
  const load = () => { calls++; return new Promise<string>(resolve => { complete = resolve; }); };
  const first = cache.get("mp4", load);
  const second = cache.get("MP4", load);
  assert.equal(first, second);
  await Promise.resolve();
  assert.equal(calls, 1);
  complete("IINA");
  assert.equal(await first, "IINA");
  assert.equal(await cache.get("mp4", load), "IINA");
  assert.equal(calls, 1);
});

test("different types and changed OS associations get fresh lookups", async () => {
  let time = 0;
  const cache = new DefaultPlayerNameCache(() => time);
  assert.equal(await cache.get("mp4", async () => "IINA"), "IINA");
  assert.equal(await cache.get("mov", async () => "QuickTime"), "QuickTime");
  time = 30_001;
  assert.equal(await cache.get("mp4", async () => "VLC"), "VLC");
});

test("missing associations are cached briefly and transient failures can retry", async () => {
  const cache = new DefaultPlayerNameCache();
  assert.equal(await cache.get("mp4", async () => null), null);
  assert.equal(await cache.get("mp4", async () => { throw new Error("should use cache"); }), null);
  await assert.rejects(cache.get("mov", async () => { throw new Error("drive unavailable"); }));
  assert.equal(await cache.get("mov", async () => "IINA"), "IINA");
});
