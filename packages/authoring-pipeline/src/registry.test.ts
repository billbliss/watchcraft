import assert from "node:assert/strict";
import test from "node:test";

import {
  capabilityRegistrySha256,
  DEFAULT_CAPABILITY_REGISTRY,
  parseArtifactReference,
  parseCapabilityRegistry,
  resolveJobSpecAgainstRegistry,
  verifyRegistryResolutionSnapshot,
} from "./index.ts";

const lexicalSpec = {
  operation: "generate" as const,
  artifact_kind: "analysis",
  output_schema: { id: "watchcraft.analysis.lexical", version: 1 },
  handler: { id: "watchcraft.analysis.lexical", version: "1" },
  source: { media_asset_id: "operator:lexical-analysis" },
  inputs: [],
  dependencies: [],
  configuration: { title: "Color workflow", text: "Balance exposure first." },
};

const transcriptionSmokeSpec = {
  operation: "generate" as const,
  artifact_kind: "transcript",
  output_schema: { id: "watchcraft.transcript", version: 1 },
  handler: { id: "watchcraft.transcript.mlx-whisper-smoke", version: "1" },
  source: { media_asset_id: "synthetic:mlx-audio-smoke" },
  inputs: [],
  dependencies: [],
  configuration: { fixture_text: "Watchcraft verifies audio." },
};

const httpTranscriptionSmokeSpec = {
  operation: "generate" as const,
  artifact_kind: "transcript",
  output_schema: { id: "watchcraft.transcript", version: 1 },
  handler: { id: "watchcraft.transcript.mlx-whisper-http-smoke", version: "1" },
  source: { media_asset_id: "fixture:openai-whisper-jfk-flac" },
  inputs: [],
  dependencies: [],
  configuration: { url: "https://example.invalid/fixture.flac" },
};

const sourceAudioDigest = "a".repeat(64);
const stagedSourceAudio = {
  store: "r2" as const,
  algorithm: "sha256" as const,
  digest: sourceAudioDigest,
  byte_length: 1024,
  media_type: "audio/webm",
  artifact_kind: "source-audio",
  schema: { id: "watchcraft.source-audio", version: 1 },
  key: `staging/00000000-0000-4000-8000-000000000000/sha256/${sourceAudioDigest.slice(0, 2)}/${sourceAudioDigest.slice(2)}`,
  retention: { class: "ephemeral" as const, expires_at: 2_000_000_000_000 },
};

const stagedTranscriptionSmokeSpec = {
  operation: "generate" as const,
  artifact_kind: "transcript",
  output_schema: { id: "watchcraft.transcript", version: 1 },
  handler: { id: "watchcraft.transcript.mlx-whisper-staged-smoke", version: "1" },
  source: { media_asset_id: "youtube:WPtpUu3uIUI" },
  inputs: [stagedSourceAudio],
  dependencies: [],
  configuration: {
    acquisition: {
      method: { id: "watchcraft.youtube.yt-dlp-local", version: "1" },
      source: { media_asset_id: "youtube:WPtpUu3uIUI" },
      media: {
        algorithm: "sha256",
        digest: sourceAudioDigest,
        byte_length: 1024,
        duration_seconds: 59,
      },
    },
    maximum_bytes: 10_000_000,
    maximum_duration_seconds: 300,
    language: "en",
    model: "mlx-community/whisper-tiny-mlx",
  },
};

const productionTranscriptionSpec = {
  ...stagedTranscriptionSmokeSpec,
  handler: {
    id: "watchcraft.transcript.mlx-whisper-large-v3-turbo-q4",
    version: "1",
  },
  configuration: {
    ...stagedTranscriptionSmokeSpec.configuration,
    maximum_bytes: 100_000_000,
    maximum_duration_seconds: 7_200,
    model: "mlx-community/whisper-large-v3-turbo-q4",
  },
};

const transcriptDigest = "d".repeat(64);
const transcriptArtifact = {
  store: "r2" as const,
  algorithm: "sha256" as const,
  digest: transcriptDigest,
  byte_length: 12_345,
  media_type: "application/json",
  artifact_kind: "transcript",
  schema: { id: "watchcraft.transcript", version: 1 },
  key: `objects/sha256/${transcriptDigest.slice(0, 2)}/${transcriptDigest.slice(2)}`,
};

