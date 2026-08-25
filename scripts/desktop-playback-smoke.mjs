import { mkdtempSync, rmSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { spawnSync } from "node:child_process";

const repositoryRoot = resolve(import.meta.dirname, "..");
const temporaryRoot = mkdtempSync(join(tmpdir(), "watchcraft-playback-smoke-"));
const providedVideo = process.env.WATCHCRAFT_SMOKE_VIDEO?.trim();
const videoPath = providedVideo ? resolve(providedVideo) : join(temporaryRoot, "fixture.mp4");

function smokeAppDataDirectory() {
  if (process.platform === "darwin") {
    return join(homedir(), "Library", "Application Support", "app.watchcraft.reader.smoke");
  }
  if (process.platform === "win32") {
    return join(process.env.APPDATA ?? homedir(), "app.watchcraft.reader.smoke");
  }
  return join(process.env.XDG_DATA_HOME ?? join(homedir(), ".local", "share"), "app.watchcraft.reader.smoke");
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: repositoryRoot,
    encoding: "utf8",
    stdio: "inherit",
    ...options,
  });
  if (result.error) throw result.error;
  return result.status ?? 1;
}

function runDesktopPhase(name, primeScope) {
  process.stdout.write(`\nWatchcraft playback smoke: ${name}\n`);
  return run(
    "npm",
    [
      "run",
      "dev",
      "--workspace",
      "@watchcraft/desktop",
      "--",
      "--config",
      "src-tauri/tauri.smoke.conf.json",
    ],
    {
      env: {
        ...process.env,
        WATCHCRAFT_PLAYBACK_SMOKE_VIDEO: videoPath,
        WATCHCRAFT_PLAYBACK_SMOKE_PRIME: primeScope ? "1" : "0",
      },
    },
  );
}

let exitCode = 1;
const appDataDirectory = smokeAppDataDirectory();

try {
  rmSync(appDataDirectory, { recursive: true, force: true });
  if (!providedVideo) {
    const ffmpegStatus = run("ffmpeg", [
      "-hide_banner",
      "-loglevel",
      "error",
      "-f",
      "lavfi",
      "-i",
      "color=c=black:s=160x90:r=30:d=2",
      "-f",
      "lavfi",
      "-i",
      "anullsrc=channel_layout=stereo:sample_rate=44100",
      "-c:v",
      "libx264",
      "-pix_fmt",
      "yuv420p",
      "-c:a",
      "aac",
      "-shortest",
      "-movflags",
      "+faststart",
      "-y",
      videoPath,
    ]);
    if (ffmpegStatus !== 0) throw new Error("Could not generate the playback fixture");
  }

  const primeStatus = runDesktopPhase("prime selected-folder access", true);
  if (primeStatus !== 0) throw new Error("Initial native playback failed");

  const restoreStatus = runDesktopPhase("verify playback after restart", false);
  if (restoreStatus !== 0) throw new Error("Native playback failed after restart");

  process.stdout.write("\nWatchcraft playback smoke passed.\n");
  exitCode = 0;
} catch (error) {
  console.error(`\nWatchcraft playback smoke failed: ${error instanceof Error ? error.message : String(error)}`);
} finally {
  rmSync(temporaryRoot, { recursive: true, force: true });
  rmSync(appDataDirectory, { recursive: true, force: true });
}

process.exit(exitCode);
