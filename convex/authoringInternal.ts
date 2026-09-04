import { v } from "convex/values";

import {
  internalMutation,
  internalQuery,
  type MutationCtx,
  type QueryCtx,
} from "./_generated/server";

import {
  canonicalJson,
  type AuthoringJob,
  type AuthoringRun,
  type JsonValue,
  jobSpecSha256,
  parseAuthoringJob,
  parseAuthoringJobSpec,
  parseAuthoringRun,
} from "../packages/authoring-pipeline/src/contracts.ts";
import {
  type RunCommand,
  applyRunCommand,
  createAuthoringRun,
} from "../packages/authoring-pipeline/src/run-state-machine.ts";
import {
  type JobCommand,
  applyJobCommand,
  createAuthoringJob,
  syntheticTranscriptJobSpec,
} from "../packages/authoring-pipeline/src/state-machine.ts";

type RunCommandWithoutRevision = RunCommand extends infer Command
  ? Command extends RunCommand
    ? Omit<Command, "expected_revision">
    : never
  : never;

async function jobDocument(ctx: MutationCtx, jobId: string) {
  return ctx.db
    .query("authoring_jobs")
    .withIndex("by_job_id", (query) => query.eq("job_id", jobId))
    .unique();
}

async function readableJobDocument(ctx: QueryCtx, jobId: string) {
  return ctx.db
    .query("authoring_jobs")
    .withIndex("by_job_id", (query) => query.eq("job_id", jobId))
    .unique();
}

async function runDocument(ctx: MutationCtx, runId: string) {
  return ctx.db
    .query("authoring_runs")
    .withIndex("by_run_id", (query) => query.eq("run_id", runId))
    .unique();
}

async function readableRunDocument(ctx: QueryCtx, runId: string) {
  return ctx.db
    .query("authoring_runs")
    .withIndex("by_run_id", (query) => query.eq("run_id", runId))
    .unique();
}

async function commandEvent(ctx: MutationCtx, jobId: string, commandId: string) {
  return ctx.db
    .query("authoring_job_events")
    .withIndex("by_job_command", (query) =>
      query.eq("job_id", jobId).eq("command_id", commandId))
    .unique();
}

async function runCommandEvent(ctx: MutationCtx, runId: string, commandId: string) {
  return ctx.db
    .query("authoring_run_events")
    .withIndex("by_run_command", (query) =>
      query.eq("run_id", runId).eq("command_id", commandId))
    .unique();
}

async function recordEvent(
  ctx: MutationCtx,
  previous: AuthoringJob | null,
  result: AuthoringJob,
  commandId: string,
  now: number,
) {
  await ctx.db.insert("authoring_job_events", {
    job_id: result.job_id,
    command_id: commandId,
    from_state: previous?.state,
    to_state: result.state,
    revision: result.revision,
    recorded_at: now,
    result,
  });
}

async function recordRunEvent(
  ctx: MutationCtx,
  previous: AuthoringRun | null,
  result: AuthoringRun,
  commandId: string,
  now: number,
) {
  await ctx.db.insert("authoring_run_events", {
    run_id: result.run_id,
    command_id: commandId,
    from_state: previous?.state,
    to_state: result.state,
    revision: result.revision,
    recorded_at: now,
    result,
  });
}

async function applyStoredCommand(
  ctx: MutationCtx,
  jobId: string,
  command: JobCommand,
  now: number,
): Promise<AuthoringJob> {
  const duplicate = await commandEvent(ctx, jobId, command.command_id);
  if (duplicate) return parseAuthoringJob(duplicate.result);

  const stored = await jobDocument(ctx, jobId);
  if (!stored) throw new Error(`Unknown authoring job ${jobId}.`);
  const previous = parseAuthoringJob(stored.aggregate);
  const next = applyJobCommand(previous, command, now);
  await ctx.db.replace(stored._id, { job_id: jobId, aggregate: next });
  await recordEvent(ctx, previous, next, command.command_id, now);
  return next;
}

