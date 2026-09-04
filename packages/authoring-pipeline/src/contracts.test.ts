import assert from "node:assert/strict";
import test from "node:test";

import {
  parseAuthoringJobSpec,
  parseAuthoringRun,
  syntheticTranscriptJobSpec,
} from "./index.ts";

test("versioned authoring runs are validated as coherent JSON aggregates", () => {
  const run = parseAuthoringRun({
    kind: "watchcraft.authoring-run",
    schema_version: 1,
    run_id: "run-1",
    revision: 1,
    request: { source: "synthetic", options: ["smoke"] },
    source_snapshot: null,
    plan: null,
    approval_sha256: null,
    approval: null,
    job_ids: ["job-1"],
    state: "requested",
    created_at: 100,
    updated_at: 100,
    last_command_id: "create-run",
  });

  assert.equal(run.state, "requested");
  assert.deepEqual(run.job_ids, ["job-1"]);
  const { approval_sha256: _approvalDigest, ...legacyRun } = run;
  assert.equal(parseAuthoringRun(legacyRun).approval_sha256, null);
  assert.throws(() => parseAuthoringRun({ ...run, state: "invented" }), /Unsupported run state/);
});

test("job specification validation rejects non-JSON material configuration", () => {
  const spec = syntheticTranscriptJobSpec();
  assert.deepEqual(parseAuthoringJobSpec(spec), spec);
  assert.throws(() => parseAuthoringJobSpec({
    ...spec,
    configuration: { duration_ms: Number.NaN },
  }), /finite numbers/);
});
