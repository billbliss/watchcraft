import {
  canonicalJson,
  type ArtifactReference,
  type JsonValue,
  parseArtifactReference,
  sha256Hex,
} from "./contracts.ts";

export type ProjectExecutionState =
  | "awaiting_approval"
  | "approved"
  | "running"
  | "complete"
  | "failed"
  | "cancelled";

export interface ProjectExecutionItem {
  item_id: string;
  run_id: string;
  job_ids: string[];
  state: "pending" | "claimed" | "succeeded" | "failed" | "cancelled";
  claim: null | {
    owner: string;
    claimed_at: number;
    expires_at: number;
  };
  failure: null | { message: string; occurred_at: number };
  completed_at: number | null;
}

export interface ProjectExecution {
  kind: "watchcraft.project-execution";
  schema_version: 1;
  execution_id: string;
  revision: number;
  project: { project_id: string; revision: number };
  plan: {
    job_id: string;
    artifact: ArtifactReference;
    plan_hash: string;
  };
  selection: { item_ids: string[] };
  policy: {
    recipe: { id: string; version: string };
    concurrency: number;
  };
  estimate: { [key: string]: JsonValue };
  items: ProjectExecutionItem[];
  approval_sha256: string;
  approval: null | { actor: string; approved_at: number; approval_sha256: string };
  state: ProjectExecutionState;
  created_at: number;
  updated_at: number;
  last_command_id: string;
}

export interface ProjectExecutionInput {
  execution_id: string;
  project: ProjectExecution["project"];
  plan: ProjectExecution["plan"];
  selection: ProjectExecution["selection"];
  policy: ProjectExecution["policy"];
  estimate: ProjectExecution["estimate"];
  items: Array<Pick<ProjectExecutionItem, "item_id" | "run_id" | "job_ids">>;
}

function requiredString(value: unknown, label: string): string {
  if (typeof value !== "string" || value.length === 0) throw new TypeError(`${label} is required.`);
  return value;
}

export function projectExecutionApprovalSha256(input: ProjectExecutionInput): string {
  return sha256Hex(canonicalJson({
    project: input.project,
    plan: input.plan,
    selection: input.selection,
    policy: input.policy,
    estimate: input.estimate,
    items: input.items,
  } as unknown as JsonValue));
}

export function createProjectExecution(
  input: ProjectExecutionInput,
  commandId: string,
  now: number,
): ProjectExecution {
  requiredString(input.execution_id, "Execution ID");
  requiredString(commandId, "Command ID");
  requiredString(input.project.project_id, "Project ID");
  requiredString(input.plan.job_id, "Plan job ID");
  requiredString(input.plan.plan_hash, "Plan hash");
  requiredString(input.policy?.recipe?.id, "Execution recipe ID");
  requiredString(input.policy?.recipe?.version, "Execution recipe version");
  if (!input.estimate || typeof input.estimate !== "object" || Array.isArray(input.estimate)) {
    throw new TypeError("Execution estimate must be an object.");
  }
  if (!Number.isSafeInteger(input.project.revision) || input.project.revision < 1) {
    throw new TypeError("Project revision must be a positive integer.");
  }
  if (!Number.isSafeInteger(input.policy.concurrency) || input.policy.concurrency < 1 || input.policy.concurrency > 8) {
    throw new TypeError("Execution concurrency must be between 1 and 8.");
  }
  const artifact = parseArtifactReference(input.plan.artifact);
  if (
    artifact.artifact_kind !== "project-processing-plan"
    || artifact.schema.id !== "watchcraft.project-processing-plan"
    || artifact.schema.version !== 1
  ) throw new TypeError("Project execution requires a project-processing-plan@1 artifact.");
  const itemIds = input.selection.item_ids.map((value) => requiredString(value, "Selected item ID"));
  if (itemIds.length === 0 || new Set(itemIds).size !== itemIds.length) {
    throw new TypeError("Project execution selection must contain unique items.");
  }
  if (
    input.items.length !== itemIds.length
    || input.items.some((item, index) => item.item_id !== itemIds[index])
  ) throw new TypeError("Project execution work must exactly cover its ordered selection.");
  const runs = new Set<string>();
  const jobs = new Set<string>();
  const items = input.items.map((item) => {
    requiredString(item.run_id, "Child run ID");
    if (runs.has(item.run_id)) throw new TypeError("Child run IDs must be unique.");
    runs.add(item.run_id);
    if (item.job_ids.length === 0) throw new TypeError("Each execution item requires child jobs.");
    for (const jobId of item.job_ids) {
      requiredString(jobId, "Child job ID");
      if (jobs.has(jobId)) throw new TypeError("Child job IDs must be unique.");
      jobs.add(jobId);
    }
    return {
      ...item,
      job_ids: [...item.job_ids],
      state: "pending" as const,
      claim: null,
      failure: null,
      completed_at: null,
    };
  });
  const normalized = { ...input, plan: { ...input.plan, artifact }, items: input.items };
  return {
    kind: "watchcraft.project-execution",
    schema_version: 1,
    execution_id: input.execution_id,
    revision: 1,
    project: structuredClone(input.project),
    plan: structuredClone(normalized.plan),
    selection: { item_ids: [...itemIds] },
    policy: structuredClone(input.policy),
    estimate: structuredClone(input.estimate),
    items,
    approval_sha256: projectExecutionApprovalSha256(normalized),
    approval: null,
    state: "awaiting_approval",
    created_at: now,
    updated_at: now,
    last_command_id: commandId,
  };
}

