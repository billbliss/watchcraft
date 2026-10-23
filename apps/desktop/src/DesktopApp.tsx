import { isYouTubeSource, submissionUrl } from "@watchcraft/catalog-core";
import { getVersion } from "@tauri-apps/api/app";
import { invoke } from "@tauri-apps/api/core";
import { getCurrent, onOpenUrl } from "@tauri-apps/plugin-deep-link";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactElement } from "react";
import { App } from "../../web/src/App";
import { CollectionSettings, type RegisteredCollection } from "./CollectionSettings";
import { CollectionSetup, needsCollectionSetup } from "./CollectionSetup";
import {
  DesktopCatalogRepository,
  type DesktopLibraryLocation,
} from "./desktopCatalogRepository";
import { collectionUrlFromDeepLink } from "./deepLink";
import { singleFlight } from "./singleFlight";
import { DiagnosticsDialog } from "../../web/src/DiagnosticsDialog";
import { installBrowserDiagnostics, type DiagnosticEvent } from "../../web/src/diagnostics";
import { DesktopDiagnosticsService } from "./desktopDiagnostics";

type ScopeStatus = "checking" | "ready" | "needs-access";

const restoreLibrary = singleFlight(
  (): Promise<DesktopLibraryLocation | null> =>
    invoke<DesktopLibraryLocation | null>("load_current_collection"),
);

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function SettingsIcon(): ReactElement {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <path d="M12 8.4a3.6 3.6 0 1 0 0 7.2 3.6 3.6 0 0 0 0-7.2Z" />
      <path d="m19.2 13.1 1.5 1.2-1.8 3.1-1.8-.7c-.5.4-1 .7-1.6.9l-.3 1.9h-3.6l-.3-1.9c-.6-.2-1.1-.5-1.6-.9l-1.8.7-1.8-3.1 1.5-1.2a7 7 0 0 1 0-1.9L6.1 10l1.8-3.1 1.8.7c.5-.4 1-.7 1.6-.9l.3-1.9h3.6l.3 1.9c.6.2 1.1.5 1.6.9l1.8-.7 1.8 3.1-1.5 1.2a7 7 0 0 1 0 1.9Z" />
    </svg>
  );
}

