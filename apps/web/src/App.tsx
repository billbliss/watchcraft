import {
  clockSeconds,
  displayClock,
  inferTimelineClockMode,
  orderedItems,
  topicPassesFrequencyFilter,
  type CatalogItem,
  type CatalogRepository,
  type CollectionManifest,
  type OrderedCatalogItem,
  type Topic,
  type TopicFamily,
  type VideoAnalysis,
} from "@watchcraft/catalog-core";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactElement,
} from "react";
import type { DiagnosticEvent } from "./diagnostics";

interface AppProps {
  repository: CatalogRepository;
  onCollectionLoaded?: (manifest: CollectionManifest) => void;
  onDiagnosticEvent?: (event: DiagnosticEvent) => void;
  onOpenDiagnostics?: () => void;
  onOpenSettings?: () => void;
  routeBasePath?: string;
  sidebarFooter?: ReactElement;
  videoRouteMode?: "path" | "query";
}

const MIN_SIDEBAR_WIDTH = 270;
const MAX_SIDEBAR_RATIO = 0.58;
const MIN_PLAYER_HEIGHT = 190;
const MIN_DETAILS_HEIGHT = 190;
const SPLITTER_SIZE = 8;

function boundedSidebarWidth(width: number): number {
  const maximum = Math.max(MIN_SIDEBAR_WIDTH, window.innerWidth * MAX_SIDEBAR_RATIO);
  return Math.round(Math.min(Math.max(width, MIN_SIDEBAR_WIDTH), maximum));
}

function defaultSidebarWidth(): number {
  return boundedSidebarWidth(window.innerWidth / 3);
}

function initialSidebarWidth(): number {
  const saved = Number(localStorage.getItem("watchcraftSidebarWidth"));
  return Number.isFinite(saved) && saved > 0
    ? boundedSidebarWidth(saved)
    : defaultSidebarWidth();
}

function boundedPlayerHeight(height: number): number {
  const maximum = Math.max(
    MIN_PLAYER_HEIGHT,
    window.innerHeight - MIN_DETAILS_HEIGHT - SPLITTER_SIZE,
  );
  return Math.round(Math.min(Math.max(height, MIN_PLAYER_HEIGHT), maximum));
}

function defaultPlayerHeight(): number {
  return boundedPlayerHeight(window.innerHeight * 0.52);
}

function initialPlayerHeight(): number {
  const saved = Number(localStorage.getItem("watchcraftPlayerHeight"));
  return Number.isFinite(saved) && saved > 0
    ? boundedPlayerHeight(saved)
    : defaultPlayerHeight();
}

function normalizedRouteBasePath(routeBasePath: string): string {
  const withLeadingSlash = routeBasePath.startsWith("/") ? routeBasePath : `/${routeBasePath}`;
  return withLeadingSlash.endsWith("/") ? withLeadingSlash : `${withLeadingSlash}/`;
}

function routeVideoId(videoRouteMode: "path" | "query", routeBasePath: string): string | null {
  if (videoRouteMode === "query") {
    return new URLSearchParams(window.location.search).get("video");
  }
  const basePath = normalizedRouteBasePath(routeBasePath);
  if (!window.location.pathname.startsWith(basePath)) return null;
  const relativePath = window.location.pathname.slice(basePath.length);
  const match = relativePath.match(/^video\/([^/]+)\/?$/);
  return match ? decodeURIComponent(match[1]) : null;
}

function initialTopics(): Set<string> {
  return new Set(new URLSearchParams(window.location.search).getAll("topic"));
}

function initialFamilies(): Set<string> {
  return new Set(new URLSearchParams(window.location.search).getAll("family"));
}

function dateLabel(item: CatalogItem): string {
  if (typeof item.date === "string") return item.date;
  return item.date?.display ?? "";
}

function locationLabels(item: CatalogItem): string[] {
  return item.locations
    .map((location) =>
      typeof location === "string" ? location : location.name ?? "",
    )
    .filter(Boolean);
}

function normalized(value: string): string {
  return value.toLocaleLowerCase().replace(/\s+/g, " ").trim();
}

function searchGroups(value: string): string[] {
  const groups: string[] = [];
  const pattern = /"([^"]+)"|(\S+)/g;
  for (const match of normalized(value).matchAll(pattern)) {
    const quoted = match[1];
    const token = quoted || match[2];
    if (!token) continue;
    if (quoted) groups.push(normalized(token));
    else if (/^\d+(?:\.\d+)?$/.test(token) && groups.length) {
      groups[groups.length - 1] += ` ${token}`;
    } else groups.push(token);
  }
  return groups;
}

function topicHaystack(topic: Topic): string {
  return normalized(
    [topic.label, topic.canonical_key, ...topic.aliases].join(" "),
  );
}

