import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent,
  type ReactElement,
} from "react";
import type { PublicCollectionDirectoryEntry } from "@watchcraft/catalog-core";
import { displayCollectionSource, displayLocalPath } from "./collectionSource";
import {
  FALLBACK_FEATURED_COLLECTIONS,
  FEATURED_COLLECTION_DIRECTORY_URL,
  readFeaturedCollections,
} from "./featuredCollections";

export interface RegisteredCollection {
  collectionId: string;
  title: string;
  revision: number;
  sourceType: "folder" | "url";
  sourceLabel: string;
  active: boolean;
  archived: boolean;
  mediaRoot: string | null;
  mediaExpected: number;
  mediaFound: number;
  mediaExtra: number;
  mediaModes: Array<"managed-local" | "referenced-local" | "remote">;
}

const MEDIA_MODE_LABELS = {
  "managed-local": "Managed local media",
  "referenced-local": "Referenced local media",
  remote: "Web Video",
} as const;

interface CollectionSettingsProps {
  appVersion: string | null;
  busy: boolean;
  collections: RegisteredCollection[];
  error: string | null;
  onAddFolder: (openAfter: boolean) => Promise<boolean>;
  onAddUrl: (url: string, openAfter: boolean) => Promise<boolean>;
  onClose: () => void;
  onLocateMedia: (collection: RegisteredCollection) => Promise<void>;
  onRemove: (collection: RegisteredCollection) => Promise<void>;
  onSetArchived: (collection: RegisteredCollection, archived: boolean) => Promise<void>;
  onSwitch: (collection: RegisteredCollection) => Promise<void>;
  onUpdate: (collection: RegisteredCollection) => Promise<void>;
}

function mediaSummary(collection: RegisteredCollection): string | null {
  if (collection.mediaExpected === 0) return null;
  const parts = [`${collection.mediaFound} of ${collection.mediaExpected} local videos found`];
  if (collection.mediaExtra > 0) parts.push(`${collection.mediaExtra} extra on disk`);
  return parts.join(" · ");
}

