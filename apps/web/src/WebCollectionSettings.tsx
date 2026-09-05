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
import {
  FALLBACK_FEATURED_WEB_COLLECTIONS,
  WEB_COLLECTION_DIRECTORY_URL,
  readFeaturedWebCollections,
  type FeaturedWebCollection,
} from "./webCollectionDirectory";
import type { SavedWebCollection } from "./webCollectionRegistry";

interface WebCollectionSettingsProps {
  activeCollectionId: string | null;
  busy: boolean;
  collections: SavedWebCollection[];
  error: string | null;
  openFeaturedPicker: boolean;
  onAddUrl: (url: string, openAfter: boolean) => Promise<boolean>;
  onClose: () => void;
  onOpenDiagnostics: () => void;
  onRemove: (collection: SavedWebCollection) => void;
  onSwitch: (collection: SavedWebCollection) => void;
}

export function WebCollectionSettings({
  activeCollectionId,
  busy,
  collections,
  error,
  openFeaturedPicker,
  onAddUrl,
  onClose,
  onOpenDiagnostics,
  onRemove,
  onSwitch,
}: WebCollectionSettingsProps): ReactElement {
  const [openAfter, setOpenAfter] = useState(true);
  const [url, setUrl] = useState("");
  const [featuredCollections, setFeaturedCollections] = useState<FeaturedWebCollection[]>(
    FALLBACK_FEATURED_WEB_COLLECTIONS,
  );
  const [featuredLoading, setFeaturedLoading] = useState(true);
  const [pickerOpen, setPickerOpen] = useState(openFeaturedPicker);
  const [highlightedIndex, setHighlightedIndex] = useState(openFeaturedPicker ? 0 : -1);
  const inputRef = useRef<HTMLInputElement>(null);

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
    void fetch(WEB_COLLECTION_DIRECTORY_URL, { cache: "no-store" })
      .then((response) => {
        if (!response.ok) throw new Error(`Directory request failed (${response.status}).`);
        return response.json() as Promise<unknown>;
      })
      .then((value) => {
        if (!active) return;
        const discovered = readFeaturedWebCollections(value);
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

  useEffect(() => {
    if (!openFeaturedPicker || collections.length > 0) return;
    setPickerOpen(true);
    setHighlightedIndex(0);
    const frame = window.requestAnimationFrame(() => inputRef.current?.focus());
    return () => window.cancelAnimationFrame(frame);
  }, [collections.length, openFeaturedPicker]);

  function chooseFeaturedCollection(collection: FeaturedWebCollection): void {
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

  function submit(event: FormEvent): void {
    event.preventDefault();
    if (!url.trim() || busy) return;
    void onAddUrl(url.trim(), openAfter).then((added) => {
      if (added) {
        setUrl("");
        setPickerOpen(false);
      }
    });
  }

  function closeFromBackdrop(event: MouseEvent<HTMLDivElement>): void {
    if (event.target === event.currentTarget && !busy) onClose();
  }

  return (
    <div className="web-settings-backdrop" onMouseDown={closeFromBackdrop}>
      <section aria-labelledby="web-settings-title" aria-modal="true" className="web-settings-dialog" role="dialog">
        <header className="web-settings-header">
          <div>
            <span className="eyebrow">Watchcraft</span>
            <h2 id="web-settings-title">Settings</h2>
          </div>
          <button aria-label="Close settings" className="web-settings-close" disabled={busy} onClick={onClose} type="button">×</button>
        </header>

        <div className="web-settings-content">
          <section>
            <div className="web-settings-section-heading">
              <div>
                <h3>Collections</h3>
                <p>Collection URLs saved in this browser.</p>
              </div>
              <span>{collections.length}</span>
            </div>
            <div className="web-collection-registry">
              {collections.length === 0 ? (
                <p className="web-empty-collection-registry">No collections saved yet.</p>
              ) : null}
              {collections.map((collection) => {
                const active = collection.collectionId === activeCollectionId;
                return (
                  <article
                    className={`web-collection-entry ${active ? "active" : ""}`}
                    key={collection.url}
                    onDoubleClick={(event) => {
                      if (busy || active) return;
                      if ((event.target as HTMLElement).closest("button")) return;
                      onSwitch(collection);
                    }}
                    title={active ? undefined : "Double-click to open"}
                  >
                    <div className="web-collection-copy">
                      <div className="web-collection-title-row">
                        <strong>{collection.title}</strong>
                        {active ? <span className="web-active-badge">Open</span> : null}
                      </div>
                      <span title={collection.url}>URL · {collection.url}</span>
                    </div>
                    <div className="web-collection-actions">
                      {!active ? <button disabled={busy} onClick={() => onSwitch(collection)} type="button">Open</button> : null}
                      <button
                        className="web-danger-action"
                        disabled={busy}
                        onClick={() => onRemove(collection)}
                        title="Remove from this browser"
                        type="button"
                      >
                        Remove
                      </button>
                    </div>
                  </article>
                );
              })}
            </div>
          </section>

          <section className="web-add-collection-section">
            <div className="web-settings-section-heading">
              <div>
                <h3>Add a collection</h3>
                <p>Choose a featured collection or paste a Watchcraft manifest URL.</p>
              </div>
            </div>
            <form className="web-collection-url-form" onSubmit={submit}>
              <div className="web-collection-combobox">
                <div className="web-collection-combobox-row">
                  <input
                    aria-activedescendant={highlightedIndex >= 0 ? `featured-web-collection-${highlightedIndex}` : undefined}
                    aria-autocomplete="list"
                    aria-controls="featured-web-collections"
                    aria-expanded={pickerOpen}
                    aria-haspopup="listbox"
                    aria-label="Collection URL or featured collection"
                    autoCapitalize="none"
                    autoComplete="off"
                    autoCorrect="off"
                    disabled={busy}
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
                    className="web-featured-toggle"
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
                  <div aria-label="Featured collections" className="web-featured-list" id="featured-web-collections" role="listbox">
                    <div className="web-featured-list-heading">
                      <strong>Featured collections</strong>
                      {featuredLoading ? <span>Updating…</span> : null}
                    </div>
                    {matchingFeaturedCollections.map((collection, index) => (
                      <button
                        aria-selected={index === highlightedIndex}
                        className={index === highlightedIndex ? "web-featured-option highlighted" : "web-featured-option"}
                        id={`featured-web-collection-${index}`}
                        key={collection.url}
                        onClick={() => chooseFeaturedCollection(collection)}
                        onMouseDown={(event) => event.preventDefault()}
                        role="option"
                        type="button"
                      >
                        <strong>{collection.title}</strong>
                        <span>
                          {[collection.category, collection.videoCount === null
                            ? null
                            : `${collection.videoCount} ${collection.videoCount === 1 ? "video" : "videos"}`]
                            .filter(Boolean)
                            .join(" · ")}
                        </span>
                        <small>{collection.url}</small>
                      </button>
                    ))}
                    {matchingFeaturedCollections.length === 0 ? (
                      <p className="web-featured-empty">
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
            <label className="web-open-after-option">
              <input checked={openAfter} disabled={busy} onChange={(event) => setOpenAfter(event.target.checked)} type="checkbox" />
              <span>Open the collection after adding it</span>
            </label>
          </section>

          <p className="web-settings-note">
            Watchcraft Web plays web video. Collections that use videos on your computer
            require the <a href="/#download">desktop app</a>.
          </p>

          <button className="web-diagnostics-button" onClick={onOpenDiagnostics} type="button">
            View diagnostics…
          </button>

          {error ? <p className="web-settings-error" role="alert">{error}</p> : null}
          {busy ? <p className="web-settings-progress" role="status">Loading collection…</p> : null}
        </div>
      </section>
    </div>
  );
}
