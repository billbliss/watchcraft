import { randomUUID } from "node:crypto";

import type { R2ArtifactStore } from "./artifact-store.ts";
import {
  type AuthoringJob,
  type JsonValue,
  parseAuthoringJob,
} from "./contracts.ts";
import type { AuthoringControlPlane } from "./control-client.ts";
import { SYNTHETIC_TRANSCRIPT_HANDLER } from "./state-machine.ts";

export interface WorkerRequest {
  jobId: string;
  specSha256: string;
  dispatchGeneration: number;
  expectedRevision: number;
  githubRunId?: string;
}

export interface WorkerResult {
  job: AuthoringJob;
  artifactBytes: Uint8Array;
}

function requiredString(value: JsonValue | undefined, name: string): string {
  if (typeof value !== "string" || !value) throw new TypeError(`${name} must be a non-empty string.`);
  return value;
}

function requiredDuration(value: JsonValue | undefined): number {
  if (!Number.isSafeInteger(value) || (value as number) <= 0) {
    throw new TypeError("duration_ms must be a positive integer.");
  }
  return value as number;
}

export function runSyntheticTranscriptHandler(job: AuthoringJob): JsonValue {
  if (
    job.spec.operation !== "generate"
    || job.spec.artifact_kind !== "transcript"
    || job.spec.handler.id !== SYNTHETIC_TRANSCRIPT_HANDLER.id
    || job.spec.handler.version !== SYNTHETIC_TRANSCRIPT_HANDLER.version
  ) {
    throw new Error(`Unsupported authoring handler ${job.spec.handler.id}@${job.spec.handler.version}.`);
  }
  const text = requiredString(job.spec.configuration.text, "text");
  const language = requiredString(job.spec.configuration.language, "language");
  const durationMs = requiredDuration(job.spec.configuration.duration_ms);
  return {
    schema_version: 1,
    video: job.spec.source.media_asset_id,
    model: `${job.spec.handler.id}@${job.spec.handler.version}`,
    language,
    text,
    segments: [{ start: 0, end: durationMs / 1000, text }],
    discarded_segments: [],
    provenance: {
      kind: "synthetic-pipeline-smoke",
      job_id: job.job_id,
      spec_sha256: job.spec_sha256,
    },
  };
}

export async function runAuthoringWorker(
  request: WorkerRequest,
  dependencies: {
    control: AuthoringControlPlane;
    artifacts: Pick<R2ArtifactStore, "putJson" | "getBytes">;
    owner?: string;
    attemptId?: string;
    leaseDurationMs?: number;
  },
): Promise<WorkerResult> {
  const attemptId = dependencies.attemptId ?? randomUUID();
  const owner = dependencies.owner ?? "github-actions";
  const leaseDurationMs = dependencies.leaseDurationMs ?? 5 * 60_000;
  let job = parseAuthoringJob(await dependencies.control.claimJob({
    job_id: request.jobId,
    command_id: `${attemptId}:claim`,
    expected_revision: request.expectedRevision,
    attempt_id: attemptId,
    owner,
    spec_sha256: request.specSha256,
    dispatch_generation: request.dispatchGeneration,
    lease_duration_ms: leaseDurationMs,
    github_run_id: request.githubRunId,
  }));

  job = parseAuthoringJob(await dependencies.control.startJob({
    job_id: job.job_id,
    command_id: `${attemptId}:start`,
    expected_revision: job.revision,
    attempt_id: attemptId,
  }));
  let transcript: JsonValue;
  try {
    transcript = runSyntheticTranscriptHandler(job);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    await dependencies.control.failJob({
      job_id: job.job_id,
      command_id: `${attemptId}:handler-fail`,
      expected_revision: job.revision,
      attempt_id: attemptId,
      failure: {
        classification: "handler_failed",
        message: message.slice(0, 500),
        retryable: false,
      },
    }).catch(() => undefined);
    throw error;
  }

  let artifact;
  let artifactBytes;
  try {
    artifact = await dependencies.artifacts.putJson(transcript, {
      artifactKind: job.spec.artifact_kind,
      mediaType: "application/json",
      schema: job.spec.output_schema,
    });
    artifactBytes = await dependencies.artifacts.getBytes(artifact);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    await dependencies.control.failJob({
      job_id: job.job_id,
      command_id: `${attemptId}:storage-fail`,
      expected_revision: job.revision,
      attempt_id: attemptId,
      failure: {
        classification: "artifact_store_failed",
        message: message.slice(0, 500),
        retryable: true,
      },
    }).catch(() => undefined);
    throw error;
  }

  job = parseAuthoringJob(await dependencies.control.succeedJob({
    job_id: job.job_id,
    command_id: `${attemptId}:succeed`,
    expected_revision: job.revision,
    attempt_id: attemptId,
    artifact,
  }));
  return { job, artifactBytes };
}
