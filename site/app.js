import { collectionDeepLink, newestRelease, visibleCollections } from "./directory.mjs";

const RELEASES_URL = "https://api.github.com/repos/billbliss/watchcraft/releases?per_page=20";
const RELEASES_PAGE = "https://github.com/billbliss/watchcraft/releases";
const COLLECTIONS_URL = "https://billbliss.github.io/watchcraft-collections/collections.json";

const fallbackCollections = [
  {
    title: "Hello, Watchcraft! — Managed",
    description: "A tiny self-contained video downloaded into Watchcraft’s private storage.",
    media_modes: ["managed-local"],
    manifest_url: "https://billbliss.github.io/watchcraft-collections/collections/hello-world-managed/collection.json",
    archived: true,
  },
  {
    title: "Hello, Watchcraft! — Referenced",
    description: "The same tiny video kept in a folder that remains under your control.",
    media_modes: ["referenced-local"],
    package_url: "https://billbliss.github.io/watchcraft-collections/downloads/hello-world-referenced.zip",
    archived: true,
  },
  {
    title: "Learning Adobe Premiere Pro",
    description: "Four public YouTube lessons with searchable topics and chapter navigation.",
    media_modes: ["remote"],
    manifest_url: "https://billbliss.github.io/watchcraft-collections/collections/premiere-pro-ai-tools/collection.json",
  },
];

function assetLabel(name) {
  if (/\.dmg$/i.test(name)) return "macOS — Apple Silicon";
  if (/\.exe$/i.test(name)) return "Windows installer";
  if (/\.msi$/i.test(name)) return "Windows MSI";
  if (/\.AppImage$/i.test(name)) return "Linux AppImage";
  if (/\.deb$/i.test(name)) return "Linux — Debian/Ubuntu";
  return null;
}

function renderRelease(release, kind) {
  const meta = document.querySelector(`#${kind}-meta`);
  const assets = document.querySelector(`#${kind}-assets`);
  assets.replaceChildren();
  if (!release) {
    meta.textContent = kind === "beta"
      ? "The first downloadable beta has not been published yet."
      : "No stable release has been published yet.";
    const link = document.createElement("a");
    link.className = "button secondary";
    link.href = RELEASES_PAGE;
    link.textContent = "View releases";
    assets.append(link);
    return;
  }

  const date = new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(
    new Date(release.published_at),
  );
  meta.textContent = `${release.name || release.tag_name} · Published ${date}`;
  for (const asset of release.assets) {
    const label = assetLabel(asset.name);
    if (!label) continue;
    const link = document.createElement("a");
    link.className = "button";
    link.href = asset.browser_download_url;
    link.textContent = label;
    assets.append(link);
  }
  if (!assets.children.length) {
    const link = document.createElement("a");
    link.className = "button secondary";
    link.href = release.html_url;
    link.textContent = "View release";
    assets.append(link);
  }
}

async function loadReleases() {
  try {
    const response = await fetch(RELEASES_URL, { headers: { Accept: "application/vnd.github+json" } });
    if (!response.ok) throw new Error(`GitHub returned ${response.status}`);
    const releases = await response.json();
    const stableRelease = newestRelease(releases, false);
    renderRelease(newestRelease(releases, true), "beta");
    renderRelease(stableRelease, "stable");
    return Boolean(stableRelease);
  } catch {
    renderRelease(null, "beta");
    renderRelease(null, "stable");
    return false;
  }
}

function modeLabel(mode) {
  return {
    "managed-local": "Managed local media",
    "referenced-local": "Referenced local media",
    remote: "Remote media",
  }[mode] || mode;
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const input = document.createElement("textarea");
    input.value = text;
    input.setAttribute("readonly", "");
    input.style.position = "fixed";
    input.style.opacity = "0";
    document.body.append(input);
    input.select();
    const copied = document.execCommand("copy");
    input.remove();
    return copied;
  }
}

function collectionCard(collection, stableAvailable) {
  const card = document.createElement("article");
  card.className = "collection-card";

  const mode = document.createElement("div");
  mode.className = "mode";
  mode.textContent = (collection.media_modes || []).map(modeLabel).join(" · ");
  const title = document.createElement("h3");
  title.textContent = collection.title;
  const description = document.createElement("p");
  description.textContent = collection.description;
  const actions = document.createElement("div");
  actions.className = "collection-actions";

  if (collection.manifest_url) {
    const preferredChannel = stableAvailable ? "release" : "beta";
    const open = document.createElement("a");
    open.className = "button";
    open.href = collectionDeepLink(collection.manifest_url, preferredChannel);
    open.textContent = stableAvailable ? "Open in Watchcraft" : "Open in Watchcraft Beta";
    actions.append(open);
    if (stableAvailable) {
      const openBeta = document.createElement("a");
      openBeta.className = "button secondary";
      openBeta.href = collectionDeepLink(collection.manifest_url, "beta");
      openBeta.textContent = "Open in Beta";
      actions.append(openBeta);
    }
    const copy = document.createElement("button");
    copy.className = "button secondary";
    copy.type = "button";
    copy.textContent = "Copy collection URL";
    copy.addEventListener("click", async () => {
      const copied = await copyText(collection.manifest_url);
      copy.textContent = copied ? "Copied" : "Copy unavailable";
      setTimeout(() => { copy.textContent = "Copy collection URL"; }, 1600);
    });
    const inspect = document.createElement("a");
    inspect.className = "button secondary";
    inspect.href = collection.manifest_url;
    inspect.textContent = "View manifest";
    actions.append(copy, inspect);
  } else if (collection.package_url) {
    const download = document.createElement("a");
    download.className = "button";
    download.href = collection.package_url;
    download.textContent = "Download collection";
    actions.append(download);
  }

  card.append(mode, title, description, actions);
  return card;
}

async function loadCollections(stableAvailable) {
  let collections = fallbackCollections;
  try {
    const response = await fetch(COLLECTIONS_URL);
    if (!response.ok) throw new Error(`Collection directory returned ${response.status}`);
    const directory = await response.json();
    if (Array.isArray(directory.collections) && directory.collections.length) {
      collections = directory.collections;
    }
  } catch {
    // The embedded directory keeps the page useful if the optional public index is unavailable.
  }
  const grid = document.querySelector("#collection-grid");
  grid.replaceChildren(
    ...visibleCollections(collections).map(
      (collection) => collectionCard(collection, stableAvailable),
    ),
  );
}

void loadReleases().then(loadCollections);
