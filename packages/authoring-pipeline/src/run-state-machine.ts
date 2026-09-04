import {
  type ArtifactReference,
  type AuthoringRun,
  type JsonValue,
  parseAuthoringRun,
} from "./contracts.ts";
import { JobTransitionError } from "./state-machine.ts";

interface RunCommandBase {
  command_id: string;
  expected_revision: number;
}

export type RunCommand =
  | (RunCommandBase & {
      type: "plan";
      source_snapshot: ArtifactReference | null;
      plan: ArtifactReference | null;
      approval_sha256: string;
      job_ids: string[];
    })
  | (RunCommandBase & { type: "approve"; actor: string; approval_sha256: string })
  | (RunCommandBase & { type: "start" })
  | (RunCommandBase & { type: "succeed" })
  | (RunCommandBase & { type: "fail" })
  | (RunCommandBase & { type: "retry" })
  | (RunCommandBase & { type: "cancel" });

function requireState(run: AuthoringRun, ...states: AuthoringRun["state"][]): void {
  if (!states.includes(run.state)) {
    throw new JobTransitionError(
      `Cannot apply command while run ${run.run_id} is ${run.state}; expected ${states.join(" or ")}.`,
    );
  }
}

export function createAuthoringRun(
  runId: string,
  request: { [key: string]: JsonValue },
  commandId: string,
  now: number,
): AuthoringRun {
  if (!runId || !commandId) throw new TypeError("Run and command IDs are required.");
  return parseAuthoringRun({
    kind: "watchcraft.authoring-run",
    schema_version: 1,
    run_id: runId,
    revision: 1,
    request,
    source_snapshot: null,
    plan: null,
    approval_sha256: null,
    approval: null,
    job_ids: [],
    state: "requested",
    created_at: now,
    updated_at: now,
    last_command_id: commandId,
  });
}

export function applyRunCommand(run: AuthoringRun, command: RunCommand, now: number): AuthoringRun {
  if (command.expected_revision !== run.revision) {
    throw new JobTransitionError(
      `Stale run revision ${command.expected_revision}; current revision is ${run.revision}.`,
    );
  }
  if (!command.command_id) throw new TypeError("Command ID is required.");
  const next = structuredClone(run);
  switch (command.type) {
    case "plan":
      requireState(next, "requested");
      if (!/^[a-f0-9]{64}$/.test(command.approval_sha256) || command.job_ids.length === 0) {
        throw new TypeError("A plan requires an approval digest and at least one job.");
      }
      next.source_snapshot = command.source_snapshot;
      next.plan = command.plan;
      next.approval_sha256 = command.approval_sha256;
      next.job_ids = [...new Set(command.job_ids)];
      next.state = "planned";
      break;
    case "approve":
      requireState(next, "planned");
      if (command.approval_sha256 !== next.approval_sha256) {
        throw new JobTransitionError("Approval does not match the immutable run plan.");
      }
      next.approval = {
        actor: command.actor,
        approved_at: now,
        spec_sha256: command.approval_sha256,
      };
      next.state = "approved";
      break;
    case "start":
      requireState(next, "approved");
      next.state = "running";
      break;
    case "succeed":
      requireState(next, "running");
      next.state = "complete";
      break;
    case "fail":
      requireState(next, "running");
      next.state = "failed";
      break;
    case "retry":
      requireState(next, "failed");
      next.state = "approved";
      break;
    case "cancel":
      requireState(next, "requested", "planned", "approved", "running", "failed");
      next.state = "cancelled";
      break;
  }
  next.revision += 1;
  next.updated_at = now;
  next.last_command_id = command.command_id;
  return parseAuthoringRun(next);
}
