import { useEffect, useState, type FormEvent, type MouseEvent, type ReactElement } from "react";

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
}

interface CollectionSettingsProps {
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
          <button aria-label="Close settings" className="settings-close" disabled={busy} onClick={onClose} type="button">×</button>
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
                      <span className="collection-source" title={collection.sourceLabel}>
                        {collection.sourceType === "url" ? "URL" : "Folder"} · {collection.sourceLabel}
                      </span>
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
                <p>Install from a folder on this computer or from a collection manifest URL.</p>
              </div>
            </div>
            <button className="primary-action compact-action" disabled={busy} onClick={() => void onAddFolder(openAfter)} type="button">
              Choose folder…
            </button>
            <div className="settings-or"><span>or</span></div>
            <form className="collection-url-form" onSubmit={submitUrl}>
              <label htmlFor="collection-url">Collection URL</label>
              <div>
                <input
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
              </div>
            </form>
            <label className="open-after-option">
              <input checked={openAfter} disabled={busy} onChange={(event) => setOpenAfter(event.target.checked)} type="checkbox" />
              <span>Open the collection after adding it</span>
            </label>
          </section>

          {error ? <p className="settings-error" role="alert">{error}</p> : null}
          {busy ? <p className="settings-progress" role="status">Working…</p> : null}
        </div>
      </section>
    </div>
  );
}
