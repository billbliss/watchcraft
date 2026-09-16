import { enqueueWorkflow } from "./portalWorkflows";
import { ConvexError, v } from "convex/values";
import { mutation, query, type QueryCtx } from "./_generated/server";
import { internal } from "./_generated/api";
import type { CatalogProject } from "../packages/authoring-pipeline/src/project-contracts";
import type { ProjectExecution } from "../packages/authoring-pipeline/src/project-execution";
import type { AuthoringJob } from "../packages/authoring-pipeline/src/contracts";

export async function portalIdentity(ctx: Pick<QueryCtx, "auth">) {
  const identity = await ctx.auth.getUserIdentity();
  const userId = process.env.CLERK_PORTAL_USER_ID;
  const issuer = process.env.CLERK_JWT_ISSUER_DOMAIN;
  return identity && userId && issuer && identity.subject === userId && identity.issuer === issuer
    ? identity : null;
}

function object(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}
function amount(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : null;
}
function estimateSummary(execution: ProjectExecution) {
  const wrapper = object(execution.estimate);
  const fullPlan = object(wrapper.plan_estimate);
  const estimate = wrapper.plan_estimate ? fullPlan : wrapper;
  const projection = object(estimate.projection);
  const time = object(projection.time);
  const cost = object(projection.cost);
  return {
    expectedSeconds: amount(time.expected_seconds ?? estimate.expected_seconds),
    highSeconds: amount(time.high_seconds ?? estimate.high_seconds),
    expectedCostUsd: amount(cost.expected_usd ?? estimate.expected_cost_usd),
    highCostUsd: amount(cost.high_usd ?? estimate.high_cost_usd),
    confidence: typeof projection.confidence === "string" ? projection.confidence : null,
    fullPlanItems: wrapper.plan_estimate ? amount(wrapper.planned_items) : null,
    concurrency: amount(time.assumed_concurrency ?? estimate.assumed_concurrency),
    caveats: Array.isArray(estimate.caveats) ? estimate.caveats.filter((item): item is string => typeof item === "string") : [],
  };
}

export const access = query({
  args: {},
  returns: v.object({ authorized: v.boolean() }),
  handler: async (ctx) => ({ authorized: Boolean(await portalIdentity(ctx)) }),
});