async function applyStoredRunCommand(
  ctx: MutationCtx,
  runId: string,
  command: RunCommand,
  now: number,
): Promise<AuthoringRun> {
  const duplicate = await runCommandEvent(ctx, runId, command.command_id);
  if (duplicate) return parseAuthoringRun(duplicate.result);
  const stored = await runDocument(ctx, runId);
  if (!stored) throw new Error(`Unknown authoring run ${runId}.`);
  const previous = parseAuthoringRun(stored.aggregate);
  const next = applyRunCommand(previous, command, now);
  await ctx.db.replace(stored._id, { run_id: runId, aggregate: next });
  await recordRunEvent(ctx, previous, next, command.command_id, now);
  return next;
}

async function applyRunForJob(
  ctx: MutationCtx,
  job: AuthoringJob,
  command: RunCommandWithoutRevision,
  now: number,
): Promise<AuthoringRun | null> {
  const stored = await runDocument(ctx, job.run_id);
  if (!stored) return null;
  const run = parseAuthoringRun(stored.aggregate);
  return applyStoredRunCommand(ctx, run.run_id, {
    ...command,
    expected_revision: run.revision,
  } as RunCommand, now);
}

export const getSubmission = internalQuery({
  args: { job_id: v.string() },
  returns: v.any(),
  handler: async (ctx, args) => {
    const storedJob = await readableJobDocument(ctx, args.job_id);
    if (!storedJob) throw new Error(`Unknown authoring job ${args.job_id}.`);
    const job = parseAuthoringJob(storedJob.aggregate);
    const storedRun = await readableRunDocument(ctx, job.run_id);
    return {
      job,
      run: storedRun ? parseAuthoringRun(storedRun.aggregate) : null,
    };
  },
});

export const submitJob = internalMutation({
  args: {
    job_id: v.string(),
    run_id: v.string(),
    command_prefix: v.string(),
    request: v.any(),
    spec: v.any(),
  },
  returns: v.any(),
  handler: async (ctx, args) => {
    const now = Date.now();
    const spec = parseAuthoringJobSpec(args.spec);
    const createJobCommand = `${args.command_prefix}:create-job`;
    const existingJob = await jobDocument(ctx, args.job_id);
    if (existingJob) {
      const duplicate = await commandEvent(ctx, args.job_id, createJobCommand);
      if (!duplicate) throw new Error(`Authoring job ${args.job_id} already exists.`);
      const job = parseAuthoringJob(existingJob.aggregate);
      if (job.run_id !== args.run_id || job.spec_sha256 !== jobSpecSha256(spec)) {
        throw new Error(`Submission replay for ${args.job_id} does not match its original job.`);
      }
      const storedRun = await runDocument(ctx, args.run_id);
      if (!storedRun) throw new Error(`Authoring run ${args.run_id} is missing.`);
      const run = parseAuthoringRun(storedRun.aggregate);
      if (canonicalJson(run.request) !== canonicalJson(args.request as JsonValue)) {
        throw new Error(`Submission replay for ${args.job_id} does not match its original request.`);
      }
      return { job, run };
    }
    if (await runDocument(ctx, args.run_id)) {
      throw new Error(`Authoring run ${args.run_id} already exists.`);
    }

    const run = createAuthoringRun(
      args.run_id,
      args.request as { [key: string]: JsonValue },
      `${args.command_prefix}:create-run`,
      now,
    );
    await ctx.db.insert("authoring_runs", { run_id: run.run_id, aggregate: run });
    await recordRunEvent(ctx, null, run, run.last_command_id, now);

    const createdJob = createAuthoringJob(args.job_id, args.run_id, spec, createJobCommand, now);
    await ctx.db.insert("authoring_jobs", { job_id: createdJob.job_id, aggregate: createdJob });
    await recordEvent(ctx, null, createdJob, createJobCommand, now);
    const job = await applyStoredCommand(ctx, createdJob.job_id, {
      type: "request_approval",
      command_id: `${args.command_prefix}:request-approval`,
      expected_revision: createdJob.revision,
    }, now);
    const plannedRun = await applyStoredRunCommand(ctx, run.run_id, {
      type: "plan",
      command_id: `${args.command_prefix}:plan-run`,
      expected_revision: run.revision,
      source_snapshot: null,
      plan: null,
      approval_sha256: job.spec_sha256,
      job_ids: [job.job_id],
    }, now);
    return { job, run: plannedRun };
  },
});

