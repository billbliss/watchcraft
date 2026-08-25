import { invoke } from "@tauri-apps/api/core";
import { useEffect, useRef, useState, type ReactElement } from "react";
import { DesktopApp } from "./DesktopApp";

const SMOKE_TIMEOUT_MS = 20_000;
const IDLE_PRELOAD_MS = 6_000;

export function PlaybackSmokeTest(): ReactElement {
  const [libraryRoot, setLibraryRoot] = useState<string | null>(null);
  const finishedRef = useRef(false);
  const playAttemptedRef = useRef(false);
  const previewFrameObservedRef = useRef(false);

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
      if (
        !playAttemptedRef.current
        && video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA
        && video.videoWidth > 0
      ) {
        previewFrameObservedRef.current = true;
      }
      if (video.currentTime >= 0.25) {
        void finish(true, `Normal catalog playback advanced to ${video.currentTime.toFixed(2)}s`);
        return;
      }
      if (!playAttemptedRef.current && performance.now() - startedAt >= IDLE_PRELOAD_MS) {
        if (!previewFrameObservedRef.current) {
          void finish(false, "No preview frame decoded before playback");
          return;
        }
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
  }, [libraryRoot]);

  if (!libraryRoot) {
    return <main className="playback-smoke">Preparing the normal Watchcraft catalog…</main>;
  }
  return <DesktopApp initialLibraryRoot={libraryRoot} />;
}
