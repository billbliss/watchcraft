import {
  parseArtifactReference,
  sha256Hex,
  type ArtifactReference,
  type JsonValue,
} from "./contracts.ts";
import {
  parseCatalogProject,
  validateProjectIteratorCandidate,
  validateProjectIteratorSnapshot,
  type CatalogProject,
  type CollectionIteratorSnapshot,
} from "./project-contracts.ts";

export type IteratorOutputCapability =
  | "video-items"
  | "ordered-placements"
  | "hierarchical-nodes"
  | "ranked-placements";

export interface CollectionTypeRegistration {
  id: string;
  version: string;
  required_iterator_capabilities: IteratorOutputCapability[];
  validate_configuration(configuration: Record<string, JsonValue>): void;
  validate_snapshot(snapshot: CollectionIteratorSnapshot): void;
}

export interface CollectionIteratorRegistration {
  id: string;
  version: string;
  output_capabilities: IteratorOutputCapability[];
  validate_configuration(configuration: Record<string, JsonValue>): void;
}

export interface CatalogCapabilityRegistry {
  kind: "watchcraft.catalog-capability-registry";
  schema_version: 1;
  registry_version: string;
  collection_types: CollectionTypeRegistration[];
  iterators: CollectionIteratorRegistration[];
}

function objectValue(
  value: JsonValue | undefined,
  label: string,
): Record<string, JsonValue> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${label} must be an object.`);
  }
  return value;
}

function onlyKeys(
  candidate: Record<string, JsonValue>,
  allowed: string[],
  label: string,
): void {
  const unexpected = Object.keys(candidate).filter(
    (key) => !allowed.includes(key),
  );
  if (unexpected.length > 0)
    throw new TypeError(
      `${label} contains unsupported field ${unexpected[0]}.`,
    );
}

function requiredString(value: JsonValue | undefined, label: string): string {
  if (typeof value !== "string" || value.length === 0)
    throw new TypeError(`${label} must be a non-empty string.`);
  return value;
}

function requiredBoolean(value: JsonValue | undefined, label: string): boolean {
  if (typeof value !== "boolean")
    throw new TypeError(`${label} must be a boolean.`);
  return value;
}

function requiredInteger(
  value: JsonValue | undefined,
  label: string,
  minimum = 1,
): number {
  if (!Number.isSafeInteger(value) || (value as number) < minimum) {
    throw new TypeError(
      `${label} must be an integer greater than or equal to ${minimum}.`,
    );
  }
  return value as number;
}

function requiredUrl(
  value: JsonValue | undefined,
  label: string,
  hostname: string,
): URL {
  const source = requiredString(value, label);
  let url: URL;
  try {
    url = new URL(source);
  } catch {
    throw new TypeError(`${label} must be an absolute URL.`);
  }
  if (url.protocol !== "https:" || !url.hostname.endsWith(hostname)) {
    throw new TypeError(`${label} must be an HTTPS ${hostname} URL.`);
  }
  return url;
}

function optionalStringArray(
  value: JsonValue | undefined,
  label: string,
): string[] {
  if (value === undefined) return [];
  if (
    !Array.isArray(value) ||
    value.some((entry) => typeof entry !== "string" || entry.length === 0)
  ) {
    throw new TypeError(`${label} must be an array of non-empty strings.`);
  }
  if (new Set(value).size !== value.length)
    throw new TypeError(`${label} must not contain duplicates.`);
  return value as string[];
}

function validatePresentationBooleans(
  value: JsonValue | undefined,
  allowed: string[],
  label: string,
): void {
  if (value === undefined) return;
  const presentation = objectValue(value, label);
  onlyKeys(presentation, allowed, label);
  for (const [field, entry] of Object.entries(presentation)) {
    if (field === "source_backlink_label")
      requiredString(entry, `${label} ${field}`);
    else requiredBoolean(entry, `${label} ${field}`);
  }
}

function validateVideoCollectionConfiguration(
  configuration: Record<string, JsonValue>,
): void {
  onlyKeys(
    configuration,
    ["structure", "presentation"],
    "Video collection configuration",
  );
  if (
    requiredString(configuration.structure, "Video collection structure") !==
    "ordered-list"
  ) {
    throw new TypeError("Video collection structure must be ordered-list.");
  }
  validatePresentationBooleans(
    configuration.presentation,
    [],
    "Video collection presentation",
  );
}

function validateCourseConfiguration(
  configuration: Record<string, JsonValue>,
): void {
  onlyKeys(
    configuration,
    ["preserve_source_hierarchy", "completion_basis", "presentation"],
    "Course configuration",
  );
  requiredBoolean(
    configuration.preserve_source_hierarchy,
    "Course hierarchy flag",
  );
  if (
    requiredString(
      configuration.completion_basis,
      "Course completion basis",
    ) !== "video-placements"
  ) {
    throw new TypeError("Course completion basis must be video-placements.");
  }
  validatePresentationBooleans(
    configuration.presentation,
    ["show_units", "show_lessons", "show_source_backlinks"],
    "Course presentation",
  );
}

function validateRankedConfiguration(
  configuration: Record<string, JsonValue>,
): void {
  onlyKeys(
    configuration,
    [
      "ranking_is_snapshot_relative",
      "retain_previous_publication_until_approved",
      "presentation",
    ],
    "Ranked video catalog configuration",
  );
  requiredBoolean(
    configuration.ranking_is_snapshot_relative,
    "Snapshot-relative ranking flag",
  );
  requiredBoolean(
    configuration.retain_previous_publication_until_approved,
    "Previous-publication retention flag",
  );
  validatePresentationBooleans(
    configuration.presentation,
    ["show_rank", "show_observed_at", "source_backlink_label"],
    "Ranked video catalog presentation",
  );
}

function validateSelection(
  value: JsonValue | undefined,
  kind: string,
  allowed: string[],
  label: string,
): Record<string, JsonValue> {
  const selection = objectValue(value, label);
  onlyKeys(selection, ["kind", ...allowed], label);
  if (requiredString(selection.kind, `${label} kind`) !== kind) {
    throw new TypeError(`${label} kind must be ${kind}.`);
  }
  return selection;
}

function validateYouTubePlaylistConfiguration(
  configuration: Record<string, JsonValue>,
): void {
  onlyKeys(
    configuration,
    ["canonical_url", "playlist_id", "selection"],
    "YouTube playlist iterator configuration",
  );
  const url = requiredUrl(
    configuration.canonical_url,
    "YouTube playlist URL",
    "youtube.com",
  );
  const playlistId = requiredString(
    configuration.playlist_id,
    "YouTube playlist ID",
  );
  if (url.searchParams.get("list") !== playlistId)
    throw new TypeError("YouTube playlist URL and ID must agree.");
  const selection = validateSelection(
    configuration.selection,
    "published-order",
    ["excluded_item_ids"],
    "YouTube playlist selection",
  );
  optionalStringArray(
    selection.excluded_item_ids,
    "YouTube playlist exclusions",
  );
}

function validateKhanCourseConfiguration(
  configuration: Record<string, JsonValue>,
): void {
  onlyKeys(
    configuration,
    ["canonical_url", "course_id", "selection"],
    "Khan course iterator configuration",
  );
  requiredUrl(
    configuration.canonical_url,
    "Khan course URL",
    "khanacademy.org",
  );
  requiredString(configuration.course_id, "Khan course ID");
  const selection = validateSelection(
    configuration.selection,
    "complete-course-outline",
    ["included_content_kinds"],
    "Khan course selection",
  );
  const included = optionalStringArray(
    selection.included_content_kinds,
    "Khan included content kinds",
  );
  if (!included.includes("video"))
    throw new TypeError("Khan course selection must include video content.");
}

function validateYouTubePopularConfiguration(
  configuration: Record<string, JsonValue>,
): void {
  onlyKeys(
    configuration,
    ["canonical_url", "channel_handle", "selection"],
    "YouTube popular iterator configuration",
  );
  requiredUrl(
    configuration.canonical_url,
    "YouTube channel URL",
    "youtube.com",
  );
  const handle = requiredString(
    configuration.channel_handle,
    "YouTube channel handle",
  );
  if (!handle.startsWith("@"))
    throw new TypeError("YouTube channel handle must begin with @.");
  const selection = validateSelection(
    configuration.selection,
    "ranked-videos",
    ["ranking", "limit", "include_shorts", "include_live_archives"],
    "YouTube popular selection",
  );
  if (
    requiredString(selection.ranking, "YouTube ranking") !== "provider-popular"
  ) {
    throw new TypeError(
      "YouTube popular iterator ranking must be provider-popular.",
    );
  }
  requiredInteger(selection.limit, "YouTube popular result limit");
  requiredBoolean(selection.include_shorts, "YouTube Shorts inclusion flag");
  requiredBoolean(
    selection.include_live_archives,
    "YouTube live archive inclusion flag",
  );
}

function requireNodeTypes(
  snapshot: CollectionIteratorSnapshot,
  types: string[],
  label: string,
): void {
  const observed = new Set(snapshot.nodes.map((node) => node.node_type));
  for (const type of types) {
    if (!observed.has(type))
      throw new TypeError(`${label} snapshot must contain a ${type} node.`);
  }
}

function validateVideoSnapshot(snapshot: CollectionIteratorSnapshot): void {
  if (snapshot.items.some((item) => item.media.length === 0)) {
    throw new TypeError(
      "Video collection items must have a resolved media identity.",
    );
  }
}

function validateCourseSnapshot(snapshot: CollectionIteratorSnapshot): void {
  validateVideoSnapshot(snapshot);
  requireNodeTypes(snapshot, ["course", "unit", "lesson"], "Course");
  if (snapshot.coverage.basis !== "placements") {
    throw new TypeError(
      "Course snapshot coverage must be based on placements.",
    );
  }
}

function validateRankedSnapshot(snapshot: CollectionIteratorSnapshot): void {
  validateVideoSnapshot(snapshot);
  requireNodeTypes(snapshot, ["ranked-shelf"], "Ranked video catalog");
  for (const placement of snapshot.placements) {
    if (placement.metadata.rank_observed !== placement.position) {
      throw new TypeError(
        `Ranked placement ${placement.placement_id} must bind its observed rank.`,
      );
    }
  }
}

export const DEFAULT_CATALOG_CAPABILITY_REGISTRY: CatalogCapabilityRegistry = {
  kind: "watchcraft.catalog-capability-registry",
  schema_version: 1,
  registry_version: "2026-09-08.1",
  collection_types: [
    {
      id: "watchcraft.video-collection",
      version: "1",
      required_iterator_capabilities: ["video-items", "ordered-placements"],
      validate_configuration: validateVideoCollectionConfiguration,
      validate_snapshot: validateVideoSnapshot,
    },
    {
      id: "watchcraft.course",
      version: "1",
      required_iterator_capabilities: [
        "video-items",
        "ordered-placements",
        "hierarchical-nodes",
      ],
      validate_configuration: validateCourseConfiguration,
      validate_snapshot: validateCourseSnapshot,
    },
    {
      id: "watchcraft.ranked-video-catalog",
      version: "1",
      required_iterator_capabilities: [
        "video-items",
        "ordered-placements",
        "ranked-placements",
      ],
      validate_configuration: validateRankedConfiguration,
      validate_snapshot: validateRankedSnapshot,
    },
  ],
  iterators: [
    {
      id: "watchcraft.youtube-playlist",
      version: "1",
      output_capabilities: ["video-items", "ordered-placements"],
      validate_configuration: validateYouTubePlaylistConfiguration,
    },
    {
      id: "watchcraft.khan-course",
      version: "1",
      output_capabilities: [
        "video-items",
        "ordered-placements",
        "hierarchical-nodes",
      ],
      validate_configuration: validateKhanCourseConfiguration,
    },
    {
      id: "watchcraft.youtube-channel-popular",
      version: "1",
      output_capabilities: [
        "video-items",
        "ordered-placements",
        "hierarchical-nodes",
        "ranked-placements",
      ],
      validate_configuration: validateYouTubePopularConfiguration,
    },
  ],
};

function identity(value: { id: string; version: string }): string {
  return `${value.id}@${value.version}`;
}

export function validateCatalogCapabilityRegistry(
  registry: CatalogCapabilityRegistry,
): void {
  if (
    registry.kind !== "watchcraft.catalog-capability-registry" ||
    registry.schema_version !== 1 ||
    !registry.registry_version
  ) {
    throw new TypeError("Unsupported catalog capability registry schema.");
  }
  const typeKeys = registry.collection_types.map(identity);
  const iteratorKeys = registry.iterators.map(identity);
  if (new Set(typeKeys).size !== typeKeys.length)
    throw new TypeError("Collection type identities must be unique.");
  if (new Set(iteratorKeys).size !== iteratorKeys.length)
    throw new TypeError("Collection iterator identities must be unique.");
  for (const registration of [
    ...registry.collection_types,
    ...registry.iterators,
  ]) {
    if (!registration.id || !registration.version)
      throw new TypeError("Catalog capability identities must be non-empty.");
  }
}

export function validateCatalogProjectCapabilities(
  projectValue: unknown,
  registry: CatalogCapabilityRegistry = DEFAULT_CATALOG_CAPABILITY_REGISTRY,
): {
  project: CatalogProject;
  collection_type: CollectionTypeRegistration;
  iterator: CollectionIteratorRegistration;
} {
  validateCatalogCapabilityRegistry(registry);
  const project = parseCatalogProject(projectValue);
  const collectionType = registry.collection_types.find(
    (candidate) => identity(candidate) === identity(project.collection_type),
  );
  if (!collectionType)
    throw new TypeError(
      `Unknown collection type ${identity(project.collection_type)}.`,
    );
  const iterator = registry.iterators.find(
    (candidate) => identity(candidate) === identity(project.iterator),
  );
  if (!iterator)
    throw new TypeError(
      `Unknown collection iterator ${identity(project.iterator)}.`,
    );
  collectionType.validate_configuration(project.collection_type.configuration);
  iterator.validate_configuration(project.iterator.configuration);
  const capabilities = new Set(iterator.output_capabilities);
  const missing = collectionType.required_iterator_capabilities.filter(
    (capability) => !capabilities.has(capability),
  );
  if (missing.length > 0) {
    throw new TypeError(
      `${identity(project.iterator)} cannot populate ${identity(project.collection_type)}; missing ${missing.join(", ")}.`,
    );
  }
  return { project, collection_type: collectionType, iterator };
}

export function validateCatalogProjectSnapshot(
  projectValue: unknown,
  snapshotValue: unknown,
  snapshotBytes?: Uint8Array,
  registry: CatalogCapabilityRegistry = DEFAULT_CATALOG_CAPABILITY_REGISTRY,
): { project: CatalogProject; snapshot: CollectionIteratorSnapshot } {
  const resolved = validateCatalogProjectCapabilities(projectValue, registry);
  const { project, snapshot } = validateProjectIteratorSnapshot(
    resolved.project,
    snapshotValue,
    snapshotBytes,
  );
  resolved.collection_type.validate_snapshot(snapshot);
  return { project, snapshot };
}

export function validateCatalogProjectCandidate(
  projectValue: unknown,
  snapshotValue: unknown,
  referenceValue: unknown,
  snapshotBytes: Uint8Array,
  registry: CatalogCapabilityRegistry = DEFAULT_CATALOG_CAPABILITY_REGISTRY,
): {
  project: CatalogProject;
  snapshot: CollectionIteratorSnapshot;
  reference: ArtifactReference;
} {
  const resolved = validateCatalogProjectCapabilities(projectValue, registry);
  const { project, snapshot } = validateProjectIteratorCandidate(
    resolved.project,
    snapshotValue,
  );
  resolved.collection_type.validate_snapshot(snapshot);
  const reference = parseArtifactReference(referenceValue);
  if (
    reference.artifact_kind !== "collection-iterator-snapshot" ||
    reference.schema.id !== "watchcraft.collection-iterator-snapshot" ||
    reference.schema.version !== 1 ||
    reference.media_type !== "application/json"
  ) {
    throw new TypeError("Iterator candidate has the wrong artifact contract.");
  }
  if (
    reference.byte_length !== snapshotBytes.byteLength ||
    reference.digest !== sha256Hex(snapshotBytes)
  ) {
    throw new TypeError(
      "Iterator candidate reference does not match its exact bytes.",
    );
  }
  return { project, snapshot, reference };
}

export function acceptCatalogProjectCandidate(
  projectValue: unknown,
  snapshotValue: unknown,
  referenceValue: unknown,
  snapshotBytes: Uint8Array,
  registry: CatalogCapabilityRegistry = DEFAULT_CATALOG_CAPABILITY_REGISTRY,
): CatalogProject {
  const { project, reference } = validateCatalogProjectCandidate(
    projectValue,
    snapshotValue,
    referenceValue,
    snapshotBytes,
    registry,
  );
  const accepted = structuredClone(project);
  accepted.revision += 1;
  accepted.iterator.accepted_snapshot = reference;
  return parseCatalogProject(accepted);
}