const educationalAnalysisSpec = {
  operation: "generate" as const,
  artifact_kind: "analysis",
  output_schema: { id: "watchcraft.video-analysis", version: 2 },
  handler: { id: "watchcraft.analysis.educational-video", version: "1" },
  source: { media_asset_id: "youtube:WPtpUu3uIUI" },
  inputs: [],
  dependencies: [transcriptArtifact],
  configuration: {
    model: "gpt-5-nano",
    prompt_version: 3,
    retries: 5,
    timeout_seconds: 300,
    max_transcript_chars: 1_500_000,
    source_metadata: {
      type: "youtube",
      source_id: "youtube:WPtpUu3uIUI",
      title: "Three hotel-management techniques",
    },
    video: "WPtpUu3uIUI.youtube",
  },
};

const secondAnalysisArtifact = {
  ...transcriptArtifact,
  digest: "e".repeat(64),
  artifact_kind: "analysis",
  schema: { id: "watchcraft.video-analysis", version: 2 },
  key: `objects/sha256/ee/${"e".repeat(62)}`,
};

const firstAnalysisArtifact = {
  ...secondAnalysisArtifact,
  digest: "c".repeat(64),
  key: `objects/sha256/cc/${"c".repeat(62)}`,
};

const topicNormalizationSpec = {
  operation: "generate" as const,
  artifact_kind: "topic-normalization",
  output_schema: { id: "watchcraft.topic-normalization", version: 1 },
  handler: { id: "watchcraft.normalize.collection-topics", version: "1" },
  source: { media_asset_id: "catalog-project:essence-of-linear-algebra" },
  inputs: [],
  dependencies: [firstAnalysisArtifact, secondAnalysisArtifact],
  configuration: { project_id: "essence-of-linear-algebra" },
};

const playlistIteratorSpec = {
  operation: "generate" as const,
  artifact_kind: "collection-iterator-snapshot",
  output_schema: {
    id: "watchcraft.collection-iterator-snapshot",
    version: 1,
  },
  handler: { id: "watchcraft.iterator.youtube-playlist", version: "1" },
  source: { media_asset_id: "youtube-playlist:PL1234567890_example" },
  inputs: [],
  dependencies: [],
  configuration: { project: { project_id: "example" } },
};

const iteratorSnapshotDigest = "f".repeat(64);
const iteratorSnapshotArtifact = {
  store: "r2" as const,
  algorithm: "sha256" as const,
  digest: iteratorSnapshotDigest,
  byte_length: 15_512,
  media_type: "application/json",
  artifact_kind: "collection-iterator-snapshot",
  schema: { id: "watchcraft.collection-iterator-snapshot", version: 1 },
  key: `objects/sha256/${iteratorSnapshotDigest.slice(0, 2)}/${iteratorSnapshotDigest.slice(2)}`,
};

const projectProcessingPlanSpec = {
  operation: "generate" as const,
  artifact_kind: "project-processing-plan",
  output_schema: { id: "watchcraft.project-processing-plan", version: 1 },
  handler: { id: "watchcraft.planner.video-collection", version: "1" },
  source: { media_asset_id: "catalog-project:essence-of-linear-algebra" },
  inputs: [iteratorSnapshotArtifact],
  dependencies: [],
  configuration: { project: { project_id: "essence-of-linear-algebra" } },
};