export function DesktopApp(): ReactElement {
  const [diagnostics] = useState(() => new DesktopDiagnosticsService());
  const [diagnosticsEnabled, setDiagnosticsEnabled] = useState(false);
  const [diagnosticsOpen, setDiagnosticsOpen] = useState(false);
  const [appVersion, setAppVersion] = useState<string | null>(null);
  const [libraryRoot, setLibraryRoot] = useState<string | null>(null);
  const [scopeStatus, setScopeStatus] = useState<ScopeStatus>("checking");
  const [libraryLocation, setLibraryLocation] = useState<DesktopLibraryLocation | null>(null);
  const [youtubeBridgeBaseUrl, setYoutubeBridgeBaseUrl] = useState<string | null>(null);
  const [videoStreamBaseUrl, setVideoStreamBaseUrl] = useState<string | null | undefined>(undefined);
  const [collections, setCollections] = useState<RegisteredCollection[]>([]);
  const [libraryError, setLibraryError] = useState<string | null>(null);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [setup, setSetup] = useState<{ collection: RegisteredCollection; openAfter: boolean; initialStep?: "intro" | "folder" } | null>(null);
  const [pendingDeepLinkUrl, setPendingDeepLinkUrl] = useState<string | null>(null);
  const processingDeepLink = useRef<string | null>(null);
  const recordDiagnostic = useCallback((event: DiagnosticEvent): void => {
    diagnostics.record(event);
  }, [diagnostics]);
  const repository = useMemo(
    () => libraryLocation
      && youtubeBridgeBaseUrl
      && videoStreamBaseUrl !== undefined
      && scopeStatus === "ready"
      && setup?.collection.collectionId !== libraryLocation.collectionId
      ? new DesktopCatalogRepository(
          libraryLocation,
          youtubeBridgeBaseUrl,
          videoStreamBaseUrl,
        )
      : null,
    [libraryLocation, scopeStatus, videoStreamBaseUrl, youtubeBridgeBaseUrl, setup?.collection.collectionId],
  );

  const refreshCollections = useCallback(async (): Promise<RegisteredCollection[]> => {
    const registered = await invoke<RegisteredCollection[]>("list_registered_collections");
    setCollections(registered);
    return registered;
  }, []);

  const openLocation = useCallback((location: DesktopLibraryLocation): void => {
    setLibraryLocation(location);
    if (location.selectedRoot) setLibraryRoot(location.selectedRoot);
    setScopeStatus("ready");
    setLibraryError(null);
  }, []);

  useEffect(() => {
    void getVersion().then(setAppVersion).catch(() => setAppVersion(null));
  }, []);

  useEffect(() => {
    let active = true;
    let uninstall: (() => void) | undefined;
    void diagnostics.snapshot().then((snapshot) => {
      if (!active) return;
      setDiagnosticsEnabled(snapshot.enabled);
      if (snapshot.enabled) uninstall = installBrowserDiagnostics(diagnostics);
    }).catch(() => undefined);
    return () => {
      active = false;
      uninstall?.();
    };
  }, [diagnostics]);

  useEffect(() => {
    let current = true;
    setScopeStatus("checking");
    void Promise.all([
      restoreLibrary(),
      invoke<string>("youtube_bridge_base_url"),
      invoke<string | null>("video_stream_base_url"),
    ])
      .then(async ([location, bridgeBaseUrl, streamBaseUrl]) => {
        if (!current) return;
        setYoutubeBridgeBaseUrl(bridgeBaseUrl);
        setVideoStreamBaseUrl(streamBaseUrl);
        const registered = await refreshCollections();
        if (!current) return;
        const pending = registered.find(collection => collection.active && needsCollectionSetup(collection));
        if (pending) setSetup({ collection: pending, openAfter: true });
        if (location) openLocation(location);
        else setScopeStatus("needs-access");
      })
      .catch((error: unknown) => {
        if (!current) return;
        setScopeStatus("needs-access");
        setLibraryError(errorMessage(error));
      });
    return () => {
      current = false;
    };
  }, [openLocation, refreshCollections]);

  useEffect(() => {
    function openSettingsShortcut(event: KeyboardEvent): void {
      if ((event.metaKey || event.ctrlKey) && event.key === ",") {
        event.preventDefault();
        setSettingsError(null);
        setSettingsOpen(true);
      }
    }
    window.addEventListener("keydown", openSettingsShortcut);
    return () => window.removeEventListener("keydown", openSettingsShortcut);
  }, []);

  useEffect(() => {
    let disposed = false;
    let stopListening: (() => void) | undefined;

    function receiveDeepLinks(urls: string[]): void {
      const collectionUrl = urls
        .map(collectionUrlFromDeepLink)
        .find((url): url is string => Boolean(url));
      if (collectionUrl) {
        setPendingDeepLinkUrl(collectionUrl);
      } else if (urls.length > 0) {
        setSettingsError("That Watchcraft link is invalid or does not contain a secure collection URL.");
        setSettingsOpen(true);
      }
    }

    void onOpenUrl(receiveDeepLinks)
      .then((unlisten) => {
        if (disposed) unlisten();
        else stopListening = unlisten;
      })
      .catch((error: unknown) => {
        if (!disposed) console.error("Could not listen for Watchcraft links", error);
      });

    void getCurrent()
      .then((urls) => {
        if (!disposed && urls) receiveDeepLinks(urls);
      })
      .catch((error: unknown) => {
        if (!disposed) console.error("Could not read the opening Watchcraft link", error);
      });

    return () => {
      disposed = true;
      stopListening?.();
    };
  }, []);

  function defaultFolder(): string | null {
    return libraryRoot
      ?? collections.find(
        (collection) => !collection.archived && collection.sourceType === "folder",
      )?.sourceLabel
      ?? null;
  }

  async function addFolder(openAfter: boolean): Promise<boolean> {
    setBusy(true);
    setSettingsError(null);
    try {
      const location = await invoke<DesktopLibraryLocation | null>("choose_collection_folder", {
        defaultPath: defaultFolder(),
        openAfter,
      });
      if (!location) return false;
      const registered = await refreshCollections();
      const installed = registered.find(collection => collection.collectionId === location.collectionId);
      if (installed?.active) openLocation(location);
      if (installed && needsCollectionSetup(installed)) beginSetup(installed, openAfter);
      else if (openAfter) setSettingsOpen(false);
      return true;
    } catch (error: unknown) {
      const message = errorMessage(error);
      setSettingsError(message);
      if (!repository) setLibraryError(message);
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function suggestCollection(source?: string): Promise<boolean> {
    try { await invoke("open_external_url", { url: submissionUrl(source) }); return true; }
    catch (error) { setSettingsError(errorMessage(error)); setSettingsOpen(true); return false; }
  }

  async function addUrl(url: string, openAfter: boolean): Promise<boolean> {
    if (isYouTubeSource(url)) {
      setSettingsError(null);
      return false;
    }
    setBusy(true);
    setSettingsError(null);
    try {
      const location = await invoke<DesktopLibraryLocation | null>("install_collection_url", {
        url,
        openAfter,
      });
      if (!location) throw new Error("The collection was installed but could not be opened.");
      const registered = await refreshCollections();
      const installed = registered.find(
        (collection) => collection.collectionId === location.collectionId,
      );
      if (installed?.active) openLocation(location);
      if (installed && needsCollectionSetup(installed)) beginSetup(installed, openAfter);
      else if (openAfter) setSettingsOpen(false);
      return true;
    } catch (error: unknown) {
      const message = errorMessage(error);
      setSettingsError(message);
      if (!repository) setLibraryError(message);
      return false;
    } finally {
      setBusy(false);
    }
  }

  function beginSetup(collection: RegisteredCollection, openAfter: boolean, initialStep: "intro" | "folder" = "intro"): void {
    setSettingsError(null);
    setSettingsOpen(false);
    setSetup({ collection, openAfter, initialStep });
  }

  async function chooseMediaFolder(collection: RegisteredCollection): Promise<RegisteredCollection | null> {
    const location = await invoke<DesktopLibraryLocation | null>(
      "choose_collection_media_folder",
      { collectionId: collection.collectionId, defaultPath: defaultFolder() },
    );
    if (!location) return null;
    if (collection.active) openLocation(location);
    const registered = await refreshCollections();
    const updated = registered.find(candidate => candidate.collectionId === collection.collectionId);
    if (!updated) throw new Error("The installed collection is no longer available.");
    setSetup(previous => previous?.collection.collectionId === updated.collectionId ? { ...previous, collection: updated } : previous);
    return updated;
  }

  async function locateCollectionMedia(collection: RegisteredCollection): Promise<void> {
    beginSetup(collection, needsCollectionSetup(collection) || collection.active,
      needsCollectionSetup(collection) ? "intro" : "folder");
  }

  async function finishSetup(): Promise<void> {
    if (!setup) return;
    const location = await invoke<DesktopLibraryLocation>("complete_collection_setup", {
      collectionId: setup.collection.collectionId, activate: setup.openAfter,
    });
    const registered = await refreshCollections();
    if (setup.openAfter || registered.some(collection => collection.collectionId === location.collectionId && collection.active)) openLocation(location);
    setSettingsOpen(!setup.openAfter);
    setSetup(null);
  }

  async function updateCollection(collection: RegisteredCollection): Promise<void> {
    setBusy(true);
    setSettingsError(null);
    try {
      const location = await invoke<DesktopLibraryLocation | null>("install_collection_url", {
        url: collection.sourceLabel,
        openAfter: collection.active,
      });
      if (!location) throw new Error("The collection update could not be opened.");
      const registered = await refreshCollections();
      const updated = registered.find(
        (candidate) => candidate.collectionId === collection.collectionId,
      );
      if (updated?.active) openLocation(location);
      if (updated && needsCollectionSetup(updated)) beginSetup(updated, collection.active);
    } catch (error: unknown) {
      setSettingsError(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  async function switchCollection(collection: RegisteredCollection): Promise<void> {
    if (needsCollectionSetup(collection)) { beginSetup(collection, true); return; }
    setBusy(true);
    setSettingsError(null);
    try {
      const location = await invoke<DesktopLibraryLocation>("activate_registered_collection", {
        collectionId: collection.collectionId,
      });
      openLocation(location);
      await refreshCollections();
      setSettingsOpen(false);
    } catch (error: unknown) {
      setSettingsError(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  async function removeCollection(collection: RegisteredCollection): Promise<void> {
    const removesManagedMedia = collection.mediaModes.includes("managed-local");
    const confirmed = window.confirm(
      removesManagedMedia
        ? `Remove “${collection.title}” from Watchcraft?\n\nMedia managed by Watchcraft will be deleted. User-owned files will not be touched.`
        : `Remove “${collection.title}” from Watchcraft?\n\nIts original collection files and videos will not be deleted.`,
    );
    if (!confirmed) return;
    setBusy(true);
    setSettingsError(null);
    try {
      const location = await invoke<DesktopLibraryLocation>("remove_registered_collection", {
        collectionId: collection.collectionId,
      });
      openLocation(location);
      await refreshCollections();
    } catch (error: unknown) {
      setSettingsError(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  async function setCollectionArchived(
    collection: RegisteredCollection,
    archived: boolean,
  ): Promise<void> {
    setBusy(true);
    setSettingsError(null);
    try {
      const location = await invoke<DesktopLibraryLocation>(
        "set_registered_collection_archived",
        { collectionId: collection.collectionId, archived },
      );
      openLocation(location);
      await refreshCollections();
    } catch (error: unknown) {
      setSettingsError(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (
      !pendingDeepLinkUrl
      || scopeStatus === "checking"
      || !youtubeBridgeBaseUrl
      || setup !== null
      || busy
      || processingDeepLink.current === pendingDeepLinkUrl
    ) {
      return;
    }
    const requestedUrl = pendingDeepLinkUrl;
    processingDeepLink.current = requestedUrl;
    setPendingDeepLinkUrl(null);
    const confirmed = window.confirm(
      `Add this collection to Watchcraft?\n\n${requestedUrl}`,
    );
    if (!confirmed) {
      processingDeepLink.current = null;
      return;
    }
    setSettingsError(null);
    setSettingsOpen(true);
    void addUrl(requestedUrl, true).finally(() => {
      processingDeepLink.current = null;
    });
  }, [pendingDeepLinkUrl, scopeStatus, youtubeBridgeBaseUrl, setup, busy]);

  const setupDialog = setup ? (
    <CollectionSetup
      key={setup.collection.collectionId}
      collection={setup.collection}
      openAfter={setup.openAfter}
      initialStep={setup.initialStep}
      onChooseFolder={() => chooseMediaFolder(setup.collection)}
      onFinish={finishSetup}
      onCancel={() => { setSetup(null); setSettingsOpen(true); }}
    />
  ) : null;

  const settings = settingsOpen && !diagnosticsOpen && !setup ? (
    <CollectionSettings
      onSuggestCollection={(source) => void suggestCollection(source)}
      appVersion={appVersion}
      busy={busy}
      collections={collections}
      error={settingsError}
      onAddFolder={addFolder}
      onAddUrl={addUrl}
      onClose={() => setSettingsOpen(false)}
      onLocateMedia={locateCollectionMedia}
      onOpenDiagnostics={diagnosticsEnabled ? () => setDiagnosticsOpen(true) : undefined}
      onRemove={removeCollection}
      onSetArchived={setCollectionArchived}
      onSwitch={switchCollection}
      onUpdate={updateCollection}
    />
  ) : null;

  if (!repository) {
    return (
      <>
        <main className="desktop-welcome">
          <section className="desktop-welcome-card">
            <span className="eyebrow">Watchcraft</span>
            <h1>Learn a craft by watching</h1>
            {libraryError ? <p className="desktop-library-error" role="alert">{libraryError}</p> : null}
            {scopeStatus === "checking" ? (
              <p>Restoring your collections…</p>
            ) : (
              <>
                <p>Add a Watchcraft collection from a folder on this computer or from a URL.</p>
                <div className="welcome-actions">
                  <button className="primary-action" onClick={() => void addFolder(true)} type="button">Choose collection folder</button>
                  <button onClick={() => { setSettingsError(null); setSettingsOpen(true); }} type="button">Add from URL…</button>
                </div>
              </>
            )}
          </section>
        </main>
        {settings}
        {setupDialog}
        {diagnosticsOpen ? <DiagnosticsDialog onClose={() => setDiagnosticsOpen(false)} service={diagnostics} /> : null}
      </>
    );
  }

  return (
    <div className="desktop-root">
      <App
        key={libraryLocation?.manifestPath}
        onDiagnosticEvent={diagnosticsEnabled ? recordDiagnostic : undefined}
        onOpenDiagnostics={diagnosticsEnabled ? () => setDiagnosticsOpen(true) : undefined}
        onAddToWatchcraft={() => void suggestCollection()}
        onOpenSettings={() => {
          setSettingsError(null);
          setSettingsOpen(true);
        }}
        repository={repository}
        sidebarFooter={(
          <button
            aria-label="Open Watchcraft settings"
            className="desktop-settings-button"
            onClick={() => { setSettingsError(null); setSettingsOpen(true); }}
            title="Settings"
            type="button"
          >
            <SettingsIcon />
            <span>Settings</span>
          </button>
        )}
      />
      {settings}
      {setupDialog}
      {diagnosticsOpen ? <DiagnosticsDialog onClose={() => setDiagnosticsOpen(false)} service={diagnostics} /> : null}
    </div>
  );
}
