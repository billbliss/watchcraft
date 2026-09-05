/// <reference types="vite/client" />

import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { convexTest } from "convex-test";

import {
  artifactKey,
  capabilityRegistrySha256,
  DEFAULT_CAPABILITY_REGISTRY,
  resolveJobSpecAgainstRegistry,
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
const operatorToken = "test-operator-token-that-is-not-a-production-secret";
const registryAdminToken = "test-registry-admin-token-that-is-not-a-production-secret";

beforeEach(() => {
  vi.stubEnv("AUTHORING_WORKER_TOKEN_SHA256", sha256Hex(workerToken));
  vi.stubEnv("AUTHORING_OPERATOR_TOKEN_SHA256", sha256Hex(operatorToken));
  vi.stubEnv("AUTHORING_REGISTRY_ADMIN_TOKEN_SHA256", sha256Hex(registryAdminToken));
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

async function publishAndActivateDefaultRegistry(t: ReturnType<typeof convexTest>) {
  const registrySha256 = capabilityRegistrySha256(DEFAULT_CAPABILITY_REGISTRY);
  const published = await post(t, "/authoring/admin/registry/publish", {
    command_id: "publish-default-registry",
    actor: "test-registry-admin",
    registry: DEFAULT_CAPABILITY_REGISTRY,
  }, registryAdminToken);
  expect(published.status).toBe(200);
  const activated = await post(t, "/authoring/admin/registry/activate", {
    environment: "production",
    command_id: "activate-default-registry",
    actor: "test-registry-admin",
    registry_version: DEFAULT_CAPABILITY_REGISTRY.registry_version,
    registry_sha256: registrySha256,
    expected_revision: 0,
  }, registryAdminToken);
  expect(activated.status).toBe(200);
  return activated.json();
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

  const hiddenOrphanResponse = await post(t, "/authoring/admin/cleanup/list", {
    include_unmarked: false,
    limit: 10,
  }, registryAdminToken);
  const hiddenOrphan = await hiddenOrphanResponse.json() as any;
  expect(hiddenOrphan.orphan_jobs).toEqual([]);
  const listedOrphanResponse = await post(t, "/authoring/admin/cleanup/list", {
    include_unmarked: true,
    limit: 10,
  }, registryAdminToken);
  const listedOrphan = await listedOrphanResponse.json() as any;
  expect(listedOrphan.orphan_jobs).toEqual([
    expect.objectContaining({ job_id: "job-1", run_id: "run-1", state: "succeeded" }),
  ]);

  const wrongOrphanConfirmation = await post(t, "/authoring/admin/cleanup/purge-orphan-job", {
    job_id: "job-1",
    confirmation: "wrong-job",
    command_id: "cleanup-orphan-wrong",
    actor: "test-registry-admin",
  }, registryAdminToken);
  expect(wrongOrphanConfirmation.status).toBe(409);
  const orphanCleanupResponse = await post(t, "/authoring/admin/cleanup/purge-orphan-job", {
    job_id: "job-1",
    confirmation: "job-1",
    command_id: "cleanup-orphan",
    actor: "test-registry-admin",
  }, registryAdminToken);
  expect(orphanCleanupResponse.status).toBe(200);
  const orphanCleanup = await orphanCleanupResponse.json() as any;
  expect(orphanCleanup).toMatchObject({
    job_id: "job-1",
    missing_run_id: "run-1",
    deleted_job_events: 8,
    retained_artifacts: [artifact],
  });
  const orphanCleanupReplay = await post(t, "/authoring/admin/cleanup/purge-orphan-job", {
    job_id: "job-1",
    confirmation: "job-1",
    command_id: "cleanup-orphan",
    actor: "test-registry-admin",
  }, registryAdminToken);
  expect(orphanCleanupReplay.status).toBe(200);
  await expect(orphanCleanupReplay.json()).resolves.toEqual(orphanCleanup);
  const cleaned = await t.run(async (ctx) => ({
    jobs: await ctx.db.query("authoring_jobs").collect(),
    jobEvents: await ctx.db.query("authoring_job_events").collect(),
    cleanupEvents: await ctx.db.query("authoring_cleanup_events").collect(),
  }));
  expect(cleaned.jobs).toEqual([]);
  expect(cleaned.jobEvents).toEqual([]);
  expect(cleaned.cleanupEvents).toHaveLength(1);

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

test("registry publication is immutable and activation is environment-scoped and compare-and-set", async () => {
  const t = convexTest(schema, modules);
  const unauthorized = await post(t, "/authoring/admin/registry/publish", {
    command_id: "publish-default-registry",
    actor: "wrong",
    registry: DEFAULT_CAPABILITY_REGISTRY,
  }, operatorToken);
  expect(unauthorized.status).toBe(401);

  const active = await publishAndActivateDefaultRegistry(t) as any;
  expect(active).toMatchObject({
    environment: "production",
    revision: 1,
    registry_version: DEFAULT_CAPABILITY_REGISTRY.registry_version,
  });

  const operatorView = await post(t, "/authoring/operator/registry/get-active", {
    environment: "production",
  }, operatorToken);
  expect(operatorView.status).toBe(200);
  const view = await operatorView.json() as any;
  expect(view.active).toEqual(active);
  expect(view.registry).toEqual(DEFAULT_CAPABILITY_REGISTRY);

  const changed = structuredClone(DEFAULT_CAPABILITY_REGISTRY);
  changed.execution_profiles[0].timeout_minutes += 1;
  const overwrite = await post(t, "/authoring/admin/registry/publish", {
    command_id: "publish-mutated-registry",
    actor: "test-registry-admin",
    registry: changed,
  }, registryAdminToken);
  expect(overwrite.status).toBe(409);

  const staleActivation = await post(t, "/authoring/admin/registry/activate", {
    environment: "production",
    command_id: "stale-activation",
    actor: "test-registry-admin",
    registry_version: DEFAULT_CAPABILITY_REGISTRY.registry_version,
    registry_sha256: capabilityRegistrySha256(DEFAULT_CAPABILITY_REGISTRY),
    expected_revision: 0,
  }, registryAdminToken);
  expect(staleActivation.status).toBe(409);
  const events = await t.run((ctx) => ctx.db.query("authoring_registry_events").collect());
  expect(events).toHaveLength(1);
  expect(events[0]).toMatchObject({
    actor: "test-registry-admin",
    from_revision: 0,
    to_registry_sha256: capabilityRegistrySha256(DEFAULT_CAPABILITY_REGISTRY),
  });
});

test("registered lease and retry policy are enforced by the control plane", async () => {
  const t = convexTest(schema, modules);
  const spec = resolveJobSpecAgainstRegistry({
    operation: "generate",
    artifact_kind: "analysis",
    output_schema: { id: "watchcraft.analysis.lexical", version: 1 },
    handler: { id: "watchcraft.analysis.lexical", version: "1" },
    source: { media_asset_id: "lesson-policy" },
    inputs: [],
    dependencies: [],
    configuration: { title: "Policy", text: "Policy test" },
  }, DEFAULT_CAPABILITY_REGISTRY);
  const created = await t.mutation(internal.authoringInternal.createJob, {
    job_id: "job-policy",
    run_id: "run-policy",
    command_id: "create-policy",
    spec,
  }) as any;
  const awaiting = await t.mutation(internal.authoringInternal.requestApproval, {
    job_id: created.job_id,
    command_id: "request-policy",
    expected_revision: created.revision,
  }) as any;
  const ready = await t.mutation(internal.authoringInternal.approveJob, {
    job_id: created.job_id,
    command_id: "approve-policy",
    expected_revision: awaiting.revision,
    actor: "operator",
    spec_sha256: created.spec_sha256,
  }) as any;
  const pending = await t.mutation(internal.authoringInternal.requestDispatch, {
    job_id: created.job_id,
    command_id: "pending-policy",
    expected_revision: ready.revision,
  }) as any;
  const dispatched = await t.mutation(internal.authoringInternal.recordDispatch, {
    job_id: created.job_id,
    command_id: "dispatch-policy",
    expected_revision: pending.revision,
    generation: 1,
    github_run_id: "policy-run",
    github_run_url: "https://github.com/billbliss/watchcraft/actions/runs/policy-run",
  }) as any;
  const claimed = await t.mutation(internal.authoringInternal.claimJob, {
    job_id: created.job_id,
    command_id: "claim-policy",
    expected_revision: dispatched.revision,
    attempt_id: "attempt-policy",
    owner: "worker",
    spec_sha256: created.spec_sha256,
    dispatch_generation: 1,
    lease_duration_ms: 1_000,
  }) as any;
  expect(claimed.lease.expires_at - claimed.lease.acquired_at).toBe(300_000);

  const failed = await t.mutation(internal.authoringInternal.failJob, {
    job_id: created.job_id,
    command_id: "fail-policy",
    expected_revision: claimed.revision,
    attempt_id: "attempt-policy",
    failure: {
      classification: "unregistered_transient_failure",
      message: "The worker cannot make this retryable by assertion.",
      retryable: true,
    },
  }) as any;
  expect(failed).toMatchObject({
    state: "terminal_failed",
    failure: { classification: "unregistered_transient_failure", retryable: false },
  });
});

test("operator and worker credentials drive a persisted non-transcript analysis run", async () => {
  const t = convexTest(schema, modules);
  const request = {
    kind: "lexical-analysis-smoke",
    purpose: "smoke",
    retention: { class: "ephemeral", expires_at: 0 },
  };
  const spec = {
    operation: "generate",
    artifact_kind: "analysis",
    output_schema: { id: "watchcraft.analysis.lexical", version: 1 },
    handler: { id: "watchcraft.analysis.lexical", version: "1" },
    source: { media_asset_id: "lesson-1" },
    inputs: [],
    dependencies: [],
    configuration: {
      title: "Color workflow",
      text: "Balance exposure and color before applying the final grade.",
      max_topics: 8,
    },
  };
  const rejected = await post(t, "/authoring/operator/submissions/submit", {
    job_id: "analysis-job",
    run_id: "analysis-run",
    command_prefix: "submit",
    request,
    spec,
  }, workerToken);
  expect(rejected.status).toBe(401);

  const missingRegistry = await post(t, "/authoring/operator/submissions/submit", {
    job_id: "analysis-job",
    run_id: "analysis-run",
    command_prefix: "submit",
    request,
    spec,
  }, operatorToken);
  expect(missingRegistry.status).toBe(409);
  await expect(missingRegistry.json()).resolves.toMatchObject({
    error: expect.stringContaining("No active authoring capability registry"),
  });
  await publishAndActivateDefaultRegistry(t);

  const submittedResponse = await post(t, "/authoring/operator/submissions/submit", {
    job_id: "analysis-job",
    run_id: "analysis-run",
    command_prefix: "submit",
    request,
    spec,
  }, operatorToken);
  expect(submittedResponse.status).toBe(200);
  const submitted = await submittedResponse.json() as any;
  expect(submitted.job).toMatchObject({ state: "awaiting_approval", revision: 2 });
  expect(submitted.job.spec.registry_snapshot).toMatchObject({
    registry_version: DEFAULT_CAPABILITY_REGISTRY.registry_version,
    execution_profile: { id: "python-portable", version: "1" },
  });
  expect(submitted.run).toMatchObject({ state: "planned", revision: 2 });

  const changedReplay = await post(t, "/authoring/operator/submissions/submit", {
    job_id: "analysis-job",
    run_id: "analysis-run",
    command_prefix: "submit",
    request: { kind: "different-analysis" },
    spec,
  }, operatorToken);
  expect(changedReplay.status).toBe(409);

  const approvedResponse = await post(t, "/authoring/operator/submissions/approve", {
    job_id: "analysis-job",
    command_id: "approve",
    expected_revision: submitted.job.revision,
    actor: "test-operator",
    spec_sha256: submitted.job.spec_sha256,
  }, operatorToken);
  expect(approvedResponse.status).toBe(200);
  const approved = await approvedResponse.json() as any;
  expect(approved.job.state).toBe("ready");
  expect(approved.run.state).toBe("approved");

  const pendingResponse = await post(t, "/authoring/operator/submissions/request-dispatch", {
    job_id: "analysis-job",
    command_id: "request-dispatch",
    expected_revision: approved.job.revision,
  }, operatorToken);
  const pending = await pendingResponse.json() as any;
  expect(pending).toMatchObject({ state: "dispatch_pending", revision: 4 });

  const dispatchedResponse = await post(t, "/authoring/jobs/dispatch/record", {
    job_id: "analysis-job",
    command_id: "record-dispatch",
    expected_revision: pending.revision,
    generation: pending.dispatch.generation,
    github_run_id: "789",
    github_run_url: "https://github.com/billbliss/watchcraft/actions/runs/789",
  });
  expect(dispatchedResponse.status).toBe(200);
  const dispatched = await dispatchedResponse.json() as any;

  const operatorClaim = await post(t, "/authoring/jobs/claim", {
    job_id: "analysis-job",
  }, operatorToken);
  expect(operatorClaim.status).toBe(401);
  const claimedResponse = await post(t, "/authoring/jobs/claim", {
    job_id: "analysis-job",
    command_id: "claim",
    expected_revision: dispatched.revision,
    attempt_id: "analysis-attempt",
    owner: "github-actions:789",
    spec_sha256: dispatched.spec_sha256,
    dispatch_generation: dispatched.dispatch.generation,
    lease_duration_ms: 60_000,
    github_run_id: "789",
  });
  const claimed = await claimedResponse.json() as any;
  const startedResponse = await post(t, "/authoring/jobs/start", {
    job_id: "analysis-job",
    command_id: "start",
    expected_revision: claimed.revision,
    attempt_id: "analysis-attempt",
  });
  const started = await startedResponse.json() as any;
  const digest = "b".repeat(64);
  const artifact = {
    store: "r2",
    algorithm: "sha256",
    digest,
    byte_length: 200,
    media_type: "application/json",
    artifact_kind: "analysis",
    schema: { id: "watchcraft.analysis.lexical", version: 1 },
    key: artifactKey(digest),
  };
  const completedResponse = await post(t, "/authoring/jobs/succeed", {
    job_id: "analysis-job",
    command_id: "succeed",
    expected_revision: started.revision,
    attempt_id: "analysis-attempt",
    artifact,
  });
  expect(completedResponse.status).toBe(200);

  const finalResponse = await post(t, "/authoring/operator/submissions/get", {
    job_id: "analysis-job",
  }, operatorToken);
  const final = await finalResponse.json() as any;
  expect(final.job).toMatchObject({ state: "succeeded", revision: 8, result: artifact });
  expect(final.run).toMatchObject({ state: "complete", revision: 5 });
  const snapshot = await t.run(async (ctx) => ({
    jobEvents: await ctx.db.query("authoring_job_events").collect(),
    runEvents: await ctx.db.query("authoring_run_events").collect(),
  }));
  expect(snapshot.jobEvents).toHaveLength(8);
  expect(snapshot.runEvents).toHaveLength(5);

  const listedResponse = await post(t, "/authoring/admin/cleanup/list", {
    include_unmarked: false,
    limit: 10,
  }, registryAdminToken);
  expect(listedResponse.status).toBe(200);
  const listed = await listedResponse.json() as any;
  expect(listed.runs).toEqual([
    expect.objectContaining({
      run_id: "analysis-run",
      state: "complete",
      request_kind: "lexical-analysis-smoke",
      cleanup_eligible: true,
      retention: { class: "ephemeral", expires_at: 0 },
    }),
  ]);

  const wrongConfirmation = await post(t, "/authoring/admin/cleanup/purge-run", {
    run_id: "analysis-run",
    confirmation: "wrong-run",
    command_id: "cleanup-analysis-wrong",
    actor: "test-registry-admin",
    allow_unmarked: false,
  }, registryAdminToken);
  expect(wrongConfirmation.status).toBe(409);

  const cleanedResponse = await post(t, "/authoring/admin/cleanup/purge-run", {
    run_id: "analysis-run",
    confirmation: "analysis-run",
    command_id: "cleanup-analysis",
    actor: "test-registry-admin",
    allow_unmarked: false,
  }, registryAdminToken);
  expect(cleanedResponse.status).toBe(200);
  await expect(cleanedResponse.json()).resolves.toMatchObject({
    run_id: "analysis-run",
    deleted_jobs: 1,
    deleted_job_events: 8,
    deleted_run_events: 5,
    retained_artifacts: [artifact],
  });

  const legacySubmittedResponse = await post(t, "/authoring/operator/submissions/submit", {
    job_id: "legacy-job",
    run_id: "legacy-run",
    command_prefix: "legacy-submit",
    request: { kind: "legacy-debug" },
    spec,
  }, operatorToken);
  const legacySubmitted = await legacySubmittedResponse.json() as any;
  const legacyCancelledResponse = await post(t, "/authoring/operator/submissions/cancel", {
    job_id: "legacy-job",
    command_id: "legacy-cancel",
    expected_revision: legacySubmitted.job.revision,
  }, operatorToken);
  expect(legacyCancelledResponse.status).toBe(200);

  const protectedCleanup = await post(t, "/authoring/admin/cleanup/purge-run", {
    run_id: "legacy-run",
    confirmation: "legacy-run",
    command_id: "cleanup-unmarked-denied",
    actor: "test-registry-admin",
    allow_unmarked: false,
  }, registryAdminToken);
  expect(protectedCleanup.status).toBe(409);
  await expect(protectedCleanup.json()).resolves.toMatchObject({
    error: expect.stringContaining("no ephemeral retention policy"),
  });

  const explicitCleanup = await post(t, "/authoring/admin/cleanup/purge-run", {
    run_id: "legacy-run",
    confirmation: "legacy-run",
    command_id: "cleanup-unmarked",
    actor: "test-registry-admin",
    allow_unmarked: true,
  }, registryAdminToken);
  expect(explicitCleanup.status).toBe(200);
  const cleanupResult = await explicitCleanup.json() as any;
  expect(cleanupResult).toMatchObject({ run_id: "legacy-run", deleted_jobs: 1 });
  const cleanupReplay = await post(t, "/authoring/admin/cleanup/purge-run", {
    run_id: "legacy-run",
    confirmation: "legacy-run",
    command_id: "cleanup-unmarked",
    actor: "test-registry-admin",
    allow_unmarked: true,
  }, registryAdminToken);
  expect(cleanupReplay.status).toBe(200);
  await expect(cleanupReplay.json()).resolves.toEqual(cleanupResult);
});
