import { randomUUID } from "node:crypto";

import {
  R2ArtifactStore,
  controlClientFromEnvironment,
  r2ConfigFromEnvironment,
  runAuthoringWorker,
} from "../packages/authoring-pipeline/src/index.ts";

async function main(): Promise<void> {
  const control = controlClientFromEnvironment();
  const artifacts = new R2ArtifactStore(r2ConfigFromEnvironment());
  const jobId = randomUUID();
  const runId = randomUUID();
  const commandPrefix = randomUUID();
  const githubRunId = process.env.GITHUB_RUN_ID ?? "local-smoke";
  const githubServerUrl = process.env.GITHUB_SERVER_URL ?? "https://github.com";
  const githubRepository = process.env.GITHUB_REPOSITORY ?? "billbliss/watchcraft";
  const githubRunUrl = `${githubServerUrl}/${githubRepository}/actions/runs/${githubRunId}`;

  const prepared = await control.prepareSmokeJob({
    job_id: jobId,
    run_id: runId,
    command_prefix: commandPrefix,
    github_run_id: githubRunId,
    github_run_url: githubRunUrl,
  });
  const result = await runAuthoringWorker({
    jobId: prepared.job_id,
    specSha256: prepared.spec_sha256,
    dispatchGeneration: prepared.dispatch_generation,
    expectedRevision: prepared.revision,
    githubRunId,
  }, {
    control,
    artifacts,
    owner: `github-actions:${githubRunId}`,
  });

  if (result.job.state !== "succeeded" || !result.job.result) {
    throw new Error(`Smoke job ended in unexpected state ${result.job.state}.`);
  }
  const transcript = JSON.parse(new TextDecoder().decode(result.artifactBytes)) as {
    text?: unknown;
  };
  if (transcript.text !== "Hello from the Watchcraft authoring pipeline.") {
    throw new Error("Stored smoke transcript did not round-trip through R2.");
  }

  console.log(JSON.stringify({
    job_id: result.job.job_id,
    state: result.job.state,
    revision: result.job.revision,
    artifact_sha256: result.job.result.digest,
    artifact_bytes: result.job.result.byte_length,
  }, null, 2));
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});
