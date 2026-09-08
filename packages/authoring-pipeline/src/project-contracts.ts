import Ajv2020, { type ErrorObject } from "ajv/dist/2020.js";
import addFormats from "ajv-formats";

import projectSchema from "../project/catalog-project.schema.json" with { type: "json" };
import snapshotSchema from "../project/collection-iterator-snapshot.schema.json" with { type: "json" };
import {
  canonicalJson,
  parseArtifactReference,
  sha256Hex,
  type ArtifactReference,
  type JsonValue,
} from "./contracts.ts";

export interface VersionedIdentity {
  id: string;
  version: string;
}

export interface ConfiguredCollectionType extends VersionedIdentity {
  configuration: Record<string, JsonValue>;
}

export interface ExtensionEnvelope {
  schema: VersionedIdentity;
  value: JsonValue;
}

export interface CollectionIterator extends VersionedIdentity {
  configuration: Record<string, JsonValue>;
  access_profile: string;
  accepted_snapshot?: ArtifactReference;
  refresh: {
    mode: "on-demand";
    stale_while_refresh: boolean;
  };
  extensions?: Record<string, ExtensionEnvelope>;
}

export interface MetadataBasis {
  origin: "editorial" | "source-observation" | "generated" | "legacy-import";
  iterator_snapshot_sha256?: string;
  source_path?: string;
  generator?: VersionedIdentity;
}

export interface CatalogProject {
  kind: "watchcraft.catalog-project";
  schema_version: 1;
  project_id: string;
  revision: number;
  collection_type: ConfiguredCollectionType;
  iterator: CollectionIterator;
  metadata: {
    title: string;
    description?: string;
    publisher?: {
      name: string;
      canonical_url?: string;
      provider_id?: string;
    };
    language?: string;
    artwork?: Array<{
      role: "thumbnail" | "banner" | "icon";
      url: string;
      alt?: string;
    }>;
    tags?: string[];
  };
  metadata_basis: Record<string, MetadataBasis>;
  publication: {
    collection_id: string;
    listed: boolean;
  };
  extensions?: Record<string, ExtensionEnvelope>;
}

export interface IteratorSnapshotNode {
  node_id: string;
  node_type: string;
  title: string;
  canonical_url?: string;
  parent_node_id: string | null;
  position: number;
  metadata: Record<string, JsonValue>;
  extensions?: Record<string, ExtensionEnvelope>;
}

export interface IteratorSnapshotItem {
  item_id: string;
  title: string;
  canonical_url: string;
  media: Array<{
    type: string;
    media_id: string;
    canonical_url?: string;
    metadata?: Record<string, JsonValue>;
  }>;
  attribution: {
    publisher: string;
    publisher_url?: string;
    license?: string | null;
    license_url?: string | null;
  };
  source_provenance: Record<string, JsonValue>;
  metadata: Record<string, JsonValue>;
  extensions?: Record<string, ExtensionEnvelope>;
}

export interface IteratorSnapshotPlacement {
  placement_id: string;
  item_id: string;
  parent_node_id: string;
  position: number;
  source_url: string;
  metadata: Record<string, JsonValue>;
  extensions?: Record<string, ExtensionEnvelope>;
}

export interface CollectionIteratorSnapshot {
  kind: "watchcraft.collection-iterator-snapshot";
  schema_version: 1;
  project: {
    project_id: string;
    revision: number;
  };
  iterator: VersionedIdentity;
  observed_at: string;
  source: {
    source_id: string;
    source_type: string;
    title: string;
    canonical_url: string;
    metadata: Record<string, JsonValue>;
  };
  nodes: IteratorSnapshotNode[];
  items: IteratorSnapshotItem[];
  placements: IteratorSnapshotPlacement[];
  coverage: {
    basis: "source-entries" | "items" | "placements";
    expected: number;
    resolved: number;
    unresolved: Array<{
      source_ref: string;
      classification: string;
      message: string;
    }>;
  };
  metadata_proposals: Array<{
    field: string;
    value: JsonValue;
    basis: {
      source_path: string;
      confidence?: number;
    };
  }>;
  structure_hash: string;
  provenance: {
    access_profile: string;
    discovery_mode: "bounded-crawl" | "provider-query" | "legacy-import";
    requested_url: string;
    retrieved_urls: string[];
    warnings: string[];
  };
  extensions?: Record<string, ExtensionEnvelope>;
}

