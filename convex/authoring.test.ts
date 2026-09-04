/// <reference types="vite/client" />

import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { convexTest } from "convex-test";

import {
  artifactKey,
  sha256Hex,
  syntheticTranscriptJobSpec,
} from "../packages/authoring-pipeline/src/index.ts";
import { internal } from "./_generated/api";
import schema from "./schema.ts";

const modules = import.meta.glob([
  "./**/*.{ts,js}",
  "!./**/*.test.ts",
  "!./vitest.config.mts",
]);
const workerToken = "test-worker-token-that-is-not-a-production-secret";

beforeEach(() => {
  vi.stubEnv("AUTHORING_WORKER_TOKEN_SHA256", sha256Hex(workerToken));
});

afterEach(() => {
  vi.unstubAllEnvs();
});

async function post(t: ReturnType<typeof convexTest>, path: string, body: unknown, token = workerToken) {
  return t.fetch(path, {
    method: "POST",
    headers: {
      authorization: `Bearer ${token}`,
      "content-type": "application/json",
    },
    body: JSON.stringify(body),
  });
}

test("worker endpoints reject missing or incorrect credentials", async () => {
  const t = convexTest(schema, modules);
  const response = await post(t, "/authoring/smoke/prepare", {}, "wrong-token");
  expect(response.status).toBe(401);
  await expect(response.json()).resolves.toEqual({ error: "Unauthorized." });
});

test("the persisted smoke lifecycle is transactional and command-idempotent", async () => {
  const t = convexTest(schema, modules);
  const prepareBody = {
    job_id: "job-1",
    run_id: "run-1",
    command_prefix: "prepare-1",
    github_run_id: "123",
    github_run_url: "https://github.com/billbliss/watchcraft/actions/runs/123",
  };
  const preparedResponse = await post(t, "/authoring/smoke/prepare", prepareBody);
  expect(preparedResponse.status).toBe(200);
  const prepared = await preparedResponse.json() as {
    job_id: string;
    spec_sha256: string;
    dispatch_generation: number;
    revision: number;
  };
  expect(prepared).toMatchObject({ job_id: "job-1", dispatch_generation: 1, revision: 5 });

  const claimBody = {
    job_id: "job-1",
    command_id: "attempt-1:claim",
    expected_revision: prepared.revision,
    attempt_id: "attempt-1",
    owner: "github-actions:123",
    spec_sha256: prepared.spec_sha256,
    dispatch_generation: prepared.dispatch_generation,
    lease_duration_ms: 60_000,
    github_run_id: "123",
  };
  const firstClaim = await post(t, "/authoring/jobs/claim", claimBody);
  expect(firstClaim.status).toBe(200);
  const claimed = await firstClaim.json() as any;
  expect(claimed).toMatchObject({ state: "claimed", revision: 6 });

  const duplicateClaim = await post(t, "/authoring/jobs/claim", claimBody);
  expect(duplicateClaim.status).toBe(200);
  expect(await duplicateClaim.json()).toEqual(claimed);

  const startedResponse = await post(t, "/authoring/jobs/start", {
    job_id: "job-1",
    command_id: "attempt-1:start",
    expected_revision: claimed.revision,
    attempt_id: "attempt-1",
  });
  expect(startedResponse.status).toBe(200);
  const started = await startedResponse.json() as any;

  const digest = "a".repeat(64);
  const artifact = {
    store: "r2",
    algorithm: "sha256",
    digest,
    byte_length: 100,
    media_type: "application/json",
    artifact_kind: "transcript",
    schema: { id: "watchcraft.transcript", version: 1 },
    key: artifactKey(digest),
  };
  const completionBody = {
    job_id: "job-1",
    command_id: "attempt-1:succeed",
    expected_revision: started.revision,
    attempt_id: "attempt-1",
    artifact,
  };
  const completedResponse = await post(t, "/authoring/jobs/succeed", completionBody);
  expect(completedResponse.status).toBe(200);
  const completed = await completedResponse.json() as any;
  expect(completed).toMatchObject({ state: "succeeded", revision: 8, result: artifact });

  const duplicateCompletion = await post(t, "/authoring/jobs/succeed", completionBody);
  expect(duplicateCompletion.status).toBe(200);
  expect(await duplicateCompletion.json()).toEqual(completed);

  const snapshot = await t.run(async (ctx) => ({
    jobs: await ctx.db.query("authoring_jobs").collect(),
    events: await ctx.db.query("authoring_job_events").collect(),
  }));
  expect(snapshot.jobs).toHaveLength(1);
  expect(snapshot.events).toHaveLength(8);
  expect(snapshot.jobs[0]?.aggregate).toEqual(completed);
});