const projectPlanDigest = "9".repeat(64);
const projectPlanArtifact = {
  ...iteratorSnapshotArtifact,
  digest: projectPlanDigest,
  byte_length: 32_253,
  artifact_kind: "project-processing-plan",
  schema: { id: "watchcraft.project-processing-plan", version: 1 },
  key: `objects/sha256/${projectPlanDigest.slice(0, 2)}/${projectPlanDigest.slice(2)}`,
};
const normalizationDigest = "8".repeat(64);
const normalizationArtifact = {
  ...iteratorSnapshotArtifact,
  digest: normalizationDigest,
  byte_length: 50_000,
  artifact_kind: "topic-normalization",
  schema: { id: "watchcraft.topic-normalization", version: 1 },
  key: `objects/sha256/${normalizationDigest.slice(0, 2)}/${normalizationDigest.slice(2)}`,
};
const terminologyResolutionSpec = {
  operation: "generate" as const,
  artifact_kind: "terminology-resolution",
  output_schema: { id: "watchcraft.terminology-resolution", version: 1 },
  handler: { id: "watchcraft.resolve.collection-terminology", version: "2" },
  source: { media_asset_id: "catalog-project:essence-of-linear-algebra" },
  inputs: [],
  dependencies: [
    transcriptArtifact,
    { ...transcriptArtifact, digest: "7".repeat(64), key: `objects/sha256/77/${"7".repeat(62)}` },
    firstAnalysisArtifact,
    secondAnalysisArtifact,
  ],
  configuration: { project: { project_id: "essence-of-linear-algebra" } },
};
const collectionCompilationSpec = {
  operation: "compile" as const,
  artifact_kind: "collection-compilation",
  output_schema: { id: "watchcraft.collection-compilation", version: 1 },
  handler: { id: "watchcraft.compile.video-collection", version: "2" },
  source: { media_asset_id: "catalog-project:essence-of-linear-algebra" },
  inputs: [projectPlanArtifact, iteratorSnapshotArtifact],
  dependencies: [
    transcriptArtifact,
    { ...transcriptArtifact, digest: "7".repeat(64), key: `objects/sha256/77/${"7".repeat(62)}` },
    firstAnalysisArtifact,
    secondAnalysisArtifact,
    normalizationArtifact,
  ],
  configuration: { project: { project_id: "essence-of-linear-algebra" } },
};

test("the checked-in registry is valid, stable, and fully resolves an approved job", () => {
  const registry = parseCapabilityRegistry(DEFAULT_CAPABILITY_REGISTRY);
  const spec = resolveJobSpecAgainstRegistry(lexicalSpec, registry);

  assert.equal(spec.registry_snapshot?.registry_version, "2026-09-09.3");
  assert.equal(spec.registry_snapshot?.registry_sha256, capabilityRegistrySha256(registry));
  assert.equal(spec.registry_snapshot?.execution_profile.id, "python-portable");
  assert.equal(spec.registry_snapshot?.execution_profile.dispatcher.workflow, "authoring-worker.yml");
  assert.deepEqual(verifyRegistryResolutionSnapshot(spec, registry), spec.registry_snapshot);
});

test("collection compilation binds complete typed project resources", () => {
  const spec = resolveJobSpecAgainstRegistry(
    collectionCompilationSpec,
    DEFAULT_CAPABILITY_REGISTRY,
  );
  assert.equal(spec.registry_snapshot?.handler.id, "watchcraft.compile.video-collection");
  assert.equal(spec.registry_snapshot?.execution_profile.id, "python-portable");
  assert.deepEqual(spec.inputs, [projectPlanArtifact, iteratorSnapshotArtifact]);
  assert.equal(spec.dependencies.length, 5);
  assert.throws(
    () => resolveJobSpecAgainstRegistry(
      {
        ...collectionCompilationSpec,
        dependencies: [transcriptArtifact, normalizationArtifact],
      },
      DEFAULT_CAPABILITY_REGISTRY,
    ),
    /requires between 1 and 10000 matching artifacts/,
  );
});

test("terminology resolution binds the complete transcript and draft-analysis corpus", () => {
  const spec = resolveJobSpecAgainstRegistry(
    terminologyResolutionSpec,
    DEFAULT_CAPABILITY_REGISTRY,
  );
  assert.equal(
    spec.registry_snapshot?.handler.id,
    "watchcraft.resolve.collection-terminology",
  );
  assert.equal(spec.registry_snapshot?.handler.version, "2");
  assert.equal(spec.registry_snapshot?.execution_profile.id, "python-openai");
  assert.equal(spec.dependencies.length, 4);
  assert.throws(
    () => resolveJobSpecAgainstRegistry(
      {
        ...terminologyResolutionSpec,
        dependencies: [
          transcriptArtifact,
          { ...transcriptArtifact, digest: "7".repeat(64), key: `objects/sha256/77/${"7".repeat(62)}` },
        ],
      },
      DEFAULT_CAPABILITY_REGISTRY,
    ),
    /requires between 1 and 10000 matching artifacts/,
  );
});

