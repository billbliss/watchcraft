import { sha256 } from "@noble/hashes/sha2.js";
import { bytesToHex } from "@noble/hashes/utils.js";

export type JsonPrimitive = null | boolean | number | string;
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue };

export interface ArtifactReference {
  store: "r2";
  algorithm: "sha256";
  digest: string;
  byte_length: number;
  media_type: string;
  artifact_kind: string;
  schema: {
    id: string;
    version: number;
  };
  key: string;
  retention?: {
    class: "ephemeral";
    expires_at: number;
  };
}

export type AuthoringOperation = "generate" | "import" | "validate" | "compile";

export interface RegistryArtifactContract {
  artifact_kind: string;
  schema: {
    id: string;
    version: number;
  };
}

export interface RegistryHandlerDefinition {
  id: string;
  version: string;
  operation: AuthoringOperation;
  inputs: RegistryArtifactContract[];
  dependencies: RegistryArtifactContract[];
  output: RegistryArtifactContract;
  execution_profile: {
    id: string;
    version: string;
  };
  lease_class: string;
  retry_policy: {
    max_attempts: number;
    retryable_classifications: string[];
  };
}

export interface RegistryExecutionProfile {
  id: string;
  version: string;
  dispatcher: {
    kind: "github-actions";
    workflow: string;
  };
  platform: {
    os: "linux" | "macos" | "windows";
    architecture: "x64" | "arm64";
  };
  dependency_class: string;
  cache_class: string;
  timeout_minutes: number;
  lease_duration_ms: number;
  heartbeat_interval_ms: number;
  data_access: "public" | "private-derived" | "private-source";
  secret_capabilities: string[];
}

export interface AuthoringCapabilityRegistry {
  kind: "watchcraft.authoring-capability-registry";
  schema_version: 1;
  registry_version: string;
  handlers: RegistryHandlerDefinition[];
  execution_profiles: RegistryExecutionProfile[];
}

export interface RegistryResolutionSnapshot {
  registry_version: string;
  registry_sha256: string;
  handler: RegistryHandlerDefinition;
  execution_profile: RegistryExecutionProfile;
}

export interface AuthoringJobSpec {
  operation: AuthoringOperation;
  artifact_kind: string;
  output_schema: {
    id: string;
    version: number;
  };
  handler: {
    id: string;
    version: string;
  };
  source: {
    media_asset_id: string;
    edition_id?: string;
    coordinate_id?: string;
  };
  inputs: ArtifactReference[];
  dependencies: ArtifactReference[];
  configuration: { [key: string]: JsonValue };
  /** Absent only on pre-registry jobs and the synthetic control-plane smoke. */
  registry_snapshot?: RegistryResolutionSnapshot;
}

export type AuthoringJobState =
  | "proposed"
  | "awaiting_approval"
  | "ready"
  | "dispatch_pending"
  | "dispatched"
  | "claimed"
  | "running"
  | "succeeded"
  | "retryable_failed"
  | "terminal_failed"
  | "cancelled";

export interface JobApproval {
  actor: string;
  approved_at: number;
  spec_sha256: string;
}

export interface JobDispatch {
  generation: number;
  requested_at: number;
  github_run_id?: string;
  github_run_url?: string;
  recorded_at?: number;
}

export interface JobLease {
  attempt_id: string;
  owner: string;
  acquired_at: number;
  expires_at: number;
  heartbeat_at: number;
}

export interface JobFailure {
  classification: string;
  message: string;
  retryable: boolean;
  occurred_at: number;
}

export interface JobAttemptSummary {
  attempt_id: string;
  owner: string;
  state: "claimed" | "running" | "succeeded" | "failed";
  started_at: number;
  updated_at: number;
  github_run_id?: string;
  artifact?: ArtifactReference;
  failure?: JobFailure;
}

export interface AuthoringJob {
  kind: "watchcraft.authoring-job";
  schema_version: 1;
  job_id: string;
  run_id: string;
  revision: number;
  spec: AuthoringJobSpec;
  spec_sha256: string;
  idempotency_key: string;
  state: AuthoringJobState;
  approval: JobApproval | null;
  dispatch: JobDispatch | null;
  lease: JobLease | null;
  attempts: JobAttemptSummary[];
  result: ArtifactReference | null;
  failure: JobFailure | null;
  created_at: number;
  updated_at: number;
  last_command_id: string;
}