test("generic control mutations persist a retryable failure, retry, and cancellation", async () => {
  const t = convexTest(schema, modules);
  const created = await t.mutation(internal.authoringInternal.createJob, {
    job_id: "job-generic",
    run_id: "run-generic",
    command_id: "create",
    spec: syntheticTranscriptJobSpec(),
  }) as any;
  expect(created).toMatchObject({ state: "proposed", revision: 1 });

  const duplicateCreate = await t.mutation(internal.authoringInternal.createJob, {
    job_id: "job-generic",
    run_id: "run-generic",
    command_id: "create",
    spec: syntheticTranscriptJobSpec(),
  });
  expect(duplicateCreate).toEqual(created);

  const awaitingApproval = await t.mutation(internal.authoringInternal.requestApproval, {
    job_id: created.job_id,
    command_id: "request-approval",
    expected_revision: created.revision,
  }) as any;
  const ready = await t.mutation(internal.authoringInternal.approveJob, {
    job_id: created.job_id,
    command_id: "approve",
    expected_revision: awaitingApproval.revision,
    actor: "operator",
    spec_sha256: created.spec_sha256,
  }) as any;
  const dispatchPending = await t.mutation(internal.authoringInternal.requestDispatch, {
    job_id: created.job_id,
    command_id: "request-dispatch",
    expected_revision: ready.revision,
  }) as any;
  const dispatched = await t.mutation(internal.authoringInternal.recordDispatch, {
    job_id: created.job_id,
    command_id: "record-dispatch",
    expected_revision: dispatchPending.revision,
    generation: 1,
    github_run_id: "456",
    github_run_url: "https://github.com/billbliss/watchcraft/actions/runs/456",
  }) as any;
  const claimed = await t.mutation(internal.authoringInternal.claimJob, {
    job_id: created.job_id,
    command_id: "attempt-1:claim",
    expected_revision: dispatched.revision,
    attempt_id: "attempt-1",
    owner: "worker",
    spec_sha256: created.spec_sha256,
    dispatch_generation: 1,
    lease_duration_ms: 60_000,
  }) as any;
  const failed = await t.mutation(internal.authoringInternal.failJob, {
    job_id: created.job_id,
    command_id: "attempt-1:fail",
    expected_revision: claimed.revision,
    attempt_id: "attempt-1",
    failure: {
      classification: "temporary_upstream_failure",
      message: "Try again later.",
      retryable: true,
    },
  }) as any;
  expect(failed).toMatchObject({ state: "retryable_failed", revision: 7 });

  const retried = await t.mutation(internal.authoringInternal.retryJob, {
    job_id: created.job_id,
    command_id: "retry",
    expected_revision: failed.revision,
  }) as any;
  expect(retried).toMatchObject({ state: "ready", revision: 8, failure: null });
  const cancelled = await t.mutation(internal.authoringInternal.cancelJob, {
    job_id: created.job_id,
    command_id: "cancel",
    expected_revision: retried.revision,
  }) as any;
  expect(cancelled).toMatchObject({ state: "cancelled", revision: 9 });

  const snapshot = await t.run(async (ctx) => ({
    jobs: await ctx.db.query("authoring_jobs").collect(),
    events: await ctx.db.query("authoring_job_events").collect(),
  }));
  expect(snapshot.jobs).toHaveLength(1);
  expect(snapshot.events).toHaveLength(9);
  expect(snapshot.jobs[0]?.aggregate).toEqual(cancelled);
});
