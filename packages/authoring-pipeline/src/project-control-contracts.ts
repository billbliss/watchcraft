import {
  canonicalJson,
  parseArtifactReference,
  sha256Hex,
  type ArtifactReference,
  type JsonValue,
} from "./contracts.ts";
import type {
  CatalogProject,
  CollectionIteratorSnapshot,
} from "./project-contracts.ts";

function objectValue(value: unknown, label: string): Record<string, any> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${label} must be an object.`);
  }
  return value as Record<string, any>;
}

function stringValue(value: unknown, label: string): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new TypeError(`${label} must be a non-empty string.`);
  }
  return value;
}

function integerValue(value: unknown, label: string): number {
  if (!Number.isSafeInteger(value) || (value as number) < 1) {
    throw new TypeError(`${label} must be a positive integer.`);
  }
  return value as number;
}

function arrayValue(value: unknown, label: string): any[] {
  if (!Array.isArray(value)) throw new TypeError(`${label} must be an array.`);
  return value;
}

function assertUnique(values: string[], label: string): void {
  if (new Set(values).size !== values.length) {
    throw new TypeError(`${label} must be unique.`);
  }
}

function identity(value: unknown, label: string): { id: string; version: string } {
  const candidate = objectValue(value, label);
  return {
    id: stringValue(candidate.id, `${label} ID`),
    version: stringValue(candidate.version, `${label} version`),
  };
}

function assertAcceptedReference(reference: ArtifactReference): void {
  if (
    reference.artifact_kind !== "collection-iterator-snapshot" ||
    reference.schema.id !== "watchcraft.collection-iterator-snapshot" ||
    reference.schema.version !== 1 ||
    reference.media_type !== "application/json"
  ) {
    throw new TypeError("Accepted iterator snapshot has the wrong artifact contract.");
  }
}

function assertKnownCapabilities(project: Record<string, any>): void {
  const collectionType = identity(project.collection_type, "Collection type");
  const iterator = identity(project.iterator, "Collection iterator");
  const pair = `${collectionType.id}@${collectionType.version}|${iterator.id}@${iterator.version}`;
  const supported = new Set([
    "watchcraft.video-collection@1|watchcraft.youtube-playlist@1",
    "watchcraft.video-collection@1|watchcraft.explicit-membership@1",
    "watchcraft.grouped-video-collection@1|watchcraft.explicit-membership@1",
    "watchcraft.course@1|watchcraft.khan-course@1",
    "watchcraft.ranked-video-catalog@1|watchcraft.youtube-channel-popular@1",
  ]);
  if (!supported.has(pair)) {
    throw new TypeError(`Unsupported catalog capability combination ${pair}.`);
  }
  objectValue(project.collection_type.configuration, "Collection type configuration");
  objectValue(project.iterator.configuration, "Collection iterator configuration");
}

function assertMetadataBasis(project: Record<string, any>, accepted?: ArtifactReference): void {
  const bases = objectValue(project.metadata_basis, "Catalog project metadata basis");
  for (const [field, value] of Object.entries(bases)) {
    const basis = objectValue(value, `Metadata basis ${field}`);
    const origin = stringValue(basis.origin, `Metadata basis ${field} origin`);
    if (!new Set(["editorial", "source-observation", "generated", "legacy-import"]).has(origin)) {
      throw new TypeError(`Metadata basis ${field} has an unsupported origin.`);
    }
    if (origin === "source-observation") {
      if (
        stringValue(basis.iterator_snapshot_sha256, `Metadata basis ${field} digest`) !==
          accepted?.digest ||
        typeof basis.source_path !== "string" ||
        basis.source_path.length === 0
      ) {
        throw new TypeError(
          `Metadata basis ${field} does not reference the accepted iterator snapshot.`,
        );
      }
    }
    if (origin === "generated") identity(basis.generator, `Metadata basis ${field} generator`);
  }
}

export function validateCatalogProjectForControl(value: unknown): CatalogProject {
  const project = objectValue(value, "Catalog project");
  if (project.kind !== "watchcraft.catalog-project" || project.schema_version !== 1) {
    throw new TypeError("Unsupported catalog project schema.");
  }
  stringValue(project.project_id, "Catalog project ID");
  integerValue(project.revision, "Catalog project revision");
  assertKnownCapabilities(project);
  const iterator = objectValue(project.iterator, "Collection iterator");
  stringValue(iterator.access_profile, "Collection iterator access profile");
  objectValue(iterator.refresh, "Collection iterator refresh policy");
  const metadata = objectValue(project.metadata, "Catalog project metadata");
  stringValue(metadata.title, "Catalog project title");
  const publication = objectValue(project.publication, "Catalog project publication");
  stringValue(publication.collection_id, "Published collection ID");
  if (typeof publication.listed !== "boolean") {
    throw new TypeError("Published collection listed flag must be a boolean.");
  }
  let accepted: ArtifactReference | undefined;
  if (iterator.accepted_snapshot !== undefined) {
    accepted = parseArtifactReference(iterator.accepted_snapshot);
    assertAcceptedReference(accepted);
    iterator.accepted_snapshot = accepted;
  }
  assertMetadataBasis(project, accepted);
  return structuredClone(project) as CatalogProject;
}

function structureSha256(snapshot: Record<string, any>): string {
  return sha256Hex(canonicalJson({
    source: {
      source_id: snapshot.source.source_id,
      source_type: snapshot.source.source_type,
    },
    nodes: snapshot.nodes.map((node: Record<string, any>) => ({
      node_id: node.node_id,
      node_type: node.node_type,
      parent_node_id: node.parent_node_id,
      position: node.position,
    })),
    items: snapshot.items.map((item: Record<string, any>) => ({
      item_id: item.item_id,
      media: item.media.map((media: Record<string, any>) => ({
        type: media.type,
        media_id: media.media_id,
      })),
    })),
    placements: snapshot.placements.map((placement: Record<string, any>) => ({
      placement_id: placement.placement_id,
      item_id: placement.item_id,
      parent_node_id: placement.parent_node_id,
      position: placement.position,
    })),
  } as JsonValue));
}

export function validateIteratorSnapshotForControl(
  value: unknown,
): CollectionIteratorSnapshot {
  const snapshot = objectValue(value, "Iterator snapshot");
  if (
    snapshot.kind !== "watchcraft.collection-iterator-snapshot" ||
    snapshot.schema_version !== 1
  ) {
    throw new TypeError("Unsupported iterator snapshot schema.");
  }
  const project = objectValue(snapshot.project, "Iterator snapshot project");
  stringValue(project.project_id, "Iterator snapshot project ID");
  integerValue(project.revision, "Iterator snapshot project revision");
  identity(snapshot.iterator, "Iterator snapshot iterator");
  const source = objectValue(snapshot.source, "Iterator snapshot source");
  stringValue(source.source_id, "Iterator snapshot source ID");
  stringValue(source.source_type, "Iterator snapshot source type");
  const nodes = arrayValue(snapshot.nodes, "Iterator snapshot nodes");
  const items = arrayValue(snapshot.items, "Iterator snapshot items");
  const placements = arrayValue(snapshot.placements, "Iterator snapshot placements");
  if (nodes.length === 0) throw new TypeError("Iterator snapshot requires a root node.");
  const nodeMap = new Map<string, Record<string, any>>();
  const nodeIds: string[] = [];
  for (const value of nodes) {
    const node = objectValue(value, "Iterator snapshot node");
    const nodeId = stringValue(node.node_id, "Iterator snapshot node ID");
    stringValue(node.node_type, `Iterator snapshot node ${nodeId} type`);
    integerValue(node.position, `Iterator snapshot node ${nodeId} position`);
    if (node.parent_node_id !== null) {
      stringValue(node.parent_node_id, `Iterator snapshot node ${nodeId} parent`);
    }
    nodeIds.push(nodeId);
    nodeMap.set(nodeId, node);
  }
  assertUnique(nodeIds, "Iterator snapshot node IDs");
  if (nodes.filter((node) => node.parent_node_id === null).length !== 1) {
    throw new TypeError("Iterator snapshot must contain exactly one root node.");
  }
  for (const node of nodeMap.values()) {
    const visited = new Set([node.node_id]);
    let parentId = node.parent_node_id;
    while (parentId !== null) {
      if (visited.has(parentId)) throw new TypeError("Iterator snapshot node graph must be acyclic.");
      visited.add(parentId);
      const parent = nodeMap.get(parentId);
      if (!parent) throw new TypeError(`Iterator snapshot node ${node.node_id} has a missing parent.`);
      parentId = parent.parent_node_id;
    }
  }
  assertUnique(
    nodes.map((node) => `${node.parent_node_id ?? "<root>"}:${node.position}`),
    "Iterator snapshot sibling node positions",
  );
  const itemMap = new Map<string, Record<string, any>>();
  const itemIds: string[] = [];
  for (const value of items) {
    const item = objectValue(value, "Iterator snapshot item");
    const itemId = stringValue(item.item_id, "Iterator snapshot item ID");
    const media = arrayValue(item.media, `Iterator snapshot item ${itemId} media`);
    if (media.length === 0) throw new TypeError(`Iterator snapshot item ${itemId} has no media.`);
    for (const value of media) {
      const identity = objectValue(value, `Iterator snapshot item ${itemId} media identity`);
      stringValue(identity.type, "Media type");
      stringValue(identity.media_id, "Media ID");
    }
    itemIds.push(itemId);
    itemMap.set(itemId, item);
  }
  assertUnique(itemIds, "Iterator snapshot item IDs");
  const placementIds: string[] = [];
  for (const value of placements) {
    const placement = objectValue(value, "Iterator snapshot placement");
    const placementId = stringValue(placement.placement_id, "Iterator snapshot placement ID");
    const itemId = stringValue(placement.item_id, `Placement ${placementId} item ID`);
    const parentId = stringValue(placement.parent_node_id, `Placement ${placementId} parent ID`);
    integerValue(placement.position, `Placement ${placementId} position`);
    if (!itemMap.has(itemId) || !nodeMap.has(parentId)) {
      throw new TypeError(`Iterator snapshot placement ${placementId} has a missing reference.`);
    }
    placementIds.push(placementId);
  }
  assertUnique(placementIds, "Iterator snapshot placement IDs");
  assertUnique(
    placements.map((placement) => `${placement.parent_node_id}:${placement.position}`),
    "Iterator snapshot placement positions",
  );
  const coverage = objectValue(snapshot.coverage, "Iterator snapshot coverage");
  const expected = Number(coverage.expected);
  const resolved = Number(coverage.resolved);
  const unresolved = arrayValue(coverage.unresolved, "Iterator snapshot unresolved coverage");
  if (
    !Number.isSafeInteger(expected) || expected < 0 ||
    !Number.isSafeInteger(resolved) || resolved < 0 ||
    expected !== resolved + unresolved.length
  ) {
    throw new TypeError("Iterator snapshot coverage arithmetic is inconsistent.");
  }
  const provenance = objectValue(snapshot.provenance, "Iterator snapshot provenance");
  stringValue(provenance.access_profile, "Iterator snapshot access profile");
  if (snapshot.structure_hash !== structureSha256(snapshot)) {
    throw new TypeError("Iterator snapshot structure hash is invalid.");
  }
  return structuredClone(snapshot) as CollectionIteratorSnapshot;
}

function assertProjectSnapshotIdentity(
  project: CatalogProject,
  snapshot: CollectionIteratorSnapshot,
  exactRevision: boolean,
): void {
  if (
    snapshot.project.project_id !== project.project_id ||
    (exactRevision
      ? snapshot.project.revision !== project.revision
      : snapshot.project.revision > project.revision)
  ) {
    throw new TypeError("Iterator snapshot belongs to a different catalog project revision.");
  }
  if (
    snapshot.iterator.id !== project.iterator.id ||
    snapshot.iterator.version !== project.iterator.version
  ) {
    throw new TypeError("Iterator snapshot identity does not match the catalog project iterator.");
  }
  if (snapshot.provenance.access_profile !== project.iterator.access_profile) {
    throw new TypeError("Iterator snapshot access profile does not match the catalog project.");
  }
  const nodeTypes = new Set(snapshot.nodes.map((node) => node.node_type));
  if (project.collection_type.id === "watchcraft.course") {
    for (const nodeType of ["course", "unit", "lesson"]) {
      if (!nodeTypes.has(nodeType)) {
        throw new TypeError(`Course snapshot must contain a ${nodeType} node.`);
      }
    }
    if (snapshot.coverage.basis !== "placements") {
      throw new TypeError("Course snapshot coverage must be based on placements.");
    }
  }
  if (project.collection_type.id === "watchcraft.ranked-video-catalog") {
    if (!nodeTypes.has("ranked-shelf")) {
      throw new TypeError("Ranked video catalog snapshot must contain a ranked-shelf node.");
    }
    for (const placement of snapshot.placements) {
      if (placement.metadata.rank_observed !== placement.position) {
        throw new TypeError(
          `Ranked placement ${placement.placement_id} must bind its observed rank.`,
        );
      }
    }
  }
}

function assertExactBytes(reference: ArtifactReference, bytes: Uint8Array): void {
  if (
    reference.byte_length !== bytes.byteLength ||
    reference.digest !== sha256Hex(bytes)
  ) {
    throw new TypeError("Iterator candidate reference does not match its exact bytes.");
  }
}

export function validateAcceptedProjectSnapshotForControl(
  projectValue: unknown,
  snapshotValue: unknown,
  snapshotBytes: Uint8Array,
): { project: CatalogProject; snapshot: CollectionIteratorSnapshot } {
  const project = validateCatalogProjectForControl(projectValue);
  const snapshot = validateIteratorSnapshotForControl(snapshotValue);
  const reference = project.iterator.accepted_snapshot;
  if (!reference) throw new TypeError("Catalog project has no accepted iterator snapshot.");
  assertProjectSnapshotIdentity(project, snapshot, false);
  assertExactBytes(reference, snapshotBytes);
  return { project, snapshot };
}

export function acceptCatalogProjectCandidateForControl(
  projectValue: unknown,
  snapshotValue: unknown,
  referenceValue: unknown,
  snapshotBytes: Uint8Array,
): CatalogProject {
  const project = validateCatalogProjectForControl(projectValue);
  const snapshot = validateIteratorSnapshotForControl(snapshotValue);
  const reference = parseArtifactReference(referenceValue);
  assertAcceptedReference(reference);
  assertProjectSnapshotIdentity(project, snapshot, true);
  assertExactBytes(reference, snapshotBytes);
  const accepted = structuredClone(project);
  accepted.revision += 1;
  accepted.iterator.accepted_snapshot = reference;
  return validateCatalogProjectForControl(accepted);
}
