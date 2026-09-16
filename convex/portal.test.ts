/// <reference types="vite/client" />
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { convexTest } from "convex-test";
import { readFile } from "node:fs/promises";
import { createProjectExecution } from "../packages/authoring-pipeline/src/project-execution";
import { createAuthoringJob } from "../packages/authoring-pipeline/src/state-machine";
import { artifactKey, type ArtifactReference, type AuthoringJobSpec } from "../packages/authoring-pipeline/src/contracts";
import { api, internal } from "./_generated/api";
import schema from "./schema";

const modules = import.meta.glob(["./**/*.{ts,js}", "!./**/*.test.ts", "!./vitest.config.mts"]);
const issuer = "https://test-portal.clerk.accounts.dev";
const owner = { subject: "user_portal_owner", issuer };

beforeEach(() => {
  vi.stubEnv("CLERK_JWT_ISSUER_DOMAIN", issuer);
  vi.stubEnv("CLERK_PORTAL_USER_ID", owner.subject);
});
afterEach(() => vi.unstubAllEnvs());

test("anonymous users cannot see the link or read portal data", async () => {
  const t = convexTest(schema, modules);
  expect(await t.query(api.portal.access)).toEqual({ authorized: false });
  await expect(t.query(api.portal.overview)).rejects.toThrow("Portal access denied");
});

test("signed-in strangers and the same subject from another issuer are denied", async () => {
  const t = convexTest(schema, modules);
  for (const identity of [
    { subject: "user_someone_else", issuer, email: "owner@example.com" },
    { ...owner, issuer: "https://different.clerk.accounts.dev" },
  ]) {
    const stranger = t.withIdentity(identity);
    expect(await stranger.query(api.portal.access)).toEqual({ authorized: false });
    await expect(stranger.query(api.portal.overview)).rejects.toThrow("Portal access denied");
  }
});

test("missing configuration fails closed, including for a signed-in owner", async () => {
  const t = convexTest(schema, modules).withIdentity(owner);
  for (const setting of ["CLERK_PORTAL_USER_ID", "CLERK_JWT_ISSUER_DOMAIN"]) {
    vi.stubEnv(setting, "");
    expect(await t.query(api.portal.access)).toEqual({ authorized: false });
    await expect(t.query(api.portal.overview)).rejects.toThrow("Portal access denied");
    vi.stubEnv("CLERK_PORTAL_USER_ID", owner.subject);
    vi.stubEnv("CLERK_JWT_ISSUER_DOMAIN", issuer);
  }
});

async function seed(t: ReturnType<typeof convexTest>) {
  const project = JSON.parse(await readFile(new URL("../packages/authoring-pipeline/project/examples/current-playlist.project.json", import.meta.url), "utf8"));
  const artifact: ArtifactReference = {
    store: "r2", algorithm: "sha256", digest: "e".repeat(64), byte_length: 4096,
    media_type: "application/json", artifact_kind: "project-processing-plan",
    schema: { id: "watchcraft.project-processing-plan", version: 1 }, key: artifactKey("e".repeat(64)),
  };
  const spec: AuthoringJobSpec = {
    operation: "generate", artifact_kind: "project-processing-plan",
    output_schema: artifact.schema, handler: { id: "watchcraft.project.plan", version: "1" },
    source: { media_asset_id: `catalog-project:${project.project_id}` },
    inputs: [project.iterator.accepted_snapshot], dependencies: [], configuration: { project },
  };
  const job = { ...createAuthoringJob("plan", "plan-run", spec, "create-plan", 1000), state: "succeeded", result: artifact };
  const execution = createProjectExecution({
    execution_id: "submission", project: { project_id: project.project_id, revision: project.revision },
    plan: { job_id: job.job_id, artifact, plan_hash: "plan-hash" },
    selection: { item_ids: ["item"] }, policy: { recipe: { id: "watchcraft.youtube-video", version: "1" }, concurrency: 1 },
    estimate: { selected_items: 1, planned_items: 2, plan_estimate: {
      projection: { confidence: "low", time: { expected_seconds: 120, high_seconds: 300, assumed_concurrency: 2 }, cost: { expected_usd: 0, high_usd: .5 } }, caveats: ["Based on duration"] } },
    items: [{ item_id: "item", run_id: "item-run", job_ids: ["worker"] }],
  }, "create-submission", 1000);
  await t.run(async (ctx) => {
    await ctx.db.insert("authoring_catalog_projects", { project_id: project.project_id, current_revision: project.revision, updated_at: 1000, aggregate: project });
    await ctx.db.insert("authoring_jobs", { job_id: job.job_id, aggregate: job });
    await ctx.db.insert("authoring_project_executions", { execution_id: execution.execution_id, project_id: project.project_id, updated_at: 1000, submitted_by: "Bill", aggregate: execution });
  });
  return { execution, project, job };
}
const decision = (execution: ReturnType<typeof createProjectExecution>, choice: "accept" | "reject" = "accept") => ({
  executionId: execution.execution_id, commandId: "review-1", expectedRevision: execution.revision,
  approvalSha256: execution.approval_sha256, decision: choice,
});