export function parseProjectExecution(value: unknown): ProjectExecution {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError("Project execution must be an object.");
  }
  const execution = value as ProjectExecution;
  if (execution.kind !== "watchcraft.project-execution" || execution.schema_version !== 1) {
    throw new TypeError("Unsupported project execution schema.");
  }
  requiredString(execution.execution_id, "Execution ID");
  requiredString(execution.last_command_id, "Last command ID");
  if (!Number.isSafeInteger(execution.revision) || execution.revision < 1) {
    throw new TypeError("Execution revision must be a positive integer.");
  }
  if (![
    "awaiting_approval", "approved", "running", "complete", "failed", "cancelled",
  ].includes(execution.state)) throw new TypeError("Unsupported project execution state.");
  requiredString(execution.project?.project_id, "Project ID");
  requiredString(execution.plan?.job_id, "Plan job ID");
  requiredString(execution.plan?.plan_hash, "Plan hash");
  const artifact = parseArtifactReference(execution.plan?.artifact);
  if (
    artifact.artifact_kind !== "project-processing-plan"
    || artifact.schema.id !== "watchcraft.project-processing-plan"
    || artifact.schema.version !== 1
  ) throw new TypeError("Project execution requires a project-processing-plan@1 artifact.");
  if (!Number.isSafeInteger(execution.project.revision) || execution.project.revision < 1) {
    throw new TypeError("Project revision must be a positive integer.");
  }
  if (!Number.isSafeInteger(execution.policy?.concurrency) || execution.policy.concurrency < 1 || execution.policy.concurrency > 8) {
    throw new TypeError("Execution concurrency must be between 1 and 8.");
  }
  requiredString(execution.policy?.recipe?.id, "Execution recipe ID");
  requiredString(execution.policy?.recipe?.version, "Execution recipe version");
  if (!Array.isArray(execution.items) || execution.items.length === 0) {
    throw new TypeError("Project execution requires work items.");
  }
  if (
    !Array.isArray(execution.selection?.item_ids)
    || execution.selection.item_ids.length !== execution.items.length
    || new Set(execution.selection.item_ids).size !== execution.selection.item_ids.length
  ) throw new TypeError("Project execution selection must contain unique items matching its work.");
  const childRuns = new Set<string>();
  const childJobs = new Set<string>();
  for (const [index, item] of execution.items.entries()) {
    if (item.item_id !== execution.selection.item_ids[index]) {
      throw new TypeError("Project execution work must exactly cover its ordered selection.");
    }
    requiredString(item.run_id, "Child run ID");
    if (childRuns.has(item.run_id)) throw new TypeError("Child run IDs must be unique.");
    childRuns.add(item.run_id);
    if (!Array.isArray(item.job_ids) || item.job_ids.length === 0) {
      throw new TypeError("Each execution item requires child jobs.");
    }
    for (const jobId of item.job_ids) {
      requiredString(jobId, "Child job ID");
      if (childJobs.has(jobId)) throw new TypeError("Child job IDs must be unique.");
      childJobs.add(jobId);
    }
    if (!["pending", "claimed", "succeeded", "failed", "cancelled"].includes(item.state)) {
      throw new TypeError("Unsupported project execution item state.");
    }
    if ((item.state === "claimed") !== (item.claim !== null)) {
      throw new TypeError("Only a claimed execution item may retain a claim.");
    }
  }
  const approvalInput: ProjectExecutionInput = {
    execution_id: execution.execution_id,
    project: execution.project,
    plan: { ...execution.plan, artifact },
    selection: execution.selection,
    policy: execution.policy,
    estimate: execution.estimate,
    items: execution.items.map(({ item_id, run_id, job_ids }) => ({ item_id, run_id, job_ids })),
  };
  if (execution.approval_sha256 !== projectExecutionApprovalSha256(approvalInput)) {
    throw new TypeError("Project execution approval digest is invalid.");
  }
  if (
    (execution.state === "awaiting_approval" && execution.approval !== null)
    || (["approved", "running", "complete", "failed"].includes(execution.state) && execution.approval === null)
  ) {
    throw new TypeError("Project execution approval does not match its state.");
  }
  if (execution.state === "complete" && execution.items.some((item) => item.state !== "succeeded")) {
    throw new TypeError("A complete project execution requires every item to succeed.");
  }
  return structuredClone(execution);
}