export const overview = query({
  args: {},
  handler: async (ctx) => {
    if (!await portalIdentity(ctx)) throw new ConvexError("Portal access denied.");
    // Filter via indexes before limiting: completed work cannot crowd out the review queue.
    const executionList = (state: string, count: number, order: "asc" | "desc") => ctx.db
      .query("authoring_project_executions").withIndex("by_state_updated", (q) => q.eq("aggregate.state", state))
      .order(order).take(count + 1);
    const [pending, accepted, running, completed, failed, jobGroups] = await Promise.all([
      executionList("awaiting_approval", 50, "asc"),
      executionList("approved", 50, "asc"),
      executionList("running", 50, "desc"),
      executionList("complete", 20, "desc"),
      executionList("failed", 50, "desc"),
      Promise.all(["ready", "dispatch_pending", "dispatched", "claimed", "running"].map((state) => ctx.db
        .query("authoring_jobs").withIndex("by_state_updated", (q) => q.eq("aggregate.state", state))
        .order("desc").take(101))),
    ]);
    const executions = [...pending, ...accepted, ...running, ...completed, ...failed];
    const projectIds = [...new Set(executions.map((record) => record.project_id))];
    const projects = await Promise.all(projectIds.map((id) => ctx.db.query("authoring_catalog_projects")
      .withIndex("by_project_id", (q) => q.eq("project_id", id)).unique()));
    const projectTitles = new Map(projects.filter((p) => p !== null).map((p) => [p.project_id, (p.aggregate as CatalogProject).metadata.title]));
    const requesterLabels = new Map(await Promise.all(executions.map(async record => {
      const requests = await ctx.db.query("collection_requests").withIndex("by_execution", q => q.eq("execution_id", record.execution_id)).take(50);
      const receipts = (await Promise.all(requests.map(request => ctx.db.query("collection_request_receipts").withIndex("by_request", q => q.eq("request_id", request._id)).take(100)))).flat();
      return [record.execution_id, receipts.length ? [...new Set(receipts.map(receipt => receipt.owner_label ?? "Anonymous"))].join(", ") : null] as const;
    })));
    const workflows = await Promise.all(executions.map(record => ctx.db.query("portal_workflows").withIndex("by_execution", q => q.eq("execution_id", record.execution_id)).unique()));
    const queuedWorkflows = await ctx.db.query("portal_workflows").withIndex("by_state_lease", q => q.eq("state", "queued")).take(101);
    const activeTitles = workflows.filter(w => w?.state === "running" && w.lease_until > Date.now()).map(w => {
      const record = executions.find(record => record.execution_id === w!.execution_id);
      return record ? projectTitles.get(record.project_id) ?? record.project_id : "current collection";
    });
    const summary = (record: typeof executions[number]) => {
      const execution = record.aggregate as ProjectExecution;
      const project = projects.find(p => p?.project_id === record.project_id)?.aggregate as CatalogProject | undefined;
      const entries = project?.revision === execution.project.revision ? object(project.iterator.configuration).entries : [];
      const metadata = new Map<string, Record<string, any>>((Array.isArray(entries) ? entries : []).map(entry => [String(object(entry).item_id), object(entry)]));
      return {
        workflow: workflows.find(w => w?.execution_id === record.execution_id) ?? null,
        queuePosition: queuedWorkflows.some(w => w.execution_id === record.execution_id) ? queuedWorkflows.findIndex(w => w.execution_id === record.execution_id) + 1 : null,
        waitingOn: activeTitles.join(", ") || null,
        id: record.execution_id, projectId: record.project_id,
        title: projectTitles.get(record.project_id) ?? record.project_id,
        state: execution.state, revision: execution.revision, approvalSha256: execution.approval_sha256,
        submittedAt: execution.created_at, submittedBy: requesterLabels.get(record.execution_id) ?? record.submitted_by ?? null,
        submitterIsCli: !requesterLabels.get(record.execution_id) && Boolean(record.submitted_by),
        updatedAt: record.updated_at, projectRevision: execution.project.revision,
        completed: execution.items.filter((item) => item.state === "succeeded").length,
        total: execution.items.length, concurrency: execution.policy.concurrency,
        selectedItems: execution.items.map(item => ({ id: item.item_id, title: typeof metadata.get(item.item_id)?.title === "string" ? metadata.get(item.item_id)!.title as string : null,
          url: /^youtube:[A-Za-z0-9_-]{11}$/.test(item.item_id) ? `https://www.youtube.com/watch?v=${item.item_id.slice(8)}` : null })),
        estimate: estimateSummary(execution),
      };
    };
    const jobProjects = new Map(executions.flatMap((record) => (record.aggregate as ProjectExecution).items
      .flatMap((item) => item.job_ids.map((id) => [id, record.project_id] as const))));
    const jobVideos = new Map(executions.flatMap(record => {
      const items = new Map(summary(record).selectedItems.map(item => [item.id, item]));
      return (record.aggregate as ProjectExecution).items.flatMap(item =>
        item.job_ids.map(id => [id, items.get(item.item_id)!] as const));
    }));
    const jobs = jobGroups.flat().sort((a, b) => b.aggregate.updated_at - a.aggregate.updated_at);
    return {
      pending: pending.slice(0, 50).map(summary), hasMorePending: pending.length > 50,
      accepted: accepted.slice(0, 50).map(summary), hasMoreAccepted: accepted.length > 50,
      running: running.slice(0, 50).map(summary), hasMoreRunning: running.length > 50,
      failed: failed.slice(0, 50).map(summary),
      completed: completed.slice(0, 20).map(summary), hasMoreCompleted: completed.length > 20,
      activeJobs: jobs.slice(0, 100).map((record) => {
        const job = record.aggregate as AuthoringJob;
        const projectId = jobProjects.get(job.job_id);
        const attempt = job.attempts.at(-1);
        const progress = attempt?.state === "running" || attempt?.state === "claimed" ? attempt.progress : undefined;
        return {
          id: job.job_id, title: job.spec.artifact_kind.replaceAll("-", " "),
          videoTitle: jobVideos.get(job.job_id)?.title ?? null,
          videoId: jobVideos.get(job.job_id)?.id ?? null,
          project: projectId ? projectTitles.get(projectId) ?? projectId : job.spec.source.media_asset_id,
          state: job.state, updatedAt: job.updated_at, startedAt: attempt?.started_at ?? null,
          progress: progress ? { phase: progress.phase, completed: progress.completed, total: progress.total ?? null, unit: progress.unit, updatedAt: progress.updated_at } : null,
        };
      }),
      hasMoreJobs: jobs.length > 100,
    };
  },
});

