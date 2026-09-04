import assert from "node:assert/strict";
import test from "node:test";

import { applyRunCommand, createAuthoringRun } from "./index.ts";

test("a run binds approval to its immutable single-job plan", () => {
  const digest = "a".repeat(64);
  let run = createAuthoringRun("run-1", { purpose: "analysis" }, "create", 100);
  run = applyRunCommand(run, {
    type: "plan",
    command_id: "plan",
    expected_revision: run.revision,
    source_snapshot: null,
    plan: null,
    approval_sha256: digest,
    job_ids: ["job-1"],
  }, 101);
  assert.throws(() => applyRunCommand(run, {
    type: "approve",
    command_id: "wrong-approval",
    expected_revision: run.revision,
    actor: "operator",
    approval_sha256: "b".repeat(64),
  }, 102), /immutable run plan/);
  run = applyRunCommand(run, {
    type: "approve",
    command_id: "approve",
    expected_revision: run.revision,
    actor: "operator",
    approval_sha256: digest,
  }, 102);
  run = applyRunCommand(run, {
    type: "start",
    command_id: "start",
    expected_revision: run.revision,
  }, 103);
  run = applyRunCommand(run, {
    type: "succeed",
    command_id: "succeed",
    expected_revision: run.revision,
  }, 104);
  assert.equal(run.state, "complete");
  assert.equal(run.revision, 5);
});
