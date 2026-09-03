import {
  collectionBrowseCopy,
  collectionCategories,
  collectionDeepLink,
  collectionSupportsWeb,
  collectionWebLink,
  collectionsInCategory,
  developerInfoEnabled,
  newestRelease,
  videoCountLabel,
  withFallbackCategories,
} from "./directory.mjs";

const RELEASES_URL = "https://api.github.com/repos/billbliss/watchcraft/releases?per_page=20";
const RELEASES_PAGE = "https://github.com/billbliss/watchcraft/releases";
const COLLECTIONS_URL = "https://collections.watchcraft.stream/directory.json";
const WEB_COLLECTIONS_KEY = "watchcraft.web.collections.v1";
const FALLBACK_CATEGORIES = {
  "hello-world-managed": "Examples",
  "hello-world-referenced": "Examples",
  "premiere-pro-ai-tools": "Video Editing",
  "davinci-resolve": "Video Editing",
  "official-ptgui-tutorial": "Image Editing",
  "essence-of-linear-algebra": "Mathematics",
  "justinguitar-grade-1-beginner-guitar-course": "Music",
  "plumbing-repairs-and-upgrades": "Home Improvement",
  "techniquely-with-lan-lam-america-s-test-kitchen": "Cooking",
  "photoshop-tutorial-for-beginners-complete-series": "Image Editing",
  "electrical-upgrades": "Home Improvement",
  "photoshop-advanced-course-masking-retouching-3d-lighting-and-cameras": "Image Editing",
  "30-days-of-photoshop": "Image Editing",
  "vegan-recipes-goodful": "Cooking",
};

const fallbackCollections = [
  {
    title: "Hello, Watchcraft! — Managed",
    description: "A Watchcraft-made example showing how a collection can keep its video in app-managed storage.",
    category: "Examples",
    video_count: 1,
    media_modes: ["managed-local"],
    manifest_url: "https://collections.watchcraft.stream/collections/hello-world-managed/collection.json",
    archived: true,
  },
  {
    title: "Hello, Watchcraft! — Referenced",
    description: "A Watchcraft-made example showing how a collection can play video from a folder you control.",
    category: "Examples",
    video_count: 1,
    media_modes: ["referenced-local"],
    package_url: "https://collections.watchcraft.stream/downloads/hello-world-referenced.zip",
    archived: true,
  },
  {
    title: "Learning Adobe Premiere Pro",
    description: "A practical Premiere Pro learning path from Adobe Video, Think Media, Primal Video, and Gavin Herman, spanning first edits through AI-assisted workflows.",
    category: "Video Editing",
    video_count: 4,
    media_modes: ["remote"],
    manifest_url: "https://collections.watchcraft.stream/collections/premiere-pro-ai-tools/collection.json",
  },
];