export const review = mutation({
  args: {
    executionId: v.string(), commandId: v.string(), expectedRevision: v.number(), approvalSha256: v.string(),
    decision: v.union(v.literal("accept"), v.literal("reject")),
  },
  returns: v.object({ decision: v.union(v.literal("accept"), v.literal("reject")), executionId: v.string() }),
  handler: async (ctx, args) => {
    const identity = await portalIdentity(ctx);
    if (!identity) throw new ConvexError("Portal access denied.");
    if (!args.commandId || args.commandId.length > 200) throw new ConvexError("Invalid review request.");
    const previous = await ctx.db.query("portal_review_events").withIndex("by_command", (q) => q.eq("command_id", args.commandId)).unique();
    if (previous) {
      if (previous.execution_id !== args.executionId || previous.decision !== args.decision
        || previous.expected_revision !== args.expectedRevision || previous.approval_sha256 !== args.approvalSha256
        || previous.actor !== identity.tokenIdentifier) throw new ConvexError("This review request was already used for another decision.");
      return { decision: previous.decision, executionId: previous.execution_id };
    }
    const stored = await ctx.db.query("authoring_project_executions").withIndex("by_execution_id", (q) => q.eq("execution_id", args.executionId)).unique();
    if (!stored) throw new ConvexError("This submission no longer exists.");
    const execution = stored.aggregate as ProjectExecution;
    if (execution.state !== "awaiting_approval" || execution.revision !== args.expectedRevision
      || execution.approval_sha256 !== args.approvalSha256) {
      throw new ConvexError("This submission changed or was already reviewed. Refresh the queue before deciding.");
    }
    try {
      if (args.decision === "accept") {
        await enqueueWorkflow(ctx, execution);
        await ctx.runMutation(internal.authoringInternal.approveProjectExecution, {
          execution_id: args.executionId, command_id: `portal:${args.commandId}`, expected_revision: args.expectedRevision,
          approval_sha256: args.approvalSha256, actor: identity.tokenIdentifier,
        });
      } else {
        await ctx.runMutation(internal.authoringInternal.cancelProjectExecution, {
          execution_id: args.executionId, command_id: `portal:${args.commandId}`, expected_revision: args.expectedRevision,
        });
      }
    } catch {
      throw new ConvexError("The submission could not be reviewed. Its project or processing plan may have changed; refresh and try again.");
    }
    await ctx.db.insert("portal_review_events", {
      command_id: args.commandId, execution_id: args.executionId, decision: args.decision,
      expected_revision: args.expectedRevision, approval_sha256: args.approvalSha256,
      actor: identity.tokenIdentifier, actor_label: identity.email ?? identity.name ?? identity.subject, recorded_at: Date.now(),
    });
    return { decision: args.decision, executionId: args.executionId };
  },
});

