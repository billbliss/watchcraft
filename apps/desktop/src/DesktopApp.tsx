import { open } from "@tauri-apps/plugin-dialog";
import { invoke } from "@tauri-apps/api/core";
import { useEffect, useMemo, useState, type ReactElement } from "react";
import { App } from "../../web/src/App";
import { DesktopCatalogRepository } from "./desktopCatalogRepository";

const LIBRARY_ROOT_KEY = "watchcraft.desktop.libraryRoot";

export function DesktopApp(): ReactElement {
  const [libraryRoot, setLibraryRoot] = useState<string | null>(() =>
    localStorage.getItem(LIBRARY_ROOT_KEY),
  );
  const [scopeStatus, setScopeStatus] = useState<"checking" | "ready" | "needs-access">(
    libraryRoot ? "checking" : "needs-access",
  );
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
        if (current) setScopeStatus(allowed ? "ready" : "needs-access");
      })
      .catch(() => {
        if (current) setScopeStatus("needs-access");
      });
    return () => {
      current = false;
    };
  }, [libraryRoot]);

  async function chooseLibrary(): Promise<void> {
    const selected = await open({
      directory: true,
      multiple: false,
      title: "Choose a Watchcraft library folder",
    });
    if (typeof selected !== "string") return;
    const allowed = await invoke<boolean>("ensure_library_scope", { path: selected });
    if (!allowed) return;
    localStorage.setItem(LIBRARY_ROOT_KEY, selected);
    setLibraryRoot(selected);
    setScopeStatus("ready");
  }

  if (!repository) {
    return (
      <main className="desktop-welcome">
        <section className="desktop-welcome-card">
          <span className="eyebrow">Watchcraft</span>
          <h1>Learn a craft by watching</h1>
          {scopeStatus === "checking" ? (
            <p>Restoring read-only access to your library…</p>
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
