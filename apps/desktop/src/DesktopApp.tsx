import { invoke } from "@tauri-apps/api/core";
import { useEffect, useMemo, useState, type ReactElement } from "react";
import { App } from "../../web/src/App";
import {
  DesktopCatalogRepository,
  type DesktopLibraryLocation,
} from "./desktopCatalogRepository";

const LIBRARY_ROOT_KEY = "watchcraft.desktop.libraryRoot";

interface DesktopAppProps {
  initialLibraryRoot?: string | null;
}

type ScopeStatus = "checking" | "ready" | "needs-access";

let restoreLibraryRequest: Promise<DesktopLibraryLocation | null> | null = null;

function restoreLibrary(legacyRoot: string | null): Promise<DesktopLibraryLocation | null> {
  restoreLibraryRequest ??= invoke<DesktopLibraryLocation | null>("load_current_collection")
    .then((location) => {
      if (location || !legacyRoot) return location;
      return invoke<DesktopLibraryLocation | null>("ensure_library_scope", { path: legacyRoot });
    });
  return restoreLibraryRequest;
}

export function DesktopApp({ initialLibraryRoot }: DesktopAppProps = {}): ReactElement {
  const [libraryRoot, setLibraryRoot] = useState<string | null>(() =>
    initialLibraryRoot ?? localStorage.getItem(LIBRARY_ROOT_KEY),
  );
  const [scopeStatus, setScopeStatus] = useState<ScopeStatus>("checking");
  const [libraryLocation, setLibraryLocation] = useState<DesktopLibraryLocation | null>(null);
  const [libraryError, setLibraryError] = useState<string | null>(null);
  const repository = useMemo(
    () => libraryLocation && scopeStatus === "ready"
      ? new DesktopCatalogRepository(libraryLocation)
      : null,
    [libraryLocation, scopeStatus],
  );

  useEffect(() => {
    let current = true;
    setScopeStatus("checking");
    void restoreLibrary(libraryRoot)
      .then((location) => {
        if (!current) return;
        setLibraryLocation(location);
        if (location) {
          setLibraryRoot(location.selectedRoot);
          localStorage.removeItem(LIBRARY_ROOT_KEY);
        }
        setScopeStatus(location ? "ready" : "needs-access");
        setLibraryError(null);
      })
      .catch((error: unknown) => {
        if (!current) return;
        setScopeStatus("needs-access");
        setLibraryError(error instanceof Error ? error.message : String(error));
      });
    return () => {
      current = false;
    };
  }, [libraryRoot]);

  async function chooseLibrary(): Promise<void> {
    setLibraryError(null);
    try {
      const location = await invoke<DesktopLibraryLocation | null>("choose_library_folder", {
        defaultPath: libraryRoot,
      });
      if (!location) return;
      localStorage.removeItem(LIBRARY_ROOT_KEY);
      setLibraryRoot(location.selectedRoot);
      setLibraryLocation(location);
      setScopeStatus("ready");
    } catch (error: unknown) {
      setScopeStatus("needs-access");
      setLibraryError(error instanceof Error ? error.message : String(error));
    }
  }

  if (!repository) {
    return (
      <main className="desktop-welcome">
        <section className="desktop-welcome-card">
          <span className="eyebrow">Watchcraft</span>
          <h1>Learn a craft by watching</h1>
          {libraryError ? <p className="desktop-library-error" role="alert">{libraryError}</p> : null}
          {scopeStatus === "checking" ? (
            <p>Restoring read-only access to your library…</p>
          ) : (
            <>
              <p>
                Choose the folder containing a Watchcraft collection, or choose
                the collection folder itself.
              </p>
              <button className="primary-action" onClick={() => void chooseLibrary()} type="button">
                {libraryRoot ? "Connect library folder" : "Choose library folder"}
              </button>
            </>
          )}
        </section>
      </main>
    );
  }

  return (
    <div className="desktop-root">
      <button
        className="desktop-change-library"
        onClick={() => void chooseLibrary()}
        title={libraryRoot ?? undefined}
        type="button"
      >
        Change library
      </button>
      <App key={libraryLocation?.manifestPath} repository={repository} />
    </div>
  );
}