test("collection topic normalization binds a variable complete analysis set", () => {
  const spec = resolveJobSpecAgainstRegistry(
    topicNormalizationSpec,
    DEFAULT_CAPABILITY_REGISTRY,
  );
  assert.equal(spec.registry_snapshot?.handler.id, "watchcraft.normalize.collection-topics");
  assert.equal(spec.registry_snapshot?.execution_profile.id, "python-openai");
  assert.deepEqual(spec.dependencies, [firstAnalysisArtifact, secondAnalysisArtifact]);
  assert.deepEqual(spec.registry_snapshot?.handler.dependencies[0]?.cardinality, {
    minimum: 1,
    maximum: 10_000,
  });
  assert.throws(
    () => resolveJobSpecAgainstRegistry(
      { ...topicNormalizationSpec, dependencies: [] },
      DEFAULT_CAPABILITY_REGISTRY,
    ),
    /requires between 1 and 10000 matching artifacts/,
  );
  assert.throws(
    () => resolveJobSpecAgainstRegistry(
      { ...topicNormalizationSpec, dependencies: [transcriptArtifact] },
      DEFAULT_CAPABILITY_REGISTRY,
    ),
    /requires between 1 and 10000 matching artifacts/,
  );
});

test("educational analysis binds an authoritative transcript to the OpenAI profile", () => {
  const spec = resolveJobSpecAgainstRegistry(
    educationalAnalysisSpec,
    DEFAULT_CAPABILITY_REGISTRY,
  );
  assert.equal(
    spec.registry_snapshot?.handler.id,
    "watchcraft.analysis.educational-video",
  );
  assert.deepEqual(spec.dependencies, [transcriptArtifact]);
  assert.equal(spec.registry_snapshot?.execution_profile.id, "python-openai");
  assert.equal(
    spec.registry_snapshot?.execution_profile.dispatcher.workflow,
    "authoring-openai-worker.yml",
  );
  assert.equal(
    spec.registry_snapshot?.execution_profile.data_access,
    "private-derived",
  );
  assert.ok(
    spec.registry_snapshot?.execution_profile.secret_capabilities.includes(
      "openai.responses",
    ),
  );
});

test("playlist iteration is routed to the portable Python worker", () => {
  const spec = resolveJobSpecAgainstRegistry(
    playlistIteratorSpec,
    DEFAULT_CAPABILITY_REGISTRY,
  );
  assert.equal(
    spec.registry_snapshot?.handler.id,
    "watchcraft.iterator.youtube-playlist",
  );
  assert.equal(spec.registry_snapshot?.execution_profile.id, "python-portable");
  assert.equal(
    spec.registry_snapshot?.execution_profile.dispatcher.workflow,
    "authoring-worker.yml",
  );
});

test("project planning consumes an iterator snapshot on the portable worker", () => {
  const spec = resolveJobSpecAgainstRegistry(
    projectProcessingPlanSpec,
    DEFAULT_CAPABILITY_REGISTRY,
  );
  assert.equal(spec.registry_snapshot?.handler.id, "watchcraft.planner.video-collection");
  assert.deepEqual(spec.inputs, [iteratorSnapshotArtifact]);
  assert.equal(spec.registry_snapshot?.execution_profile.id, "python-portable");
  assert.equal(
    spec.registry_snapshot?.handler.output.artifact_kind,
    "project-processing-plan",
  );
});

test("educational analysis may bind a typed output from an earlier pipeline job", () => {
  const dependency = {
    kind: "job-output" as const,
    job_id: "transcription-job-1",
    artifact_kind: "transcript",
    schema: { id: "watchcraft.transcript", version: 1 },
  };
  const spec = resolveJobSpecAgainstRegistry(
    { ...educationalAnalysisSpec, dependencies: [dependency] },
    DEFAULT_CAPABILITY_REGISTRY,
  );
  assert.deepEqual(spec.dependencies, [dependency]);
  assert.equal(spec.registry_snapshot?.handler.dependencies[0]?.artifact_kind, "transcript");
});

