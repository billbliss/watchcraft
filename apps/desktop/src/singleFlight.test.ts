import assert from "node:assert/strict";
import test from "node:test";
import { singleFlight } from "./singleFlight.ts";

test("deduplicates only an active request and does not return stale results", async () => {
  const pending: Array<(value: string) => void> = [];
  let calls = 0;
  const restore = singleFlight(
    (selectedCollection: string) => new Promise<string>((resolve) => {
      calls += 1;
      pending.push(() => resolve(selectedCollection));
    }),
  );

  const first = restore("old collection");
  const duplicate = restore("ignored while restoring");
  assert.strictEqual(duplicate, first);
  assert.equal(calls, 1);

  pending.shift()?.("old collection");
  assert.equal(await first, "old collection");

  const replacement = restore("new collection");
  assert.notStrictEqual(replacement, first);
  assert.equal(calls, 2);
  pending.shift()?.("new collection");
  assert.equal(await replacement, "new collection");
});