test("review queues retain older pending work and include only active jobs", async () => {
  const t = convexTest(schema, modules);
  const { execution, project, job } = await seed(t);
  await t.run(async (ctx) => {
    for (let i = 0; i < 60; i++) await ctx.db.insert("authoring_project_executions", {
      execution_id: `done-${i}`, project_id: project.project_id, updated_at: 2000 + i,
      aggregate: { ...execution, execution_id: `done-${i}`, state: "complete", estimate: {}, items: execution.items.map(item => ({ ...item, state: "succeeded" })) },
    });
    for (const state of ["ready", "running", "terminal_failed", "cancelled"]) await ctx.db.insert("authoring_jobs", {
      job_id: state, aggregate: { ...job, job_id: state, state, updated_at: 3000 },
    });
  });
  const data = await t.withIdentity(owner).query(api.portal.overview);
  expect(data.pending).toHaveLength(1);
  expect(data.pending[0]).toMatchObject({ title: project.metadata.title, submittedBy: "Bill", submittedAt: 1000,
    estimate: { expectedSeconds: 120, expectedCostUsd: 0, fullPlanItems: 2, confidence: "low" } });
  expect(data.activeJobs.map(j => j.state).sort()).toEqual(["ready", "running"]);
  expect(data.completed).toHaveLength(20);
  expect(data.hasMoreCompleted).toBe(true);
  expect(data.completed[0]).toMatchObject({ submittedBy: null, estimate: { expectedSeconds: null, expectedCostUsd: null } });
});

test.each(["accept", "reject"] as const)("owner can %s once with an authenticated audit trail", async (choice) => {
  const t = convexTest(schema, modules);
  const { execution } = await seed(t);
  const operator = t.withIdentity({ ...owner, email: "owner@example.com" });
  const args = decision(execution, choice);
  expect(await operator.mutation(api.portal.review, args)).toEqual({ decision: choice, executionId: execution.execution_id });
  expect(await operator.mutation(api.portal.review, args)).toEqual({ decision: choice, executionId: execution.execution_id });
  const records = await t.run(async ctx => ({
    workflows: await ctx.db.query("portal_workflows").collect(),
    audits: await ctx.db.query("portal_review_events").collect(),
    stored: await ctx.db.query("authoring_project_executions").first(),
  }));
  expect(records.workflows).toHaveLength(choice === "accept" ? 1 : 0);
  expect(records.audits).toHaveLength(1);
  expect(records.audits[0]).toMatchObject({ actor_label: "owner@example.com", decision: choice });
  expect(records.audits[0].actor).toContain(owner.subject);
  expect(records.stored).toMatchObject({ submitted_by: "Bill", aggregate: { state: choice === "accept" ? "approved" : "cancelled" } });
  await expect(operator.mutation(api.portal.review, { ...args, decision: choice === "accept" ? "reject" : "accept" })).rejects.toThrow("already used");
  await expect(operator.mutation(api.portal.review, { ...args, commandId: "another" })).rejects.toThrow("already reviewed");
});

