const INSTALL_SCHEMES = new Set([
  "watchcraft:",
  "watchcraft-beta:",
  "watchcraft-dev:",
  "watchcraft-smoke:",
]);

export function collectionUrlFromDeepLink(value: string): string | null {
  let deepLink: URL;
  try {
    deepLink = new URL(value);
  } catch {
    return null;
  }
  if (
    !INSTALL_SCHEMES.has(deepLink.protocol)
    || deepLink.hostname !== "install"
    || (deepLink.pathname !== "" && deepLink.pathname !== "/")
  ) {
    return null;
  }

  const requested = deepLink.searchParams.get("url");
  if (!requested) return null;
  let collectionUrl: URL;
  try {
    collectionUrl = new URL(requested);
  } catch {
    return null;
  }
  if (
    collectionUrl.protocol !== "https:"
    || !collectionUrl.hostname
    || collectionUrl.username
    || collectionUrl.password
  ) {
    return null;
  }
  return collectionUrl.href;
}