function itemHaystack(
  ordered: OrderedCatalogItem,
  manifest: CollectionManifest,
): string {
  const { item, path } = ordered;
  const topics = item.topic_ids
    .map((topicId) => {
      const topic = manifest.topics[topicId];
      return topic ? topicHaystack(topic) : "";
    })
    .join(" ");
  const families = item.family_ids
    .map((familyId) => manifest.topic_families[familyId]?.label ?? "")
    .join(" ");
  return normalized(
    [
      item.title,
      item.summary,
      path.join(" "),
      dateLabel(item),
      locationLabels(item).join(" "),
      topics,
      families,
    ].join(" "),
  );
}

function writeRoute(
  itemId: string | null,
  query: string,
  selectedTopics: Set<string>,
  selectedFamilies: Set<string>,
  routeBasePath: string,
  videoRouteMode: "path" | "query",
): void {
  const params = new URLSearchParams(window.location.search);
  params.delete("q");
  params.delete("topic");
  params.delete("family");
  params.delete("video");
  if (query.trim()) params.set("q", query.trim());
  for (const topicId of [...selectedTopics].sort()) {
    params.append("topic", topicId);
  }
  for (const familyId of [...selectedFamilies].sort()) {
    params.append("family", familyId);
  }
  const basePath = normalizedRouteBasePath(routeBasePath);
  if (itemId && videoRouteMode === "query") params.set("video", itemId);
  const path = itemId && videoRouteMode === "path"
    ? `${basePath}video/${encodeURIComponent(itemId)}`
    : basePath;
  const search = params.toString();
  window.history.replaceState(null, "", `${path}${search ? `?${search}` : ""}`);
}

function LoadingScreen(): ReactElement {
  return (
    <main className="status-screen">
      <div className="status-card">
        <span className="eyebrow">Watchcraft</span>
        <h1>Opening your catalog…</h1>
      </div>
    </main>
  );
}

