import { useCallback, useEffect, useMemo, useState, type ReactElement } from "react";
import type { CollectionManifest } from "@watchcraft/catalog-core";
import { App } from "./App";
import { WebCollectionSettings } from "./WebCollectionSettings";
import {
  HttpCatalogRepository,
  repositoryFromLocation,
} from "./catalog/httpCatalogRepository";
import {
  WEB_COLLECTIONS_KEY,
  WEB_LAST_COLLECTION_KEY,
  isLegacyWebDemoUrl,
  readLastWebCollectionUrl,
  readWebCollections,
  removeWebCollection,
  saveWebCollection,
  type SavedWebCollection,
} from "./webCollectionRegistry";

interface WebLocationState {
  catalogUrl: string;
  mediaRootUrl: string | null;
}

interface InitialWebAppState {
  collections: SavedWebCollection[];
  currentLocation: WebLocationState | null;
  settingsOpen: boolean;
}

function locationState(): WebLocationState | null {
  const repository = repositoryFromLocation(window.location);
  if (!repository) return null;
  return {
    catalogUrl: repository.manifestLocation,
    mediaRootUrl: repository.configuredMediaRootUrl?.href ?? null,
  };
}

function readSavedCollections(): SavedWebCollection[] {
  try {
    return readWebCollections(window.localStorage.getItem(WEB_COLLECTIONS_KEY))
      .filter((collection) => !isLegacyWebDemoUrl(collection.url, window.location.href));
  } catch {
    return [];
  }
}

function writeCollectionRoute(catalogUrl: string | null, mode: "push" | "replace"): void {
  const url = new URL(window.location.href);
  url.search = "";
  url.hash = "";
  if (catalogUrl) url.searchParams.set("catalog", catalogUrl);
  const route = `${url.pathname}${url.search}`;
  if (mode === "push") window.history.pushState(null, "", route);
  else window.history.replaceState(null, "", route);
}

function initialWebAppState(): InitialWebAppState {
  const collections = readSavedCollections();
  const explicitLocation = locationState();
  if (explicitLocation) {
    return { collections, currentLocation: explicitLocation, settingsOpen: false };
  }

  try {
    const savedUrl = readLastWebCollectionUrl(
      window.localStorage.getItem(WEB_LAST_COLLECTION_KEY),
    );
    const savedCollection = collections.find((collection) => collection.url === savedUrl)
      ?? collections[0];
    if (savedCollection) {
      writeCollectionRoute(savedCollection.url, "replace");
      return {
        collections,
        currentLocation: { catalogUrl: savedCollection.url, mediaRootUrl: null },
        settingsOpen: false,
      };
    }
    window.localStorage.removeItem(WEB_LAST_COLLECTION_KEY);
  } catch {
    // An empty library still opens the collection chooser without browser storage.
  }
  return { collections, currentLocation: null, settingsOpen: true };
}

function persistSavedCollections(collections: SavedWebCollection[]): void {
  try {
    window.localStorage.setItem(WEB_COLLECTIONS_KEY, JSON.stringify(collections));
  } catch {
    // The viewer still works when browser storage is unavailable.
  }
}

function persistLastCollection(url: string): void {
  try {
    window.localStorage.setItem(WEB_LAST_COLLECTION_KEY, url);
  } catch {
    // Remembering the active collection is optional.
  }
}

function clearLastCollection(): void {
  try {
    window.localStorage.removeItem(WEB_LAST_COLLECTION_KEY);
  } catch {
    // Browser storage is optional.
  }
}

function isCollectionManifest(value: unknown): value is CollectionManifest {
  if (!value || typeof value !== "object") return false;
  const manifest = value as Partial<CollectionManifest>;
  return manifest.kind === "watchcraft.collection"
    && manifest.schema_version === 4
    && typeof manifest.collection_id === "string"
    && typeof manifest.title === "string";
}

function EmptyWebApp({ onChoose }: { onChoose: () => void }): ReactElement {
  return (
    <main className="status-screen">
      <div className="status-card web-empty-library">
        <span className="eyebrow">Watchcraft Web</span>
        <h1>Choose a collection to begin</h1>
        <p>Browse featured web-video collections or add a collection URL.</p>
        <div className="web-empty-library-actions">
          <button className="action primary" onClick={onChoose} type="button">Choose a collection</button>
          <a href="/">Watchcraft home</a>
        </div>
      </div>
    </main>
  );
}