test("reviews fail closed and cannot approve stale or different work", async () => {
  const t = convexTest(schema, modules);
  const { execution } = await seed(t);
  const args = decision(execution);
  for (const client of [t, t.withIdentity({ ...owner, subject: "stranger" }), t.withIdentity({ ...owner, issuer: "https://other.example" })]) {
    await expect(client.mutation(api.portal.review, args)).rejects.toThrow("Portal access denied");
  }
  const operator = t.withIdentity(owner);
  await expect(operator.mutation(api.portal.review, { ...args, expectedRevision: 99 })).rejects.toThrow("already reviewed");
  await expect(operator.mutation(api.portal.review, { ...args, approvalSha256: "wrong" })).rejects.toThrow("already reviewed");
  await t.run(async ctx => {
    const project = (await ctx.db.query("authoring_catalog_projects").first())!;
    await ctx.db.patch(project._id, { current_revision: 2, aggregate: { ...project.aggregate, revision: 2 } });
  });
  await expect(operator.mutation(api.portal.review, args)).rejects.toThrow("project or processing plan may have changed");
  expect(await t.run(ctx => ctx.db.query("portal_review_events").collect())).toEqual([]);
});

test("submitter attribution survives creation and approval", async () => {
  const t = convexTest(schema, modules);
  const { execution } = await seed(t);
  const input = { ...execution, execution_id: "new-submission", items: execution.items.map(({ item_id, run_id, job_ids }) => ({ item_id, run_id, job_ids })) };
  await t.mutation(internal.authoringInternal.createProjectExecutionRecord, { command_id: "new", execution: input, submitted_by: "CLI operator" });
  const created = (await t.withIdentity(owner).query(api.portal.overview)).pending.find(item => item.id === input.execution_id)!;
  expect(created.submittedBy).toBe("CLI operator");
  await t.withIdentity(owner).mutation(api.portal.review, { executionId: created.id, commandId: "accept-new", expectedRevision: created.revision, approvalSha256: created.approvalSha256, decision: "accept" });
  expect((await t.withIdentity(owner).query(api.portal.overview)).accepted[0].submittedBy).toBe("CLI operator");
});

test("only accepted work enters processing, and only the owner can request a PR", async () => {
  const t = convexTest(schema, modules);
  const { execution } = await seed(t);
  expect(await t.mutation(internal.portalWorkflows.claim, { runner_id: "runner" })).toEqual({ workflow: null });
  await t.withIdentity(owner).mutation(api.portal.review, decision(execution));
  const claimed = await t.mutation(internal.portalWorkflows.claim, { runner_id: "runner" });
  expect(claimed.workflow).toMatchObject({ execution_id: execution.execution_id, phase: "processing" });
  expect(await t.mutation(internal.portalWorkflows.claim, { runner_id: "other" })).toEqual({ workflow: null });
  const update = { execution_id: execution.execution_id, runner_id: "runner", phase: "processing" };
  await expect(t.mutation(internal.portalWorkflows.update, { ...update, runner_id: "other", event: "heartbeat" })).rejects.toThrow("claim expired");
  await expect(t.mutation(internal.portalWorkflows.update, { ...update, event: "complete" })).rejects.toThrow("Finish the approved");
  await t.mutation(internal.portalWorkflows.update, { ...update, event: "failed" });
  await expect(t.mutation(api.portalWorkflows.retry, { executionId: execution.execution_id })).rejects.toThrow("Portal access denied");
  await t.withIdentity(owner).mutation(api.portalWorkflows.retry, { executionId: execution.execution_id });
  await expect(t.withIdentity(owner).mutation(api.portalWorkflows.requestPullRequest, { executionId: execution.execution_id })).rejects.toThrow("Wait for the collection preview");
  await t.run(async ctx => {
    const row = (await ctx.db.query("portal_workflows").first())!;
    await ctx.db.patch(row._id, { phase: "ready", state: "ready", preview_url: "https://example.test/collection.json" });
  });
  await expect(t.mutation(api.portalWorkflows.requestPullRequest, { executionId: execution.execution_id })).rejects.toThrow("Portal access denied");
  const operator = t.withIdentity(owner);
  await operator.mutation(api.portalWorkflows.requestPullRequest, { executionId: execution.execution_id });
  await operator.mutation(api.portalWorkflows.requestPullRequest, { executionId: execution.execution_id });
  expect(await t.run(ctx => ctx.db.query("portal_workflows").collect())).toMatchObject([{ phase: "pull_request", state: "queued" }]);
});

