import assert from "node:assert/strict";
import test from "node:test";

import {
  type ArtifactReference,
  type AuthoringControlPlane,
  type AuthoringJob,
  type ClaimRequest,
  type FailureReport,
  type JsonValue,
  type JobCommand,
  applyJobCommand,
  artifactKey,
  canonicalJson,
  createAuthoringJob,
  runAuthoringWorker,
  sha256Hex,
  syntheticTranscriptJobSpec,
} from "./index.ts";

function serialized<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

class InMemoryControlPlane implements AuthoringControlPlane {
  job: AuthoringJob;
  readonly commandResults = new Map<string, AuthoringJob>();
  now = 100;
  rejectNextCompletion = false;

  constructor() {
    let job = createAuthoringJob(
      "job-1",
      "run-1",
      syntheticTranscriptJobSpec(),
      "create",
      this.now++,
    );
    for (const command of [
      { type: "request_approval", command_id: "request-approval" },
      { type: "approve", command_id: "approve", actor: "operator", spec_sha256: job.spec_sha256 },
      { type: "request_dispatch", command_id: "request-dispatch" },
    ] as const) {
      job = applyJobCommand(job, { ...command, expected_revision: job.revision } as JobCommand, this.now++);
    }
    job = applyJobCommand(job, {
      type: "record_dispatch",
      command_id: "record-dispatch",
      expected_revision: job.revision,
      generation: 1,
      github_run_id: "123",
      github_run_url: "https://github.com/billbliss/watchcraft/actions/runs/123",
    }, this.now++);
    this.job = serialized(job);
  }

  async prepareSmokeJob(): Promise<never> {
    throw new Error("Job is already prepared in this test.");
  }

  private apply(command: JobCommand): AuthoringJob {
    const duplicate = this.commandResults.get(command.command_id);
    if (duplicate) return serialized(duplicate);
    this.job = serialized(applyJobCommand(this.job, command, this.now++));
    this.commandResults.set(command.command_id, serialized(this.job));
    return serialized(this.job);
  }

  expireLeaseAndRedispatch(): AuthoringJob {
    this.now = this.job.lease!.expires_at;
    this.job = this.apply({
      type: "expire_lease",
      command_id: "expire-first-attempt",
      expected_revision: this.job.revision,
    });
    this.job = this.apply({
      type: "retry",
      command_id: "retry-first-attempt",
      expected_revision: this.job.revision,
    });
    this.job = this.apply({
      type: "request_dispatch",
      command_id: "request-second-dispatch",
      expected_revision: this.job.revision,
    });
    this.job = this.apply({
      type: "record_dispatch",
      command_id: "record-second-dispatch",
      expected_revision: this.job.revision,
      generation: 2,
      github_run_id: "124",
      github_run_url: "https://github.com/billbliss/watchcraft/actions/runs/124",
    });
    return serialized(this.job);
  }

  async claimJob(input: ClaimRequest) {
    return this.apply({
      type: "claim",
      command_id: input.command_id,
      expected_revision: input.expected_revision,
      attempt_id: input.attempt_id,
      owner: input.owner,
      spec_sha256: input.spec_sha256,
      generation: input.dispatch_generation,
      lease_duration_ms: input.lease_duration_ms,
      github_run_id: input.github_run_id,
    });
  }

  async startJob(input: {
    job_id: string;
    command_id: string;
    expected_revision: number;
    attempt_id: string;
  }) {
    return this.apply({ type: "start", ...input });
  }

  async heartbeatJob(input: {
    job_id: string;
    command_id: string;
    expected_revision: number;
    attempt_id: string;
    lease_duration_ms: number;
  }) {
    return this.apply({ type: "heartbeat", ...input });
  }

  async succeedJob(input: {
    job_id: string;
    command_id: string;
    expected_revision: number;
    attempt_id: string;
    artifact: ArtifactReference;
  }) {
    if (this.rejectNextCompletion) {
      this.rejectNextCompletion = false;
      throw new Error("Simulated control-plane outage after artifact upload.");
    }
    return this.apply({ type: "succeed", ...input });
  }

  async failJob(input: {
    job_id: string;
    command_id: string;
    expected_revision: number;
    attempt_id: string;
    failure: FailureReport;
  }) {
    return this.apply({ type: "fail", ...input });
  }
}

class InMemoryArtifacts {
  readonly objects = new Map<string, Uint8Array>();
  putCount = 0;

