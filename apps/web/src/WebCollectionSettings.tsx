import { useEffect, useState, type FormEvent, type MouseEvent, type ReactElement } from "react";
import type { SavedWebCollection } from "./webCollectionRegistry";

interface WebCollectionSettingsProps {
  activeUrl: string;
  busy: boolean;
  collections: SavedWebCollection[];
  error: string | null;
  onAddUrl: (url: string, openAfter: boolean) => Promise<boolean>;
  onClose: () => void;
  onRemove: (collection: SavedWebCollection) => void;
  onSwitch: (collection: SavedWebCollection) => void;
}

export function WebCollectionSettings({
  activeUrl,
  busy,
  collections,
  error,
  onAddUrl,
  onClose,
  onRemove,
  onSwitch,
}: WebCollectionSettingsProps): ReactElement {
  const [openAfter, setOpenAfter] = useState(true);
  const [url, setUrl] = useState("");

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent): void {
      if (event.key === "Escape" && !busy) onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [busy, onClose]);

  function submit(event: FormEvent): void {
    event.preventDefault();
    if (!url.trim() || busy) return;
    void onAddUrl(url.trim(), openAfter).then((added) => {
      if (added) setUrl("");
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
              {collections.map((collection) => {
                const active = collection.url === activeUrl;
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
                        disabled={busy || collections.length === 1}
                        onClick={() => onRemove(collection)}
                        title={collections.length === 1 ? "Add another collection before removing this one" : "Remove from this browser"}
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
                <p>Save a Watchcraft collection manifest URL in this browser.</p>
              </div>
            </div>
            <form className="web-collection-url-form" onSubmit={submit}>
              <input
                aria-label="Collection URL"
                autoCapitalize="none"
                autoCorrect="off"
                disabled={busy}
                onChange={(event) => setUrl(event.target.value)}
                placeholder="https://example.com/course.watchcraft"
                spellCheck={false}
                type="url"
                value={url}
              />
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

          {error ? <p className="web-settings-error" role="alert">{error}</p> : null}
          {busy ? <p className="web-settings-progress" role="status">Loading collection…</p> : null}
        </div>
      </section>
    </div>
  );
}