test("active job rows resolve the individual video from their execution", async () => {
  const t = convexTest(schema, modules);
  const { project, job } = await seed(t);
  await t.run(async ctx => {
    const stored = (await ctx.db.query("authoring_catalog_projects").first())!;
    await ctx.db.patch(stored._id, { aggregate: { ...project, iterator: { ...project.iterator, configuration: { entries: [{ item_id: "item", title: "A specific video" }] } } } });
    await ctx.db.insert("authoring_jobs", { job_id: "worker", aggregate: { ...job, job_id: "worker", state: "running" } });
  });
  const data = await t.withIdentity(owner).query(api.portal.overview);
  expect(data.activeJobs.find(job => job.id === "worker")).toMatchObject({ videoTitle: "A specific video", videoId: "item", project: project.metadata.title });
});

test("failure details deduplicate repeated snapshots and preserve attempt history", async () => {
  const t = convexTest(schema, modules);
  const { execution } = await seed(t);
  const claimed = { ...execution, items: execution.items.map(item => ({ ...item, state: "claimed", claim: { owner: "runner", claimed_at: 2000, expires_at: 5000 } })) };
  const failed = { ...execution, state: "failed", items: execution.items.map(item => ({ ...item, state: "failed", failure: { message: "Download failed", occurred_at: 3000 } })) };
  await t.run(async ctx => {
    const row = (await ctx.db.query("authoring_project_executions").first())!;
    await ctx.db.patch(row._id, { aggregate: failed });
    for (const [index, result] of [claimed, failed, failed].entries()) await ctx.db.insert("authoring_project_execution_events", { execution_id: execution.execution_id, command_id: `event-${index}`, command_sha256: "test", to_state: result.state, revision: index, recorded_at: 3000, result });
  });
  await expect(t.query(api.portal.failureDetails, { executionId: execution.execution_id })).rejects.toThrow("Portal access denied");
  const details = await t.withIdentity(owner).query(api.portal.failureDetails, { executionId: execution.execution_id });
  expect(details).toMatchObject({ completed: 0, total: 1, historyLimited: false, failures: [{ attempts: 1, failureCount: 1, errors: [{ message: "Download failed", occurred_at: 3000 }] }] });
});

test("collection-level failures expose the worker reason, attempts, and log", async () => {
  const t = convexTest(schema, modules);
  const { execution, job } = await seed(t);
  await t.run(async ctx => {
    await ctx.db.insert("portal_workflows", { execution_id: execution.execution_id, state: "failed", phase: "normalization", updated_at: 4000, lease_until: 0 });
    await ctx.db.insert("authoring_jobs", { job_id: "normalization", aggregate: { ...job, job_id: "normalization", state: "terminal_failed", spec: { ...job.spec, artifact_kind: "topic-normalization", configuration: { plan_job_id: execution.plan.job_id } }, failure: { classification: "analysis_dependency_invalid", message: "sections must be a list", retryable: false, occurred_at: 4000 }, attempts: [{ github_run_id: "123", state: "failed" }] } });
  });
  const result = await t.withIdentity(owner).query(api.portal.failureDetails, { executionId: execution.execution_id });
  expect(result?.stageFailure).toMatchObject({ jobId: "normalization", attempts: 1, message: "sections must be a list", logUrl: "https://github.com/billbliss/watchcraft/actions/runs/123" });
  expect(result?.stageFailure?.guidance).toContain("cannot be retried unchanged");
});

test("the newest retryable stage failure replaces an older permanent failure in diagnostics", async () => {
  const t = convexTest(schema, modules);
  const { execution, job } = await seed(t);
  await t.run(async ctx => {
    await ctx.db.insert("portal_workflows", { execution_id: execution.execution_id, state: "failed", phase: "normalization", updated_at: 5000, lease_until: 0 });
    for (const [state, time, message] of [["terminal_failed", 4000, "Old validation error"], ["retryable_failed", 5000, "Duplicate display label"]] as const) {
      await ctx.db.insert("authoring_jobs", { job_id: state, aggregate: { ...job, job_id: state, state, updated_at: time, spec: { ...job.spec, artifact_kind: "topic-normalization", configuration: { plan_job_id: execution.plan.job_id } }, failure: { classification: "normalization_provider_failed", message, retryable: state === "retryable_failed", occurred_at: time }, attempts: [] } });
    }
  });
  const result = await t.withIdentity(owner).query(api.portal.failureDetails, { executionId: execution.execution_id });
  expect(result?.stageFailure).toMatchObject({ message: "Duplicate display label", jobId: "retryable_failed", guidance: "Retry this stage. Completed videos will be reused." });
});
