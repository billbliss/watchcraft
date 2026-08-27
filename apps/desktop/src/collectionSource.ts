interface CollectionSource {
  sourceType: "folder" | "url";
  sourceLabel: string;
}

export function displayCollectionSource(collection: CollectionSource): string {
  if (collection.sourceType !== "folder") return collection.sourceLabel;

  // Windows canonical paths may carry the Win32 extended-length prefix. Keep
  // that path intact in the registry, but do not expose the implementation
  // detail in the UI.
  if (collection.sourceLabel.startsWith("\\\\?\\UNC\\")) {
    return `\\\\${collection.sourceLabel.slice("\\\\?\\UNC\\".length)}`;
  }
  if (collection.sourceLabel.startsWith("\\\\?\\")) {
    return collection.sourceLabel.slice("\\\\?\\".length);
  }
  return collection.sourceLabel;
}
