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
