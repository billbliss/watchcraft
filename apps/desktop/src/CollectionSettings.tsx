import { useEffect, useState, type FormEvent, type MouseEvent, type ReactElement } from "react";
import { displayCollectionSource } from "./collectionSource";

export interface RegisteredCollection {
  collectionId: string;
  title: string;
  revision: number;
  sourceType: "folder" | "url";
  sourceLabel: string;
  active: boolean;
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
  onRemove: (collection: RegisteredCollection) => Promise<void>;
  onSwitch: (collection: RegisteredCollection) => Promise<void>;
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
  onRemove,
  onSwitch,
}: CollectionSettingsProps): ReactElement {
  const [openAfter, setOpenAfter] = useState(true);
  const [url, setUrl] = useState("");

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
            <span className="settings-version">Version {appVersion ?? "…"}</span>
            <button aria-label="Close settings" className="settings-close" disabled={busy} onClick={onClose} type="button">×</button>
          </div>
        </header>

        <div className="settings-content">
          <section className="settings-section">
            <div className="settings-section-heading">
              <div>
                <h3>Collections</h3>
                <p>Switch between installed collections or remove a registration from this device.</p>
              </div>
              <span>{collections.length}</span>
            </div>
            <div className="collection-registry">
              {collections.map((collection) => {
                const media = mediaSummary(collection);
                const sourceLabel = displayCollectionSource(collection);
                return (
                  <article
                    className={`collection-entry ${collection.active ? "active" : ""}`}
                    key={collection.collectionId}
                    onDoubleClick={(event) => {
                      if (busy || collection.active) return;
                      if ((event.target as HTMLElement).closest("button")) return;
                      void onSwitch(collection);
                    }}
                    title={collection.active ? undefined : "Double-click to open"}
                  >
                    <div className="collection-entry-copy">
                      <div className="collection-title-row">
                        <strong>{collection.title}</strong>
                        {collection.active ? <span className="active-badge">Open</span> : null}
                      </div>
                      <span className="collection-source" title={sourceLabel}>
                        {collection.sourceType === "url" ? "URL" : "Folder"} · {sourceLabel}
                      </span>
                      {collection.mediaModes.length > 0 ? (
                        <small>{collection.mediaModes.map((mode) => MEDIA_MODE_LABELS[mode]).join(" · ")}</small>
                      ) : null}
                      {media ? <small>{media}</small> : null}
                    </div>
                    <div className="collection-actions">
                      {!collection.active ? (
                        <button disabled={busy} onClick={() => void onSwitch(collection)} type="button">Open</button>
                      ) : null}
                      <button
                        className="danger-action"
                        disabled={busy || collections.length === 1}
                        onClick={() => void onRemove(collection)}
                        title={collections.length === 1 ? "Add another collection before removing this one" : "Remove from Watchcraft"}
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
