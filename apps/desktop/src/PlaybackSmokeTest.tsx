import { invoke } from "@tauri-apps/api/core";
import { useEffect, useMemo, useRef, useState, type ReactElement } from "react";
import { App } from "../../web/src/App";
import { DesktopCatalogRepository } from "./desktopCatalogRepository";

const SMOKE_TIMEOUT_MS = 20_000;

export function PlaybackSmokeTest(): ReactElement {
  const [libraryRoot, setLibraryRoot] = useState<string | null>(null);
  const finishedRef = useRef(false);
  const repository = useMemo(
    () => libraryRoot ? new DesktopCatalogRepository(libraryRoot) : null,
    [libraryRoot],
  );

  async function finish(passed: boolean, detail: string): Promise<void> {
    if (finishedRef.current) return;
    finishedRef.current = true;
    await invoke("finish_playback_smoke", { passed, detail });
  }

  useEffect(() => {
    void invoke<string | null>("playback_smoke_library_root")
      .then((path) => {
        if (!path) return finish(false, "Native smoke-test library path is unavailable");
        setLibraryRoot(path);
      })
      .catch((error: unknown) => finish(false, String(error)));
  }, []);

  useEffect(() => {
    if (!repository) return;
    const deadline = window.setTimeout(() => {
      void finish(false, "Timed out before normal catalog playback advanced");
    }, SMOKE_TIMEOUT_MS);
    const poll = window.setInterval(() => {
      const errorBanner = document.querySelector<HTMLElement>(".media-error");
      const video = document.querySelector<HTMLVideoElement>(".player-shell video");
      if (errorBanner) {
        const error = video?.error;
        void finish(
          false,
          `Normal catalog player failed (media ${error?.code ?? "unknown"}: ${error?.message ?? "no detail"})`,
        );
        return;
      }
      if (!video) return;
      video.muted = true;
      if (video.currentTime >= 0.25) {
        void finish(true, `Normal catalog playback advanced to ${video.currentTime.toFixed(2)}s`);
        return;
      }
      if (video.paused) void video.play().catch(() => undefined);
    }, 100);
    return () => {
      window.clearInterval(poll);
      window.clearTimeout(deadline);
    };
  }, [repository]);

  if (!repository) {
    return <main className="playback-smoke">Preparing the normal Watchcraft catalog…</main>;
  }
  return <App repository={repository} />;
}