export const approveSubmission = internalMutation({
  args: {
    job_id: v.string(),
    command_id: v.string(),
    expected_revision: v.number(),
    actor: v.string(),
    spec_sha256: v.string(),
  },
  returns: v.any(),
  handler: async (ctx, args) => {
    const now = Date.now();
    const job = await applyStoredCommand(ctx, args.job_id, {
      type: "approve",
      command_id: `${args.command_id}:job`,
      expected_revision: args.expected_revision,
      actor: args.actor,
      spec_sha256: args.spec_sha256,
    }, now);
    const run = await applyRunForJob(ctx, job, {
      type: "approve",
      command_id: `${args.command_id}:run`,
      actor: args.actor,
      approval_sha256: args.spec_sha256,
    }, now);
    return { job, run };
  },
});

export const createJob = internalMutation({
  args: {
    job_id: v.string(),
    run_id: v.string(),
    command_id: v.string(),
    spec: v.any(),
  },
  returns: v.any(),
  handler: async (ctx, args) => {
    const duplicate = await commandEvent(ctx, args.job_id, args.command_id);
    if (duplicate) return parseAuthoringJob(duplicate.result);
    if (await jobDocument(ctx, args.job_id)) {
      throw new Error(`Authoring job ${args.job_id} already exists.`);
    }
    const now = Date.now();
    const created = createAuthoringJob(
      args.job_id,
      args.run_id,
      parseAuthoringJobSpec(args.spec),
      args.command_id,
      now,
    );
    await ctx.db.insert("authoring_jobs", { job_id: args.job_id, aggregate: created });
    await recordEvent(ctx, null, created, args.command_id, now);
    return created;
  },
});

export const requestApproval = internalMutation({
  args: {
    job_id: v.string(),
    command_id: v.string(),
    expected_revision: v.number(),
  },
  returns: v.any(),
  handler: (ctx, args) => applyStoredCommand(ctx, args.job_id, {
    type: "request_approval",
    ...args,
  }, Date.now()),
});

export const approveJob = internalMutation({
  args: {
    job_id: v.string(),
    command_id: v.string(),
    expected_revision: v.number(),
    actor: v.string(),
    spec_sha256: v.string(),
  },
  returns: v.any(),
  handler: (ctx, args) => applyStoredCommand(ctx, args.job_id, {
    type: "approve",
    ...args,
  }, Date.now()),
});

export const requestDispatch = internalMutation({
  args: {
    job_id: v.string(),
    command_id: v.string(),
    expected_revision: v.number(),
  },
  returns: v.any(),
  handler: (ctx, args) => applyStoredCommand(ctx, args.job_id, {
    type: "request_dispatch",
    ...args,
  }, Date.now()),
});

export const recordDispatch = internalMutation({
  args: {
    job_id: v.string(),
    command_id: v.string(),
    expected_revision: v.number(),
    generation: v.number(),
    github_run_id: v.string(),
    github_run_url: v.string(),
  },
  returns: v.any(),
  handler: async (ctx, args) => {
    const now = Date.now();
    const job = await applyStoredCommand(ctx, args.job_id, {
      type: "record_dispatch",
      ...args,
    }, now);
    await applyRunForJob(ctx, job, {
      type: "start",
      command_id: `${args.command_id}:run`,
    }, now);
    return job;
  },
});

