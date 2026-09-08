import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  acceptCatalogProjectCandidate,
  acceptCatalogProjectCandidateForControl,
  artifactKey,
  DEFAULT_CATALOG_CAPABILITY_REGISTRY,
  parseCatalogProject,
  parseCollectionIteratorSnapshot,
  sha256Hex,
  validateCatalogCapabilityRegistry,
  validateAcceptedProjectSnapshotForControl,
  validateCatalogProjectForControl,
  validateCatalogProjectCapabilities,
  validateCatalogProjectSnapshot,
} from "./index.ts";

const examples = new URL("../project/examples/", import.meta.url);

async function example(stem: string): Promise<{
  project: unknown;
  snapshot: unknown;
  snapshotBytes: Uint8Array;
}> {
  const projectBytes = await readFile(
    new URL(`${stem}.project.json`, examples),
  );
  const snapshotBytes = await readFile(
    new URL(`${stem}.snapshot.json`, examples),
  );
  return {
    project: JSON.parse(projectBytes.toString("utf8")),
    snapshot: JSON.parse(snapshotBytes.toString("utf8")),
    snapshotBytes,
  };
}

test("current, Khan, and popular-video designs satisfy the typed contracts", async () => {
  validateCatalogCapabilityRegistry(DEFAULT_CATALOG_CAPABILITY_REGISTRY);
  assert.equal(
    DEFAULT_CATALOG_CAPABILITY_REGISTRY.registry_version,
    "2026-09-08.1",
  );
  for (const stem of ["current-playlist", "khan-course", "youtube-popular"]) {
    const { project, snapshot, snapshotBytes } = await example(stem);
    const validated = validateCatalogProjectSnapshot(
      project,
      snapshot,
      snapshotBytes,
    );
    assert.equal(
      validated.project.project_id,
      validated.snapshot.project.project_id,
    );
    assert.equal(
      validateCatalogProjectForControl(project).project_id,
      validated.project.project_id,
    );
    assert.equal(
      validateAcceptedProjectSnapshotForControl(
        project,
        snapshot,
        snapshotBytes,
      ).snapshot.structure_hash,
      validated.snapshot.structure_hash,
    );
  }
});

test("catalog project parsing rejects unknown fields and invalid snapshot references", async () => {
  const { project } = await example("current-playlist");
  assert.throws(
    () =>
      parseCatalogProject({
        ...(project as object),
        accidental_behavior: true,
      }),
    /additional properties/,
  );

  const invalid = structuredClone(project) as any;
  invalid.iterator.accepted_snapshot.artifact_kind = "transcript";
  assert.throws(
    () => parseCatalogProject(invalid),
    /must be equal to constant|wrong artifact contract/,
  );
});

test("iterator snapshots fail closed on graph, coverage, and structure drift", async () => {
  const { snapshot } = await example("khan-course");

  const missingParent = structuredClone(snapshot) as any;
  missingParent.nodes[1].parent_node_id = "missing";
  assert.throws(
    () => parseCollectionIteratorSnapshot(missingParent),
    /references missing parent/,
  );

  const incompleteCoverage = structuredClone(snapshot) as any;
  incompleteCoverage.coverage.expected += 1;
  assert.throws(
    () => parseCollectionIteratorSnapshot(incompleteCoverage),
    /coverage arithmetic/,
  );

  const structuralDrift = structuredClone(snapshot) as any;
  structuralDrift.placements[0].position = 2;
  assert.throws(
    () => parseCollectionIteratorSnapshot(structuralDrift),
    /placement positions|structure hash/,
  );
});

test("collection types and iterators are independently registered and compatibility checked", async () => {
  const { project } = await example("khan-course");
  const current = await example("current-playlist");
  const incompatible = structuredClone(current.project) as any;
  incompatible.collection_type = (project as any).collection_type;
  assert.throws(
    () => validateCatalogProjectCapabilities(incompatible),
    /cannot populate.*missing hierarchical-nodes/,
  );

  const unknown = structuredClone(project) as any;
  unknown.collection_type.id = "watchcraft.unknown";
  assert.throws(
    () => validateCatalogProjectCapabilities(unknown),
    /Unknown collection type/,
  );

  const invalidConfiguration = structuredClone(
    (await example("youtube-popular")).project,
  ) as any;
  invalidConfiguration.iterator.configuration.selection.limit = 0;
  assert.throws(
    () => validateCatalogProjectCapabilities(invalidConfiguration),
    /result limit/,
  );

  const duplicateRegistry = {
    ...DEFAULT_CATALOG_CAPABILITY_REGISTRY,
    collection_types: [
      ...DEFAULT_CATALOG_CAPABILITY_REGISTRY.collection_types,
      DEFAULT_CATALOG_CAPABILITY_REGISTRY.collection_types[0],
    ],
  };
  assert.throws(
    () => validateCatalogCapabilityRegistry(duplicateRegistry),
    /identities must be unique/,
  );
});

test("accepted snapshot identity and exact bytes are bound to the project revision", async () => {
  const { project, snapshot, snapshotBytes } = await example("youtube-popular");
  assert.throws(
    () => validateCatalogProjectSnapshot(project, snapshot),
    /bytes are required/,
  );
  const wrongRevision = structuredClone(snapshot) as any;
  wrongRevision.project.revision += 1;
  assert.throws(
    () => validateCatalogProjectSnapshot(project, wrongRevision, snapshotBytes),
    /different catalog project revision/,
  );

  const changedBytes = new Uint8Array([...snapshotBytes, 0x20]);
  assert.throws(
    () => validateCatalogProjectSnapshot(project, snapshot, changedBytes),
    /does not match its bytes/,
  );
});

test("accepting a candidate advances the project without mutating the source revision", async () => {
  const { project, snapshot } = await example("current-playlist");
  const candidate = structuredClone(snapshot) as any;
  candidate.observed_at = "2026-09-08T09:48:10Z";
  candidate.provenance.discovery_mode = "bounded-crawl";
  const bytes = new TextEncoder().encode(JSON.stringify(candidate));
  const digest = sha256Hex(bytes);
  const reference = {
    store: "r2" as const,
    algorithm: "sha256" as const,
    digest,
    byte_length: bytes.byteLength,
    media_type: "application/json",
    artifact_kind: "collection-iterator-snapshot",
    schema: { id: "watchcraft.collection-iterator-snapshot", version: 1 },
    key: artifactKey(digest),
  };

  const accepted = acceptCatalogProjectCandidate(
    project,
    candidate,
    reference,
    bytes,
  );
  assert.equal((project as any).revision, 1);
  assert.equal(accepted.revision, 2);
  assert.deepEqual(accepted.iterator.accepted_snapshot, reference);
  assert.deepEqual(
    acceptCatalogProjectCandidateForControl(
      project,
      candidate,
      reference,
      bytes,
    ),
    accepted,
  );
  assert.equal(
    validateCatalogProjectSnapshot(accepted, candidate, bytes).project.revision,
    2,
  );

  const wrongRevision = structuredClone(candidate);
  wrongRevision.project.revision = 2;
  assert.throws(
    () => acceptCatalogProjectCandidate(project, wrongRevision, reference, bytes),
    /different catalog project revision/,
  );
});
