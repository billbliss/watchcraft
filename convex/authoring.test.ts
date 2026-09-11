/// <reference types="vite/client" />

import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { convexTest } from "convex-test";
import { readFile } from "node:fs/promises";

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

test("catalog project snapshot acceptance is verified, revisioned, and queryable", async () => {
  const t = convexTest(schema, modules);
  const projectBytes = await readFile(new URL(
    "../packages/authoring-pipeline/project/examples/current-playlist.project.json",
    import.meta.url,
  ));
  const acceptedSnapshotBytes = await readFile(new URL(
    "../packages/authoring-pipeline/project/examples/current-playlist.snapshot.json",
    import.meta.url,
  ));
  const project = JSON.parse(projectBytes.toString("utf8"));
  const candidate = JSON.parse(acceptedSnapshotBytes.toString("utf8"));
  candidate.observed_at = "2026-09-08T09:48:10Z";
  candidate.provenance.discovery_mode = "bounded-crawl";
  const candidateJson = JSON.stringify(candidate);
  const candidateBytes = new TextEncoder().encode(candidateJson);
  const candidateDigest = sha256Hex(candidateBytes);
  const artifact = {
    store: "r2",
    algorithm: "sha256",
    digest: candidateDigest,
    byte_length: candidateBytes.byteLength,
    media_type: "application/json",
    artifact_kind: "collection-iterator-snapshot",
    schema: { id: "watchcraft.collection-iterator-snapshot", version: 1 },
    key: artifactKey(candidateDigest),
  };

  const importedResponse = await post(t, "/authoring/operator/projects/import", {
    command_id: "import-project-1",
    actor: "test-operator",
    project,
    accepted_snapshot_json: acceptedSnapshotBytes.toString("utf8"),
  }, operatorToken);
  expect(importedResponse.status).toBe(200);
  await expect(importedResponse.json()).resolves.toMatchObject({
    created: true,
    project: { project_id: "essence-of-linear-algebra", revision: 1 },
  });
  const importReplay = await post(t, "/authoring/operator/projects/import", {
    command_id: "import-project-1",
    actor: "test-operator",
    project,
    accepted_snapshot_json: acceptedSnapshotBytes.toString("utf8"),
  }, operatorToken);
  expect(importReplay.status).toBe(200);
  await expect(importReplay.json()).resolves.toMatchObject({
    created: true,
    project: { project_id: "essence-of-linear-algebra", revision: 1 },
  });

  const spec = {
    operation: "generate",
    artifact_kind: "collection-iterator-snapshot",
    output_schema: { id: "watchcraft.collection-iterator-snapshot", version: 1 },
    handler: { id: "watchcraft.iterator.youtube-playlist", version: "1" },
    source: {
      media_asset_id: "youtube-playlist:PLZHQObOWTQDPD3MizzM2xVFitgF8hE_ab",
    },
    inputs: [],
    dependencies: [],
    configuration: { project, observed_at: candidate.observed_at },
  };
  let job = await t.mutation(internal.authoringInternal.createJob, {
    job_id: "iterator-job-1",
    run_id: "iterator-run-1",
    command_id: "iterator-create",
    spec,
  }) as any;
  job = await t.mutation(internal.authoringInternal.requestApproval, {
    job_id: job.job_id,
    command_id: "iterator-request-approval",
    expected_revision: job.revision,
  }) as any;
  job = await t.mutation(internal.authoringInternal.approveJob, {
    job_id: job.job_id,
    command_id: "iterator-approve",
    expected_revision: job.revision,
    actor: "test-operator",
    spec_sha256: job.spec_sha256,
  }) as any;
  job = await t.mutation(internal.authoringInternal.requestDispatch, {
    job_id: job.job_id,
    command_id: "iterator-request-dispatch",
    expected_revision: job.revision,
  }) as any;
  job = await t.mutation(internal.authoringInternal.recordDispatch, {
    job_id: job.job_id,
    command_id: "iterator-record-dispatch",
    expected_revision: job.revision,
    generation: 1,
    github_run_id: "123",
    github_run_url: "https://github.com/billbliss/watchcraft/actions/runs/123",
  }) as any;
  job = await t.mutation(internal.authoringInternal.claimJob, {
    job_id: job.job_id,
    command_id: "iterator-claim",
    expected_revision: job.revision,
    attempt_id: "iterator-attempt-1",
    owner: "github-actions:123",
    spec_sha256: job.spec_sha256,
    dispatch_generation: 1,
    lease_duration_ms: 300_000,
    github_run_id: "123",
  }) as any;
  job = await t.mutation(internal.authoringInternal.startJob, {
    job_id: job.job_id,
    command_id: "iterator-start",
    expected_revision: job.revision,
    attempt_id: "iterator-attempt-1",
  }) as any;
  job = await t.mutation(internal.authoringInternal.succeedJob, {
    job_id: job.job_id,
    command_id: "iterator-succeed",
    expected_revision: job.revision,
    attempt_id: "iterator-attempt-1",
    artifact,
  }) as any;
  expect(job.state).toBe("succeeded");

  const acceptanceBody = {
    project_id: project.project_id,
    job_id: job.job_id,
    expected_revision: 1,
    command_id: "accept-candidate-1",
    actor: "test-operator",
    snapshot_json: candidateJson,
  };
  const tampered = await post(t, "/authoring/operator/projects/accept-snapshot", {
    ...acceptanceBody,
    command_id: "accept-tampered",
    snapshot_json: `${candidateJson} `,
  }, operatorToken);
  expect(tampered.status).toBe(409);
  await expect(tampered.json()).resolves.toEqual({
    error: "Iterator candidate reference does not match its exact bytes.",
  });

  const acceptedResponse = await post(
    t,
    "/authoring/operator/projects/accept-snapshot",
    acceptanceBody,
    operatorToken,
  );
  expect(acceptedResponse.status).toBe(200);
  const accepted = await acceptedResponse.json() as any;
  expect(accepted).toMatchObject({
    previous_revision: 1,
    candidate_job_id: "iterator-job-1",
    project: {
      project_id: "essence-of-linear-algebra",
      revision: 2,
      iterator: { accepted_snapshot: artifact },
    },
  });

  const replay = await post(
    t,
    "/authoring/operator/projects/accept-snapshot",
    acceptanceBody,
    operatorToken,
  );
  expect(replay.status).toBe(200);
  await expect(replay.json()).resolves.toEqual(accepted);

  const status = await post(t, "/authoring/operator/projects/get", {
    project_id: project.project_id,
  }, operatorToken);
  expect(status.status).toBe(200);
  await expect(status.json()).resolves.toMatchObject({
    project: { revision: 2, iterator: { accepted_snapshot: artifact } },
  });
  const history = await post(t, "/authoring/operator/projects/history", {
    project_id: project.project_id,
    limit: 20,
  }, operatorToken);
  expect(history.status).toBe(200);
  await expect(history.json()).resolves.toMatchObject({
    current_revision: 2,
    revisions: [
      { revision: 2, transition: "accept-snapshot", candidate_job_id: job.job_id },
      { revision: 1, transition: "import", candidate_job_id: null },
    ],
  });

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
  const running = await t.mutation(internal.authoringInternal.startJob, {
    job_id: created.job_id,
    command_id: "attempt-1:start",
    expected_revision: claimed.revision,
    attempt_id: "attempt-1",
  }) as any;
  const checkpointDigest = "b".repeat(64);
  const heartbeat = await t.mutation(internal.authoringInternal.heartbeatJob, {
    job_id: created.job_id,
    command_id: "attempt-1:heartbeat",
    expected_revision: running.revision,
    attempt_id: "attempt-1",
    lease_duration_ms: 60_000,
    progress: {
      phase: "enumerating",
      completed: 1,
      total: 3,
      unit: "placements",
      current: "Lesson one",
    },
    checkpoint: {
      sequence: 1,
      spec_sha256: created.spec_sha256,
      artifact: {
        algorithm: "sha256",
        digest: checkpointDigest,
        byte_length: 512,
        media_type: "application/json",
        key: artifactKey(checkpointDigest),
        store: "r2",
        artifact_kind: "collection-iterator-checkpoint",
        schema: { id: "watchcraft.collection-iterator-checkpoint", version: 1 },
      },
    },
  }) as any;
  expect(heartbeat.attempts[0]).toMatchObject({
    progress: { phase: "enumerating", completed: 1, total: 3, unit: "placements" },
    checkpoint: { sequence: 1, spec_sha256: created.spec_sha256 },
  });
  const failed = await t.mutation(internal.authoringInternal.failJob, {
    job_id: created.job_id,
    command_id: "attempt-1:fail",
    expected_revision: heartbeat.revision,
    attempt_id: "attempt-1",
    failure: {
      classification: "temporary_upstream_failure",
      message: "Try again later.",
      retryable: true,
    },
  }) as any;
  expect(failed).toMatchObject({ state: "retryable_failed", revision: 9 });

  const retried = await t.mutation(internal.authoringInternal.retryJob, {
    job_id: created.job_id,
    command_id: "retry",
    expected_revision: failed.revision,
  }) as any;
  expect(retried).toMatchObject({ state: "ready", revision: 10, failure: null });
  expect(retried.attempts[0].checkpoint.sequence).toBe(1);
  const cancelled = await t.mutation(internal.authoringInternal.cancelJob, {
    job_id: created.job_id,
    command_id: "cancel",
    expected_revision: retried.revision,
  }) as any;
  expect(cancelled).toMatchObject({ state: "cancelled", revision: 11 });

  const snapshot = await t.run(async (ctx) => ({
    jobs: await ctx.db.query("authoring_jobs").collect(),
    events: await ctx.db.query("authoring_job_events").collect(),
  }));
  expect(snapshot.jobs).toHaveLength(1);
  expect(snapshot.events).toHaveLength(11);
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

  const adminView = await post(t, "/authoring/admin/registry/get-active", {
    environment: "production",
  }, registryAdminToken);
  expect(adminView.status).toBe(200);
  await expect(adminView.json()).resolves.toEqual(view);

  const operatorCannotUseAdminView = await post(t, "/authoring/admin/registry/get-active", {
    environment: "production",
  }, operatorToken);
  expect(operatorCannotUseAdminView.status).toBe(401);

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

test("lease expiration honors the registered maximum attempt count", async () => {
  vi.useFakeTimers();
  try {
    vi.setSystemTime(new Date("2026-09-11T19:00:00Z"));
    const t = convexTest(schema, modules);
    const spec = resolveJobSpecAgainstRegistry(
      lexicalAnalysisSpec("operator:lease-limit"),
      DEFAULT_CAPABILITY_REGISTRY,
    );
    let job = await t.mutation(internal.authoringInternal.createJob, {
      job_id: "lease-limit-job",
      run_id: "lease-limit-run",
      command_id: "lease-limit:create",
      spec,
    }) as any;
    job = await t.mutation(internal.authoringInternal.requestApproval, {
      job_id: job.job_id,
      command_id: "lease-limit:request-approval",
      expected_revision: job.revision,
    }) as any;
    job = await t.mutation(internal.authoringInternal.approveJob, {
      job_id: job.job_id,
      command_id: "lease-limit:approve",
      expected_revision: job.revision,
      actor: "test-operator",
      spec_sha256: job.spec_sha256,
    }) as any;

    for (let attempt = 1; attempt <= 3; attempt += 1) {
      job = await t.mutation(internal.authoringInternal.requestDispatch, {
        job_id: job.job_id,
        command_id: `lease-limit:${attempt}:request-dispatch`,
        expected_revision: job.revision,
      }) as any;
      job = await t.mutation(internal.authoringInternal.recordDispatch, {
        job_id: job.job_id,
        command_id: `lease-limit:${attempt}:record-dispatch`,
        expected_revision: job.revision,
        generation: job.dispatch.generation,
        github_run_id: `lease-limit-${attempt}`,
        github_run_url: `https://github.com/example/runs/lease-limit-${attempt}`,
      }) as any;
      job = await t.mutation(internal.authoringInternal.claimJob, {
        job_id: job.job_id,
        command_id: `lease-limit:${attempt}:claim`,
        expected_revision: job.revision,
        attempt_id: `lease-limit:attempt-${attempt}`,
        owner: "test-worker",
        spec_sha256: job.spec_sha256,
        dispatch_generation: job.dispatch.generation,
        lease_duration_ms: 1,
      }) as any;
      vi.setSystemTime(job.lease.expires_at + 1);
      expect(
        await t.mutation(internal.authoringInternal.reconcileExpiredLeases, {}),
      ).toBe(1);
      job = await t.run(async (ctx) => (
        await ctx.db.query("authoring_jobs").withIndex("by_job_id", (q) => (
          q.eq("job_id", "lease-limit-job")
        )).unique()
      )) as any;
      job = job.aggregate;
      expect(job.state).toBe(attempt < 3 ? "retryable_failed" : "terminal_failed");
      if (attempt < 3) {
        job = await t.mutation(internal.authoringInternal.retryJob, {
          job_id: job.job_id,
          command_id: `lease-limit:${attempt}:retry`,
          expected_revision: job.revision,
        }) as any;
      }
    }
    expect(job.attempts).toHaveLength(3);
    expect(job.failure).toMatchObject({
      classification: "lease_expired",
      retryable: false,
    });
  } finally {
    vi.useRealTimers();
  }
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

test("a pipeline run gates analysis on transcription and completes after both jobs", async () => {
  const t = convexTest(schema, modules);
  await publishAndActivateDefaultRegistry(t);
  const sourceAudioDigest = "1".repeat(64);
  const sourceAudio = {
    store: "r2",
    algorithm: "sha256",
    digest: sourceAudioDigest,
    byte_length: 1024,
    media_type: "audio/webm",
    artifact_kind: "source-audio",
    schema: { id: "watchcraft.source-audio", version: 1 },
    key: `staging/00000000-0000-4000-8000-000000000000/sha256/${sourceAudioDigest.slice(0, 2)}/${sourceAudioDigest.slice(2)}`,
    retention: { class: "ephemeral", expires_at: 2_000_000_000_000 },
  };
  const transcriptionSpec = {
    operation: "generate",
    artifact_kind: "transcript",
    output_schema: { id: "watchcraft.transcript", version: 1 },
    handler: {
      id: "watchcraft.transcript.mlx-whisper-large-v3-turbo-q4",
      version: "1",
    },
    source: { media_asset_id: "youtube:WPtpUu3uIUI" },
    inputs: [sourceAudio],
    dependencies: [],
    configuration: {
      acquisition: {
        source: { media_asset_id: "youtube:WPtpUu3uIUI" },
        media: {
          algorithm: "sha256",
          digest: sourceAudioDigest,
          byte_length: 1024,
          duration_seconds: 60,
        },
      },
      maximum_bytes: 100_000_000,
      maximum_duration_seconds: 7_200,
      language: "en",
      model: "mlx-community/whisper-large-v3-turbo-q4",
    },
  };
  const dependency = {
    kind: "job-output",
    job_id: "pipeline-transcription",
    artifact_kind: "transcript",
    schema: { id: "watchcraft.transcript", version: 1 },
  };
  const analysisSpec = {
    operation: "generate",
    artifact_kind: "analysis",
    output_schema: { id: "watchcraft.video-analysis", version: 2 },
    handler: { id: "watchcraft.analysis.educational-video", version: "1" },
    source: { media_asset_id: "youtube:WPtpUu3uIUI" },
    inputs: [],
    dependencies: [dependency],
    configuration: {
      model: "gpt-5-nano",
      prompt_version: 3,
      retries: 5,
      timeout_seconds: 300,
      max_transcript_chars: 1_500_000,
      source_metadata: {
        type: "youtube",
        source_id: "youtube:WPtpUu3uIUI",
        title: "Knife skills",
      },
      video: "WPtpUu3uIUI.youtube",
    },
  };
  const submittedResponse = await post(t, "/authoring/operator/pipelines/submit", {
    run_id: "pipeline-run",
    command_prefix: "pipeline-submit",
    request: {
      kind: "youtube-video",
      source_id: "youtube:WPtpUu3uIUI",
      stages: ["transcription", "educational-video-analysis"],
    },
    jobs: [
      { job_id: "pipeline-transcription", spec: transcriptionSpec },
      { job_id: "pipeline-analysis", spec: analysisSpec },
    ],
  }, operatorToken);
  expect(submittedResponse.status).toBe(200);
  const submitted = await submittedResponse.json() as any;
  expect(submitted.run).toMatchObject({ state: "planned", job_ids: [
    "pipeline-transcription",
    "pipeline-analysis",
  ] });
  expect(submitted.jobs[1].spec.dependencies).toEqual([dependency]);
  const retrievedResponse = await post(t, "/authoring/operator/pipelines/get", {
    run_id: "pipeline-run",
  }, operatorToken);
  expect(retrievedResponse.status).toBe(200);
  expect(await retrievedResponse.json()).toEqual(submitted);
  const missingResponse = await post(t, "/authoring/operator/pipelines/get", {
    run_id: "missing-pipeline-run",
  }, operatorToken);
  expect(missingResponse.status).toBe(200);
  expect(await missingResponse.json()).toEqual({ run: null, jobs: [] });
  const replayedSubmission = await post(t, "/authoring/operator/pipelines/submit", {
    run_id: "pipeline-run",
    command_prefix: "pipeline-submit",
    request: {
      kind: "youtube-video",
      source_id: "youtube:WPtpUu3uIUI",
      stages: ["transcription", "educational-video-analysis"],
    },
    jobs: [
      { job_id: "pipeline-transcription", spec: transcriptionSpec },
      { job_id: "pipeline-analysis", spec: analysisSpec },
    ],
  }, operatorToken);
  expect(replayedSubmission.status).toBe(200);
  expect(await replayedSubmission.json()).toEqual(submitted);

  const approvedResponse = await post(t, "/authoring/operator/pipelines/approve", {
    run_id: submitted.run.run_id,
    command_id: "pipeline-approve",
    expected_revision: submitted.run.revision,
    actor: "test-operator",
    approval_sha256: submitted.run.approval_sha256,
  }, operatorToken);
  expect(approvedResponse.status).toBe(200);
  const approved = await approvedResponse.json() as any;
  expect(approved.run.state).toBe("approved");
  expect(approved.jobs.map((job: any) => job.state)).toEqual(["ready", "ready"]);
  const replayedApproval = await post(t, "/authoring/operator/pipelines/approve", {
    run_id: submitted.run.run_id,
    command_id: "pipeline-approve",
    expected_revision: submitted.run.revision,
    actor: "test-operator",
    approval_sha256: submitted.run.approval_sha256,
  }, operatorToken);
  expect(replayedApproval.status).toBe(200);
  expect(await replayedApproval.json()).toEqual(approved);

  const earlyAnalysis = await post(t, "/authoring/operator/submissions/request-dispatch", {
    job_id: "pipeline-analysis",
    command_id: "early-analysis-dispatch",
    expected_revision: approved.jobs[1].revision,
  }, operatorToken);
  expect(earlyAnalysis.status).toBe(409);
  await expect(earlyAnalysis.json()).resolves.toMatchObject({
    error: expect.stringContaining("pipeline-transcription is ready"),
  });

  async function executeJob(job: any, artifact: any, runId: string) {
    const pendingResponse = await post(t, "/authoring/operator/submissions/request-dispatch", {
      job_id: job.job_id,
      command_id: `${job.job_id}:request-dispatch`,
      expected_revision: job.revision,
    }, operatorToken);
    expect(pendingResponse.status).toBe(200);
    const pending = await pendingResponse.json() as any;
    const dispatchedResponse = await post(t, "/authoring/jobs/dispatch/record", {
      job_id: job.job_id,
      command_id: `${job.job_id}:record-dispatch`,
      expected_revision: pending.revision,
      generation: pending.dispatch.generation,
      github_run_id: `run-${job.job_id}`,
      github_run_url: `https://github.com/example/runs/${job.job_id}`,
    });
    const dispatched = await dispatchedResponse.json() as any;
    const claimedResponse = await post(t, "/authoring/jobs/claim", {
      job_id: job.job_id,
      command_id: `${job.job_id}:claim`,
      expected_revision: dispatched.revision,
      attempt_id: `${job.job_id}:attempt`,
      owner: "test-worker",
      spec_sha256: dispatched.spec_sha256,
      dispatch_generation: dispatched.dispatch.generation,
      lease_duration_ms: 60_000,
    });
    const claimed = await claimedResponse.json() as any;
    const startedResponse = await post(t, "/authoring/jobs/start", {
      job_id: job.job_id,
      command_id: `${job.job_id}:start`,
      expected_revision: claimed.revision,
      attempt_id: `${job.job_id}:attempt`,
    });
    const started = await startedResponse.json() as any;
    const completedResponse = await post(t, "/authoring/jobs/succeed", {
      job_id: job.job_id,
      command_id: `${job.job_id}:succeed`,
      expected_revision: started.revision,
      attempt_id: `${job.job_id}:attempt`,
      artifact,
    });
    expect(completedResponse.status).toBe(200);
    const statusResponse = await post(t, "/authoring/jobs/get", {
      job_id: job.job_id,
    });
    expect(statusResponse.status).toBe(200);
    const status = await statusResponse.json() as any;
    expect(status.run.run_id).toBe(runId);
    return status;
  }

  const transcriptDigest = "2".repeat(64);
  const transcription = await executeJob(approved.jobs[0], {
    store: "r2",
    algorithm: "sha256",
    digest: transcriptDigest,
    byte_length: 20_000,
    media_type: "application/json",
    artifact_kind: "transcript",
    schema: { id: "watchcraft.transcript", version: 1 },
    key: artifactKey(transcriptDigest),
  }, submitted.run.run_id);
  expect(transcription.run.state).toBe("running");

  const analysisDigest = "3".repeat(64);
  const analysis = await executeJob(approved.jobs[1], {
    store: "r2",
    algorithm: "sha256",
    digest: analysisDigest,
    byte_length: 10_000,
    media_type: "application/json",
    artifact_kind: "analysis",
    schema: { id: "watchcraft.video-analysis", version: 2 },
    key: artifactKey(analysisDigest),
  }, submitted.run.run_id);
  expect(analysis.run).toMatchObject({ state: "complete", revision: 5 });
});

function lexicalAnalysisSpec(sourceId: string) {
  return {
    operation: "generate" as const,
    artifact_kind: "analysis",
    output_schema: { id: "watchcraft.analysis.lexical", version: 1 },
    handler: { id: "watchcraft.analysis.lexical", version: "1" },
    source: { media_asset_id: sourceId },
    inputs: [],
    dependencies: [],
    configuration: { title: sourceId, text: "concurrent pipeline test", max_topics: 8 },
  };
}

function lexicalArtifact(fill: string) {
  const digest = fill.repeat(64);
  return {
    store: "r2",
    algorithm: "sha256",
    digest,
    byte_length: 100,
    media_type: "application/json",
    artifact_kind: "analysis",
    schema: { id: "watchcraft.analysis.lexical", version: 1 },
    key: artifactKey(digest),
  };
}

async function approvedLexicalPipeline(
  t: ReturnType<typeof convexTest>,
  runId: string,
  jobIds: string[],
) {
  await publishAndActivateDefaultRegistry(t);
  const submitted = await t.mutation(internal.authoringInternal.submitPipeline, {
    run_id: runId,
    command_prefix: `${runId}:submit`,
    request: { kind: "concurrent-regression" },
    jobs: jobIds.map((jobId) => ({
      job_id: jobId,
      spec: lexicalAnalysisSpec(`operator:${jobId}`),
    })),
  }) as any;
  return t.mutation(internal.authoringInternal.approvePipeline, {
    run_id: runId,
    command_id: `${runId}:approve`,
    expected_revision: submitted.run.revision,
    actor: "test-operator",
    approval_sha256: submitted.run.approval_sha256,
  }) as any;
}

async function startConcurrentJob(t: ReturnType<typeof convexTest>, job: any) {
  const generation = (job.dispatch?.generation ?? 0) + 1;
  const pending = await t.mutation(internal.authoringInternal.requestDispatch, {
    job_id: job.job_id,
    command_id: `${job.job_id}:${generation}:request-dispatch`,
    expected_revision: job.revision,
  }) as any;
  const dispatched = await t.mutation(internal.authoringInternal.recordDispatch, {
    job_id: job.job_id,
    command_id: `${job.job_id}:${generation}:record-dispatch`,
    expected_revision: pending.revision,
    generation: pending.dispatch.generation,
    github_run_id: `run-${job.job_id}`,
    github_run_url: `https://github.com/example/runs/${job.job_id}`,
  }) as any;
  const attemptId = `${job.job_id}:attempt-${dispatched.dispatch.generation}`;
  const claimed = await t.mutation(internal.authoringInternal.claimJob, {
    job_id: job.job_id,
    command_id: `${job.job_id}:${generation}:claim`,
    expected_revision: dispatched.revision,
    attempt_id: attemptId,
    owner: "test-worker",
    spec_sha256: dispatched.spec_sha256,
    dispatch_generation: dispatched.dispatch.generation,
    lease_duration_ms: 60_000,
  }) as any;
  return t.mutation(internal.authoringInternal.startJob, {
    job_id: job.job_id,
    command_id: `${job.job_id}:${generation}:start`,
    expected_revision: claimed.revision,
    attempt_id: attemptId,
  }) as any;
}

test("sibling jobs can record terminal outcomes after their run has failed", async () => {
  const t = convexTest(schema, modules);
  const approved = await approvedLexicalPipeline(
    t,
    "concurrent-run",
    ["failed-first", "failed-second", "succeeded-third"],
  );
  const [first, second, third] = await Promise.all(
    approved.jobs.map((job: any) => startConcurrentJob(t, job)),
  );

  const firstFailure = await t.mutation(internal.authoringInternal.failJob, {
    job_id: first.job_id,
    command_id: `${first.job_id}:fail`,
    expected_revision: first.revision,
    attempt_id: first.lease.attempt_id,
    failure: {
      classification: "artifact_store_failed",
      message: "temporary failure",
      retryable: true,
    },
  }) as any;
  expect(firstFailure.state).toBe("retryable_failed");

  const secondFailure = await t.mutation(internal.authoringInternal.failJob, {
    job_id: second.job_id,
    command_id: `${second.job_id}:fail`,
    expected_revision: second.revision,
    attempt_id: second.lease.attempt_id,
    failure: {
      classification: "handler_failed",
      message: "permanent failure",
      retryable: false,
    },
  }) as any;
  expect(secondFailure.state).toBe("terminal_failed");

  const thirdSuccess = await t.mutation(internal.authoringInternal.succeedJob, {
    job_id: third.job_id,
    command_id: `${third.job_id}:succeed`,
    expected_revision: third.revision,
    attempt_id: third.lease.attempt_id,
    artifact: lexicalArtifact("7"),
  }) as any;
  expect(thirdSuccess.state).toBe("succeeded");

  const snapshot = await t.run(async (ctx) => ({
    run: await ctx.db.query("authoring_runs").withIndex("by_run_id", (q) => (
      q.eq("run_id", "concurrent-run")
    )).unique(),
    jobs: await ctx.db.query("authoring_jobs").collect(),
  }));
  expect(snapshot.run?.aggregate).toMatchObject({ state: "failed" });
  expect(
    snapshot.jobs
      .filter(({ aggregate }: any) => aggregate.run_id === "concurrent-run")
      .map(({ aggregate }: any) => aggregate.state)
      .sort(),
  ).toEqual(["retryable_failed", "succeeded", "terminal_failed"]);
});

test("cancelling one pipeline job cancels every unfinished sibling", async () => {
  const t = convexTest(schema, modules);
  const approved = await approvedLexicalPipeline(
    t,
    "cancel-run",
    ["cancel-first", "cancel-second"],
  );
  const cancelled = await t.mutation(internal.authoringInternal.cancelJob, {
    job_id: approved.jobs[0].job_id,
    command_id: "cancel-run:cancel",
    expected_revision: approved.jobs[0].revision,
  }) as any;
  expect(cancelled.state).toBe("cancelled");

  const snapshot = await t.run(async (ctx) => ({
    run: await ctx.db.query("authoring_runs").withIndex("by_run_id", (q) => (
      q.eq("run_id", "cancel-run")
    )).unique(),
    jobs: await ctx.db.query("authoring_jobs").collect(),
  }));
  expect(snapshot.run?.aggregate).toMatchObject({ state: "cancelled" });
  expect(
    snapshot.jobs
      .filter(({ aggregate }: any) => aggregate.run_id === "cancel-run")
      .map(({ aggregate }: any) => aggregate.state),
  ).toEqual(["cancelled", "cancelled"]);
});

test("a failed run completes after its retry and successful sibling finish", async () => {
  const t = convexTest(schema, modules);
  const approved = await approvedLexicalPipeline(
    t,
    "retry-sibling-run",
    ["retry-first", "retry-second"],
  );
  let [first, second] = await Promise.all(
    approved.jobs.map((job: any) => startConcurrentJob(t, job)),
  );
  first = await t.mutation(internal.authoringInternal.failJob, {
    job_id: first.job_id,
    command_id: `${first.job_id}:fail`,
    expected_revision: first.revision,
    attempt_id: first.lease.attempt_id,
    failure: {
      classification: "artifact_store_failed",
      message: "temporary failure",
      retryable: true,
    },
  }) as any;
  second = await t.mutation(internal.authoringInternal.succeedJob, {
    job_id: second.job_id,
    command_id: `${second.job_id}:succeed`,
    expected_revision: second.revision,
    attempt_id: second.lease.attempt_id,
    artifact: lexicalArtifact("8"),
  }) as any;
  expect(second.state).toBe("succeeded");

  first = await t.mutation(internal.authoringInternal.retryJob, {
    job_id: first.job_id,
    command_id: `${first.job_id}:retry`,
    expected_revision: first.revision,
  }) as any;
  first = await startConcurrentJob(t, first);
  first = await t.mutation(internal.authoringInternal.succeedJob, {
    job_id: first.job_id,
    command_id: `${first.job_id}:retry-succeed`,
    expected_revision: first.revision,
    attempt_id: first.lease.attempt_id,
    artifact: lexicalArtifact("9"),
  }) as any;
  expect(first.state).toBe("succeeded");

  const run = await t.run(async (ctx) => (
    await ctx.db.query("authoring_runs").withIndex("by_run_id", (q) => (
      q.eq("run_id", "retry-sibling-run")
    )).unique()
  ));
  expect(run?.aggregate).toMatchObject({ state: "complete" });
});

test("one lease reconciliation recovers every expired sibling", async () => {
  vi.useFakeTimers();
  try {
    vi.setSystemTime(new Date("2026-09-11T20:00:00Z"));
    const t = convexTest(schema, modules);
    const approved = await approvedLexicalPipeline(
      t,
      "expired-siblings-run",
      ["expired-first", "expired-second"],
    );
    const running = await Promise.all(
      approved.jobs.map((job: any) => startConcurrentJob(t, job)),
    );
    vi.setSystemTime(Math.max(...running.map((job: any) => job.lease.expires_at)) + 1);

    expect(
      await t.mutation(internal.authoringInternal.reconcileExpiredLeases, {}),
    ).toBe(2);

    const snapshot = await t.run(async (ctx) => ({
      run: await ctx.db.query("authoring_runs").withIndex("by_run_id", (q) => (
        q.eq("run_id", "expired-siblings-run")
      )).unique(),
      jobs: await ctx.db.query("authoring_jobs").collect(),
    }));
    expect(snapshot.run?.aggregate).toMatchObject({ state: "failed" });
    expect(
      snapshot.jobs
        .filter(({ aggregate }: any) => aggregate.run_id === "expired-siblings-run")
        .map(({ aggregate }: any) => aggregate.state),
    ).toEqual(["retryable_failed", "retryable_failed"]);
  } finally {
    vi.useRealTimers();
  }
});