test("the MLX transcription smoke resolves to its dedicated Apple silicon workflow", () => {
  const spec = resolveJobSpecAgainstRegistry(transcriptionSmokeSpec, DEFAULT_CAPABILITY_REGISTRY);
  assert.equal(spec.registry_snapshot?.execution_profile.id, "macos-mlx");
  assert.deepEqual(spec.registry_snapshot?.execution_profile.platform, {
    os: "macos",
    architecture: "arm64",
  });
  assert.equal(
    spec.registry_snapshot?.execution_profile.dispatcher.workflow,
    "authoring-mlx-worker.yml",
  );

  const httpSpec = resolveJobSpecAgainstRegistry(
    httpTranscriptionSmokeSpec,
    DEFAULT_CAPABILITY_REGISTRY,
  );
  assert.equal(
    httpSpec.registry_snapshot?.handler.id,
    "watchcraft.transcript.mlx-whisper-http-smoke",
  );
  assert.equal(httpSpec.registry_snapshot?.execution_profile.id, "macos-mlx");

  const stagedSmokeSpec = resolveJobSpecAgainstRegistry(
    stagedTranscriptionSmokeSpec,
    DEFAULT_CAPABILITY_REGISTRY,
  );
  assert.equal(
    stagedSmokeSpec.registry_snapshot?.handler.id,
    "watchcraft.transcript.mlx-whisper-staged-smoke",
  );
  assert.equal(stagedSmokeSpec.registry_snapshot?.execution_profile.id, "macos-mlx");

  const productionSpec = resolveJobSpecAgainstRegistry(
    productionTranscriptionSpec,
    DEFAULT_CAPABILITY_REGISTRY,
  );
  assert.equal(
    productionSpec.registry_snapshot?.handler.id,
    "watchcraft.transcript.mlx-whisper-large-v3-turbo-q4",
  );
  assert.equal(productionSpec.registry_snapshot?.execution_profile.id, "macos-mlx");
});

test("artifact references distinguish immutable results from expiring staged inputs", () => {
  assert.deepEqual(
    parseArtifactReference(stagedSourceAudio, { allowEphemeral: true }),
    stagedSourceAudio,
  );
  assert.throws(
    () => parseArtifactReference(stagedSourceAudio),
    /allowed only as staged job inputs/,
  );
  assert.throws(
    () => parseArtifactReference({ ...stagedSourceAudio, retention: undefined }),
    /Authoritative artifact key/,
  );
  assert.throws(
    () => parseArtifactReference({
      ...stagedSourceAudio,
      key: stagedSourceAudio.key.replace(sourceAudioDigest.slice(2), "b".repeat(62)),
    }, { allowEphemeral: true }),
    /bind its acquisition ID and digest/,
  );
});

test("registry validation rejects duplicate identities and dangling profiles", () => {
  const registry = structuredClone(DEFAULT_CAPABILITY_REGISTRY);
  registry.handlers.push(structuredClone(registry.handlers[0]));
  assert.throws(() => parseCapabilityRegistry(registry), /handler identities must be unique/);

  const dangling = structuredClone(DEFAULT_CAPABILITY_REGISTRY);
  dangling.handlers[0].execution_profile.id = "missing";
  assert.throws(() => parseCapabilityRegistry(dangling), /references missing profile/);
});

test("resolution rejects unregistered behavior and worker verification rejects drift", () => {
  assert.throws(() => resolveJobSpecAgainstRegistry({
    ...lexicalSpec,
    output_schema: { id: "watchcraft.analysis.other", version: 1 },
  }, DEFAULT_CAPABILITY_REGISTRY), /output does not match/);

  const spec = resolveJobSpecAgainstRegistry(lexicalSpec, DEFAULT_CAPABILITY_REGISTRY);
  const changedRegistry = structuredClone(DEFAULT_CAPABILITY_REGISTRY);
  changedRegistry.execution_profiles[0].timeout_minutes += 1;
  assert.throws(
    () => verifyRegistryResolutionSnapshot(spec, changedRegistry),
    /not supported by this worker revision/,
  );
});
