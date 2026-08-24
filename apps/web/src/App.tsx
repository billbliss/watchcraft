import {
  clockSeconds,
  displayClock,
  inferTimelineClockMode,
  orderedItems,
  type CatalogItem,
  type CatalogRepository,
  type CollectionManifest,
  type OrderedCatalogItem,
  type Topic,
  type VideoAnalysis,
} from "@watchcraft/catalog-core";
import { useEffect, useMemo, useRef, useState, type ReactElement } from "react";

interface AppProps {
  repository: CatalogRepository;
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

function routeVideoId(): string | null {
  const match = window.location.pathname.match(/^\/video\/([^/]+)\/?$/);
  return match ? decodeURIComponent(match[1]) : null;
}

function initialTopics(): Set<string> {
  return new Set(new URLSearchParams(window.location.search).getAll("topic"));
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

function itemHaystack(
  ordered: OrderedCatalogItem,
  manifest: CollectionManifest,
): string {
  const { item, path } = ordered;
  const topics = item.topic_ids
    .map((topicId) => manifest.topics[topicId]?.label ?? "")
    .join(" ");
  return normalized(
    [
      item.title,
      item.summary,
      path.join(" "),
      dateLabel(item),
      locationLabels(item).join(" "),
      topics,
    ].join(" "),
  );
}

function writeRoute(
  itemId: string | null,
  query: string,
  selectedTopics: Set<string>,
): void {
  const params = new URLSearchParams(window.location.search);
  params.delete("q");
  params.delete("topic");
  if (query.trim()) params.set("q", query.trim());
  for (const topicId of [...selectedTopics].sort()) {
    params.append("topic", topicId);
  }
  const path = itemId ? `/video/${encodeURIComponent(itemId)}` : "/";
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

export function App({ repository }: AppProps): ReactElement {
  const [manifest, setManifest] = useState<CollectionManifest | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(routeVideoId);
  const [query, setQuery] = useState(
    () => new URLSearchParams(window.location.search).get("q") ?? "",
  );
  const [selectedTopics, setSelectedTopics] = useState<Set<string>>(initialTopics);
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
  const playerRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    let current = true;
    repository
      .loadCollection()
      .then((collection) => {
        if (!current) return;
        setManifest(collection);
        document.title = `${collection.title} — Watchcraft`;
      })
      .catch((error: unknown) => {
        if (current) {
          setLoadError(error instanceof Error ? error.message : String(error));
        }
      });
    return () => {
      current = false;
    };
  }, [repository]);

  const items = useMemo(
    () => (manifest ? orderedItems(manifest) : []),
    [manifest],
  );

  const filteredItems = useMemo(() => {
    if (!manifest) return [];
    const terms = normalized(query).split(" ").filter(Boolean);
    return items.filter((ordered) => {
      if (
        selectedTopics.size > 0 &&
        ![...selectedTopics].every((topicId) =>
          ordered.item.topic_ids.includes(topicId),
        )
      ) {
        return false;
      }
      const haystack = itemHaystack(ordered, manifest);
      return terms.every((term) => haystack.includes(term));
    });
  }, [items, manifest, query, selectedTopics]);

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
    writeRoute(selectedId, query, selectedTopics);
  }, [query, selectedId, selectedTopics]);

  useEffect(() => {
    if (!selectedItem) {
      setAnalysis(null);
      return;
    }
    let current = true;
    setAnalysis(null);
    setAnalysisError(null);
    setMediaDuration(null);
    setHighlightedTopic(null);
    repository
      .loadAnalysis(selectedItem)
      .then((loaded) => {
        if (current) setAnalysis(loaded);
      })
      .catch((error: unknown) => {
        if (current) {
          setAnalysisError(error instanceof Error ? error.message : String(error));
        }
      });
    return () => {
      current = false;
    };
  }, [repository, selectedItem]);

  const displayedTopics = useMemo(() => {
    if (!manifest) return [];
    return Object.values(manifest.topics)
      .filter((topic) => {
        const percentage = manifest.stats.video_count
          ? (topic.video_count * 100) / manifest.stats.video_count
          : 0;
        return selectedTopics.has(topic.topic_id) || percentage <= topicThreshold;
      })
      .sort((left, right) =>
        left.label.localeCompare(right.label, undefined, { sensitivity: "base" }),
      );
  }, [manifest, selectedTopics, topicThreshold]);

  const selectedItemTopics = selectedItem && manifest
    ? selectedItem.topic_ids
        .map((topicId) => manifest.topics[topicId])
        .filter((topic): topic is Topic => Boolean(topic))
    : [];
  const relatedTopics = highlightedTopic && manifest
    ? (manifest.topics[highlightedTopic]?.related_topic_ids ?? [])
        .map((topicId) => manifest.topics[topicId])
        .filter((topic): topic is Topic => Boolean(topic))
    : [];
  const mediaUrl = selectedItem ? repository.mediaUrl(selectedItem) : null;
  const timelineClockMode = useMemo(
    () => inferTimelineClockMode(analysis?.sections ?? [], mediaDuration),
    [analysis, mediaDuration],
  );
  const hasFilters = Boolean(query.trim() || selectedTopics.size);

  function toggleTopic(topicId: string): void {
    setSelectedTopics((previous) => {
      const next = new Set(previous);
      if (next.has(topicId)) next.delete(topicId);
      else next.add(topicId);
      return next;
    });
  }

  function seek(start: string): void {
    const player = playerRef.current;
    if (!player) return;
    const applySeek = () => {
      player.currentTime = clockSeconds(start, timelineClockMode);
      void player.play();
    };
    if (player.readyState >= HTMLMediaElement.HAVE_METADATA) applySeek();
    else player.addEventListener("loadedmetadata", applySeek, { once: true });
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
                  setSelectedTopics(new Set());
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
            {selectedTopics.size > 0 && <b>{selectedTopics.size}</b>}
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
                type="range"
                value={topicThreshold}
              />
            </label>
            <div className="facet-list">
              {displayedTopics.map((topic) => (
                <label className="facet" key={topic.topic_id}>
                  <input
                    checked={selectedTopics.has(topic.topic_id)}
                    onChange={() => toggleTopic(topic.topic_id)}
                    type="checkbox"
                  />
                  <span>{topic.label}</span>
                  <small>{topic.video_count}</small>
                </label>
              ))}
            </div>
          </div>
        </details>

        <nav aria-label="Videos" className="video-list">
          {filteredItems.map(({ item, path }) => (
            <button
              className={`video-row ${item.item_id === selectedId ? "active" : ""}`}
              key={item.item_id}
              onClick={() => setSelectedId(item.item_id)}
              type="button"
            >
              <strong>{item.title}</strong>
              <span>{path.join(" / ")}</span>
              <span>{[dateLabel(item), ...locationLabels(item)].filter(Boolean).join(" · ")}</span>
            </button>
          ))}
          {filteredItems.length === 0 && (
            <p className="empty-state">No videos match the current filters.</p>
          )}
        </nav>
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
              <div className="player-shell">
                {mediaUrl ? (
                  <video
                    controls
                    key={mediaUrl}
                    onLoadedMetadata={(event) => {
                      const duration = event.currentTarget.duration;
                      setMediaDuration(Number.isFinite(duration) ? duration : null);
                    }}
                    playsInline
                    preload="metadata"
                    ref={playerRef}
                    src={mediaUrl}
                  />
                ) : (
                  <div className="no-media">No playable media source is available.</div>
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
                <div className="detail-columns">
                  <section>
                    <p className="eyebrow">{selectedOrdered?.path.join(" / ")}</p>
                    <h2>{selectedItem.title}</h2>
                    <div className="facts">
                      {dateLabel(selectedItem) && <span>{dateLabel(selectedItem)}</span>}
                      {locationLabels(selectedItem).map((location) => (
                        <span key={location}>{location}</span>
                      ))}
                    </div>
                    {repository.canOpenInDefaultPlayer !== false && (
                      <button
                        className="primary-action"
                        onClick={() => void repository.openInDefaultPlayer(selectedItem)}
                        type="button"
                      >
                        Open in default player
                      </button>
                    )}
                    <p className="summary">{selectedItem.summary}</p>
                    <h3>Topics</h3>
                    <div className="topic-pills">
                      {selectedItemTopics.map((topic) => {
                        const navigable = Boolean(selectedItem.topic_sections[topic.topic_id]?.length);
                        return (
                          <button
                            className={`topic-pill ${navigable ? "navigable" : ""} ${highlightedTopic === topic.topic_id ? "active" : ""}`}
                            disabled={!navigable}
                            key={topic.topic_id}
                            onClick={() => setHighlightedTopic(
                              highlightedTopic === topic.topic_id ? null : topic.topic_id,
                            )}
                            type="button"
                          >
                            {topic.label}
                          </button>
                        );
                      })}
                    </div>
                    <div className="related-box">
                      <strong>Related topics</strong>
                      {highlightedTopic ? (
                        relatedTopics.length ? (
                          <div className="topic-pills">
                            {relatedTopics.map((topic) => (
                              <button
                                className="topic-pill related"
                                key={topic.topic_id}
                                onClick={() => {
                                  setSelectedTopics((previous) => new Set(previous).add(topic.topic_id));
                                  setHighlightedTopic(topic.topic_id);
                                }}
                                type="button"
                              >
                                {topic.label}
                              </button>
                            ))}
                          </div>
                        ) : <p>No related topics are recorded.</p>
                      ) : <p>Select a topic to highlight its chapters and see related topics.</p>}
                    </div>
                  </section>

                  <section className="chapters-column">
                    <h3>Chapters</h3>
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