function setupGalleryCarousel() {
  const carousel = document.querySelector(".gallery-preview");
  if (!carousel) return;

  const track = carousel.querySelector(".gallery-preview-track");
  const slides = Array.from(track.children);
  const dots = carousel.querySelector(".carousel-dots");
  const previous = carousel.querySelector(".carousel-arrow.previous");
  const next = carousel.querySelector(".carousel-arrow.next");
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  let currentSlide = 0;
  let physicalSlide = 1;
  let autoAdvance;
  let scrollFrame;
  let scrollSettled;

  const firstClone = slides[0].cloneNode(true);
  const lastClone = slides.at(-1).cloneNode(true);
  for (const clone of [firstClone, lastClone]) {
    clone.setAttribute("aria-hidden", "true");
    clone.tabIndex = -1;
  }
  track.prepend(lastClone);
  track.append(firstClone);

  function updateCarouselState(index) {
    currentSlide = (index + slides.length) % slides.length;
    Array.from(dots.children).forEach((dot, dotIndex) => {
      dot.classList.toggle("is-active", dotIndex === currentSlide);
      dot.setAttribute("aria-current", dotIndex === currentSlide ? "true" : "false");
    });
  }

  function showSlide(index, behavior = "smooth") {
    updateCarouselState(index);
    physicalSlide = currentSlide + 1;
    track.scrollTo({ left: physicalSlide * track.clientWidth, behavior });
  }

  function moveBy(amount) {
    const movingPastEnd = amount > 0 && currentSlide === slides.length - 1;
    const movingPastStart = amount < 0 && currentSlide === 0;
    updateCarouselState(currentSlide + amount);
    physicalSlide = movingPastEnd
      ? slides.length + 1
      : movingPastStart
        ? 0
        : currentSlide + 1;
    track.scrollTo({ left: physicalSlide * track.clientWidth, behavior: "smooth" });
  }

  function settleCarousel() {
    physicalSlide = Math.round(track.scrollLeft / track.clientWidth);
    if (physicalSlide === 0) {
      physicalSlide = slides.length;
      track.scrollTo({ left: physicalSlide * track.clientWidth, behavior: "auto" });
    } else if (physicalSlide === slides.length + 1) {
      physicalSlide = 1;
      track.scrollTo({ left: track.clientWidth, behavior: "auto" });
    }
    updateCarouselState(physicalSlide - 1);
  }

  function stopAutoAdvance() {
    window.clearInterval(autoAdvance);
  }

  function startAutoAdvance() {
    stopAutoAdvance();
    if (reduceMotion.matches || document.hidden) return;
    autoAdvance = window.setInterval(() => moveBy(1), 5000);
  }

  slides.forEach((_, index) => {
    const dot = document.createElement("button");
    dot.className = "carousel-dot";
    dot.type = "button";
    dot.setAttribute("aria-label", `Show screenshot ${index + 1} of ${slides.length}`);
    dot.addEventListener("click", () => {
      showSlide(index);
      startAutoAdvance();
    });
    dots.append(dot);
  });

  previous.addEventListener("click", () => {
    moveBy(-1);
    startAutoAdvance();
  });
  next.addEventListener("click", () => {
    moveBy(1);
    startAutoAdvance();
  });
  track.addEventListener("scroll", () => {
    window.cancelAnimationFrame(scrollFrame);
    scrollFrame = window.requestAnimationFrame(() => {
      window.clearTimeout(scrollSettled);
      scrollSettled = window.setTimeout(settleCarousel, 120);
    });
  }, { passive: true });
  carousel.addEventListener("pointerenter", stopAutoAdvance);
  carousel.addEventListener("pointerleave", startAutoAdvance);
  carousel.addEventListener("focusin", stopAutoAdvance);
  carousel.addEventListener("focusout", () => {
    window.setTimeout(() => {
      if (!carousel.contains(document.activeElement)) startAutoAdvance();
    });
  });
  reduceMotion.addEventListener("change", startAutoAdvance);
  document.addEventListener("visibilitychange", startAutoAdvance);
  window.addEventListener("resize", () => showSlide(currentSlide, "auto"));

  showSlide(0, "auto");
  startAutoAdvance();
}

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
    remote: "Web Video",
  }[mode] || mode;
}

