import {
  type ArtifactReference,
  type AuthoringJob,
  type AuthoringJobSpec,
  type JobFailure,
  jobSpecSha256,
  parseArtifactReference,
} from "./contracts.ts";

export class JobTransitionError extends Error {}

interface CommandBase {
  command_id: string;
  expected_revision: number;
}

export type JobCommand =
  | (CommandBase & { type: "request_approval" })
  | (CommandBase & { type: "approve"; actor: string; spec_sha256: string })
  | (CommandBase & { type: "request_dispatch" })
  | (CommandBase & {
      type: "record_dispatch";
      generation: number;
      github_run_id: string;
      github_run_url: string;
    })
  | (CommandBase & {
      type: "claim";
      attempt_id: string;
      owner: string;
      spec_sha256: string;
      generation: number;
      lease_duration_ms: number;
      github_run_id?: string;
    })
  | (CommandBase & { type: "start"; attempt_id: string })
  | (CommandBase & {
      type: "heartbeat";
      attempt_id: string;
      lease_duration_ms: number;
    })
  | (CommandBase & { type: "succeed"; attempt_id: string; artifact: ArtifactReference })
  | (CommandBase & { type: "fail"; attempt_id: string; failure: Omit<JobFailure, "occurred_at"> })
  | (CommandBase & { type: "cancel" })
  | (CommandBase & { type: "retry" })
  | (CommandBase & { type: "expire_lease" });

function copyJob(job: AuthoringJob): AuthoringJob {
  return JSON.parse(JSON.stringify(job)) as AuthoringJob;
}

function requireState(job: AuthoringJob, ...states: AuthoringJob["state"][]): void {
  if (!states.includes(job.state)) {
    throw new JobTransitionError(
      `Cannot apply command while job ${job.job_id} is ${job.state}; expected ${states.join(" or ")}.`,
    );
  }
}

function activeAttempt(job: AuthoringJob, attemptId: string) {
  if (!job.lease || job.lease.attempt_id !== attemptId) {
    throw new JobTransitionError(`Attempt ${attemptId} does not hold the active lease.`);
  }
  const attempt = job.attempts.find((candidate) => candidate.attempt_id === attemptId);
  if (!attempt) throw new JobTransitionError(`Attempt ${attemptId} is not recorded.`);
  return attempt;
}

export function createAuthoringJob(
  jobId: string,
  runId: string,
  spec: AuthoringJobSpec,
  commandId: string,
  now: number,
): AuthoringJob {
  if (!jobId || !runId || !commandId) throw new TypeError("Job, run, and command IDs are required.");
  const specHash = jobSpecSha256(spec);
  return {
    kind: "watchcraft.authoring-job",
    schema_version: 1,
    job_id: jobId,
    run_id: runId,
    revision: 1,
    spec,
    spec_sha256: specHash,
    idempotency_key: specHash,
    state: "proposed",
    approval: null,
    dispatch: null,
    lease: null,
    attempts: [],
    result: null,
    failure: null,
    created_at: now,
    updated_at: now,
    last_command_id: commandId,
  };
}