export const cancelJob = internalMutation({
  args: {
    job_id: v.string(),
    command_id: v.string(),
    expected_revision: v.number(),
  },
  returns: v.any(),
  handler: async (ctx, args) => {
    const now = Date.now();
    const job = await applyStoredCommand(ctx, args.job_id, {
      type: "cancel",
      ...args,
    }, now);
    await applyRunForJob(ctx, job, {
      type: "cancel",
      command_id: `${args.command_id}:run`,
    }, now);
    return job;
  },
});

export const retryJob = internalMutation({
  args: {
    job_id: v.string(),
    command_id: v.string(),
    expected_revision: v.number(),
  },
  returns: v.any(),
  handler: async (ctx, args) => {
    const now = Date.now();
    const job = await applyStoredCommand(ctx, args.job_id, {
      type: "retry",
      ...args,
    }, now);
    await applyRunForJob(ctx, job, {
      type: "retry",
      command_id: `${args.command_id}:run`,
    }, now);
    return job;
  },
});

export const prepareSmokeJob = internalMutation({
  args: {
    job_id: v.string(),
    run_id: v.string(),
    command_prefix: v.string(),
    github_run_id: v.string(),
    github_run_url: v.string(),
  },
  returns: v.any(),
  handler: async (ctx, args) => {
    const now = Date.now();
    const createCommandId = `${args.command_prefix}:create`;
    let stored = await jobDocument(ctx, args.job_id);
    if (!stored) {
      const created = createAuthoringJob(
        args.job_id,
        args.run_id,
        syntheticTranscriptJobSpec(),
        createCommandId,
        now,
      );
      await ctx.db.insert("authoring_jobs", { job_id: args.job_id, aggregate: created });
      await recordEvent(ctx, null, created, createCommandId, now);
      stored = await jobDocument(ctx, args.job_id);
    }
    if (!stored) throw new Error("The smoke job could not be created.");

    let job = parseAuthoringJob(stored.aggregate);
    if (job.spec.handler.id !== "watchcraft.transcript.synthetic") {
      throw new Error(`Job ID ${args.job_id} already belongs to a different specification.`);
    }
    if (job.state === "proposed") {
      job = await applyStoredCommand(ctx, job.job_id, {
        type: "request_approval",
        command_id: `${args.command_prefix}:request-approval`,
        expected_revision: job.revision,
      }, now);
    }
    if (job.state === "awaiting_approval") {
      job = await applyStoredCommand(ctx, job.job_id, {
        type: "approve",
        command_id: `${args.command_prefix}:approve`,
        expected_revision: job.revision,
        actor: "github-actions:manual-dispatch",
        spec_sha256: job.spec_sha256,
      }, now);
    }
    if (job.state === "ready") {
      job = await applyStoredCommand(ctx, job.job_id, {
        type: "request_dispatch",
        command_id: `${args.command_prefix}:request-dispatch`,
        expected_revision: job.revision,
      }, now);
    }
    if (job.state === "dispatch_pending") {
      job = await applyStoredCommand(ctx, job.job_id, {
        type: "record_dispatch",
        command_id: `${args.command_prefix}:record-dispatch`,
        expected_revision: job.revision,
        generation: job.dispatch!.generation,
        github_run_id: args.github_run_id,
        github_run_url: args.github_run_url,
      }, now);
    }
    if (job.state !== "dispatched") {
      throw new Error(`Smoke job ${job.job_id} is unexpectedly ${job.state}.`);
    }
    return {
      job_id: job.job_id,
      spec_sha256: job.spec_sha256,
      dispatch_generation: job.dispatch!.generation,
      revision: job.revision,
    };
  },
});

