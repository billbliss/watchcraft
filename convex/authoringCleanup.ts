import { v } from "convex/values";

import {
  parseAuthoringJob,
  parseAuthoringRun,
  type AuthoringRun,
} from "../packages/authoring-pipeline/src/contracts.ts";
import {
  internalMutation,
  internalQuery,
  type MutationCtx,
  type QueryCtx,
} from "./_generated/server";

const TERMINAL_RUN_STATES = new Set<AuthoringRun["state"]>([
  "complete",
  "failed",
  "cancelled",
]);
const TERMINAL_JOB_STATES = new Set(["succeeded", "terminal_failed", "cancelled"]);

function retention(request: AuthoringRun["request"]): {
  class: "ephemeral";
  expires_at: number;
} | null {
  const value = request.retention;
  if (!value || Array.isArray(value) || typeof value !== "object") return null;
  if (value.class !== "ephemeral" || typeof value.expires_at !== "number") return null;
  if (!Number.isSafeInteger(value.expires_at) || value.expires_at < 0) return null;
  return { class: "ephemeral", expires_at: value.expires_at };
}

async function runDocument(ctx: MutationCtx | QueryCtx, runId: string) {
  return ctx.db
    .query("authoring_runs")
    .withIndex("by_run_id", (query) => query.eq("run_id", runId))
    .unique();
}

async function jobDocument(ctx: MutationCtx | QueryCtx, jobId: string) {
  return ctx.db
    .query("authoring_jobs")
    .withIndex("by_job_id", (query) => query.eq("job_id", jobId))
    .unique();
}

function runSummary(run: AuthoringRun, now: number) {
  const policy = retention(run.request);
  return {
    run_id: run.run_id,
    state: run.state,
    request_kind: typeof run.request.kind === "string" ? run.request.kind : null,
    created_at: run.created_at,
    updated_at: run.updated_at,
    job_ids: run.job_ids,
    retention: policy,
    cleanup_eligible: TERMINAL_RUN_STATES.has(run.state)
      && policy !== null
      && policy.expires_at <= now,
  };
}

export const listRuns = internalQuery({
  args: {
    include_unmarked: v.boolean(),
    limit: v.number(),
  },
  returns: v.any(),
  handler: async (ctx, args) => {
    if (!Number.isSafeInteger(args.limit) || args.limit < 1 || args.limit > 100) {
      throw new TypeError("Cleanup list limit must be between 1 and 100.");
    }
    const now = Date.now();
    const storedRuns = await ctx.db.query("authoring_runs").order("desc").take(1_001);
    const scanTruncated = storedRuns.length > 1_000;
    const runs = storedRuns
      .slice(0, 1_000)
      .map((stored) => parseAuthoringRun(stored.aggregate))
      .filter((run) => TERMINAL_RUN_STATES.has(run.state))
      .map((run) => runSummary(run, now))
      .filter((run) => args.include_unmarked || run.retention !== null)
      .sort((left, right) => right.created_at - left.created_at)
      .slice(0, args.limit);
    const orphanJobs = [];
    let orphan_scan_truncated = false;
    if (args.include_unmarked) {
      const storedJobs = await ctx.db.query("authoring_jobs").order("desc").take(201);
      orphan_scan_truncated = storedJobs.length > 200;
      for (const stored of storedJobs.slice(0, 200)) {
        const job = parseAuthoringJob(stored.aggregate);
        if (!TERMINAL_JOB_STATES.has(job.state)) continue;
        if (await runDocument(ctx, job.run_id)) continue;
        orphanJobs.push({
          job_id: job.job_id,
          run_id: job.run_id,
          state: job.state,
          created_at: job.created_at,
          updated_at: job.updated_at,
          artifact: job.result,
        });
        if (orphanJobs.length >= args.limit) break;
      }
    }
    return {
      observed_at: now,
      run_scan_truncated: scanTruncated,
      orphan_job_scan_truncated: orphan_scan_truncated,
      runs,
      orphan_jobs: orphanJobs,
    };
  },
});

