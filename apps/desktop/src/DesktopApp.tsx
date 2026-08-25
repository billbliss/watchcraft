import { invoke } from "@tauri-apps/api/core";
import { useEffect, useMemo, useState, type ReactElement } from "react";
import { App } from "../../web/src/App";
import { DesktopCatalogRepository } from "./desktopCatalogRepository";

const LIBRARY_ROOT_KEY = "watchcraft.desktop.libraryRoot";

interface DesktopAppProps {
  initialLibraryRoot?: string | null;
}

type ScopeStatus = "checking" | "ready" | "needs-access";

export function DesktopApp({ initialLibraryRoot }: DesktopAppProps = {}): ReactElement {
  const [libraryRoot, setLibraryRoot] = useState<string | null>(() =>
    initialLibraryRoot ?? localStorage.getItem(LIBRARY_ROOT_KEY),
  );
  const [scopeStatus, setScopeStatus] = useState<ScopeStatus>(
    libraryRoot ? "checking" : "needs-access",
  );
  const [libraryError, setLibraryError] = useState<string | null>(null);
  const repository = useMemo(
    () => libraryRoot && scopeStatus === "ready"
      ? new DesktopCatalogRepository(libraryRoot)
      : null,
    [libraryRoot, scopeStatus],
  );

  useEffect(() => {
    if (!libraryRoot) {
      setScopeStatus("needs-access");
      return;
    }
    let current = true;
    setScopeStatus("checking");
    void invoke<boolean>("ensure_library_scope", { path: libraryRoot })
      .then((allowed) => {
        if (!current) return;
        setScopeStatus(allowed ? "ready" : "needs-access");
        setLibraryError(allowed ? null : "Watchcraft could not restore access to that folder.");
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
      const selected = await invoke<string | null>("choose_library_folder", {
        defaultPath: libraryRoot,
      });
      if (!selected) return;
      localStorage.setItem(LIBRARY_ROOT_KEY, selected);
      setLibraryRoot(selected);
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
                Choose a Watchcraft collection folder, such as Video Catalog, or
                the folder containing it and the local videos.
              </p>
              <button className="primary-action" onClick={() => void chooseLibrary()} type="button">
                {libraryRoot ? "Reconnect library folder" : "Choose library folder"}
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
      <App key={libraryRoot} repository={repository} />
    </div>
  );
}