export function App({
  onCollectionLoaded,
  onDiagnosticEvent,
  onOpenDiagnostics,
  onOpenSettings,
  repository,
  routeBasePath = "/",
  sidebarFooter,
  videoRouteMode = "path",
}: AppProps): ReactElement {
  const [manifest, setManifest] = useState<CollectionManifest | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(
    () => routeVideoId(videoRouteMode, routeBasePath),
  );
  const [query, setQuery] = useState(
    () => new URLSearchParams(window.location.search).get("q") ?? "",
  );
  const [topicFilterQuery, setTopicFilterQuery] = useState("");
  const [selectedTopics, setSelectedTopics] = useState<Set<string>>(initialTopics);
  const [selectedFamilies, setSelectedFamilies] = useState<Set<string>>(initialFamilies);
  const [topicThreshold, setTopicThreshold] = useState(
    () => Number(localStorage.getItem("watchcraftTopicThreshold")) || 40,
  );
  const [sidebarWidth, setSidebarWidth] = useState(initialSidebarWidth);
  const [resizingSidebar, setResizingSidebar] = useState(false);
  const resizingSidebarRef = useRef(false);
  const [playerHeight, setPlayerHeight] = useState(initialPlayerHeight);
  const [resizingPlayer, setResizingPlayer] = useState(false);
  const resizingPlayerRef = useRef(false);
  const [analysis, setAnalysis] = useState<VideoAnalysis | null>(null);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [mediaDuration, setMediaDuration] = useState<number | null>(null);
  const [highlightedTopic, setHighlightedTopic] = useState<string | null>(null);
  const [openStatus, setOpenStatus] = useState<"idle" | "opening" | "opened" | "error">("idle");
  const [defaultPlayerName, setDefaultPlayerName] = useState<string | null | undefined>(undefined);
  const [mediaErrorUrl, setMediaErrorUrl] = useState<string | null>(null);
  const mediaRetryCountsRef = useRef(new Map<string, number>());
  const playerRef = useRef<HTMLVideoElement>(null);
  const youtubePlayerRef = useRef<HTMLIFrameElement>(null);

  useEffect(() => {
    let current = true;
    onDiagnosticEvent?.({
      level: "info",
      category: "collection",
      event: "catalog.loading",
      message: "Loading the collection catalog",
      fields: { manifestLocation: repository.manifestLocation },
    });
    repository
      .loadCollection()
      .then((collection) => {
        if (!current) return;
        setManifest(collection);
        onCollectionLoaded?.(collection);
        onDiagnosticEvent?.({
          level: "info",
          category: "collection",
          event: "catalog.loaded",
          message: "Loaded the collection catalog",
          fields: {
            collectionId: collection.collection_id,
            revision: collection.revision,
            videoCount: collection.stats.video_count,
          },
        });
        document.title = `${collection.title} — Watchcraft`;
      })
      .catch((error: unknown) => {
        if (current) {
          const message = error instanceof Error ? error.message : String(error);
          setLoadError(message);
          onDiagnosticEvent?.({
            level: "error",
            category: "collection",
            event: "catalog.failed",
            message,
            fields: { manifestLocation: repository.manifestLocation },
          });
        }
      });
    return () => {
      current = false;
    };
  }, [onCollectionLoaded, onDiagnosticEvent, repository]);

  const items = useMemo(
    () => (manifest ? orderedItems(manifest) : []),
    [manifest],
  );

  const filteredItems = useMemo(() => {
    if (!manifest) return [];
    const terms = searchGroups(query);
    return items.filter((ordered) => {
      if (
        selectedTopics.size > 0 &&
        ![...selectedTopics].every((topicId) =>
          ordered.item.topic_ids.includes(topicId),
        )
      ) {
        return false;
      }
      if (
        selectedFamilies.size > 0 &&
        ![...selectedFamilies].every((familyId) =>
          ordered.item.family_ids.includes(familyId),
        )
      ) {
        return false;
      }
      const haystack = itemHaystack(ordered, manifest);
      return terms.every((term) => haystack.includes(term));
    });
  }, [items, manifest, query, selectedFamilies, selectedTopics]);

  useEffect(() => {
    if (!manifest || items.length === 0) return;
    if (selectedId && filteredItems.some(({ item }) => item.item_id === selectedId)) {
      return;
    }
    setSelectedId(filteredItems[0]?.item.item_id ?? null);
  }, [filteredItems, items, manifest, selectedId]);

  const selectedItem = selectedId && manifest?.items[selectedId]
    ? manifest.items[selectedId]
    : null;
  const selectedOrdered = items.find(({ item }) => item.item_id === selectedId);

  useEffect(() => {
    writeRoute(
      selectedId,
      query,
      selectedTopics,
      selectedFamilies,
      routeBasePath,
      videoRouteMode,
    );
  }, [query, routeBasePath, selectedFamilies, selectedId, selectedTopics, videoRouteMode]);

  useEffect(() => {
    if (!selectedItem) {
      setAnalysis(null);
      return;
    }
    let current = true;
    setAnalysis(null);
    setAnalysisError(null);
    setMediaDuration(null);
    setMediaErrorUrl(null);
    setHighlightedTopic(null);
    setOpenStatus("idle");
    repository
      .loadAnalysis(selectedItem)
      .then((loaded) => {
        if (current) {
          setAnalysis(loaded);
          onDiagnosticEvent?.({
            level: "debug",
            category: "collection",
            event: "analysis.loaded",
            message: "Loaded video analysis",
            fields: { itemId: selectedItem.item_id },
          });
        }
      })
      .catch((error: unknown) => {
        if (current) {
          const message = error instanceof Error ? error.message : String(error);
          setAnalysisError(message);
          onDiagnosticEvent?.({
            level: "error",
            category: "collection",
            event: "analysis.failed",
            message,
            fields: { itemId: selectedItem.item_id, analysisPath: selectedItem.analysis.path },
          });
        }
      });
    return () => {
      current = false;
    };
  }, [onDiagnosticEvent, repository, selectedItem]);

  useEffect(() => {
    let current = true;
    setDefaultPlayerName(undefined);
    if (!selectedItem || !repository.defaultPlayerName) {
      setDefaultPlayerName(null);
      return;
    }
    void (async () => {
      let name = await repository.defaultPlayerName?.(selectedItem) ?? null;
      if (!name) {
        await new Promise((resolve) => window.setTimeout(resolve, 750));
        name = await repository.defaultPlayerName?.(selectedItem) ?? null;
      }
      if (current) setDefaultPlayerName(name);
    })();
    return () => {
      current = false;
    };
  }, [repository, selectedItem]);

  const displayedTopics = useMemo(() => {
    if (!manifest) return [];
    const facetQuery = normalized(topicFilterQuery);
    return Object.values(manifest.topics)
      .filter((topic) => {
        if (selectedTopics.has(topic.topic_id)) return true;
        if (facetQuery) return topicHaystack(topic).includes(facetQuery);
        return topicPassesFrequencyFilter(
          topic.video_count,
          manifest.stats.video_count,
          topicThreshold,
        );
      })
      .sort((left, right) => {
        const selectedDifference = Number(selectedTopics.has(right.topic_id))
          - Number(selectedTopics.has(left.topic_id));
        return selectedDifference
          || right.video_count - left.video_count
          || left.label.localeCompare(right.label, undefined, { sensitivity: "base" });
      });
  }, [manifest, selectedTopics, topicFilterQuery, topicThreshold]);

  const displayedFamilies = useMemo(() => {
    if (!manifest) return [];
    const facetQuery = normalized(topicFilterQuery);
    return Object.values(manifest.topic_families)
      .filter((family) =>
        selectedFamilies.has(family.family_id)
        || !facetQuery
        || normalized(family.canonical_key || family.label).includes(facetQuery),
      )
      .sort((left, right) => {
        const selectedDifference = Number(selectedFamilies.has(right.family_id))
          - Number(selectedFamilies.has(left.family_id));
        return selectedDifference
          || right.video_count - left.video_count
          || left.label.localeCompare(right.label, undefined, { sensitivity: "base" });
      });
  }, [manifest, selectedFamilies, topicFilterQuery]);

  const selectedItemTopics = selectedItem && manifest
    ? selectedItem.topic_ids
        .map((topicId) => manifest.topics[topicId])
        .filter((topic): topic is Topic => Boolean(topic))
    : [];
  const chapterTopics = selectedItemTopics.filter((topic) =>
    Boolean(selectedItem?.topic_sections[topic.topic_id]?.length),
  );
  const otherTopics = selectedItemTopics.filter((topic) =>
    !selectedItem?.topic_sections[topic.topic_id]?.length,
  );
  const relatedTopics = highlightedTopic && manifest
    ? (manifest.topics[highlightedTopic]?.related_topic_ids ?? [])
        .map((topicId) => manifest.topics[topicId])
        .filter((topic): topic is Topic => Boolean(topic))
        .sort((left, right) =>
          right.video_count - left.video_count
          || left.label.localeCompare(right.label, undefined, { sensitivity: "base" }),
        )
        .slice(0, 10)
    : [];
  const mediaUrl = selectedItem ? repository.mediaUrl(selectedItem) : null;
  const selectedLocation = selectedItem ? locationLabels(selectedItem)[0] : null;
  const youtubeMedia = selectedItem?.media.find((media) => media.type === "youtube") ?? null;
  const hasLocalMedia = Boolean(
    selectedItem?.media.some((media) => media.type === "local-file"),
  );
  const timelineClockMode = useMemo(
    () => inferTimelineClockMode(analysis?.sections ?? [], mediaDuration),
    [analysis, mediaDuration],
  );
  const hasFilters = Boolean(
    query.trim() || topicFilterQuery.trim() || selectedTopics.size || selectedFamilies.size,
  );

  useEffect(() => {
    if (!selectedItem) return;
    onDiagnosticEvent?.({
      level: mediaUrl ? "info" : "warn",
      category: "playback",
      event: "media.selected",
      message: mediaUrl ? "Resolved a media source for playback" : "No playable media source was resolved",
      fields: {
        itemId: selectedItem.item_id,
        mediaUrl,
        media: selectedItem.media,
      },
    });
  }, [mediaUrl, onDiagnosticEvent, selectedItem]);

  function recordMediaState(event: string, player: HTMLVideoElement, level: "debug" | "info" | "warn" = "debug"): void {
    onDiagnosticEvent?.({
      level,
      category: "playback",
      event: `media.${event}`,
      message: `HTML media event: ${event}`,
      fields: {
        itemId: selectedItem?.item_id,
        mediaUrl,
        currentTime: player.currentTime,
        duration: Number.isFinite(player.duration) ? player.duration : null,
        readyState: player.readyState,
        networkState: player.networkState,
        paused: player.paused,
        videoWidth: player.videoWidth,
        videoHeight: player.videoHeight,
      },
    });
  }

  function toggleTopic(topicId: string): void {
    setSelectedTopics((previous) => {
      const next = new Set(previous);
      if (next.has(topicId)) next.delete(topicId);
      else next.add(topicId);
      return next;
    });
  }

  function toggleFamily(familyId: string): void {
    setSelectedFamilies((previous) => {
      const next = new Set(previous);
      if (next.has(familyId)) next.delete(familyId);
      else next.add(familyId);
      return next;
    });
  }

  async function openInDefaultPlayer(): Promise<void> {
    if (!selectedItem || openStatus === "opening") return;
    setOpenStatus("opening");
    const opened = await repository.openInDefaultPlayer(selectedItem);
    onDiagnosticEvent?.({
      level: opened ? "info" : "error",
      category: "playback",
      event: opened ? "external.opened" : "external.failed",
      message: opened ? "Opened the video in the default player" : "Could not open the video in the default player",
      fields: { itemId: selectedItem.item_id, mediaUrl },
    });
    setOpenStatus(opened ? "opened" : "error");
    window.setTimeout(() => setOpenStatus("idle"), 1800);
  }

  async function openExternalMedia(): Promise<void> {
    if (!selectedItem || !repository.openExternalMedia || openStatus === "opening") return;
    setOpenStatus("opening");
    const opened = await repository.openExternalMedia(selectedItem);
    onDiagnosticEvent?.({
      level: opened ? "info" : "error",
      category: "playback",
      event: opened ? "external.opened" : "external.failed",
      message: opened ? "Opened external media" : "Could not open external media",
      fields: { itemId: selectedItem.item_id, mediaUrl },
    });
    setOpenStatus(opened ? "opened" : "error");
    window.setTimeout(() => setOpenStatus("idle"), 1800);
  }

  function seek(start: string): void {
    const seconds = clockSeconds(start, timelineClockMode);
    if (youtubeMedia && youtubePlayerRef.current?.contentWindow) {
      const target = youtubePlayerRef.current.contentWindow;
      const send = (func: string, args: unknown[]) => target.postMessage(
        JSON.stringify({ event: "command", func, args }),
        new URL(mediaUrl ?? "https://www.youtube-nocookie.com").origin,
      );
      send("seekTo", [seconds, true]);
      send("playVideo", []);
      return;
    }
    const player = playerRef.current;
    if (!player) return;
    const applySeek = () => {
      player.currentTime = seconds;
      void player.play();
    };
    if (player.readyState >= HTMLMediaElement.HAVE_METADATA) applySeek();
    else player.addEventListener("loadedmetadata", applySeek, { once: true });
  }

  function handleMediaError(sourceUrl: string, player: HTMLVideoElement): void {
    if (player.error?.code === MediaError.MEDIA_ERR_ABORTED) return;
    const retryCount = mediaRetryCountsRef.current.get(sourceUrl) ?? 0;
    onDiagnosticEvent?.({
      level: "error",
      category: "playback",
      event: "media.error",
      message: player.error?.message || "Embedded playback failed",
      fields: {
        itemId: selectedItem?.item_id,
        mediaUrl: sourceUrl,
        mediaErrorCode: player.error?.code,
        retryCount,
        networkState: player.networkState,
        readyState: player.readyState,
      },
    });
    const retryDelays = [500, 1_200, 2_500];
    if (retryCount < retryDelays.length) {
      mediaRetryCountsRef.current.set(sourceUrl, retryCount + 1);
      window.setTimeout(() => {
        if (playerRef.current !== player) return;
        setMediaErrorUrl(null);
        player.load();
      }, retryDelays[retryCount]);
      return;
    }
    setMediaErrorUrl(sourceUrl);
  }

  function retryMedia(): void {
    const player = playerRef.current;
    if (!player) return;
    setMediaErrorUrl(null);
    player.load();
    void player.play().catch((error: unknown) => onDiagnosticEvent?.({
      level: "error",
      category: "playback",
      event: "play.rejected",
      message: error instanceof Error ? error.message : String(error),
      fields: { itemId: selectedItem?.item_id, mediaUrl },
    }));
  }

  function saveSidebarWidth(width: number): void {
    const bounded = boundedSidebarWidth(width);
    setSidebarWidth(bounded);
    localStorage.setItem("watchcraftSidebarWidth", String(bounded));
  }

  function savePlayerHeight(height: number): void {
    const bounded = boundedPlayerHeight(height);
    setPlayerHeight(bounded);
    localStorage.setItem("watchcraftPlayerHeight", String(bounded));
  }

  if (loadError) {
    return (
      <main className="status-screen">
        <div className="status-card error-card">
          <span className="eyebrow">Watchcraft</span>
          <h1>Catalog unavailable</h1>
          <p>{loadError}</p>
          <code>{repository.manifestLocation}</code>
          {(onOpenSettings || onOpenDiagnostics) ? (
            <div className="status-card-actions">
              {onOpenSettings ? (
                <button className="action primary" onClick={onOpenSettings} type="button">Choose collection</button>
              ) : null}
              {onOpenDiagnostics ? (
                <button className="action" onClick={onOpenDiagnostics} type="button">View diagnostics</button>
              ) : null}
            </div>
          ) : null}
        </div>
      </main>
    );
  }
  if (!manifest) return <LoadingScreen />;

  return (
    <main
      className={`app-shell ${resizingSidebar ? "resizing-sidebar" : ""}`}
      style={{ gridTemplateColumns: `${sidebarWidth}px 8px minmax(0, 1fr)` }}
    >
      <aside className="sidebar">
        <header className="sidebar-header">
          <div className="brand-row">
            <div>
              <h1>Watchcraft</h1>
              <p className="tagline">Learn a craft by watching</p>
              <p className="collection-name">{manifest.title}</p>
            </div>
            <span className="result-count">
              {filteredItems.length} of {items.length}
            </span>
          </div>
          <div className="search-row">
            <input
              aria-label="Search videos"
              className="search-input"
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search techniques, year, location…"
              type="search"
              value={query}
            />
            {hasFilters && (
              <button
                aria-label="Clear text and topic filters"
                className="clear-button"
                onClick={() => {
                  setQuery("");
                  setTopicFilterQuery("");
                  setSelectedTopics(new Set());
                  setSelectedFamilies(new Set());
                  setHighlightedTopic(null);
                }}
                title="Clear text and topic filters"
                type="button"
              >
                ×
              </button>
            )}
          </div>
        </header>

        <details className="filters">
          <summary>
            <span>Filter by topic</span>
            {selectedTopics.size + selectedFamilies.size > 0 && (
              <b>{selectedTopics.size + selectedFamilies.size} selected</b>
            )}
          </summary>
          <div className="filter-body">
            <label className="threshold-label">
              <span>Show topics used by at most</span>
              <output>{topicThreshold}%</output>
              <input
                max="100"
                min="1"
                onChange={(event) => {
                  const next = Number(event.target.value);
                  setTopicThreshold(next);
                  localStorage.setItem("watchcraftTopicThreshold", String(next));
                }}
                style={{ "--range-progress": `${topicThreshold}%` } as CSSProperties}
                type="range"
                value={topicThreshold}
              />
            </label>
            <input
              aria-label="Find a topic or family"
              className="topic-filter-search"
              onChange={(event) => setTopicFilterQuery(event.target.value)}
              placeholder="Find a topic…"
              type="search"
              value={topicFilterQuery}
            />
            <p className="filter-note">
              Searching topics temporarily shows common and one-off topics.
            </p>
            <div className="facet-list">
              {displayedFamilies.length > 0 && (
                <section className="facet-section">
                  <h3 className="facet-heading">Families</h3>
                  {displayedFamilies.map((family: TopicFamily) => (
                    <label className="facet" key={family.family_id} title={family.description || family.label}>
                      <input
                        checked={selectedFamilies.has(family.family_id)}
                        onChange={() => toggleFamily(family.family_id)}
                        type="checkbox"
                      />
                      <span>{family.label}</span>
                      <small>{family.video_count}</small>
                    </label>
                  ))}
                </section>
              )}
              <h3 className="facet-heading">Topics</h3>
              {displayedTopics.map((topic) => (
                <label className="facet" key={topic.topic_id}>
                  <input
                    checked={selectedTopics.has(topic.topic_id)}
                    onChange={() => toggleTopic(topic.topic_id)}
                    type="checkbox"
                  />
                  <span>{topic.label}</span>
                  <small>
                    {topic.video_count} · {manifest.stats.video_count
                      ? Math.round((topic.video_count * 100) / manifest.stats.video_count)
                      : 0}%
                  </small>
                </label>
              ))}
            </div>
            <div className="filter-footer">
              {topicFilterQuery.trim()
                ? `${displayedTopics.length} topics · ${displayedFamilies.length} families`
                : `${displayedTopics.length} of ${Object.keys(manifest.topics).length} topics`}
            </div>
          </div>
        </details>

        <nav aria-label="Videos" className="video-list">
          {filteredItems.map(({ item }) => (
            <button
              className={`video-row ${item.item_id === selectedId ? "active" : ""}`}
              key={item.item_id}
              onClick={() => setSelectedId(item.item_id)}
              type="button"
            >
              <strong>{item.title}</strong>
              <span>
                {[
                  dateLabel(item) || "Date unknown",
                  locationLabels(item)[0],
                  `${item.chapter_count} ${item.chapter_count === 1 ? "chapter" : "chapters"}`,
                ].filter(Boolean).join(" · ")}
              </span>
            </button>
          ))}
          {filteredItems.length === 0 && (
            <p className="empty-state">No videos match the current filters.</p>
          )}
        </nav>
        {sidebarFooter ? <footer className="sidebar-footer">{sidebarFooter}</footer> : null}
      </aside>

      <div
        aria-label="Resize catalog and video panels"
        aria-orientation="vertical"
        aria-valuemax={Math.round(window.innerWidth * MAX_SIDEBAR_RATIO)}
        aria-valuemin={MIN_SIDEBAR_WIDTH}
        aria-valuenow={sidebarWidth}
        aria-valuetext={`${Math.round((sidebarWidth / window.innerWidth) * 100)}% of window width`}
        className="sidebar-splitter"
        onDoubleClick={() => saveSidebarWidth(defaultSidebarWidth())}
        onKeyDown={(event) => {
          if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
          event.preventDefault();
          saveSidebarWidth(sidebarWidth + (event.key === "ArrowLeft" ? -24 : 24));
        }}
        onPointerCancel={(event) => {
          resizingSidebarRef.current = false;
          setResizingSidebar(false);
          if (event.currentTarget.hasPointerCapture(event.pointerId)) {
            event.currentTarget.releasePointerCapture(event.pointerId);
          }
        }}
        onPointerDown={(event) => {
          event.preventDefault();
          event.currentTarget.setPointerCapture(event.pointerId);
          resizingSidebarRef.current = true;
          setResizingSidebar(true);
        }}
        onPointerMove={(event) => {
          if (resizingSidebarRef.current) {
            setSidebarWidth(boundedSidebarWidth(event.clientX));
          }
        }}
        onPointerUp={(event) => {
          if (!resizingSidebarRef.current) return;
          saveSidebarWidth(event.clientX);
          resizingSidebarRef.current = false;
          setResizingSidebar(false);
          event.currentTarget.releasePointerCapture(event.pointerId);
        }}
        role="separator"
        tabIndex={0}
        title="Drag to resize; double-click to reset"
      />

      <section
        className={`detail ${resizingPlayer ? "resizing-player" : ""}`}
        style={{ gridTemplateRows: `${playerHeight}px 8px minmax(190px, 1fr)` }}
      >
        {selectedItem ? (
          <>
            <div className="player-pane">
              <div className="player-stack">
                <div className="player-shell">
                  {mediaUrl && youtubeMedia ? (
                    <iframe
                      allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
                      allowFullScreen
                      key={mediaUrl}
                      ref={youtubePlayerRef}
                      referrerPolicy="strict-origin-when-cross-origin"
                      src={mediaUrl}
                      title={`YouTube player — ${selectedItem.title}`}
                    />
                  ) : mediaUrl ? (
                    <>
                      <video
                        controls
                        key={mediaUrl}
                        onCanPlayThrough={(event) => recordMediaState("canplaythrough", event.currentTarget)}
                        onCanPlay={(event) => {
                          mediaRetryCountsRef.current.delete(mediaUrl);
                          setMediaErrorUrl(null);
                          recordMediaState("canplay", event.currentTarget, "info");
                        }}
                        onLoadStart={(event) => recordMediaState("loadstart", event.currentTarget)}
                        onError={(event) => handleMediaError(mediaUrl, event.currentTarget)}
                        onLoadedMetadata={(event) => {
                          const duration = event.currentTarget.duration;
                          setMediaDuration(Number.isFinite(duration) ? duration : null);
                          recordMediaState("loadedmetadata", event.currentTarget, "info");
                        }}
                        onPlaying={(event) => recordMediaState("playing", event.currentTarget, "info")}
                        onStalled={(event) => recordMediaState("stalled", event.currentTarget, "warn")}
                        onWaiting={(event) => recordMediaState("waiting", event.currentTarget, "warn")}
                        playsInline
                        preload="auto"
                        ref={playerRef}
                        src={mediaUrl}
                      />
                      {mediaErrorUrl === mediaUrl && (
                        <div className="media-error" role="status">
                          <span>Embedded playback failed.</span>
                          <button onClick={retryMedia} type="button">Retry</button>
                          {onOpenDiagnostics ? <button onClick={onOpenDiagnostics} type="button">View diagnostics</button> : null}
                        </div>
                      )}
                    </>
                  ) : (
                    <div className="no-media">No playable media source is available.</div>
                  )}
                </div>
                {((hasLocalMedia && repository.canOpenInDefaultPlayer !== false) || youtubeMedia) && (
                  <div className="player-footer">
                    {youtubeMedia ? (
                      <button
                        className="action primary player-action"
                        disabled={openStatus === "opening" || !repository.openExternalMedia}
                        onClick={() => void openExternalMedia()}
                        type="button"
                      >
                        {openStatus === "opening" && "Opening YouTube…"}
                        {openStatus === "opened" && "Opened YouTube"}
                        {openStatus === "error" && "Could not open YouTube"}
                        {openStatus === "idle" && "Watch on YouTube"}
                      </button>
                    ) : (
                      <button
                        className="action primary player-action"
                        disabled={openStatus === "opening"}
                        onClick={() => void openInDefaultPlayer()}
                        type="button"
                      >
                        {openStatus === "opening" && "Opening…"}
                        {openStatus === "opened" && (defaultPlayerName
                          ? `Opened in ${defaultPlayerName}`
                          : "Opened in default player")}
                        {openStatus === "error" && "Could not open video"}
                        {openStatus === "idle" && (defaultPlayerName
                          ? `Open in ${defaultPlayerName}`
                          : defaultPlayerName === undefined
                            ? "Open video"
                            : "Open in default player")}
                      </button>
                    )}
                  </div>
                )}
              </div>
            </div>
            <div
              aria-label="Resize video and details panels"
              aria-orientation="horizontal"
              aria-valuemax={Math.max(
                MIN_PLAYER_HEIGHT,
                window.innerHeight - MIN_DETAILS_HEIGHT - SPLITTER_SIZE,
              )}
              aria-valuemin={MIN_PLAYER_HEIGHT}
              aria-valuenow={playerHeight}
              aria-valuetext={`${Math.round((playerHeight / window.innerHeight) * 100)}% of window height`}
              className="player-splitter"
              onDoubleClick={() => savePlayerHeight(defaultPlayerHeight())}
              onKeyDown={(event) => {
                if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
                event.preventDefault();
                savePlayerHeight(playerHeight + (event.key === "ArrowUp" ? -24 : 24));
              }}
              onPointerCancel={(event) => {
                resizingPlayerRef.current = false;
                setResizingPlayer(false);
                if (event.currentTarget.hasPointerCapture(event.pointerId)) {
                  event.currentTarget.releasePointerCapture(event.pointerId);
                }
              }}
              onPointerDown={(event) => {
                event.preventDefault();
                event.currentTarget.setPointerCapture(event.pointerId);
                resizingPlayerRef.current = true;
                setResizingPlayer(true);
              }}
              onPointerMove={(event) => {
                if (resizingPlayerRef.current) {
                  setPlayerHeight(boundedPlayerHeight(event.clientY));
                }
              }}
              onPointerUp={(event) => {
                if (!resizingPlayerRef.current) return;
                savePlayerHeight(event.clientY);
                resizingPlayerRef.current = false;
                setResizingPlayer(false);
                event.currentTarget.releasePointerCapture(event.pointerId);
              }}
              role="separator"
              tabIndex={0}
              title="Drag to resize; double-click to reset"
            />
            <div className="detail-scroll">
              <div className="detail-inner">
                <div className="detail-heading">
                  <div>
                    <p className="eyebrow">{selectedOrdered?.path.join(" / ")}</p>
                    <h2>{selectedItem.title}</h2>
                  </div>
                  <div className="detail-meta">
                    <span>{dateLabel(selectedItem) || "Date unknown"}</span>
                    {selectedLocation ? <span>{selectedLocation}</span> : null}
                  </div>
                </div>
                <div className="detail-columns">
                  <section>
                    <p className="summary">{selectedItem.summary}</p>
                    <h3>Concepts and techniques</h3>
                    <div className="topic-groups">
                      {chapterTopics.length ? (
                        <div className="topic-group">
                          <span className="topic-group-label">Chapter topics:</span>
                          {chapterTopics.map((topic) => (
                            <button
                              className={`topic-pill navigable ${highlightedTopic === topic.topic_id ? "active" : ""}`}
                              key={topic.topic_id}
                              onClick={() => setHighlightedTopic(
                                highlightedTopic === topic.topic_id ? null : topic.topic_id,
                              )}
                              type="button"
                            >
                              {topic.label}
                            </button>
                          ))}
                        </div>
                      ) : null}
                      {otherTopics.length ? (
                        <div className="topic-group">
                          <span className="topic-group-label">Other topics:</span>
                          {otherTopics.map((topic, index) => (
                            <span className="other-topic" key={topic.topic_id}>
                              {topic.label}
                              {index < otherTopics.length - 1 ? <span aria-hidden="true"> ·</span> : null}
                            </span>
                          ))}
                        </div>
                      ) : null}
                    </div>
                    <div className="related-box">
                      <strong>Related topics</strong>
                      {highlightedTopic ? (
                        relatedTopics.length ? (
                          <div className="topic-pills">
                            {relatedTopics.map((topic) => (
                              <button
                                aria-pressed={selectedTopics.has(topic.topic_id)}
                                className={`topic-pill related ${selectedTopics.has(topic.topic_id) ? "selected" : ""}`}
                                key={topic.topic_id}
                                onClick={() => toggleTopic(topic.topic_id)}
                                type="button"
                              >
                                {topic.label} · {topic.video_count}
                              </button>
                            ))}
                          </div>
                        ) : <p>No related topics are recorded.</p>
                      ) : <p>Select a topic to highlight its chapters and see related topics.</p>}
                    </div>
                  </section>

                  <section className="chapters-column">
                    <h3>Timeline</h3>
                    {analysisError && <p className="inline-error">{analysisError}</p>}
                    {!analysis && !analysisError && <p className="muted">Loading chapters…</p>}
                    <div className="timeline">
                      {analysis?.sections.map((section, index) => {
                        const highlighted = highlightedTopic
                          ? selectedItem.topic_sections[highlightedTopic]?.includes(index)
                          : false;
                        return (
                          <button
                            className={`chapter ${highlighted ? "topic-match" : ""}`}
                            key={`${section.start}-${section.title}`}
                            onClick={() => seek(section.start)}
                            type="button"
                          >
                            <time>{displayClock(section.start, timelineClockMode)}</time>
                            <span>
                              <strong>{section.title}</strong>
                              <small>{section.description}</small>
                              {highlighted && <em>Covered here</em>}
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  </section>
                </div>
              </div>
            </div>
          </>
        ) : (
          <div className="empty-detail">Select a video to begin.</div>
        )}
      </section>
    </main>
  );
}
