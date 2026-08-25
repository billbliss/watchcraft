import { convertFileSrc, invoke } from "@tauri-apps/api/core";
import { useEffect, useRef, useState, type ReactElement } from "react";

const SMOKE_TIMEOUT_MS = 15_000;

export function PlaybackSmokeTest(): ReactElement {
  const [source, setSource] = useState<string | null>(null);
  const finishedRef = useRef(false);

  async function finish(passed: boolean, detail: string): Promise<void> {
    if (finishedRef.current) return;
    finishedRef.current = true;
    await invoke("finish_playback_smoke", { passed, detail });
  }

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      void finish(false, "Timed out before playback advanced");
    }, SMOKE_TIMEOUT_MS);
    void invoke<string | null>("playback_smoke_video")
      .then((path) => {
        if (!path) return finish(false, "Native smoke-test video path is unavailable");
        setSource(convertFileSrc(path, "stream"));
      })
      .catch((error: unknown) => finish(false, String(error)));
    return () => window.clearTimeout(timeout);
  }, []);

  return (
    <main className="playback-smoke">
      <h1>Watchcraft playback smoke test</h1>
      <p>The test passes only after native embedded playback advances.</p>
      {source && (
        <video
          autoPlay
          muted
          onCanPlay={(event) => {
            void event.currentTarget.play().catch((error: unknown) => {
              void finish(false, `play() failed: ${String(error)}`);
            });
          }}
          onError={(event) => {
            const error = event.currentTarget.error;
            void finish(false, `Media error ${error?.code ?? "unknown"}: ${error?.message ?? ""}`);
          }}
          onTimeUpdate={(event) => {
            if (event.currentTarget.currentTime >= 0.25) {
              void finish(true, `Playback advanced to ${event.currentTarget.currentTime.toFixed(2)}s`);
            }
          }}
          playsInline
          preload="auto"
          src={source}
        />
      )}
    </main>
  );
}
