import assert from "node:assert/strict";
import test from "node:test";

import {
  createProjectExecution,
  parseProjectExecution,
  projectExecutionApprovalSha256,
  type ProjectExecutionInput,
} from "./index.ts";

const digest = "a".repeat(64);
const input: ProjectExecutionInput = {
  execution_id: "execution-1",
  project: { project_id: "linear-algebra", revision: 2 },
  plan: {
    job_id: "plan-job-1",
    artifact: {
      store: "r2",
      algorithm: "sha256",
      digest,
      byte_length: 1024,
      media_type: "application/json",
      artifact_kind: "project-processing-plan",
      schema: { id: "watchcraft.project-processing-plan", version: 1 },
      key: `objects/sha256/${digest.slice(0, 2)}/${digest.slice(2)}`,
    },
    plan_hash: "plan-hash-1",
  },
  selection: { item_ids: ["youtube:first", "youtube:second"] },
  policy: { recipe: { id: "watchcraft.youtube-video", version: "1" }, concurrency: 2 },
  estimate: { expected_seconds: 120, expected_cost_usd: 0.25 },
  items: [
    { item_id: "youtube:first", run_id: "run-1", job_ids: ["transcript-1", "analysis-1"] },
    { item_id: "youtube:second", run_id: "run-2", job_ids: ["transcript-2", "analysis-2"] },
  ],
};

test("creates an immutable approval proposal with reserved child identities", () => {
  const execution = createProjectExecution(input, "create-1", 1000);
  assert.equal(execution.state, "awaiting_approval");
  assert.equal(execution.revision, 1);
  assert.equal(execution.approval_sha256, projectExecutionApprovalSha256(input));
  assert.deepEqual(execution.items.map((item) => item.state), ["pending", "pending"]);
  assert.notEqual(execution.items, input.items);
  assert.deepEqual(parseProjectExecution(execution), execution);
});

test("approval digest changes with selection, policy, estimate, or child work", () => {
  const baseline = projectExecutionApprovalSha256(input);
  for (const changed of [
    { ...input, selection: { item_ids: ["youtube:first"] }, items: [input.items[0]] },
    { ...input, policy: { ...input.policy, concurrency: 1 } },
    { ...input, estimate: { ...input.estimate, expected_cost_usd: 0.5 } },
    { ...input, items: [{ ...input.items[0], run_id: "other" }, input.items[1]] },
  ]) assert.notEqual(projectExecutionApprovalSha256(changed), baseline);
});

test("rejects duplicate selections and child identities", () => {
  assert.throws(() => createProjectExecution({
    ...input,
    selection: { item_ids: ["youtube:first", "youtube:first"] },
  }, "create-1", 1000), /unique items/);
  assert.throws(() => createProjectExecution({
    ...input,
    items: [input.items[0], { ...input.items[1], run_id: input.items[0].run_id }],
  }, "create-1", 1000), /run IDs must be unique/);
});