export interface AuthoringRun {
  kind: "watchcraft.authoring-run";
  schema_version: 1;
  run_id: string;
  revision: number;
  request: { [key: string]: JsonValue };
  source_snapshot: ArtifactReference | null;
  plan: ArtifactReference | null;
  approval_sha256: string | null;
  approval: JobApproval | null;
  job_ids: string[];
  state: "requested" | "planned" | "approved" | "running" | "complete" | "failed" | "cancelled";
  created_at: number;
  updated_at: number;
  last_command_id: string;
}

function canonicalValue(value: JsonValue): JsonValue {
  if (Array.isArray(value)) return value.map(canonicalValue);
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value)
        .sort(([left], [right]) => left < right ? -1 : left > right ? 1 : 0)
        .map(([key, child]) => [key, canonicalValue(child)]),
    );
  }
  if (typeof value === "number" && !Number.isFinite(value)) {
    throw new TypeError("Canonical JSON does not permit non-finite numbers.");
  }
  return value;
}

export function canonicalJson(value: JsonValue): string {
  return JSON.stringify(canonicalValue(value));
}

export function sha256Hex(value: Uint8Array | string): string {
  const bytes = typeof value === "string" ? new TextEncoder().encode(value) : value;
  return bytesToHex(sha256(bytes));
}

export function jobSpecSha256(spec: AuthoringJobSpec): string {
  return sha256Hex(canonicalJson(spec as unknown as JsonValue));
}

export function capabilityRegistrySha256(registry: AuthoringCapabilityRegistry): string {
  return sha256Hex(canonicalJson(registry as unknown as JsonValue));
}