export const purgeRun = internalMutation({
  args: {
    run_id: v.string(),
    confirmation: v.string(),
    command_id: v.string(),
    actor: v.string(),
    allow_unmarked: v.boolean(),
  },
  returns: v.any(),
  handler: async (ctx, args) => {
    if (args.confirmation !== args.run_id) {
      throw new Error("Cleanup confirmation must exactly match the run ID.");
    }
    const replay = await ctx.db
      .query("authoring_cleanup_events")
      .withIndex("by_cleanup_command", (query) => query.eq("command_id", args.command_id))
      .unique();
    if (replay) {
      if (replay.target_kind !== "run" || replay.target_id !== args.run_id) {
        throw new Error(`Cleanup command ${args.command_id} was already used for another target.`);
      }
      return replay.result;
    }

    const storedRun = await runDocument(ctx, args.run_id);
    if (!storedRun) throw new Error(`Unknown authoring run ${args.run_id}.`);
    const run = parseAuthoringRun(storedRun.aggregate);
    if (!TERMINAL_RUN_STATES.has(run.state)) {
      throw new Error(`Run ${run.run_id} is ${run.state}; only terminal runs can be cleaned.`);
    }
    const policy = retention(run.request);
    const now = Date.now();
    if (policy && policy.expires_at > now) {
      throw new Error(
        `Run ${run.run_id} is retained until ${policy.expires_at}; it cannot be cleaned early.`,
      );
    }
    if (!policy && !args.allow_unmarked) {
      throw new Error(
        `Run ${run.run_id} has no ephemeral retention policy; use explicit unmarked cleanup authority.`,
      );
    }

    if (run.job_ids.length > 100) {
      throw new Error(`Run ${run.run_id} is too large for one bounded cleanup transaction.`);
    }
    const jobs = [];
    for (const jobId of run.job_ids) {
      const storedJob = await jobDocument(ctx, jobId);
      if (!storedJob) throw new Error(`Run ${run.run_id} references missing job ${jobId}.`);
      const job = parseAuthoringJob(storedJob.aggregate);
      if (!TERMINAL_JOB_STATES.has(job.state)) {
        throw new Error(`Job ${job.job_id} is ${job.state}; the run cannot be cleaned.`);
      }
      jobs.push({ stored: storedJob, job });
    }

    const artifacts = jobs
      .map(({ job }) => job.result)
      .filter((artifact) => artifact !== null);
    let deletedJobEvents = 0;
    for (const { stored, job } of jobs) {
      const events = await ctx.db
        .query("authoring_job_events")
        .withIndex("by_job_command", (query) => query.eq("job_id", job.job_id))
        .collect();
      for (const event of events) await ctx.db.delete(event._id);
      deletedJobEvents += events.length;
      await ctx.db.delete(stored._id);
    }
    const runEvents = await ctx.db
      .query("authoring_run_events")
      .withIndex("by_run_command", (query) => query.eq("run_id", run.run_id))
      .collect();
    for (const event of runEvents) await ctx.db.delete(event._id);
    await ctx.db.delete(storedRun._id);

    const result = {
      run_id: run.run_id,
      deleted_jobs: jobs.length,
      deleted_job_events: deletedJobEvents,
      deleted_run_events: runEvents.length,
      retained_artifacts: artifacts,
      cleaned_at: now,
    };
    await ctx.db.insert("authoring_cleanup_events", {
      command_id: args.command_id,
      target_kind: "run",
      target_id: run.run_id,
      actor: args.actor,
      recorded_at: now,
      result,
    });
    return result;
  },
});

export const purgeOrphanJob = internalMutation({
  args: {
    job_id: v.string(),
    confirmation: v.string(),
    command_id: v.string(),
    actor: v.string(),
  },
  returns: v.any(),
  handler: async (ctx, args) => {
    if (args.confirmation !== args.job_id) {
      throw new Error("Cleanup confirmation must exactly match the job ID.");
    }
    const replay = await ctx.db
      .query("authoring_cleanup_events")
      .withIndex("by_cleanup_command", (query) => query.eq("command_id", args.command_id))
      .unique();
    if (replay) {
      if (replay.target_kind !== "orphan_job" || replay.target_id !== args.job_id) {
        throw new Error(`Cleanup command ${args.command_id} was already used for another target.`);
      }
      return replay.result;
    }

    const storedJob = await jobDocument(ctx, args.job_id);
    if (!storedJob) throw new Error(`Unknown authoring job ${args.job_id}.`);
    const job = parseAuthoringJob(storedJob.aggregate);
    if (!TERMINAL_JOB_STATES.has(job.state)) {
      throw new Error(`Job ${job.job_id} is ${job.state}; only terminal jobs can be cleaned.`);
    }
    if (await runDocument(ctx, job.run_id)) {
      throw new Error(
        `Job ${job.job_id} belongs to run ${job.run_id}; clean the complete run instead.`,
      );
    }
    const events = await ctx.db
      .query("authoring_job_events")
      .withIndex("by_job_command", (query) => query.eq("job_id", job.job_id))
      .collect();
    for (const event of events) await ctx.db.delete(event._id);
    await ctx.db.delete(storedJob._id);
    const now = Date.now();
    const result = {
      job_id: job.job_id,
      missing_run_id: job.run_id,
      deleted_job_events: events.length,
      retained_artifacts: job.result ? [job.result] : [],
      cleaned_at: now,
    };
    await ctx.db.insert("authoring_cleanup_events", {
      command_id: args.command_id,
      target_kind: "orphan_job",
      target_id: job.job_id,
      actor: args.actor,
      recorded_at: now,
      result,
    });
    return result;
  },
});
