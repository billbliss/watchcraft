import { open } from "@tauri-apps/plugin-dialog";
import { useMemo, useState, type ReactElement } from "react";
import { App } from "../../web/src/App";
import { DesktopCatalogRepository } from "./desktopCatalogRepository";

const LIBRARY_ROOT_KEY = "watchcraft.desktop.libraryRoot";

export function DesktopApp(): ReactElement {
  const [libraryRoot, setLibraryRoot] = useState<string | null>(() =>
    localStorage.getItem(LIBRARY_ROOT_KEY),
  );
  const repository = useMemo(
    () => libraryRoot ? new DesktopCatalogRepository(libraryRoot) : null,
    [libraryRoot],
  );

  async function chooseLibrary(): Promise<void> {
    const selected = await open({
      directory: true,
      multiple: false,
      title: "Choose a Watchcraft library folder",
    });
    if (typeof selected !== "string") return;
    localStorage.setItem(LIBRARY_ROOT_KEY, selected);
    setLibraryRoot(selected);
  }

  if (!repository) {
    return (
      <main className="desktop-welcome">
        <section className="desktop-welcome-card">
          <span className="eyebrow">Watchcraft</span>
          <h1>Learn a craft by watching</h1>
          <p>
            Choose the root folder containing a Watchcraft collection and its
            local videos. Watchcraft receives read-only access only to the
            folder you select.
          </p>
          <button className="primary-action" onClick={() => void chooseLibrary()} type="button">
            Choose library folder
          </button>
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
