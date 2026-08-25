import { invoke } from "@tauri-apps/api/core";
import { useEffect, useMemo, useRef, useState, type ReactElement } from "react";
import { DesktopApp } from "./DesktopApp";
import { isCatalogMetadataFolder } from "./desktopCatalogRepository";

const SMOKE_TIMEOUT_MS = 20_000;
const IDLE_PRELOAD_MS = 6_000;

export function PlaybackSmokeTest(): ReactElement {
  const [libraryRoot, setLibraryRoot] = useState<string | null>(null);
  const finishedRef = useRef(false);
  const playAttemptedRef = useRef(false);
  const expectsParentPrompt = useMemo(
    () => Boolean(libraryRoot && isCatalogMetadataFolder(libraryRoot)),
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
    if (!libraryRoot) return;
    const startedAt = performance.now();
    const deadline = window.setTimeout(() => {
      void finish(false, "Timed out before normal catalog playback advanced");
    }, SMOKE_TIMEOUT_MS);
    const poll = window.setInterval(() => {
      const parentPrompt = document.querySelector<HTMLElement>(
        '[data-watchcraft-library-parent-required="true"]',
      );
      if (expectsParentPrompt) {
        if (parentPrompt) {
          void finish(true, "Metadata-only folder selection requested its parent folder");
        }
        return;
      }
      if (parentPrompt) {
        void finish(false, "A valid library root incorrectly requested its parent folder");
        return;
      }
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
      if (video.currentTime >= 0.25) {
        void finish(true, `Normal catalog playback advanced to ${video.currentTime.toFixed(2)}s`);
        return;
      }
      if (!playAttemptedRef.current && performance.now() - startedAt >= IDLE_PRELOAD_MS) {
        playAttemptedRef.current = true;
        video.muted = true;
        void video.play().catch((error: unknown) => {
          void finish(false, `The single play attempt failed: ${String(error)}`);
        });
      }
    }, 100);
    return () => {
      window.clearInterval(poll);
      window.clearTimeout(deadline);
    };
  }, [expectsParentPrompt, libraryRoot]);

  if (!libraryRoot) {
    return <main className="playback-smoke">Preparing the normal Watchcraft catalog…</main>;
  }
  return <DesktopApp initialLibraryRoot={libraryRoot} />;
}