function objectValue(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${label} must be an object.`);
  }
  return value as Record<string, unknown>;
}

function stringValue(value: unknown, label: string): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new TypeError(`${label} must be a non-empty string.`);
  }
  return value;
}

function integerValue(value: unknown, label: string, minimum = 0): number {
  if (!Number.isSafeInteger(value) || (value as number) < minimum) {
    throw new TypeError(`${label} must be an integer greater than or equal to ${minimum}.`);
  }
  return value as number;
}

function optionalString(value: unknown, label: string): string | undefined {
  return value === undefined ? undefined : stringValue(value, label);
}

function nullableObject<T>(
  value: unknown,
  label: string,
  parser: (candidate: unknown) => T,
): T | null {
  if (value === null) return null;
  if (value === undefined) throw new TypeError(`${label} must be present.`);
  return parser(value);
}

function parseJsonValue(value: unknown, label: string): JsonValue {
  if (value === null || typeof value === "string" || typeof value === "boolean") return value;
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new TypeError(`${label} must contain finite numbers.`);
    return value;
  }
  if (Array.isArray(value)) {
    return value.map((child, index) => parseJsonValue(child, `${label}[${index}]`));
  }
  const candidate = objectValue(value, label);
  return Object.fromEntries(
    Object.entries(candidate).map(([key, child]) => [key, parseJsonValue(child, `${label}.${key}`)]),
  );
}

function sha256Value(value: unknown, label: string): string {
  const digest = stringValue(value, label);
  if (!/^[a-f0-9]{64}$/.test(digest)) {
    throw new TypeError(`${label} must be a lowercase SHA-256 digest.`);
  }
  return digest;
}

function uniqueStrings(value: unknown, label: string): string[] {
  if (!Array.isArray(value)) throw new TypeError(`${label} must be an array.`);
  const entries = value.map((entry, index) => stringValue(entry, `${label}[${index}]`));
  if (new Set(entries).size !== entries.length) {
    throw new TypeError(`${label} must not contain duplicates.`);
  }
  return entries;
}

function parseRegistryArtifactContract(value: unknown, label: string): RegistryArtifactContract {
  const candidate = objectValue(value, label);
  const schema = objectValue(candidate.schema, `${label} schema`);
  return {
    artifact_kind: stringValue(candidate.artifact_kind, `${label} artifact kind`),
    schema: {
      id: stringValue(schema.id, `${label} schema ID`),
      version: integerValue(schema.version, `${label} schema version`, 1),
    },
  };
}

function parseRegistryHandler(value: unknown, label: string): RegistryHandlerDefinition {
  const candidate = objectValue(value, label);
  const operation = stringValue(candidate.operation, `${label} operation`);
  if (!["generate", "import", "validate", "compile"].includes(operation)) {
    throw new TypeError(`Unsupported registry handler operation ${operation}.`);
  }
  if (!Array.isArray(candidate.inputs) || !Array.isArray(candidate.dependencies)) {
    throw new TypeError(`${label} inputs and dependencies must be arrays.`);
  }
  const executionProfile = objectValue(candidate.execution_profile, `${label} execution profile`);
  const retryPolicy = objectValue(candidate.retry_policy, `${label} retry policy`);
  const maximumAttempts = integerValue(retryPolicy.max_attempts, `${label} maximum attempts`, 1);
  if (maximumAttempts > 20) {
    throw new TypeError(`${label} maximum attempts must not exceed 20.`);
  }
  return {
    id: stringValue(candidate.id, `${label} ID`),
    version: stringValue(candidate.version, `${label} version`),
    operation: operation as AuthoringOperation,
    inputs: candidate.inputs.map((entry, index) => parseRegistryArtifactContract(entry, `${label} input ${index}`)),
    dependencies: candidate.dependencies.map((entry, index) => parseRegistryArtifactContract(entry, `${label} dependency ${index}`)),
    output: parseRegistryArtifactContract(candidate.output, `${label} output`),
    execution_profile: {
      id: stringValue(executionProfile.id, `${label} execution profile ID`),
      version: stringValue(executionProfile.version, `${label} execution profile version`),
    },
    lease_class: stringValue(candidate.lease_class, `${label} lease class`),
    retry_policy: {
      max_attempts: maximumAttempts,
      retryable_classifications: uniqueStrings(
        retryPolicy.retryable_classifications,
        `${label} retryable classifications`,
      ),
    },
  };
}

function parseRegistryExecutionProfile(value: unknown, label: string): RegistryExecutionProfile {
  const candidate = objectValue(value, label);
  const dispatcher = objectValue(candidate.dispatcher, `${label} dispatcher`);
  const platform = objectValue(candidate.platform, `${label} platform`);
  if (dispatcher.kind !== "github-actions") {
    throw new TypeError(`${label} dispatcher must be github-actions.`);
  }
  const workflow = stringValue(dispatcher.workflow, `${label} workflow`);
  if (!/^[A-Za-z0-9._-]+\.ya?ml$/.test(workflow)) {
    throw new TypeError(`${label} workflow must be a workflow filename.`);
  }
  const os = stringValue(platform.os, `${label} operating system`);
  if (!["linux", "macos", "windows"].includes(os)) {
    throw new TypeError(`Unsupported execution operating system ${os}.`);
  }
  const architecture = stringValue(platform.architecture, `${label} architecture`);
  if (!["x64", "arm64"].includes(architecture)) {
    throw new TypeError(`Unsupported execution architecture ${architecture}.`);
  }
  const timeoutMinutes = integerValue(candidate.timeout_minutes, `${label} timeout`, 1);
  if (timeoutMinutes > 360) throw new TypeError(`${label} timeout must not exceed 360 minutes.`);
  const leaseDurationMs = integerValue(candidate.lease_duration_ms, `${label} lease duration`, 1_000);
  const heartbeatIntervalMs = integerValue(
    candidate.heartbeat_interval_ms,
    `${label} heartbeat interval`,
    1_000,
  );
  if (heartbeatIntervalMs >= leaseDurationMs) {
    throw new TypeError(`${label} heartbeat interval must be shorter than its lease duration.`);
  }
  const dataAccess = stringValue(candidate.data_access, `${label} data access`);
  if (!["public", "private-derived", "private-source"].includes(dataAccess)) {
    throw new TypeError(`Unsupported execution data access ${dataAccess}.`);
  }
  return {
    id: stringValue(candidate.id, `${label} ID`),
    version: stringValue(candidate.version, `${label} version`),
    dispatcher: { kind: "github-actions", workflow },
    platform: {
      os: os as RegistryExecutionProfile["platform"]["os"],
      architecture: architecture as RegistryExecutionProfile["platform"]["architecture"],
    },
    dependency_class: stringValue(candidate.dependency_class, `${label} dependency class`),
    cache_class: stringValue(candidate.cache_class, `${label} cache class`),
    timeout_minutes: timeoutMinutes,
    lease_duration_ms: leaseDurationMs,
    heartbeat_interval_ms: heartbeatIntervalMs,
    data_access: dataAccess as RegistryExecutionProfile["data_access"],
    secret_capabilities: uniqueStrings(candidate.secret_capabilities, `${label} secret capabilities`),
  };
}

export function parseCapabilityRegistry(value: unknown): AuthoringCapabilityRegistry {
  const candidate = objectValue(value, "Authoring capability registry");
  if (candidate.kind !== "watchcraft.authoring-capability-registry" || candidate.schema_version !== 1) {
    throw new TypeError("Unsupported authoring capability registry schema.");
  }
  if (!Array.isArray(candidate.handlers) || !Array.isArray(candidate.execution_profiles)) {
    throw new TypeError("Registry handlers and execution profiles must be arrays.");
  }
  const handlers = candidate.handlers.map((entry, index) => parseRegistryHandler(entry, `Registry handler ${index}`));
  const executionProfiles = candidate.execution_profiles.map(
    (entry, index) => parseRegistryExecutionProfile(entry, `Registry execution profile ${index}`),
  );
  const handlerKeys = handlers.map((handler) => `${handler.id}@${handler.version}`);
  const profileKeys = executionProfiles.map((profile) => `${profile.id}@${profile.version}`);
  if (new Set(handlerKeys).size !== handlerKeys.length) {
    throw new TypeError("Registry handler identities must be unique.");
  }
  if (new Set(profileKeys).size !== profileKeys.length) {
    throw new TypeError("Registry execution profile identities must be unique.");
  }
  const profileSet = new Set(profileKeys);
  for (const handler of handlers) {
    const profileKey = `${handler.execution_profile.id}@${handler.execution_profile.version}`;
    if (!profileSet.has(profileKey)) {
      throw new TypeError(`Registry handler ${handler.id}@${handler.version} references missing profile ${profileKey}.`);
    }
  }
  return {
    kind: "watchcraft.authoring-capability-registry",
    schema_version: 1,
    registry_version: stringValue(candidate.registry_version, "Registry version"),
    handlers,
    execution_profiles: executionProfiles,
  };
}

export function parseRegistryResolutionSnapshot(value: unknown): RegistryResolutionSnapshot {
  const candidate = objectValue(value, "Registry resolution snapshot");
  return {
    registry_version: stringValue(candidate.registry_version, "Registry snapshot version"),
    registry_sha256: sha256Value(candidate.registry_sha256, "Registry snapshot digest"),
    handler: parseRegistryHandler(candidate.handler, "Registry snapshot handler"),
    execution_profile: parseRegistryExecutionProfile(
      candidate.execution_profile,
      "Registry snapshot execution profile",
    ),
  };
}

export function parseArtifactReference(
  value: unknown,
  options: { allowEphemeral?: boolean } = {},
): ArtifactReference {
  const candidate = objectValue(value, "Artifact reference");
  const schema = objectValue(candidate.schema, "Artifact schema");
  const digest = sha256Value(candidate.digest, "Artifact digest");
  const key = stringValue(candidate.key, "Artifact key");
  const authoritativeKey = `objects/sha256/${digest.slice(0, 2)}/${digest.slice(2)}`;
  const retentionValue = candidate.retention;
  let retention: ArtifactReference["retention"];
  if (retentionValue === undefined) {
    if (key !== authoritativeKey) {
      throw new TypeError(`Authoritative artifact key must be ${authoritativeKey}.`);
    }
  } else {
    if (!options.allowEphemeral) {
      throw new TypeError("Ephemeral artifacts are allowed only as staged job inputs.");
    }
    const candidateRetention = objectValue(retentionValue, "Artifact retention");
    if (candidateRetention.class !== "ephemeral") {
      throw new TypeError("Staged artifact retention class must be ephemeral.");
    }
    retention = {
      class: "ephemeral",
      expires_at: integerValue(candidateRetention.expires_at, "Artifact expiration", 1),
    };
    const escapedDigest = `${digest.slice(0, 2)}/${digest.slice(2)}`;
    const acquisitionId =
      "[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}";
    if (!new RegExp(`^staging/${acquisitionId}/sha256/${escapedDigest}$`).test(key)) {
      throw new TypeError("Staged artifact key must bind its acquisition ID and digest.");
    }
  }
  if (candidate.store !== "r2" || candidate.algorithm !== "sha256") {
    throw new TypeError("Artifact reference must use R2 and SHA-256.");
  }
  return {
    store: "r2",
    algorithm: "sha256",
    digest,
    byte_length: integerValue(candidate.byte_length, "Artifact byte length"),
    media_type: stringValue(candidate.media_type, "Artifact media type"),
    artifact_kind: stringValue(candidate.artifact_kind, "Artifact kind"),
    schema: {
      id: stringValue(schema.id, "Artifact schema ID"),
      version: integerValue(schema.version, "Artifact schema version", 1),
    },
    key,
    ...(retention ? { retention } : {}),
  };
}

export function parseAuthoringJobSpec(value: unknown): AuthoringJobSpec {
  const candidate = objectValue(value, "Authoring job specification");
  const operation = stringValue(candidate.operation, "Job operation");
  if (!["generate", "import", "validate", "compile"].includes(operation)) {
    throw new TypeError(`Unsupported job operation ${operation}.`);
  }
  const outputSchema = objectValue(candidate.output_schema, "Output schema");
  const handler = objectValue(candidate.handler, "Job handler");
  const source = objectValue(candidate.source, "Job source");
  const inputs = candidate.inputs;
  const dependencies = candidate.dependencies;
  const configuration = parseJsonValue(candidate.configuration, "Job configuration");
  if (!Array.isArray(inputs) || !Array.isArray(dependencies)) {
    throw new TypeError("Job inputs and dependencies must be arrays.");
  }
  if (Array.isArray(configuration) || configuration === null || typeof configuration !== "object") {
    throw new TypeError("Job configuration must be an object.");
  }
  const editionId = source.edition_id;
  const coordinateId = source.coordinate_id;
  if (editionId !== undefined && typeof editionId !== "string") {
    throw new TypeError("Source edition ID must be a string.");
  }
  if (coordinateId !== undefined && typeof coordinateId !== "string") {
    throw new TypeError("Source coordinate ID must be a string.");
  }
  return {
    operation: operation as AuthoringJobSpec["operation"],
    artifact_kind: stringValue(candidate.artifact_kind, "Artifact kind"),
    output_schema: {
      id: stringValue(outputSchema.id, "Output schema ID"),
      version: integerValue(outputSchema.version, "Output schema version", 1),
    },
    handler: {
      id: stringValue(handler.id, "Handler ID"),
      version: stringValue(handler.version, "Handler version"),
    },
    source: {
      media_asset_id: stringValue(source.media_asset_id, "Source media asset ID"),
      ...(editionId === undefined ? {} : { edition_id: editionId }),
      ...(coordinateId === undefined ? {} : { coordinate_id: coordinateId }),
    },
    inputs: inputs.map((input) => parseArtifactReference(input, { allowEphemeral: true })),
    dependencies: dependencies.map((dependency) => parseArtifactReference(dependency)),
    configuration,
    ...(candidate.registry_snapshot === undefined
      ? {}
      : { registry_snapshot: parseRegistryResolutionSnapshot(candidate.registry_snapshot) }),
  };
}

function parseApproval(value: unknown): JobApproval {
  const candidate = objectValue(value, "Job approval");
  return {
    actor: stringValue(candidate.actor, "Approval actor"),
    approved_at: integerValue(candidate.approved_at, "Approval time"),
    spec_sha256: sha256Value(candidate.spec_sha256, "Approved specification digest"),
  };
}

function parseDispatch(value: unknown): JobDispatch {
  const candidate = objectValue(value, "Job dispatch");
  return {
    generation: integerValue(candidate.generation, "Dispatch generation", 1),
    requested_at: integerValue(candidate.requested_at, "Dispatch request time"),
    ...(candidate.github_run_id === undefined
      ? {}
      : { github_run_id: stringValue(candidate.github_run_id, "GitHub run ID") }),
    ...(candidate.github_run_url === undefined
      ? {}
      : { github_run_url: stringValue(candidate.github_run_url, "GitHub run URL") }),
    ...(candidate.recorded_at === undefined
      ? {}
      : { recorded_at: integerValue(candidate.recorded_at, "Dispatch record time") }),
  };
}

function parseLease(value: unknown): JobLease {
  const candidate = objectValue(value, "Job lease");
  const acquiredAt = integerValue(candidate.acquired_at, "Lease acquisition time");
  const heartbeatAt = integerValue(candidate.heartbeat_at, "Lease heartbeat time");
  const expiresAt = integerValue(candidate.expires_at, "Lease expiry time");
  if (heartbeatAt < acquiredAt || expiresAt <= heartbeatAt) {
    throw new TypeError("Job lease timestamps are inconsistent.");
  }
  return {
    attempt_id: stringValue(candidate.attempt_id, "Lease attempt ID"),
    owner: stringValue(candidate.owner, "Lease owner"),
    acquired_at: acquiredAt,
    expires_at: expiresAt,
    heartbeat_at: heartbeatAt,
  };
}

function parseFailure(value: unknown): JobFailure {
  const candidate = objectValue(value, "Job failure");
  if (typeof candidate.retryable !== "boolean") {
    throw new TypeError("Job failure retryable flag must be a boolean.");
  }
  return {
    classification: stringValue(candidate.classification, "Failure classification"),
    message: stringValue(candidate.message, "Failure message"),
    retryable: candidate.retryable,
    occurred_at: integerValue(candidate.occurred_at, "Failure time"),
  };
}

function parseAttempt(value: unknown): JobAttemptSummary {
  const candidate = objectValue(value, "Job attempt");
  const state = stringValue(candidate.state, "Attempt state");
  if (!["claimed", "running", "succeeded", "failed"].includes(state)) {
    throw new TypeError(`Unsupported attempt state ${state}.`);
  }
  const startedAt = integerValue(candidate.started_at, "Attempt start time");
  const updatedAt = integerValue(candidate.updated_at, "Attempt update time");
  const githubRunId = optionalString(candidate.github_run_id, "Attempt GitHub run ID");
  if (updatedAt < startedAt) throw new TypeError("Attempt timestamps are inconsistent.");
  return {
    attempt_id: stringValue(candidate.attempt_id, "Attempt ID"),
    owner: stringValue(candidate.owner, "Attempt owner"),
    state: state as JobAttemptSummary["state"],
    started_at: startedAt,
    updated_at: updatedAt,
    ...(githubRunId === undefined ? {} : { github_run_id: githubRunId }),
    ...(candidate.artifact === undefined ? {} : { artifact: parseArtifactReference(candidate.artifact) }),
    ...(candidate.failure === undefined ? {} : { failure: parseFailure(candidate.failure) }),
  };
}

export function parseAuthoringJob(value: unknown): AuthoringJob {
  const candidate = objectValue(value, "Authoring job");
  if (candidate.kind !== "watchcraft.authoring-job" || candidate.schema_version !== 1) {
    throw new TypeError("Unsupported authoring job schema.");
  }
  const state = stringValue(candidate.state, "Job state");
  const states: AuthoringJobState[] = [
    "proposed", "awaiting_approval", "ready", "dispatch_pending", "dispatched", "claimed",
    "running", "succeeded", "retryable_failed", "terminal_failed", "cancelled",
  ];
  if (!states.includes(state as AuthoringJobState)) throw new TypeError(`Unsupported job state ${state}.`);
  const spec = parseAuthoringJobSpec(candidate.spec);
  const expectedHash = jobSpecSha256(spec);
  if (candidate.spec_sha256 !== expectedHash || candidate.idempotency_key !== expectedHash) {
    throw new TypeError("Authoring job specification hash is invalid.");
  }
  if (!Array.isArray(candidate.attempts) || candidate.attempts.length > 20) {
    throw new TypeError("Job attempts must be a bounded array.");
  }
  const createdAt = integerValue(candidate.created_at, "Job creation time");
  const updatedAt = integerValue(candidate.updated_at, "Job update time");
  if (updatedAt < createdAt) throw new TypeError("Job timestamps are inconsistent.");
  return {
    kind: "watchcraft.authoring-job",
    schema_version: 1,
    job_id: stringValue(candidate.job_id, "Job ID"),
    run_id: stringValue(candidate.run_id, "Run ID"),
    revision: integerValue(candidate.revision, "Job revision", 1),
    spec,
    spec_sha256: expectedHash,
    idempotency_key: expectedHash,
    state: state as AuthoringJobState,
    approval: nullableObject(candidate.approval, "Job approval", parseApproval),
    dispatch: nullableObject(candidate.dispatch, "Job dispatch", parseDispatch),
    lease: nullableObject(candidate.lease, "Job lease", parseLease),
    attempts: candidate.attempts.map(parseAttempt),
    result: nullableObject(candidate.result, "Job result", parseArtifactReference),
    failure: nullableObject(candidate.failure, "Job failure", parseFailure),
    created_at: createdAt,
    updated_at: updatedAt,
    last_command_id: stringValue(candidate.last_command_id, "Last command ID"),
  };
}

export function parseAuthoringRun(value: unknown): AuthoringRun {
  const candidate = objectValue(value, "Authoring run");
  if (candidate.kind !== "watchcraft.authoring-run" || candidate.schema_version !== 1) {
    throw new TypeError("Unsupported authoring run schema.");
  }
  const state = stringValue(candidate.state, "Run state");
  const states: AuthoringRun["state"][] = [
    "requested", "planned", "approved", "running", "complete", "failed", "cancelled",
  ];
  if (!states.includes(state as AuthoringRun["state"])) throw new TypeError(`Unsupported run state ${state}.`);
  const request = parseJsonValue(candidate.request, "Run request");
  if (Array.isArray(request) || request === null || typeof request !== "object") {
    throw new TypeError("Run request must be an object.");
  }
  if (!Array.isArray(candidate.job_ids)) throw new TypeError("Run job IDs must be an array.");
  const createdAt = integerValue(candidate.created_at, "Run creation time");
  const updatedAt = integerValue(candidate.updated_at, "Run update time");
  if (updatedAt < createdAt) throw new TypeError("Run timestamps are inconsistent.");
  return {
    kind: "watchcraft.authoring-run",
    schema_version: 1,
    run_id: stringValue(candidate.run_id, "Run ID"),
    revision: integerValue(candidate.revision, "Run revision", 1),
    request,
    source_snapshot: nullableObject(candidate.source_snapshot, "Run source snapshot", parseArtifactReference),
    plan: nullableObject(candidate.plan, "Run plan", parseArtifactReference),
    approval_sha256: candidate.approval_sha256 === null || candidate.approval_sha256 === undefined
      ? null
      : sha256Value(candidate.approval_sha256, "Run approval digest"),
    approval: nullableObject(candidate.approval, "Run approval", parseApproval),
    job_ids: candidate.job_ids.map((jobId, index) => stringValue(jobId, `Run job ID ${index}`)),
    state: state as AuthoringRun["state"],
    created_at: createdAt,
    updated_at: updatedAt,
    last_command_id: stringValue(candidate.last_command_id, "Run last command ID"),
  };
}

export function artifactKey(digest: string): string {
  if (!/^[a-f0-9]{64}$/.test(digest)) {
    throw new TypeError("Artifact digest must be a lowercase SHA-256 digest.");
  }
  return `objects/sha256/${digest.slice(0, 2)}/${digest.slice(2)}`;
}