export function CollectionSettings({
  appVersion,
  busy,
  collections,
  error,
  onAddFolder,
  onAddUrl,
  onClose,
  onLocateMedia,
  onRemove,
  onSetArchived,
  onSwitch,
  onUpdate,
}: CollectionSettingsProps): ReactElement {
  const [openAfter, setOpenAfter] = useState(true);
  const [showArchived, setShowArchived] = useState(false);
  const [url, setUrl] = useState("");
  const [featuredCollections, setFeaturedCollections] = useState<PublicCollectionDirectoryEntry[]>(
    FALLBACK_FEATURED_COLLECTIONS,
  );
  const [featuredLoading, setFeaturedLoading] = useState(true);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [highlightedIndex, setHighlightedIndex] = useState(-1);
  const inputRef = useRef<HTMLInputElement>(null);
  const availableCollections = collections.filter((collection) => !collection.archived);
  const archivedCount = collections.length - availableCollections.length;
  const displayedCollections = showArchived ? collections : availableCollections;
  const matchingFeaturedCollections = useMemo(() => {
    const installedCollectionIds = new Set(
      collections.map((collection) => collection.collectionId),
    );
    const availableFeaturedCollections = featuredCollections.filter(
      (collection) => !installedCollectionIds.has(collection.collectionId),
    );
    const query = url.trim().toLocaleLowerCase();
    if (!query) return availableFeaturedCollections;
    return availableFeaturedCollections.filter((collection) => [
      collection.title,
      collection.category ?? "",
      collection.url,
      ...collection.mediaModes.map((mode) => MEDIA_MODE_LABELS[mode]),
    ].some((value) => value.toLocaleLowerCase().includes(query)));
  }, [collections, featuredCollections, url]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent): void {
      if (event.key === "Escape" && !busy) onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [busy, onClose]);

  useEffect(() => {
    let active = true;
    void fetch(FEATURED_COLLECTION_DIRECTORY_URL, { cache: "no-store" })
      .then((response) => {
        if (!response.ok) throw new Error(`Directory request failed (${response.status}).`);
        return response.json() as Promise<unknown>;
      })
      .then((value) => {
        if (!active) return;
        const discovered = readFeaturedCollections(value);
        if (discovered.length > 0) setFeaturedCollections(discovered);
      })
      .catch(() => {
        // Keep the bundled starter collection when the directory is unavailable.
      })
      .finally(() => {
        if (active) setFeaturedLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  function chooseFeaturedCollection(collection: PublicCollectionDirectoryEntry): void {
    setUrl(collection.url);
    setPickerOpen(false);
    setHighlightedIndex(-1);
    inputRef.current?.focus();
  }

  function onComboboxKeyDown(event: ReactKeyboardEvent<HTMLInputElement>): void {
    if (event.key === "Escape" && pickerOpen) {
      event.preventDefault();
      event.stopPropagation();
      setPickerOpen(false);
      setHighlightedIndex(-1);
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      setPickerOpen(true);
      const direction = event.key === "ArrowDown" ? 1 : -1;
      setHighlightedIndex((previous) => {
        const length = matchingFeaturedCollections.length;
        if (length === 0) return -1;
        if (previous < 0) return direction > 0 ? 0 : length - 1;
        return (previous + direction + length) % length;
      });
      return;
    }
    if (event.key === "Enter" && pickerOpen && highlightedIndex >= 0) {
      const highlighted = matchingFeaturedCollections[highlightedIndex];
      if (highlighted) {
        event.preventDefault();
        chooseFeaturedCollection(highlighted);
      }
    }
  }

  function closeFromBackdrop(event: MouseEvent<HTMLDivElement>): void {
    if (event.target === event.currentTarget && !busy) onClose();
  }

  function submitUrl(event: FormEvent): void {
    event.preventDefault();
    if (!url.trim() || busy) return;
    void onAddUrl(url.trim(), openAfter).then((added) => {
      if (added) {
        setUrl("");
        setPickerOpen(false);
      }
    });
  }

  return (
    <div className="settings-backdrop" onMouseDown={closeFromBackdrop}>
      <section aria-labelledby="settings-title" aria-modal="true" className="settings-dialog" role="dialog">
        <header className="settings-header">
          <div>
            <span className="eyebrow">Watchcraft</span>
            <h2 id="settings-title">Settings</h2>
          </div>
          <div className="settings-header-actions">
            <button aria-label="Close settings" className="settings-close" disabled={busy} onClick={onClose} type="button">×</button>
          </div>
        </header>

        <div className="settings-content">
          <section className="settings-section">
            <div className="settings-section-heading">
              <div>
                <h3>Collections</h3>
                <p>Switch collections, archive ones you rarely use, or remove a collection from this device.</p>
              </div>
              <div className="collection-heading-actions">
                <span className="collection-count">{availableCollections.length}</span>
              </div>
            </div>
            <div className="collection-registry">
              {displayedCollections.map((collection) => {
                const media = mediaSummary(collection);
                const sourceLabel = displayCollectionSource(collection);
                const canLocateMedia = collection.sourceType === "url"
                  && collection.mediaModes.includes("referenced-local");
                const cannotRemove = collections.length === 1
                  || (collection.active && availableCollections.length === 1);
                return (
                  <article
                    className={`collection-entry ${collection.active ? "active" : ""} ${collection.archived ? "archived" : ""}`}
                    key={collection.collectionId}
                    onDoubleClick={(event) => {
                      if (busy || collection.active || collection.archived) return;
                      if ((event.target as HTMLElement).closest("button")) return;
                      void onSwitch(collection);
                    }}
                    title={collection.active || collection.archived ? undefined : "Double-click to open"}
                  >
                    <div className="collection-entry-copy">
                      <div className="collection-title-row">
                        <strong>{collection.title}</strong>
                        {collection.active ? <span className="active-badge">Open</span> : null}
                        {collection.archived ? <span className="archived-badge">Archived</span> : null}
                      </div>
                      <span className="collection-source" title={sourceLabel}>
                        {collection.sourceType === "url" ? "URL" : "Folder"} · {sourceLabel}
                      </span>
                      <small>
                        Revision {collection.revision}
                        {collection.mediaModes.length > 0
                          ? ` · ${collection.mediaModes.map((mode) => MEDIA_MODE_LABELS[mode]).join(" · ")}`
                          : ""}
                      </small>
                      {collection.mediaRoot ? (
                        <small className="collection-media-root" title={collection.mediaRoot}>
                          Local media · {displayLocalPath(collection.mediaRoot)}
                        </small>
                      ) : null}
                      {media ? <small>{media}</small> : null}
                    </div>
                    <div className="collection-actions">
                      {!collection.active && !collection.archived ? (
                        <button disabled={busy} onClick={() => void onSwitch(collection)} type="button">Open</button>
                      ) : null}
                      {collection.sourceType === "url" && !collection.archived ? (
                        <button disabled={busy} onClick={() => void onUpdate(collection)} type="button">Update</button>
                      ) : null}
                      {canLocateMedia && !collection.archived ? (
                        <button disabled={busy} onClick={() => void onLocateMedia(collection)} type="button">
                          {collection.mediaRoot ? "Change folder" : "Locate videos"}
                        </button>
                      ) : null}
                      {collection.archived ? (
                        <button disabled={busy} onClick={() => void onSetArchived(collection, false)} type="button">Unarchive</button>
                      ) : (
                        <button
                          disabled={busy || collection.active || availableCollections.length === 1}
                          onClick={() => void onSetArchived(collection, true)}
                          title={
                            collection.active
                              ? "Open another collection before archiving this one"
                              : availableCollections.length === 1
                                ? "The final available collection cannot be archived"
                                : "Keep installed but remove from the everyday list"
                          }
                          type="button"
                        >
                          Archive
                        </button>
                      )}
                      <button
                        className="danger-action"
                        disabled={busy || cannotRemove}
                        onClick={() => void onRemove(collection)}
                        title={cannotRemove ? "The final available collection cannot be removed" : "Remove from Watchcraft"}
                        type="button"
                      >
                        Remove
                      </button>
                    </div>
                  </article>
                );
              })}
            </div>
            {archivedCount > 0 ? (
              <div className="collection-registry-footer">
                <label className="show-archived-option">
                  <input
                    checked={showArchived}
                    disabled={busy}
                    onChange={(event) => setShowArchived(event.target.checked)}
                    type="checkbox"
                  />
                  <span>Show archived collections ({archivedCount})</span>
                </label>
              </div>
            ) : null}
          </section>

          <section className="settings-section add-collection-section">
            <div className="settings-section-heading">
              <div>
                <h3>Add a collection</h3>
                <p>Choose a folder, select a featured collection, or paste a collection URL.</p>
              </div>
            </div>
            {error ? <p className="settings-error" role="alert">{error}</p> : null}
            <div className="add-collection-row">
              <button className="primary-action compact-action" disabled={busy} onClick={() => void onAddFolder(openAfter)} type="button">
                Choose folder containing local videos…
              </button>
              <span className="inline-or">or</span>
              <form className="collection-url-form" onSubmit={submitUrl}>
                <div className="desktop-collection-combobox">
                  <div className="desktop-collection-combobox-row">
                    <input
                      aria-activedescendant={highlightedIndex >= 0 ? `desktop-featured-collection-${highlightedIndex}` : undefined}
                      aria-autocomplete="list"
                      aria-controls="desktop-featured-collections"
                      aria-expanded={pickerOpen}
                      aria-haspopup="listbox"
                      aria-label="Collection URL or featured collection"
                      autoCapitalize="none"
                      autoComplete="off"
                      autoCorrect="off"
                      disabled={busy}
                      id="collection-url"
                      onChange={(event) => {
                        setUrl(event.target.value);
                        setPickerOpen(true);
                        setHighlightedIndex(0);
                      }}
                      onFocus={() => setPickerOpen(true)}
                      onKeyDown={onComboboxKeyDown}
                      placeholder="Paste a URL or choose a featured collection"
                      ref={inputRef}
                      role="combobox"
                      spellCheck={false}
                      type="url"
                      value={url}
                    />
                    <button
                      aria-label={pickerOpen ? "Hide featured collections" : "Browse featured collections"}
                      aria-expanded={pickerOpen}
                      className="desktop-featured-toggle"
                      disabled={busy}
                      onClick={() => {
                        setPickerOpen((open) => !open);
                        setHighlightedIndex(pickerOpen ? -1 : 0);
                      }}
                      onMouseDown={(event) => event.preventDefault()}
                      type="button"
                    >
                      <svg aria-hidden="true" viewBox="0 0 16 16">
                        <path d="m3.5 6 4.5 4 4.5-4" />
                      </svg>
                    </button>
                  </div>
                  {pickerOpen ? (
                    <div aria-label="Featured collections" className="desktop-featured-list" id="desktop-featured-collections" role="listbox">
                      <div className="desktop-featured-list-heading">
                        <strong>Featured collections</strong>
                        {featuredLoading ? <span>Updating…</span> : null}
                      </div>
                      {matchingFeaturedCollections.map((collection, index) => (
                        <button
                          aria-selected={index === highlightedIndex}
                          className={index === highlightedIndex ? "desktop-featured-option highlighted" : "desktop-featured-option"}
                          id={`desktop-featured-collection-${index}`}
                          key={collection.url}
                          onClick={() => chooseFeaturedCollection(collection)}
                          onMouseDown={(event) => event.preventDefault()}
                          role="option"
                          type="button"
                        >
                          <strong>{collection.title}</strong>
                          <span>
                            {[
                              collection.category,
                              collection.videoCount === null
                                ? null
                                : `${collection.videoCount} ${collection.videoCount === 1 ? "video" : "videos"}`,
                              collection.mediaModes.map((mode) => MEDIA_MODE_LABELS[mode]).join(" · "),
                            ].filter(Boolean).join(" · ")}
                          </span>
                          <small>{collection.url}</small>
                        </button>
                      ))}
                      {matchingFeaturedCollections.length === 0 ? (
                        <p className="desktop-featured-empty">
                          {url.trim()
                            ? "No featured collections match. You can still add this URL."
                            : "All featured collections are already installed."}
                        </p>
                      ) : null}
                    </div>
                  ) : null}
                </div>
                <button disabled={busy || !url.trim()} type="submit">Add</button>
              </form>
            </div>
            <div className="settings-bottom-row">
              <label className="open-after-option">
                <input checked={openAfter} disabled={busy} onChange={(event) => setOpenAfter(event.target.checked)} type="checkbox" />
                <span>Open the collection after adding it</span>
              </label>
              <span className="settings-version">Version {appVersion ?? "unavailable"}</span>
            </div>
          </section>

          {busy ? <p className="settings-progress" role="status">Working…</p> : null}
        </div>
      </section>
    </div>
  );
}
