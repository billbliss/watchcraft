import { ConvexError, v } from "convex/values";
import { internalAction, internalQuery, internalMutation, mutation, type MutationCtx } from "./_generated/server";
import { portalIdentity } from "./portal";
import type { ProjectExecution } from "../packages/authoring-pipeline/src/project-execution";
import { internal } from "./_generated/api";
const phases = ["processing", "terminology", "normalization", "compilation", "preview", "ready", "pull_request"];
const leaseMs = 120_000;
async function workflow(ctx: MutationCtx, executionId: string) {
  return ctx.db.query("portal_workflows").withIndex("by_execution", q => q.eq("execution_id", executionId)).unique();
}
export async function enqueueWorkflow(ctx: MutationCtx, execution: ProjectExecution) {
  if (await workflow(ctx, execution.execution_id)) return;
  await ctx.db.insert("portal_workflows", { execution_id: execution.execution_id, phase: "processing", state: "queued", lease_until: 0, updated_at: Date.now() });
}
export const requestPullRequest = mutation({
  args: { executionId: v.string() },
  handler: async (ctx, args) => {
    if (!await portalIdentity(ctx)) throw new ConvexError("Portal access denied.");
    const row = await workflow(ctx, args.executionId);
    if (!row?.preview_url) throw new ConvexError("Wait for the collection preview to finish.");
    if (row.pull_request_url || row.phase === "pull_request") return;
    if (row.state !== "ready") throw new ConvexError("This collection is still being prepared.");
    await ctx.db.patch(row._id, { phase: "pull_request", state: "queued", runner_id: undefined, lease_until: 0, updated_at: Date.now() });
  },
});
export const retry = mutation({
  args: { executionId: v.string() },
  handler: async (ctx, args) => {
    if (!await portalIdentity(ctx)) throw new ConvexError("Portal access denied.");
    const row = await workflow(ctx, args.executionId);
    if (!row || (row.state !== "failed" && !(row.state === "running" && row.lease_until < Date.now()))) throw new ConvexError("This workflow does not need a retry.");
    await ctx.db.patch(row._id, { state: "queued", runner_id: undefined, lease_until: 0, updated_at: Date.now() });
  },
});
export const claim = internalMutation({
  args: { runner_id: v.string() },
  handler: async (ctx, args) => {
    if (!/^[a-zA-Z0-9-]{1,100}$/.test(args.runner_id)) throw new Error("Invalid runner.");
    const row = await ctx.db.query("portal_workflows").withIndex("by_state_lease", q => q.eq("state", "queued")).first()
      ?? await ctx.db.query("portal_workflows").withIndex("by_state_lease", q => q.eq("state", "running").lt("lease_until", Date.now())).first();
    if (!row) return { workflow: null };
    const record = await ctx.db.query("authoring_project_executions").withIndex("by_execution_id", q => q.eq("execution_id", row.execution_id)).unique();
    const execution = record?.aggregate as ProjectExecution | undefined;
    if (!execution || !["approved", "running", "failed", "complete"].includes(execution.state)) {
      await ctx.db.patch(row._id, { state: "failed", updated_at: Date.now() });
      return { workflow: null };
    }
    await ctx.db.patch(row._id, { state: "running", runner_id: args.runner_id, lease_until: Date.now() + leaseMs, updated_at: Date.now() });
    return { workflow: { ...row, runner_id: args.runner_id, execution } };
  },
});
export const update = internalMutation({
  args: { execution_id: v.string(), runner_id: v.string(), phase: v.string(),
    event: v.union(v.literal("heartbeat"), v.literal("complete"), v.literal("failed")),
    error_message: v.optional(v.string()),
    compilation_job_id: v.optional(v.string()), preview_url: v.optional(v.string()), preview_branch: v.optional(v.string()), preview_commit: v.optional(v.string()), pull_request_url: v.optional(v.string()) },
  handler: async (ctx, args) => {
    const row = await workflow(ctx, args.execution_id);
    if (!row || row.state !== "running" || row.runner_id !== args.runner_id || row.phase !== args.phase || row.lease_until < Date.now()) throw new Error("Workflow claim expired or changed.");
    if (args.event === "heartbeat") { await ctx.db.patch(row._id, { lease_until: Date.now() + leaseMs, updated_at: Date.now() }); return { updated: true }; }
    if (args.event === "failed") { await ctx.db.patch(row._id, { failure: { message: (args.error_message ?? "The worker stopped without an error message.").slice(0, 2000), occurred_at: Date.now() }, state: "failed", runner_id: undefined, lease_until: 0, updated_at: Date.now() }); return { updated: true }; }
    const record = await ctx.db.query("authoring_project_executions").withIndex("by_execution_id", q => q.eq("execution_id", row.execution_id)).unique();
    const execution = record?.aggregate as ProjectExecution | undefined;
    if (!execution || execution.state !== "complete") throw new Error("Finish the approved item processing before assembling the collection.");
    let outputs: Record<string, string> = {};
    if (row.phase === "compilation") {
      const job = args.compilation_job_id ? await ctx.db.query("authoring_jobs").withIndex("by_job_id", q => q.eq("job_id", args.compilation_job_id!)).unique() : null;
      if (job?.aggregate.state !== "succeeded" || job.aggregate.result?.artifact_kind !== "collection-compilation" || !job.aggregate.spec.inputs.some((input: any) => input.digest === execution.plan.artifact.digest)) throw new Error("A verified compilation from this plan is required.");
      outputs.compilation_job_id = args.compilation_job_id!;
    }
    if (row.phase === "preview") {
      const project = await ctx.db.query("authoring_catalog_projects").withIndex("by_project_id", q => q.eq("project_id", execution.project.project_id)).unique();
      const collectionId = project?.aggregate.publication.collection_id;
      if (!row.compilation_job_id || !args.preview_commit || !/^[a-f0-9]{40}$/.test(args.preview_commit) || !args.preview_branch || !/^codex\/portal-[a-f0-9]{24}$/.test(args.preview_branch) || args.preview_url !== `https://raw.githubusercontent.com/billbliss/watchcraft-collections/${args.preview_commit}/collections/${collectionId}/collection.json`) throw new Error("A pinned collection preview is required.");
      outputs = { preview_url: args.preview_url, preview_branch: args.preview_branch, preview_commit: args.preview_commit };
    }
    if (row.phase === "pull_request") {
      if (!args.pull_request_url || !/^https:\/\/github.com\/billbliss\/watchcraft-collections\/pull\/[1-9][0-9]*$/.test(args.pull_request_url)) throw new Error("Invalid pull request URL.");
      outputs.pull_request_url = args.pull_request_url;
    }
    const next = row.phase === "pull_request" ? "ready" : phases[phases.indexOf(row.phase) + 1];
    if (!next) throw new Error("Invalid workflow phase.");
    await ctx.db.patch(row._id, { ...outputs, phase: next, state: next === "ready" ? "ready" : "queued", runner_id: undefined, lease_until: 0, updated_at: Date.now() });
    return { updated: true };
  },
});