export function WebApp(): ReactElement {
  const [initialState] = useState<InitialWebAppState>(initialWebAppState);
  const [currentLocation, setCurrentLocation] = useState<WebLocationState | null>(
    initialState.currentLocation,
  );
  const [collections, setCollections] = useState<SavedWebCollection[]>(initialState.collections);
  const [settingsOpen, setSettingsOpen] = useState(initialState.settingsOpen);
  const [settingsBusy, setSettingsBusy] = useState(false);
  const [settingsError, setSettingsError] = useState<string | null>(null);

  const repository = useMemo(() => currentLocation
    ? new HttpCatalogRepository({
        manifestUrl: currentLocation.catalogUrl,
        mediaRootUrl: currentLocation.mediaRootUrl ?? undefined,
      })
    : null, [currentLocation]);

  const rememberLoadedCollection = useCallback((manifest: CollectionManifest): void => {
    if (!repository) return;
    setCollections((previous) => {
      const next = saveWebCollection(previous, {
        collectionId: manifest.collection_id,
        title: manifest.title,
        url: repository.manifestLocation,
      });
      persistSavedCollections(next);
      persistLastCollection(repository.manifestLocation);
      return next;
    });
  }, [repository]);

  const switchCollection = useCallback((collection: SavedWebCollection): void => {
    writeCollectionRoute(collection.url, "push");
    persistLastCollection(collection.url);
    setCurrentLocation({ catalogUrl: collection.url, mediaRootUrl: null });
    setSettingsError(null);
    setSettingsOpen(false);
  }, []);

  useEffect(() => {
    function onPopState(): void {
      const nextLocation = locationState();
      setCurrentLocation(nextLocation);
      setSettingsOpen(nextLocation === null);
    }
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent): void {
      if ((event.metaKey || event.ctrlKey) && event.key === ",") {
        event.preventDefault();
        setSettingsError(null);
        setSettingsOpen(true);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  async function addCollection(rawUrl: string, openAfter: boolean): Promise<boolean> {
    setSettingsBusy(true);
    setSettingsError(null);
    try {
      const manifestUrl = new URL(rawUrl, window.location.href).href;
      const response = await fetch(manifestUrl, { cache: "no-store" });
      if (!response.ok) throw new Error(`Could not load the collection (${response.status}).`);
      const value: unknown = await response.json();
      if (!isCollectionManifest(value)) {
        throw new Error("That URL does not contain a supported Watchcraft collection.");
      }
      const collection: SavedWebCollection = {
        collectionId: value.collection_id,
        title: value.title,
        url: manifestUrl,
      };
      setCollections((previous) => {
        const next = saveWebCollection(previous, collection);
        persistSavedCollections(next);
        return next;
      });
      if (openAfter) switchCollection(collection);
      return true;
    } catch (error) {
      setSettingsError(error instanceof Error ? error.message : "Could not add that collection.");
      return false;
    } finally {
      setSettingsBusy(false);
    }
  }

  function removeCollection(collection: SavedWebCollection): void {
    if (!window.confirm(`Remove “${collection.title}” from this browser?`)) return;
    const next = removeWebCollection(collections, collection.url);
    setCollections(next);
    persistSavedCollections(next);
    if (next.length === 0) clearLastCollection();
    if (collection.url === repository?.manifestLocation) {
      if (next[0]) {
        switchCollection(next[0]);
      } else {
        writeCollectionRoute(null, "replace");
        setCurrentLocation(null);
        setSettingsError(null);
        setSettingsOpen(true);
      }
    }
  }

  const settingsButton = (
    <div className="web-sidebar-actions">
      <a className="web-home-link" href="/">Watchcraft home</a>
      <button
        aria-label="Open settings"
        className="web-settings-button"
        onClick={() => {
          setSettingsError(null);
          setSettingsOpen(true);
        }}
        title="Settings"
        type="button"
      >
        <svg aria-hidden="true" viewBox="0 0 24 24">
          <path d="M12 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7Z" />
          <path d="M19.1 13.5a7.8 7.8 0 0 0 0-3l2-1.6-2-3.5-2.5 1a8.8 8.8 0 0 0-2.6-1.5L13.6 2h-4l-.4 2.9a8.8 8.8 0 0 0-2.6 1.5l-2.5-1-2 3.5 2 1.6a7.8 7.8 0 0 0 0 3l-2 1.6 2 3.5 2.5-1a8.8 8.8 0 0 0 2.6 1.5l.4 2.9h4l.4-2.9a8.8 8.8 0 0 0 2.6-1.5l2.5 1 2-3.5-2-1.6Z" />
        </svg>
      </button>
    </div>
  );

  return (
    <>
      {repository ? (
        <App
          key={repository.manifestLocation}
          onCollectionLoaded={rememberLoadedCollection}
          repository={repository}
          routeBasePath={import.meta.env.BASE_URL}
          sidebarFooter={settingsButton}
          videoRouteMode="query"
        />
      ) : (
        <EmptyWebApp onChoose={() => {
          setSettingsError(null);
          setSettingsOpen(true);
        }} />
      )}
      {settingsOpen ? (
        <WebCollectionSettings
          activeUrl={repository?.manifestLocation ?? null}
          busy={settingsBusy}
          collections={collections}
          error={settingsError}
          openFeaturedPicker={repository === null}
          onAddUrl={addCollection}
          onClose={() => setSettingsOpen(false)}
          onRemove={removeCollection}
          onSwitch={switchCollection}
        />
      ) : null}
    </>
  );
}