  async putJson(
    value: JsonValue,
    description: {
      artifactKind: string;
      mediaType: string;
      schema: { id: string; version: number };
    },
  ): Promise<ArtifactReference> {
    const bytes = new TextEncoder().encode(canonicalJson(value));
    const digest = sha256Hex(bytes);
    const reference: ArtifactReference = {
      store: "r2",
      algorithm: "sha256",
      digest,
      byte_length: bytes.byteLength,
      media_type: description.mediaType,
      artifact_kind: description.artifactKind,
      schema: description.schema,
      key: artifactKey(digest),
    };
    if (!this.objects.has(reference.key)) {
      this.objects.set(reference.key, bytes);
      this.putCount += 1;
    }
    return reference;
  }

  async getBytes(reference: ArtifactReference) {
    const value = this.objects.get(reference.key);
    if (!value) throw new Error("Missing in-memory artifact.");
    return value;
  }
}

test("the worker performs a persisted control and artifact round-trip", async () => {
  const control = new InMemoryControlPlane();
  const artifacts = new InMemoryArtifacts();
  const result = await runAuthoringWorker({
    jobId: control.job.job_id,
    specSha256: control.job.spec_sha256,
    dispatchGeneration: 1,
    expectedRevision: control.job.revision,
    githubRunId: "123",
  }, {
    control,
    artifacts,
    owner: "github-actions:123",
    attemptId: "attempt-1",
  });

  assert.equal(result.job.state, "succeeded");
  assert.equal(result.job.revision, 8);
  assert.equal(artifacts.objects.size, 1);
  const reloaded = serialized(control.job);
  assert.equal(reloaded.result?.digest, result.job.result?.digest);
  assert.equal(
    JSON.parse(new TextDecoder().decode(result.artifactBytes)).text,
    "Hello from the Watchcraft authoring pipeline.",
  );
});

test("replaying an accepted completion command returns its original result", async () => {
  const control = new InMemoryControlPlane();
  const artifacts = new InMemoryArtifacts();
  const result = await runAuthoringWorker({
    jobId: control.job.job_id,
    specSha256: control.job.spec_sha256,
    dispatchGeneration: 1,
    expectedRevision: control.job.revision,
  }, {
    control,
    artifacts,
    attemptId: "attempt-1",
  });
  const replay = await control.succeedJob({
    job_id: result.job.job_id,
    command_id: "attempt-1:succeed",
    expected_revision: 7,
    attempt_id: "attempt-1",
    artifact: result.job.result!,
  });
  assert.deepEqual(replay, result.job);
  assert.equal(control.job.revision, 8);

  await assert.rejects(() => control.succeedJob({
    job_id: result.job.job_id,
    command_id: "different-late-completion",
    expected_revision: 7,
    attempt_id: "attempt-1",
    artifact: result.job.result!,
  }), /Stale job revision/);
});

test("an interrupted completion leaves an orphan safe and resumes without duplicate artifacts", async () => {
  const control = new InMemoryControlPlane();
  const artifacts = new InMemoryArtifacts();
  control.rejectNextCompletion = true;

  await assert.rejects(() => runAuthoringWorker({
    jobId: control.job.job_id,
    specSha256: control.job.spec_sha256,
    dispatchGeneration: 1,
    expectedRevision: control.job.revision,
  }, {
    control,
    artifacts,
    attemptId: "attempt-1",
    leaseDurationMs: 10,
  }), /control-plane outage/);
  assert.equal(control.job.state, "running");
  assert.equal(control.job.result, null);
  assert.equal(artifacts.objects.size, 1);

  const redispatched = serialized(control.expireLeaseAndRedispatch());
  assert.equal(redispatched.state, "dispatched");
  assert.equal(redispatched.dispatch?.generation, 2);

  const resumed = await runAuthoringWorker({
    jobId: redispatched.job_id,
    specSha256: redispatched.spec_sha256,
    dispatchGeneration: 2,
    expectedRevision: redispatched.revision,
  }, {
    control,
    artifacts,
    attemptId: "attempt-2",
    leaseDurationMs: 10,
  });
  assert.equal(resumed.job.state, "succeeded");
  assert.equal(resumed.job.attempts.length, 2);
  assert.equal(resumed.job.attempts[0]?.failure?.classification, "lease_expired");
  assert.equal(resumed.job.result?.key, [...artifacts.objects.keys()][0]);
  assert.equal(artifacts.objects.size, 1);
  assert.equal(artifacts.putCount, 1);
});
