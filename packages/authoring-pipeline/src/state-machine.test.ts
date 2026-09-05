import assert from "node:assert/strict";
import test from "node:test";

import {
  type ArtifactReference,
  applyJobCommand,
  artifactKey,
  createAuthoringJob,
  jobSpecSha256,
  syntheticTranscriptJobSpec,
} from "./index.ts";

function dispatchedJob() {
  const spec = syntheticTranscriptJobSpec();
  let job = createAuthoringJob("job-1", "run-1", spec, "create", 100);
  job = applyJobCommand(job, {
    type: "request_approval",
    command_id: "request-approval",
    expected_revision: job.revision,
  }, 101);
  job = applyJobCommand(job, {
    type: "approve",
    command_id: "approve",
    expected_revision: job.revision,
    actor: "operator",
    spec_sha256: job.spec_sha256,
  }, 102);
  job = applyJobCommand(job, {
    type: "request_dispatch",
    command_id: "request-dispatch",
    expected_revision: job.revision,
  }, 103);
  return applyJobCommand(job, {
    type: "record_dispatch",
    command_id: "record-dispatch",
    expected_revision: job.revision,
    generation: 1,
    github_run_id: "123",
    github_run_url: "https://github.com/billbliss/watchcraft/actions/runs/123",
  }, 104);
}

function transcriptArtifact(): ArtifactReference {
  const digest = "a".repeat(64);
  return {
    store: "r2",
    algorithm: "sha256",
    digest,
    byte_length: 100,
    media_type: "application/json",
    artifact_kind: "transcript",
    schema: { id: "watchcraft.transcript", version: 1 },
    key: artifactKey(digest),
  };
}

test("canonical specification hashes do not depend on object insertion order", () => {
  const spec = syntheticTranscriptJobSpec();
  const reordered = {
    ...spec,
    configuration: {
      duration_ms: spec.configuration.duration_ms,
      text: spec.configuration.text,
      language: spec.configuration.language,
    },
  };
  assert.equal(jobSpecSha256(spec), jobSpecSha256(reordered));
});

test("a dispatched job can be claimed, run, and completed exactly against its lease", () => {
  let job = dispatchedJob();
  assert.equal(job.revision, 5);
  job = applyJobCommand(job, {
    type: "claim",
    command_id: "claim",
    expected_revision: job.revision,
    attempt_id: "attempt-1",
    owner: "github-actions:123",
    spec_sha256: job.spec_sha256,
    generation: 1,
    lease_duration_ms: 1_000,
  }, 200);
  job = applyJobCommand(job, {
    type: "start",
    command_id: "start",
    expected_revision: job.revision,
    attempt_id: "attempt-1",
  }, 201);
  job = applyJobCommand(job, {
    type: "succeed",
    command_id: "succeed",
    expected_revision: job.revision,
    attempt_id: "attempt-1",
    artifact: transcriptArtifact(),
  }, 202);

  assert.equal(job.state, "succeeded");
  assert.equal(job.result?.digest, "a".repeat(64));
  assert.equal(job.lease, null);
  assert.equal(job.attempts[0]?.state, "succeeded");
});

test("approval and worker claims bind the immutable specification hash", () => {
  const spec = syntheticTranscriptJobSpec();
  let job = createAuthoringJob("job-1", "run-1", spec, "create", 100);
  job = applyJobCommand(job, {
    type: "request_approval",
    command_id: "request-approval",
    expected_revision: job.revision,
  }, 101);
  assert.throws(() => applyJobCommand(job, {
    type: "approve",
    command_id: "approve",
    expected_revision: job.revision,
    actor: "operator",
    spec_sha256: "0".repeat(64),
  }, 102), /Approval does not match/);

  const dispatched = dispatchedJob();
  assert.throws(() => applyJobCommand(dispatched, {
    type: "claim",
    command_id: "claim",
    expected_revision: dispatched.revision,
    attempt_id: "attempt-1",
    owner: "worker",
    spec_sha256: "0".repeat(64),
    generation: 1,
    lease_duration_ms: 1_000,
  }, 200), /different job specification/);
});

test("a stale or late completion cannot replace authoritative state", () => {
  let job = dispatchedJob();
  job = applyJobCommand(job, {
    type: "claim",
    command_id: "claim",
    expected_revision: job.revision,
    attempt_id: "attempt-1",
    owner: "worker",
    spec_sha256: job.spec_sha256,
    generation: 1,
    lease_duration_ms: 10,
  }, 200);
  job = applyJobCommand(job, {
    type: "start",
    command_id: "start",
    expected_revision: job.revision,
    attempt_id: "attempt-1",
  }, 201);
  const runningRevision = job.revision;
  job = applyJobCommand(job, {
    type: "expire_lease",
    command_id: "expire",
    expected_revision: job.revision,
  }, 211);
  assert.equal(job.state, "retryable_failed");
  assert.throws(() => applyJobCommand(job, {
    type: "succeed",
    command_id: "late-success",
    expected_revision: runningRevision,
    attempt_id: "attempt-1",
    artifact: transcriptArtifact(),
  }, 212), /Stale job revision/);
});

test("artifact output kind and schema must match the approved task", () => {
  let job = dispatchedJob();
  job = applyJobCommand(job, {
    type: "claim",
    command_id: "claim",
    expected_revision: job.revision,
    attempt_id: "attempt-1",
    owner: "worker",
    spec_sha256: job.spec_sha256,
    generation: 1,
    lease_duration_ms: 1_000,
  }, 200);
  job = applyJobCommand(job, {
    type: "start",
    command_id: "start",
    expected_revision: job.revision,
    attempt_id: "attempt-1",
  }, 201);
  assert.throws(() => applyJobCommand(job, {
    type: "succeed",
    command_id: "succeed",
    expected_revision: job.revision,
    attempt_id: "attempt-1",
    artifact: { ...transcriptArtifact(), artifact_kind: "chapters" },
  }, 202), /does not match/);
  const artifact = transcriptArtifact();
  assert.throws(() => applyJobCommand(job, {
    type: "succeed",
    command_id: "staged-success",
    expected_revision: job.revision,
    attempt_id: "attempt-1",
    artifact: {
      ...artifact,
      key: `staging/00000000-0000-4000-8000-000000000000/sha256/${artifact.digest.slice(0, 2)}/${artifact.digest.slice(2)}`,
      retention: { class: "ephemeral", expires_at: 2_000_000_000_000 },
    },
  }, 202), /Ephemeral artifacts are allowed only as staged job inputs/);
});