const ajv = new Ajv2020({ allErrors: true, strict: true });
addFormats(ajv);
const validateProjectSchema = ajv.compile<CatalogProject>(projectSchema);
const validateSnapshotSchema =
  ajv.compile<CollectionIteratorSnapshot>(snapshotSchema);

function validationMessage(
  label: string,
  errors: ErrorObject[] | null | undefined,
): string {
  const details =
    errors
      ?.map((error) => {
        const path = error.instancePath || "/";
        return `${path} ${error.message ?? "is invalid"}`;
      })
      .join("; ") ?? "is invalid";
  return `${label} does not satisfy its schema: ${details}.`;
}

function assertUnique(values: string[], label: string): void {
  if (new Set(values).size !== values.length)
    throw new TypeError(`${label} must be unique.`);
}

function assertMetadataBasis(project: CatalogProject): void {
  const accepted = project.iterator.accepted_snapshot;
  for (const [field, basis] of Object.entries(project.metadata_basis)) {
    if (
      basis.origin === "source-observation" &&
      (!basis.iterator_snapshot_sha256 || !basis.source_path)
    ) {
      throw new TypeError(
        `Metadata basis ${field} from a source observation must identify its snapshot and source path.`,
      );
    }
    if (basis.origin === "generated" && !basis.generator) {
      throw new TypeError(
        `Metadata basis ${field} from a generator must identify that generator.`,
      );
    }
    if (basis.iterator_snapshot_sha256 && !accepted) {
      throw new TypeError(
        `Metadata basis ${field} references an iterator snapshot that has not been accepted.`,
      );
    }
    if (
      basis.iterator_snapshot_sha256 &&
      basis.iterator_snapshot_sha256 !== accepted?.digest
    ) {
      throw new TypeError(
        `Metadata basis ${field} does not reference the accepted iterator snapshot.`,
      );
    }
  }
}

export function parseCatalogProject(value: unknown): CatalogProject {
  if (!validateProjectSchema(value)) {
    throw new TypeError(
      validationMessage("Catalog project", validateProjectSchema.errors),
    );
  }
  const project = structuredClone(value);
  if (project.iterator.accepted_snapshot) {
    const reference = parseArtifactReference(
      project.iterator.accepted_snapshot,
    );
    if (
      reference.artifact_kind !== "collection-iterator-snapshot" ||
      reference.schema.id !== "watchcraft.collection-iterator-snapshot" ||
      reference.schema.version !== 1 ||
      reference.media_type !== "application/json"
    ) {
      throw new TypeError(
        "Accepted iterator snapshot has the wrong artifact contract.",
      );
    }
    project.iterator.accepted_snapshot = reference;
  }
  assertMetadataBasis(project);
  return project;
}

export function iteratorSnapshotStructureSha256(
  snapshot: Pick<
    CollectionIteratorSnapshot,
    "source" | "nodes" | "items" | "placements"
  >,
): string {
  return sha256Hex(
    canonicalJson({
      source: {
        source_id: snapshot.source.source_id,
        source_type: snapshot.source.source_type,
      },
      nodes: snapshot.nodes.map(
        ({ node_id, node_type, parent_node_id, position }) => ({
          node_id,
          node_type,
          parent_node_id,
          position,
        }),
      ),
      items: snapshot.items.map(({ item_id, media }) => ({
        item_id,
        media: media.map(({ type, media_id }) => ({ type, media_id })),
      })),
      placements: snapshot.placements.map(
        ({ placement_id, item_id, parent_node_id, position }) => ({
          placement_id,
          item_id,
          parent_node_id,
          position,
        }),
      ),
    }),
  );
}

