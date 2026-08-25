import { invoke } from "@tauri-apps/api/core";
import { useEffect, useMemo, useState, type ReactElement } from "react";
import { App } from "../../web/src/App";
import {
  DesktopCatalogRepository,
  isCatalogMetadataFolder,
  parentLocalPath,
} from "./desktopCatalogRepository";

const LIBRARY_ROOT_KEY = "watchcraft.desktop.libraryRoot";

interface DesktopAppProps {
  initialLibraryRoot?: string | null;
}

type ScopeStatus = "checking" | "ready" | "needs-access" | "needs-parent";

export function DesktopApp({ initialLibraryRoot }: DesktopAppProps = {}): ReactElement {
  const [libraryRoot, setLibraryRoot] = useState<string | null>(() =>
    initialLibraryRoot ?? localStorage.getItem(LIBRARY_ROOT_KEY),
  );
  const [scopeStatus, setScopeStatus] = useState<ScopeStatus>(
    libraryRoot
      ? isCatalogMetadataFolder(libraryRoot) ? "needs-parent" : "checking"
      : "needs-access",
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
    if (isCatalogMetadataFolder(libraryRoot)) {
      setScopeStatus("needs-parent");
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
    const needsParent = Boolean(libraryRoot && isCatalogMetadataFolder(libraryRoot));
    setLibraryError(null);
    try {
      const selected = await invoke<string | null>("choose_library_folder", {
        defaultPath: libraryRoot
          ? needsParent ? parentLocalPath(libraryRoot) : libraryRoot
          : null,
        needsParent,
      });
      if (!selected) return;
      localStorage.setItem(LIBRARY_ROOT_KEY, selected);
      setLibraryRoot(selected);
      setScopeStatus(isCatalogMetadataFolder(selected) ? "needs-parent" : "ready");
    } catch (error: unknown) {
      setScopeStatus("needs-access");
      setLibraryError(error instanceof Error ? error.message : String(error));
    }
  }

  if (!repository) {
    return (
      <main
        className="desktop-welcome"
        data-watchcraft-library-parent-required={scopeStatus === "needs-parent" || undefined}
      >
        <section className="desktop-welcome-card">
          <span className="eyebrow">Watchcraft</span>
          <h1>Learn a craft by watching</h1>
          {libraryError ? <p className="desktop-library-error" role="alert">{libraryError}</p> : null}
          {scopeStatus === "checking" ? (
            <p>Restoring read-only access to your library…</p>
          ) : scopeStatus === "needs-parent" ? (
            <>
              <p>
                <strong>Video Catalog</strong> contains the collection metadata, but
                the videos are beside it. Choose its parent folder instead.
              </p>
              <button className="primary-action" onClick={() => void chooseLibrary()} type="button">
                Choose parent folder
              </button>
            </>
          ) : (
            <>
              <p>
                Choose the root folder containing a Watchcraft collection and its
                local videos. Watchcraft receives read-only access only to the
                folder you select.
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
