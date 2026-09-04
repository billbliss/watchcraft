import assert from "node:assert/strict";
import test from "node:test";

import { ConvexAuthoringControlClient, convexHttpUrl } from "./index.ts";

test("the control client derives the HTTP action URL from a production deployment URL", () => {
  assert.equal(
    convexHttpUrl("https://example-project-123.convex.cloud/"),
    "https://example-project-123.convex.site",
  );
  assert.throws(() => convexHttpUrl("https://dashboard.convex.dev/project"), /convex.cloud/);
});

test("the worker credential is sent only in the authorization header", async () => {
  let observedUrl = "";
  let observedInit: RequestInit | undefined;
  const fakeFetch: typeof fetch = async (input, init) => {
    observedUrl = String(input);
    observedInit = init;
    return new Response(JSON.stringify({
      job_id: "job-1",
      spec_sha256: "a".repeat(64),
      dispatch_generation: 1,
      revision: 5,
    }), { status: 200, headers: { "content-type": "application/json" } });
  };
  const client = new ConvexAuthoringControlClient(
    "https://example.convex.cloud",
    "private-worker-token",
    fakeFetch,
  );
  await client.prepareSmokeJob({
    job_id: "job-1",
    run_id: "run-1",
    command_prefix: "command",
    github_run_id: "123",
    github_run_url: "https://github.com/example/actions/runs/123",
  });

  assert.equal(observedUrl, "https://example.convex.site/authoring/smoke/prepare");
  assert.equal((observedInit?.headers as Record<string, string>).authorization, "Bearer private-worker-token");
  assert.doesNotMatch(String(observedInit?.body), /private-worker-token/);
});