function assertSnapshotGraph(snapshot: CollectionIteratorSnapshot): void {
  assertUnique(
    snapshot.nodes.map((node) => node.node_id),
    "Iterator snapshot node IDs",
  );
  assertUnique(
    snapshot.items.map((item) => item.item_id),
    "Iterator snapshot item IDs",
  );
  assertUnique(
    snapshot.placements.map((placement) => placement.placement_id),
    "Iterator snapshot placement IDs",
  );
  const nodes = new Map(snapshot.nodes.map((node) => [node.node_id, node]));
  const items = new Set(snapshot.items.map((item) => item.item_id));
  if (
    snapshot.nodes.filter((node) => node.parent_node_id === null).length !== 1
  ) {
    throw new TypeError(
      "Iterator snapshot must contain exactly one root node.",
    );
  }
  for (const node of snapshot.nodes) {
    let parentId = node.parent_node_id;
    const visited = new Set([node.node_id]);
    while (parentId !== null) {
      if (visited.has(parentId))
        throw new TypeError("Iterator snapshot node graph must be acyclic.");
      visited.add(parentId);
      const parent = nodes.get(parentId);
      if (!parent)
        throw new TypeError(
          `Iterator snapshot node ${node.node_id} references missing parent ${parentId}.`,
        );
      parentId = parent.parent_node_id;
    }
  }
  assertUnique(
    snapshot.nodes.map(
      (node) => `${node.parent_node_id ?? "<root>"}:${node.position}`,
    ),
    "Iterator snapshot sibling node positions",
  );
  for (const item of snapshot.items) {
    assertUnique(
      item.media.map((media) => `${media.type}:${media.media_id}`),
      `Media identities for ${item.item_id}`,
    );
  }
  for (const placement of snapshot.placements) {
    if (!items.has(placement.item_id)) {
      throw new TypeError(
        `Iterator snapshot placement ${placement.placement_id} references missing item ${placement.item_id}.`,
      );
    }
    if (!nodes.has(placement.parent_node_id)) {
      throw new TypeError(
        `Iterator snapshot placement ${placement.placement_id} references missing node ${placement.parent_node_id}.`,
      );
    }
  }
  assertUnique(
    snapshot.placements.map(
      (placement) => `${placement.parent_node_id}:${placement.position}`,
    ),
    "Iterator snapshot placement positions",
  );
  if (
    snapshot.coverage.expected !==
    snapshot.coverage.resolved + snapshot.coverage.unresolved.length
  ) {
    throw new TypeError(
      "Iterator snapshot coverage arithmetic is inconsistent.",
    );
  }
  if (snapshot.structure_hash !== iteratorSnapshotStructureSha256(snapshot)) {
    throw new TypeError("Iterator snapshot structure hash is invalid.");
  }
}

export function parseCollectionIteratorSnapshot(
  value: unknown,
): CollectionIteratorSnapshot {
  if (!validateSnapshotSchema(value)) {
    throw new TypeError(
      validationMessage(
        "Collection iterator snapshot",
        validateSnapshotSchema.errors,
      ),
    );
  }
  const snapshot = structuredClone(value);
  assertSnapshotGraph(snapshot);
  return snapshot;
}

export function validateProjectIteratorSnapshot(
  projectValue: unknown,
  snapshotValue: unknown,
  snapshotBytes?: Uint8Array,
): { project: CatalogProject; snapshot: CollectionIteratorSnapshot } {
  const project = parseCatalogProject(projectValue);
  const snapshot = parseCollectionIteratorSnapshot(snapshotValue);
  if (
    snapshot.project.project_id !== project.project_id ||
    snapshot.project.revision !== project.revision
  ) {
    throw new TypeError(
      "Iterator snapshot belongs to a different catalog project revision.",
    );
  }
  if (
    snapshot.iterator.id !== project.iterator.id ||
    snapshot.iterator.version !== project.iterator.version
  ) {
    throw new TypeError(
      "Iterator snapshot identity does not match the catalog project iterator.",
    );
  }
  if (snapshot.provenance.access_profile !== project.iterator.access_profile) {
    throw new TypeError(
      "Iterator snapshot access profile does not match the catalog project.",
    );
  }
  const accepted = project.iterator.accepted_snapshot;
  if (accepted && !snapshotBytes) {
    throw new TypeError(
      "Accepted iterator snapshot bytes are required to verify its content reference.",
    );
  }
  if (accepted && snapshotBytes) {
    if (
      accepted.byte_length !== snapshotBytes.byteLength ||
      accepted.digest !== sha256Hex(snapshotBytes)
    ) {
      throw new TypeError(
        "Accepted iterator snapshot reference does not match its bytes.",
      );
    }
  }
  return { project, snapshot };
}
