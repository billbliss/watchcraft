export function newestRelease(releases, prerelease) {
  return releases
    .filter((release) => !release.draft && release.prerelease === prerelease)
    .reduce((newest, release) => {
      if (!newest) return release;
      return Date.parse(release.published_at) > Date.parse(newest.published_at)
        ? release
        : newest;
    }, null);
}

export function visibleCollections(collections) {
  return collections.filter((collection) => collection.archived !== true);
}

export function collectionCategories(collections) {
  return [...new Set(
    visibleCollections(collections)
      .map((collection) => String(collection.category || "").trim())
      .filter(Boolean),
  )].sort((left, right) => left.localeCompare(right, undefined, { sensitivity: "base" }));
}

export function collectionsInCategory(collections, category) {
  const visible = visibleCollections(collections);
  if (!category) return visible;
  return visible.filter((collection) => collection.category === category);
}

export function withFallbackCategories(collections, categoriesById) {
  return collections.map((collection) => {
    const fallback = categoriesById[collection.collection_id];
    if (collection.category || !fallback) return collection;
    return { ...collection, category: fallback };
  });
}

export function collectionDeepLink(manifestUrl) {
  return `watchcraft://install?url=${encodeURIComponent(manifestUrl)}`;
}