function setupWebAppLinks() {
  let hasSavedCollections = false;
  try {
    const saved = JSON.parse(window.localStorage.getItem(WEB_COLLECTIONS_KEY) || "[]");
    hasSavedCollections = Array.isArray(saved) && saved.length > 0;
  } catch {
    // The ordinary Open web app label works when browser storage is unavailable.
  }
  if (!hasSavedCollections) return;
  for (const link of document.querySelectorAll("[data-web-app-link]")) {
    link.textContent = "Continue in Watchcraft";
  }
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

function collectionCard(collection, showDeveloperInfo) {
  const card = document.createElement("article");
  card.className = "collection-card";

  const meta = document.createElement("div");
  meta.className = "collection-card-meta";
  const mode = document.createElement("div");
  mode.className = "mode";
  mode.textContent = (collection.media_modes || []).map(modeLabel).join(" · ");
  meta.append(mode);
  if (collection.category) {
    const category = document.createElement("div");
    category.className = "collection-category";
    category.textContent = collection.category;
    meta.append(category);
  }
  const title = document.createElement("h3");
  title.textContent = collection.title;
  const description = document.createElement("p");
  description.textContent = collection.description;
  const actions = document.createElement("div");
  actions.className = "collection-actions";

  if (collection.manifest_url) {
    const supportsWeb = collectionSupportsWeb(collection);
    if (supportsWeb) {
      const openWeb = document.createElement("a");
      openWeb.className = "button";
      openWeb.href = collectionWebLink(collection.manifest_url);
      openWeb.textContent = "Open in browser";
      actions.append(openWeb);
    }
    const open = document.createElement("a");
    open.className = supportsWeb ? "button secondary" : "button";
    open.href = collectionDeepLink(collection.manifest_url);
    open.textContent = "Open in desktop app";
    actions.append(open);
    const copy = document.createElement("button");
    copy.className = "button secondary";
    copy.type = "button";
    copy.textContent = "Copy collection URL";
    copy.addEventListener("click", async () => {
      const copied = await copyText(collection.manifest_url);
      copy.textContent = copied ? "Copied" : "Copy unavailable";
      setTimeout(() => { copy.textContent = "Copy collection URL"; }, 1600);
    });
    actions.append(copy);
    if (showDeveloperInfo) {
      const inspect = document.createElement("a");
      inspect.className = "button secondary";
      inspect.href = collection.manifest_url;
      inspect.textContent = "View manifest";
      actions.append(inspect);
    }
  } else if (collection.package_url) {
    const download = document.createElement("a");
    download.className = "button";
    download.href = collection.package_url;
    download.textContent = "Download collection";
    actions.append(download);
  }

  const footer = document.createElement("div");
  footer.className = "collection-card-footer";
  const videoCount = document.createElement("span");
  videoCount.className = "collection-video-count";
  videoCount.textContent = videoCountLabel(collection.video_count);
  footer.append(actions, videoCount);

  card.append(meta, title, description, footer);
  return card;
}

function renderCollections(collections, category = "", showDeveloperInfo = false) {
  const grid = document.querySelector("#collection-grid");
  const filtered = collectionsInCategory(collections, category);
  grid.replaceChildren(
    ...filtered.map((collection) => collectionCard(collection, showDeveloperInfo)),
  );
  if (!filtered.length) {
    const empty = document.createElement("p");
    empty.className = "collection-empty";
    empty.textContent = "No collections are available in this category.";
    grid.append(empty);
  }
}

function sizeCategorySelect(select) {
  const context = document.createElement("canvas").getContext("2d");
  if (!context) return;
  const style = getComputedStyle(select);
  context.font = style.font;
  const widestOption = Math.max(
    ...Array.from(select.options, (option) => context.measureText(option.textContent || "").width),
  );
  const horizontalPadding = Number.parseFloat(style.paddingLeft)
    + Number.parseFloat(style.paddingRight);
  select.style.setProperty(
    "--category-select-width",
    `${Math.ceil(widestOption + horizontalPadding + 28)}px`,
  );
}

async function loadCollections() {
  let collections = fallbackCollections;
  try {
    const response = await fetch(COLLECTIONS_URL);
    if (!response.ok) throw new Error(`Collection directory returned ${response.status}`);
    const directory = await response.json();
    if (Array.isArray(directory.collections) && directory.collections.length) {
      collections = withFallbackCategories(directory.collections, FALLBACK_CATEGORIES);
    }
  } catch {
    // The embedded directory keeps the page useful if the optional public index is unavailable.
  }
  const showDeveloperInfo = developerInfoEnabled(window.location.search);
  document.querySelector("#collection-intro").textContent = collectionBrowseCopy(collections);
  const categorySelect = document.querySelector("#collection-category");
  for (const category of collectionCategories(collections)) {
    const option = document.createElement("option");
    option.value = category;
    option.textContent = category;
    categorySelect.append(option);
  }
  sizeCategorySelect(categorySelect);
  categorySelect.addEventListener("change", () => {
    renderCollections(collections, categorySelect.value, showDeveloperInfo);
  });
  renderCollections(collections, "", showDeveloperInfo);
}

setupGalleryCarousel();
setupWebAppLinks();
void loadReleases();
void loadCollections();
