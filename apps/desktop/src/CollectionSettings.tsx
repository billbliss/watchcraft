import { useEffect, useState, type FormEvent, type MouseEvent, type ReactElement } from "react";
import { displayCollectionSource, displayLocalPath } from "./collectionSource";

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
  remote: "Remote media",
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
  const availableCollections = collections.filter((collection) => !collection.archived);
  const archivedCount = collections.length - availableCollections.length;
  const displayedCollections = showArchived ? collections : availableCollections;

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent): void {
      if (event.key === "Escape" && !busy) onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [busy, onClose]);

  function closeFromBackdrop(event: MouseEvent<HTMLDivElement>): void {
    if (event.target === event.currentTarget && !busy) onClose();
  }

  function submitUrl(event: FormEvent): void {
    event.preventDefault();
    if (!url.trim() || busy) return;
    void onAddUrl(url.trim(), openAfter).then((added) => {
      if (added) setUrl("");
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
            <span className="settings-version">Version {appVersion ?? "unavailable"}</span>
            <button aria-label="Close settings" className="settings-close" disabled={busy} onClick={onClose} type="button">×</button>
          </div>
        </header>

        <div className="settings-content">
          <section className="settings-section">
            <div className="settings-section-heading">
              <div>
                <h3>Collections</h3>
                <p>Switch collections, archive ones you rarely use, or remove a registration from this device.</p>
              </div>
              <div className="collection-heading-actions">
                {archivedCount > 0 ? (
                  <label className="show-archived-option">
                    <input
                      checked={showArchived}
                      disabled={busy}
                      onChange={(event) => setShowArchived(event.target.checked)}
                      type="checkbox"
                    />
                    <span>Show archived collections ({archivedCount})</span>
                  </label>
                ) : null}
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
                        <button disabled={busy} onClick={() => void onSetArchived(collection, false)} type="button">Restore</button>
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
          </section>

          <section className="settings-section add-collection-section">
            <div className="settings-section-heading">
              <div>
                <h3>Add a collection</h3>
                <p>Install from a folder on this computer or from a video collection URL.</p>
              </div>
            </div>
            {error ? <p className="settings-error" role="alert">{error}</p> : null}
            <div className="add-collection-row">
              <button className="primary-action compact-action" disabled={busy} onClick={() => void onAddFolder(openAfter)} type="button">
                Choose folder containing local videos…
              </button>
              <span className="inline-or">or</span>
              <form className="collection-url-form" onSubmit={submitUrl}>
                <input
                  aria-label="Web video collection URL"
                  autoCapitalize="none"
                  autoCorrect="off"
                  disabled={busy}
                  id="collection-url"
                  onChange={(event) => setUrl(event.target.value)}
                  placeholder="https://example.com/course.watchcraft"
                  spellCheck={false}
                  type="url"
                  value={url}
                />
                <button disabled={busy || !url.trim()} type="submit">Add</button>
              </form>
            </div>
            <label className="open-after-option">
              <input checked={openAfter} disabled={busy} onChange={(event) => setOpenAfter(event.target.checked)} type="checkbox" />
              <span>Open the collection after adding it</span>
            </label>
          </section>

          {busy ? <p className="settings-progress" role="status">Working…</p> : null}
        </div>
      </section>
    </div>
  );
}