// Public repository metadata is checked on the hosted backend, independently of workers.
export const pendingPullRequests = internalQuery({
  args: {},
  handler: async (ctx) => (await ctx.db.query("portal_workflows")
    .withIndex("by_state_lease", q => q.eq("state", "ready")).collect())
    .filter(row => row.pull_request_url && row.pull_request_status !== "merged")
    .sort((a, b) => (a.pull_request_checked_at ?? 0) - (b.pull_request_checked_at ?? 0))
    .slice(0, 3),
});
export const recordPullRequestStatus = internalMutation({
  args: { executionId: v.string(), url: v.string(), head: v.string(),
    status: v.union(v.literal("open"), v.literal("closed"), v.literal("merged")),
    mergedAt: v.optional(v.number()) },
  handler: async (ctx, args) => {
    const row = await workflow(ctx, args.executionId);
    if (!row || row.pull_request_url !== args.url || row.preview_commit !== args.head) return;
    await ctx.db.patch(row._id, { pull_request_status: args.status,
      pull_request_checked_at: Date.now(), pull_request_merged_at: args.mergedAt });
  },
});
export const syncPullRequests = internalAction({
  args: {},
  handler: async (ctx) => {
    const rows = await ctx.runQuery(internal.portalWorkflows.pendingPullRequests, {});
    const results: { executionId: string; result: string }[] = [];
    for (const row of rows) {
      const match = row.pull_request_url?.match(/^https:\/\/github.com\/billbliss\/watchcraft-collections\/pull\/([1-9][0-9]*)$/);
      if (!match) continue;
      const response = await fetch(`https://api.github.com/repos/billbliss/watchcraft-collections/pulls/${match[1]}`, {
        headers: { Accept: "application/vnd.github+json", "User-Agent": "Watchcraft-portal" },
      });
      // Leave existing status intact on outages or rate limits; try again next cycle.
      if (!response.ok) { results.push({ executionId: row.execution_id, result: `GitHub HTTP ${response.status}` }); continue; }
      const pr = await response.json();
      if (pr.html_url !== row.pull_request_url || pr.head?.sha !== row.preview_commit ||
          pr.base?.repo?.full_name !== "billbliss/watchcraft-collections" || pr.base?.ref !== "main" ||
          !["open", "closed"].includes(pr.state)) continue;
      const mergedAt = pr.merged_at ? Date.parse(pr.merged_at) : undefined;
      if (pr.merged && (mergedAt === undefined || !Number.isFinite(mergedAt))) continue;
      await ctx.runMutation(internal.portalWorkflows.recordPullRequestStatus, {
        executionId: row.execution_id, url: pr.html_url, head: pr.head.sha,
        status: pr.merged ? "merged" : pr.state, ...(pr.merged ? { mergedAt } : {}),
      });
      results.push({ executionId: row.execution_id, result: pr.merged ? "merged" : pr.state });
    }
    return results;
  },
});