export const claimJob = internalMutation({
  args: {
    job_id: v.string(),
    command_id: v.string(),
    expected_revision: v.number(),
    attempt_id: v.string(),
    owner: v.string(),
    spec_sha256: v.string(),
    dispatch_generation: v.number(),
    lease_duration_ms: v.number(),
    github_run_id: v.optional(v.string()),
  },
  returns: v.any(),
  handler: (ctx, args) => applyStoredCommand(ctx, args.job_id, {
    type: "claim",
    command_id: args.command_id,
    expected_revision: args.expected_revision,
    attempt_id: args.attempt_id,
    owner: args.owner,
    spec_sha256: args.spec_sha256,
    generation: args.dispatch_generation,
    lease_duration_ms: args.lease_duration_ms,
    github_run_id: args.github_run_id,
  }, Date.now()),
});

export const startJob = internalMutation({
  args: {
    job_id: v.string(),
    command_id: v.string(),
    expected_revision: v.number(),
    attempt_id: v.string(),
  },
  returns: v.any(),
  handler: (ctx, args) => applyStoredCommand(ctx, args.job_id, {
    type: "start",
    command_id: args.command_id,
    expected_revision: args.expected_revision,
    attempt_id: args.attempt_id,
  }, Date.now()),
});

export const heartbeatJob = internalMutation({
  args: {
    job_id: v.string(),
    command_id: v.string(),
    expected_revision: v.number(),
    attempt_id: v.string(),
    lease_duration_ms: v.number(),
  },
  returns: v.any(),
  handler: (ctx, args) => applyStoredCommand(ctx, args.job_id, {
    type: "heartbeat",
    command_id: args.command_id,
    expected_revision: args.expected_revision,
    attempt_id: args.attempt_id,
    lease_duration_ms: args.lease_duration_ms,
  }, Date.now()),
});

export const succeedJob = internalMutation({
  args: {
    job_id: v.string(),
    command_id: v.string(),
    expected_revision: v.number(),
    attempt_id: v.string(),
    artifact: v.any(),
  },
  returns: v.any(),
  handler: async (ctx, args) => {
    const now = Date.now();
    const job = await applyStoredCommand(ctx, args.job_id, {
      type: "succeed",
      command_id: args.command_id,
      expected_revision: args.expected_revision,
      attempt_id: args.attempt_id,
      artifact: args.artifact,
    }, now);
    await applyRunForJob(ctx, job, {
      type: "succeed",
      command_id: `${args.command_id}:run`,
    }, now);
    return job;
  },
});

export const failJob = internalMutation({
  args: {
    job_id: v.string(),
    command_id: v.string(),
    expected_revision: v.number(),
    attempt_id: v.string(),
    failure: v.object({
      classification: v.string(),
      message: v.string(),
      retryable: v.boolean(),
    }),
  },
  returns: v.any(),
  handler: async (ctx, args) => {
    const now = Date.now();
    const job = await applyStoredCommand(ctx, args.job_id, {
      type: "fail",
      command_id: args.command_id,
      expected_revision: args.expected_revision,
      attempt_id: args.attempt_id,
      failure: args.failure,
    }, now);
    await applyRunForJob(ctx, job, {
      type: "fail",
      command_id: `${args.command_id}:run`,
    }, now);
    return job;
  },
});

export const reconcileExpiredLeases = internalMutation({
  args: {},
  returns: v.number(),
  handler: async (ctx) => {
    const now = Date.now();
    const storedJobs = await ctx.db.query("authoring_jobs").collect();
    let recovered = 0;
    for (const stored of storedJobs) {
      const job = parseAuthoringJob(stored.aggregate);
      if (
        (job.state === "claimed" || job.state === "running")
        && job.lease
        && job.lease.expires_at <= now
      ) {
        const expired = await applyStoredCommand(ctx, job.job_id, {
          type: "expire_lease",
          command_id: `lease-expiry:${job.lease.attempt_id}:${job.lease.expires_at}`,
          expected_revision: job.revision,
        }, now);
        await applyRunForJob(ctx, expired, {
          type: "fail",
          command_id: `lease-expiry:${job.lease.attempt_id}:${job.lease.expires_at}:run`,
        }, now);
        recovered += 1;
      }
    }
    return recovered;
  },
});
