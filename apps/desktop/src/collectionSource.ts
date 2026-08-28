interface CollectionSource {
  sourceType: "folder" | "url";
  sourceLabel: string;
}

export function displayCollectionSource(collection: CollectionSource): string {
  if (collection.sourceType !== "folder") return collection.sourceLabel;
  return displayLocalPath(collection.sourceLabel);
}

export function displayLocalPath(path: string): string {
  // Windows canonical paths may carry the Win32 extended-length prefix. Keep
  // that path intact in the registry, but do not expose the implementation
  // detail in the UI.
  if (path.startsWith("\\\\?\\UNC\\")) {
    return `\\\\${path.slice("\\\\?\\UNC\\".length)}`;
  }
  if (path.startsWith("\\\\?\\")) {
    return path.slice("\\\\?\\".length);
  }
  return path;
}