export const failureDetails = query({
  args: { executionId: v.string() },
  handler: async (ctx, args) => {
    if (!await portalIdentity(ctx)) throw new ConvexError("Portal access denied.");
    const record = await ctx.db.query("authoring_project_executions").withIndex("by_execution_id", q => q.eq("execution_id", args.executionId)).unique();
    if (!record) return null;
    const execution = record.aggregate as ProjectExecution;
    const project = await ctx.db.query("authoring_catalog_projects").withIndex("by_project_id", q => q.eq("project_id", record.project_id)).unique();
    const entries = project?.aggregate.revision === execution.project.revision ? object(project.aggregate.iterator.configuration).entries : [];
    const titles = new Map<string, string>((Array.isArray(entries) ? entries : []).map(entry => [String(entry.item_id), String(entry.title || entry.item_id)]));
    const workflow = await ctx.db.query("portal_workflows").withIndex("by_execution", q => q.eq("execution_id", args.executionId)).unique();
    const stageKinds: Record<string, string> = { terminology: "terminology-resolution", normalization: "topic-normalization", compilation: "collection-compilation" };
    const candidates = (await Promise.all(["terminal_failed", "retryable_failed"].map(state => ctx.db.query("authoring_jobs")
      .withIndex("by_state_updated", q => q.eq("aggregate.state", state)).order("desc").take(100)))).flat();
    const stageJob = candidates.map(row => row.aggregate as AuthoringJob).sort((a, b) => b.updated_at - a.updated_at).find(job =>
      job.spec.artifact_kind === stageKinds[workflow?.phase ?? ""] &&
      object(job.spec.configuration).plan_job_id === execution.plan.job_id);
    const affectedId = stageJob?.failure?.message.match(/youtube:[A-Za-z0-9_-]{11}/)?.[0];
    const attempt = stageJob?.attempts.at(-1);
    const stageFailure = stageJob?.failure ? {
      message: stageJob.failure.message, occurredAt: stageJob.failure.occurred_at,
      classification: stageJob.failure.classification, jobId: stageJob.job_id,
      attempts: stageJob.attempts.length, affectedVideo: affectedId ? titles.get(affectedId) ?? affectedId : null,
      logUrl: attempt?.github_run_id && /^[0-9]+$/.test(attempt.github_run_id) ? `https://github.com/billbliss/watchcraft/actions/runs/${attempt.github_run_id}` : null,
      guidance: stageJob.failure.retryable ? "Retry this stage. Completed videos will be reused." : "This job cannot be retried unchanged. Inspect the worker log and fix the input or worker code, then create a replacement job. Completed videos will be reused.",
    } : workflow?.failure ? {
      message: workflow.failure.message, occurredAt: workflow.failure.occurred_at,
      classification: "workflow_failed", jobId: null, attempts: null, affectedVideo: null, logUrl: null,
      guidance: "Inspect this stage error before retrying. Completed videos will be reused.",
    } : null;
    // Historical snapshots repeat other items' failures; count distinct occurrences only.
    const events = await ctx.db.query("authoring_project_execution_events").withIndex("by_execution_command", q => q.eq("execution_id", args.executionId)).take(101);
    const snapshots = [...events.slice(0, 100).map(event => event.result as ProjectExecution), execution];
    return {
      completed: execution.items.filter(item => item.state === "succeeded").length,
      total: execution.items.length,
      historyLimited: events.length > 100,
      stageFailure,
      failures: execution.items.filter(item => item.state === "failed").map(item => {
        const versions = snapshots.flatMap(snapshot => snapshot.items?.filter(candidate => candidate.item_id === item.item_id) ?? []);
        const attempts = new Set(versions.flatMap(version => version.claim ? [`${version.claim.owner}:${version.claim.claimed_at}`] : []));
        const failures = new Map(versions.flatMap(version => version.failure ? [[`${version.failure.occurred_at}:${version.failure.message}`, version.failure] as const] : []));
        return { id: item.item_id, title: titles.get(item.item_id) ?? item.item_id,
          attempts: attempts.size, failureCount: failures.size,
          errors: [...failures.values()].sort((a, b) => b.occurred_at - a.occurred_at),
        };
      }),
    };
  },
});
