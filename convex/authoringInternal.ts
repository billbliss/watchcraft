import { v } from "convex/values";

import {
  internalMutation,
  internalQuery,
  type MutationCtx,
  type QueryCtx,
} from "./_generated/server";

import {
  canonicalJson,
  jobSpecSha256,
  sha256Hex,
  type AuthoringJob,
  type AuthoringRun,
  type JsonValue,
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
import { resolveJobSpecAgainstRegistry } from "../packages/authoring-pipeline/src/registry.ts";
import {
  acceptCatalogProjectCandidate,
  validateCatalogProjectCapabilities,
  validateCatalogProjectSnapshot,
} from "../packages/authoring-pipeline/src/project-registry.ts";
import { activeRegistry } from "./authoringRegistry.ts";

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

async function catalogProjectDocument(
  ctx: MutationCtx | QueryCtx,
  projectId: string,
) {
  return ctx.db
    .query("authoring_catalog_projects")
    .withIndex("by_project_id", (query) => query.eq("project_id", projectId))
    .unique();
}

async function catalogProjectCommand(
  ctx: MutationCtx,
  projectId: string,
  commandId: string,
) {
  return ctx.db
    .query("authoring_catalog_project_revisions")
    .withIndex("by_project_command", (query) =>
      query.eq("project_id", projectId).eq("command_id", commandId))
    .unique();
}

function parsedJsonBytes(source: string, label: string): {
  value: unknown;
  bytes: Uint8Array;
} {
  const bytes = new TextEncoder().encode(source);
  try {
    return { value: JSON.parse(source), bytes };
  } catch {
    throw new TypeError(`${label} must be valid UTF-8 JSON.`);
  }
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

async function startRunForJob(
  ctx: MutationCtx,
  job: AuthoringJob,
  commandId: string,
  now: number,
): Promise<AuthoringRun | null> {
  const stored = await runDocument(ctx, job.run_id);
  if (!stored) return null;
  const run = parseAuthoringRun(stored.aggregate);
  if (run.state === "running") return run;
  return applyStoredRunCommand(ctx, run.run_id, {
    type: "start",
    command_id: commandId,
    expected_revision: run.revision,
  }, now);
}

async function reconcileSuccessfulRun(
  ctx: MutationCtx,
  job: AuthoringJob,
  commandId: string,
  now: number,
): Promise<AuthoringRun | null> {
  const stored = await runDocument(ctx, job.run_id);
  if (!stored) return null;
  const run = parseAuthoringRun(stored.aggregate);
  if (run.state === "complete") return run;
  if (run.state !== "running") {
    throw new Error(`Run ${run.run_id} is ${run.state} while a job succeeded.`);
  }
  const jobs = await Promise.all(run.job_ids.map((jobId) => jobDocument(ctx, jobId)));
  const allSucceeded = jobs.every(
    (storedJob) => storedJob && parseAuthoringJob(storedJob.aggregate).state === "succeeded",
  );
  if (!allSucceeded) return run;
  return applyStoredRunCommand(ctx, run.run_id, {
    type: "succeed",
    command_id: commandId,
    expected_revision: run.revision,
  }, now);
}

async function assertResolvedJobDependencies(
  ctx: MutationCtx,
  job: AuthoringJob,
): Promise<void> {
  for (const dependency of job.spec.dependencies) {
    if (!("kind" in dependency) || dependency.kind !== "job-output") continue;
    const storedDependency = await jobDocument(ctx, dependency.job_id);
    if (!storedDependency) {
      throw new Error(`Dependency job ${dependency.job_id} does not exist.`);
    }
    const upstream = parseAuthoringJob(storedDependency.aggregate);
    if (upstream.run_id !== job.run_id) {
      throw new Error(`Dependency job ${dependency.job_id} belongs to another run.`);
    }
    if (upstream.state !== "succeeded" || !upstream.result) {
      throw new Error(`Dependency job ${dependency.job_id} is ${upstream.state}; expected succeeded.`);
    }
    if (
      upstream.result.artifact_kind !== dependency.artifact_kind
      || upstream.result.schema.id !== dependency.schema.id
      || upstream.result.schema.version !== dependency.schema.version
    ) {
      throw new Error(`Dependency job ${dependency.job_id} produced an incompatible artifact.`);
    }
  }
}

export const getCatalogProject = internalQuery({
  args: { project_id: v.string() },
  returns: v.any(),
  handler: async (ctx, args) => {
    const stored = await catalogProjectDocument(ctx, args.project_id);
    if (!stored) throw new Error(`Unknown catalog project ${args.project_id}.`);
    return {
      project: validateCatalogProjectCapabilities(stored.aggregate).project,
      updated_at: stored.updated_at,
    };
  },
});

export const getCatalogProjectHistory = internalQuery({
  args: { project_id: v.string(), limit: v.number() },
  returns: v.any(),
  handler: async (ctx, args) => {
    if (!Number.isSafeInteger(args.limit) || args.limit < 1 || args.limit > 100) {
      throw new TypeError("Catalog project history limit must be between 1 and 100.");
    }
    const current = await catalogProjectDocument(ctx, args.project_id);
    if (!current) throw new Error(`Unknown catalog project ${args.project_id}.`);
    const records = await ctx.db
      .query("authoring_catalog_project_revisions")
      .withIndex("by_project_revision", (query) =>
        query.eq("project_id", args.project_id))
      .order("desc")
      .take(args.limit);
    return {
      project_id: args.project_id,
      current_revision: current.current_revision,
      revisions: records.map((record) => ({
        revision: record.revision,
        transition: record.transition,
        actor: record.actor,
        command_id: record.command_id,
        candidate_job_id: record.candidate_job_id ?? null,
        recorded_at: record.recorded_at,
        accepted_snapshot: record.aggregate.iterator?.accepted_snapshot ?? null,
      })),
    };
  },
});

export const importCatalogProject = internalMutation({
  args: {
    command_id: v.string(),
    actor: v.string(),
    project: v.any(),
    accepted_snapshot_json: v.optional(v.string()),
  },
  returns: v.any(),
  handler: async (ctx, args) => {
    const project = validateCatalogProjectCapabilities(args.project).project;
    const replay = await catalogProjectCommand(
      ctx,
      project.project_id,
      args.command_id,
    );
    if (replay) {
      if (
        replay.transition !== "import" ||
        canonicalJson(replay.aggregate as JsonValue) !==
          canonicalJson(project as unknown as JsonValue)
      ) {
        throw new Error(`Catalog project command ${args.command_id} was already used.`);
      }
      return replay.result;
    }
    const existing = await catalogProjectDocument(ctx, project.project_id);
    if (existing) {
      const current = validateCatalogProjectCapabilities(existing.aggregate).project;
      if (canonicalJson(current as unknown as JsonValue) === canonicalJson(project as unknown as JsonValue)) {
        return { created: false, project: current, updated_at: existing.updated_at };
      }
      throw new Error(
        `Catalog project ${project.project_id} already exists at revision ${current.revision}.`,
      );
    }
    if (project.iterator.accepted_snapshot) {
      if (!args.accepted_snapshot_json) {
        throw new Error("The imported project's accepted snapshot bytes are required.");
      }
      const snapshot = parsedJsonBytes(
        args.accepted_snapshot_json,
        "Accepted iterator snapshot",
      );
      validateCatalogProjectSnapshot(project, snapshot.value, snapshot.bytes);
    } else if (args.accepted_snapshot_json !== undefined) {
      throw new Error("An unbound iterator snapshot cannot be imported with this project.");
    }
    const now = Date.now();
    const result = { created: true, project, updated_at: now };
    await ctx.db.insert("authoring_catalog_projects", {
      project_id: project.project_id,
      current_revision: project.revision,
      aggregate: project,
      updated_at: now,
    });
    await ctx.db.insert("authoring_catalog_project_revisions", {
      project_id: project.project_id,
      revision: project.revision,
      aggregate: project,
      transition: "import",
      actor: args.actor,
      command_id: args.command_id,
      recorded_at: now,
      result,
    });
    return result;
  },
});

export const acceptCatalogProjectSnapshot = internalMutation({
  args: {
    project_id: v.string(),
    job_id: v.string(),
    expected_revision: v.number(),
    command_id: v.string(),
    actor: v.string(),
    snapshot_json: v.string(),
  },
  returns: v.any(),
  handler: async (ctx, args) => {
    const replay = await catalogProjectCommand(ctx, args.project_id, args.command_id);
    if (replay) {
      const replaySnapshot = parsedJsonBytes(
        args.snapshot_json,
        "Iterator candidate snapshot",
      );
      const replayReference = replay.result?.accepted_snapshot;
      if (
        replay.transition !== "accept-snapshot" ||
        replay.candidate_job_id !== args.job_id ||
        args.expected_revision !== replay.revision - 1 ||
        !replayReference ||
        replayReference.byte_length !== replaySnapshot.bytes.byteLength ||
        replayReference.digest !== sha256Hex(replaySnapshot.bytes)
      ) {
        throw new Error(`Catalog project command ${args.command_id} was already used.`);
      }
      return replay.result;
    }
    const stored = await catalogProjectDocument(ctx, args.project_id);
    if (!stored) throw new Error(`Unknown catalog project ${args.project_id}.`);
    const project = validateCatalogProjectCapabilities(stored.aggregate).project;
    if (project.revision !== args.expected_revision) {
      throw new Error(
        `Stale catalog project revision ${args.expected_revision}; current revision is ${project.revision}.`,
      );
    }
    const storedJob = await jobDocument(ctx, args.job_id);
    if (!storedJob) throw new Error(`Unknown authoring job ${args.job_id}.`);
    const job = parseAuthoringJob(storedJob.aggregate);
    if (job.state !== "succeeded" || !job.result) {
      throw new Error(`Iterator job ${job.job_id} is ${job.state}; expected succeeded.`);
    }
    if (
      job.spec.artifact_kind !== "collection-iterator-snapshot" ||
      job.spec.output_schema.id !== "watchcraft.collection-iterator-snapshot" ||
      job.spec.output_schema.version !== 1
    ) {
      throw new Error(`Job ${job.job_id} did not produce an iterator snapshot.`);
    }
    const jobProject = job.spec.configuration.project;
    if (
      canonicalJson(jobProject as JsonValue) !==
      canonicalJson(project as unknown as JsonValue)
    ) {
      throw new Error(
        `Iterator job ${job.job_id} was not run against current project revision ${project.revision}.`,
      );
    }
    const snapshot = parsedJsonBytes(args.snapshot_json, "Iterator candidate snapshot");
    const accepted = acceptCatalogProjectCandidate(
      project,
      snapshot.value,
      job.result,
      snapshot.bytes,
    );
    const now = Date.now();
    const result = {
      project: accepted,
      previous_revision: project.revision,
      accepted_snapshot: accepted.iterator.accepted_snapshot,
      candidate_job_id: job.job_id,
      accepted_at: now,
      accepted_by: args.actor,
    };
    await ctx.db.replace(stored._id, {
      project_id: project.project_id,
      current_revision: accepted.revision,
      aggregate: accepted,
      updated_at: now,
    });
    await ctx.db.insert("authoring_catalog_project_revisions", {
      project_id: project.project_id,
      revision: accepted.revision,
      aggregate: accepted,
      transition: "accept-snapshot",
      actor: args.actor,
      command_id: args.command_id,
      candidate_job_id: job.job_id,
      recorded_at: now,
      result,
    });
    return result;
  },
});

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
    environment: v.optional(v.string()),
  },
  returns: v.any(),
  handler: async (ctx, args) => {
    const now = Date.now();
    const proposedSpec = parseAuthoringJobSpec(args.spec);
    const { registry_snapshot: _submittedSnapshot, ...unresolvedSpec } = proposedSpec;
    const createJobCommand = `${args.command_prefix}:create-job`;
    const existingJob = await jobDocument(ctx, args.job_id);
    if (existingJob) {
      const duplicate = await commandEvent(ctx, args.job_id, createJobCommand);
      if (!duplicate) throw new Error(`Authoring job ${args.job_id} already exists.`);
      const job = parseAuthoringJob(existingJob.aggregate);
      const { registry_snapshot: _storedSnapshot, ...storedUnresolvedSpec } = job.spec;
      if (
        job.run_id !== args.run_id
        || canonicalJson(storedUnresolvedSpec as unknown as JsonValue)
          !== canonicalJson(unresolvedSpec as unknown as JsonValue)
      ) {
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
    const environment = args.environment ?? "production";
    const registryState = await activeRegistry(ctx, environment);
    if (!registryState) {
      throw new Error(`No active authoring capability registry for ${environment}.`);
    }
    const spec = resolveJobSpecAgainstRegistry(unresolvedSpec, registryState.registry);

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

export const submitPipeline = internalMutation({
  args: {
    run_id: v.string(),
    command_prefix: v.string(),
    request: v.any(),
    jobs: v.array(v.object({ job_id: v.string(), spec: v.any() })),
    environment: v.optional(v.string()),
  },
  returns: v.any(),
  handler: async (ctx, args) => {
    if (args.jobs.length < 2) throw new Error("A pipeline requires at least two jobs.");
    const jobIds = args.jobs.map(({ job_id }) => job_id);
    if (new Set(jobIds).size !== jobIds.length) throw new Error("Pipeline job IDs must be unique.");
    const proposedJobs = args.jobs.map(({ job_id, spec }) => ({
      job_id,
      spec: parseAuthoringJobSpec(spec),
    }));
    const existingRun = await runDocument(ctx, args.run_id);
    if (existingRun) {
      const duplicate = await runCommandEvent(
        ctx,
        args.run_id,
        `${args.command_prefix}:create-run`,
      );
      if (!duplicate) throw new Error(`Authoring run ${args.run_id} already exists.`);
      const run = parseAuthoringRun(existingRun.aggregate);
      if (
        canonicalJson(run.request) !== canonicalJson(args.request as JsonValue)
        || canonicalJson(run.job_ids) !== canonicalJson(jobIds)
      ) {
        throw new Error(`Pipeline replay for ${args.run_id} does not match its original plan.`);
      }
      const jobs: AuthoringJob[] = [];
      for (const proposed of proposedJobs) {
        const storedJob = await jobDocument(ctx, proposed.job_id);
        if (!storedJob) throw new Error(`Pipeline job ${proposed.job_id} is missing.`);
        const job = parseAuthoringJob(storedJob.aggregate);
        const { registry_snapshot: _storedSnapshot, ...storedSpec } = job.spec;
        const { registry_snapshot: _submittedSnapshot, ...submittedSpec } = proposed.spec;
        if (
          canonicalJson(storedSpec as unknown as JsonValue)
          !== canonicalJson(submittedSpec as unknown as JsonValue)
        ) {
          throw new Error(`Pipeline replay for ${args.run_id} changes job ${proposed.job_id}.`);
        }
        jobs.push(job);
      }
      return { jobs, run };
    }

    const environment = args.environment ?? "production";
    const registryState = await activeRegistry(ctx, environment);
    if (!registryState) {
      throw new Error(`No active authoring capability registry for ${environment}.`);
    }
    const resolvedJobs = proposedJobs.map(({ job_id, spec }) => ({
      job_id,
      spec: resolveJobSpecAgainstRegistry(spec, registryState.registry),
    }));
    const preceding = new Set<string>();
    for (const candidate of resolvedJobs) {
      for (const dependency of candidate.spec.dependencies) {
        if (("kind" in dependency) && dependency.kind === "job-output") {
          if (!preceding.has(dependency.job_id)) {
            throw new Error(
              `Pipeline dependency ${dependency.job_id} must reference an earlier job in the run.`,
            );
          }
          const upstream = resolvedJobs.find(({ job_id }) => job_id === dependency.job_id)!;
          if (
            upstream.spec.artifact_kind !== dependency.artifact_kind
            || upstream.spec.output_schema.id !== dependency.schema.id
            || upstream.spec.output_schema.version !== dependency.schema.version
          ) {
            throw new Error(`Pipeline dependency ${dependency.job_id} has an incompatible output.`);
          }
        }
      }
      preceding.add(candidate.job_id);
    }

    const now = Date.now();
    const run = createAuthoringRun(
      args.run_id,
      args.request as { [key: string]: JsonValue },
      `${args.command_prefix}:create-run`,
      now,
    );
    await ctx.db.insert("authoring_runs", { run_id: run.run_id, aggregate: run });
    await recordRunEvent(ctx, null, run, run.last_command_id, now);

    const jobs: AuthoringJob[] = [];
    for (const candidate of resolvedJobs) {
      const created = createAuthoringJob(
        candidate.job_id,
        args.run_id,
        candidate.spec,
        `${args.command_prefix}:${candidate.job_id}:create`,
        now,
      );
      await ctx.db.insert("authoring_jobs", { job_id: created.job_id, aggregate: created });
      await recordEvent(ctx, null, created, created.last_command_id, now);
      jobs.push(await applyStoredCommand(ctx, created.job_id, {
        type: "request_approval",
        command_id: `${args.command_prefix}:${candidate.job_id}:request-approval`,
        expected_revision: created.revision,
      }, now));
    }
    const approvalSha256 = sha256Hex(canonicalJson({
      jobs: jobs.map((job) => ({ job_id: job.job_id, spec_sha256: jobSpecSha256(job.spec) })),
    }));
    const plannedRun = await applyStoredRunCommand(ctx, run.run_id, {
      type: "plan",
      command_id: `${args.command_prefix}:plan-run`,
      expected_revision: run.revision,
      source_snapshot: null,
      plan: null,
      approval_sha256: approvalSha256,
      job_ids: jobs.map((job) => job.job_id),
    }, now);
    return { jobs, run: plannedRun };
  },
});

export const approvePipeline = internalMutation({
  args: {
    run_id: v.string(),
    command_id: v.string(),
    expected_revision: v.number(),
    actor: v.string(),
    approval_sha256: v.string(),
  },
  returns: v.any(),
  handler: async (ctx, args) => {
    const now = Date.now();
    const stored = await runDocument(ctx, args.run_id);
    if (!stored) throw new Error(`Unknown authoring run ${args.run_id}.`);
    const run = parseAuthoringRun(stored.aggregate);
    const duplicate = await runCommandEvent(ctx, args.run_id, `${args.command_id}:run`);
    if (duplicate) {
      const jobs: AuthoringJob[] = [];
      for (const jobId of run.job_ids) {
        const event = await commandEvent(ctx, jobId, `${args.command_id}:${jobId}`);
        if (!event) throw new Error(`Pipeline approval replay is missing job ${jobId}.`);
        jobs.push(parseAuthoringJob(event.result));
      }
      return { jobs, run: parseAuthoringRun(duplicate.result) };
    }
    if (run.revision !== args.expected_revision) {
      throw new Error(`Stale run revision ${args.expected_revision}; current revision is ${run.revision}.`);
    }
    if (run.approval_sha256 !== args.approval_sha256) {
      throw new Error("Approval does not match the immutable pipeline plan.");
    }
    const jobs: AuthoringJob[] = [];
    for (const jobId of run.job_ids) {
      const storedJob = await jobDocument(ctx, jobId);
      if (!storedJob) throw new Error(`Pipeline job ${jobId} is missing.`);
      const job = parseAuthoringJob(storedJob.aggregate);
      jobs.push(await applyStoredCommand(ctx, jobId, {
        type: "approve",
        command_id: `${args.command_id}:${jobId}`,
        expected_revision: job.revision,
        actor: args.actor,
        spec_sha256: job.spec_sha256,
      }, now));
    }
    const approvedRun = await applyStoredRunCommand(ctx, run.run_id, {
      type: "approve",
      command_id: `${args.command_id}:run`,
      expected_revision: run.revision,
      actor: args.actor,
      approval_sha256: args.approval_sha256,
    }, now);
    return { jobs, run: approvedRun };
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
  handler: async (ctx, args) => {
    const stored = await jobDocument(ctx, args.job_id);
    if (!stored) throw new Error(`Unknown authoring job ${args.job_id}.`);
    await assertResolvedJobDependencies(ctx, parseAuthoringJob(stored.aggregate));
    return applyStoredCommand(ctx, args.job_id, {
      type: "request_dispatch",
      ...args,
    }, Date.now());
  },
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
    await startRunForJob(ctx, job, `${args.command_id}:run`, now);
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
  handler: async (ctx, args) => {
    const stored = await jobDocument(ctx, args.job_id);
    if (!stored) throw new Error(`Unknown authoring job ${args.job_id}.`);
    const job = parseAuthoringJob(stored.aggregate);
    const registeredLease = job.spec.registry_snapshot?.execution_profile.lease_duration_ms;
    return applyStoredCommand(ctx, args.job_id, {
      type: "claim",
      command_id: args.command_id,
      expected_revision: args.expected_revision,
      attempt_id: args.attempt_id,
      owner: args.owner,
      spec_sha256: args.spec_sha256,
      generation: args.dispatch_generation,
      lease_duration_ms: registeredLease ?? args.lease_duration_ms,
      github_run_id: args.github_run_id,
    }, Date.now());
  },
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
    progress: v.optional(v.any()),
    checkpoint: v.optional(v.any()),
  },
  returns: v.any(),
  handler: (ctx, args) => applyStoredCommand(ctx, args.job_id, {
    type: "heartbeat",
    command_id: args.command_id,
    expected_revision: args.expected_revision,
    attempt_id: args.attempt_id,
    lease_duration_ms: args.lease_duration_ms,
    progress: args.progress,
    checkpoint: args.checkpoint,
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
    await reconcileSuccessfulRun(ctx, job, `${args.command_id}:run`, now);
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
    const stored = await jobDocument(ctx, args.job_id);
    if (!stored) throw new Error(`Unknown authoring job ${args.job_id}.`);
    const current = parseAuthoringJob(stored.aggregate);
    const retryPolicy = current.spec.registry_snapshot?.handler.retry_policy;
    const retryable = retryPolicy
      ? args.failure.retryable
        && retryPolicy.retryable_classifications.includes(args.failure.classification)
        && current.attempts.length < retryPolicy.max_attempts
      : args.failure.retryable;
    const job = await applyStoredCommand(ctx, args.job_id, {
      type: "fail",
      command_id: args.command_id,
      expected_revision: args.expected_revision,
      attempt_id: args.attempt_id,
      failure: { ...args.failure, retryable },
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