export function applyJobCommand(job: AuthoringJob, command: JobCommand, now: number): AuthoringJob {
  if (command.expected_revision !== job.revision) {
    throw new JobTransitionError(
      `Stale job revision ${command.expected_revision}; current revision is ${job.revision}.`,
    );
  }
  if (!command.command_id) throw new TypeError("Command ID is required.");

  const next = copyJob(job);
  switch (command.type) {
    case "request_approval":
      requireState(next, "proposed");
      next.state = "awaiting_approval";
      break;
    case "approve":
      requireState(next, "awaiting_approval");
      if (command.spec_sha256 !== next.spec_sha256) {
        throw new JobTransitionError("Approval does not match the immutable job specification.");
      }
      next.approval = { actor: command.actor, approved_at: now, spec_sha256: command.spec_sha256 };
      next.state = "ready";
      break;
    case "request_dispatch":
      requireState(next, "ready");
      next.dispatch = {
        generation: (next.dispatch?.generation ?? 0) + 1,
        requested_at: now,
      };
      next.state = "dispatch_pending";
      break;
    case "record_dispatch":
      requireState(next, "dispatch_pending");
      if (!next.dispatch || next.dispatch.generation !== command.generation) {
        throw new JobTransitionError("Dispatch generation does not match the pending request.");
      }
      next.dispatch = {
        ...next.dispatch,
        github_run_id: command.github_run_id,
        github_run_url: command.github_run_url,
        recorded_at: now,
      };
      next.state = "dispatched";
      break;
    case "claim": {
      requireState(next, "dispatched");
      if (command.spec_sha256 !== next.spec_sha256) {
        throw new JobTransitionError("Worker claimed a different job specification.");
      }
      if (!next.dispatch || command.generation !== next.dispatch.generation) {
        throw new JobTransitionError("Worker claimed a stale dispatch generation.");
      }
      if (!Number.isSafeInteger(command.lease_duration_ms) || command.lease_duration_ms <= 0) {
        throw new TypeError("Lease duration must be a positive integer.");
      }
      next.lease = {
        attempt_id: command.attempt_id,
        owner: command.owner,
        acquired_at: now,
        heartbeat_at: now,
        expires_at: now + command.lease_duration_ms,
      };
      next.attempts.push({
        attempt_id: command.attempt_id,
        owner: command.owner,
        state: "claimed",
        started_at: now,
        updated_at: now,
        github_run_id: command.github_run_id,
      });
      next.attempts = next.attempts.slice(-20);
      next.state = "claimed";
      break;
    }
    case "start": {
      requireState(next, "claimed");
      const attempt = activeAttempt(next, command.attempt_id);
      attempt.state = "running";
      attempt.updated_at = now;
      next.state = "running";
      break;
    }
    case "heartbeat": {
      requireState(next, "claimed", "running");
      const attempt = activeAttempt(next, command.attempt_id);
      if (!Number.isSafeInteger(command.lease_duration_ms) || command.lease_duration_ms <= 0) {
        throw new TypeError("Lease duration must be a positive integer.");
      }
      if (next.lease!.expires_at <= now) {
        throw new JobTransitionError("Cannot heartbeat an expired lease.");
      }
      next.lease!.heartbeat_at = now;
      next.lease!.expires_at = now + command.lease_duration_ms;
      attempt.updated_at = now;
      break;
    }
    case "succeed": {
      requireState(next, "running");
      const attempt = activeAttempt(next, command.attempt_id);
      const artifact = parseArtifactReference(command.artifact);
      if (next.lease!.expires_at <= now) {
        throw new JobTransitionError("Cannot accept success from an expired lease.");
      }
      if (
        artifact.artifact_kind !== next.spec.artifact_kind
        || artifact.schema.id !== next.spec.output_schema.id
        || artifact.schema.version !== next.spec.output_schema.version
      ) {
        throw new JobTransitionError("Artifact does not match the job's declared output.");
      }
      attempt.state = "succeeded";
      attempt.updated_at = now;
      attempt.artifact = artifact;
      next.result = artifact;
      next.failure = null;
      next.lease = null;
      next.state = "succeeded";
      break;
    }
    case "fail": {
      requireState(next, "claimed", "running");
      const attempt = activeAttempt(next, command.attempt_id);
      const failure = { ...command.failure, occurred_at: now };
      attempt.state = "failed";
      attempt.updated_at = now;
      attempt.failure = failure;
      next.failure = failure;
      next.lease = null;
      next.state = failure.retryable ? "retryable_failed" : "terminal_failed";
      break;
    }
    case "cancel":
      requireState(
        next,
        "proposed",
        "awaiting_approval",
        "ready",
        "dispatch_pending",
        "dispatched",
        "claimed",
        "running",
        "retryable_failed",
      );
      next.lease = null;
      next.state = "cancelled";
      break;
    case "retry":
      requireState(next, "retryable_failed");
      next.failure = null;
      next.state = "ready";
      break;
    case "expire_lease": {
      requireState(next, "claimed", "running");
      if (!next.lease || next.lease.expires_at > now) {
        throw new JobTransitionError("The active lease has not expired.");
      }
      const attempt = activeAttempt(next, next.lease.attempt_id);
      const failure: JobFailure = {
        classification: "lease_expired",
        message: "The worker lease expired before completion.",
        retryable: true,
        occurred_at: now,
      };
      attempt.state = "failed";
      attempt.updated_at = now;
      attempt.failure = failure;
      next.failure = failure;
      next.lease = null;
      next.state = "retryable_failed";
      break;
    }
  }

  next.revision += 1;
  next.updated_at = now;
  next.last_command_id = command.command_id;
  return next;
}

export const SYNTHETIC_TRANSCRIPT_HANDLER = {
  id: "watchcraft.transcript.synthetic",
  version: "1",
} as const;

export function syntheticTranscriptJobSpec(): AuthoringJobSpec {
  return {
    operation: "generate",
    artifact_kind: "transcript",
    output_schema: { id: "watchcraft.transcript", version: 1 },
    handler: SYNTHETIC_TRANSCRIPT_HANDLER,
    source: {
      media_asset_id: "synthetic:authoring-pipeline-smoke",
      coordinate_id: "milliseconds:v1",
    },
    inputs: [],
    dependencies: [],
    configuration: {
      language: "en",
      text: "Hello from the Watchcraft authoring pipeline.",
      duration_ms: 2000,
    },
  };
}
