import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { spawnSync } from "node:child_process";

const repositoryRoot = resolve(import.meta.dirname, "..");
const temporaryRoot = mkdtempSync(join(tmpdir(), "watchcraft-playback-smoke-"));
const providedVideo = process.env.WATCHCRAFT_SMOKE_VIDEO?.trim();
const videoPath = providedVideo ? resolve(providedVideo) : join(temporaryRoot, "fixture.mp4");

function findLibraryRoot(path) {
  let candidate = resolve(path, "..");
  while (candidate !== resolve(candidate, "..")) {
    if (
      existsSync(join(candidate, "collection.json"))
      || existsSync(join(candidate, "Video Catalog", "collection.json"))
    ) return candidate;
    candidate = resolve(candidate, "..");
  }
  throw new Error(`Could not find a Watchcraft collection above ${path}`);
}

const libraryRoot = providedVideo ? findLibraryRoot(videoPath) : temporaryRoot;

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
    stdio: "pipe",
    ...options,
  });
  if (result.error) throw result.error;
  if (result.stdout) process.stdout.write(result.stdout);
  if (result.stderr) process.stderr.write(result.stderr);
  return result;
}

function runDesktopPhase(name, primeScope, selectedLibraryRoot = libraryRoot) {
  process.stdout.write(`\nWatchcraft playback smoke: ${name}\n`);
  const result = run(
    "npm",
    [
      "run",
      "dev:smoke",
      "--workspace",
      "@watchcraft/desktop",
    ],
    {
      env: {
        ...process.env,
        WATCHCRAFT_PLAYBACK_SMOKE_VIDEO: videoPath,
        WATCHCRAFT_PLAYBACK_SMOKE_LIBRARY: selectedLibraryRoot,
        WATCHCRAFT_PLAYBACK_SMOKE_PRIME: primeScope ? "1" : "0",
      },
    },
  );
  const output = `${result.stdout ?? ""}\n${result.stderr ?? ""}`;
  return {
    status: result.status ?? 1,
    passed: output.includes("WATCHCRAFT_PLAYBACK_SMOKE_PASS:")
      && !output.includes("WATCHCRAFT_PLAYBACK_SMOKE_FAIL:"),
  };
}

let exitCode = 1;
const appDataDirectory = smokeAppDataDirectory();

try {
  rmSync(appDataDirectory, { recursive: true, force: true });
  if (!providedVideo) {
    const ffmpegResult = run("ffmpeg", [
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
    if ((ffmpegResult.status ?? 1) !== 0) throw new Error("Could not generate the playback fixture");

    const catalogRoot = join(libraryRoot, "Video Catalog");
    mkdirSync(join(catalogRoot, "analysis"), { recursive: true });
    writeFileSync(join(catalogRoot, "collection.json"), JSON.stringify({
      schema_version: 2,
      collection_id: "playback-smoke",
      title: "Playback Smoke Test",
      topic_scope: "collection",
      root: {
        type: "group",
        group_id: "root",
        title: "Playback Smoke Test",
        children: [{ type: "video", item_id: "fixture" }],
      },
      topics: {},
      topic_families: {},
      items: {
        fixture: {
          item_id: "fixture",
          title: "Native playback fixture",
          media: [{ type: "local-file", relative_path: "fixture.mp4" }],
          transcript: {},
          analysis: { path: "analysis/fixture.analysis.json", schema_version: 2 },
          summary: "A generated video used by the native playback regression test.",
          locations: [],
          topic_ids: [],
          family_ids: [],
          topic_sections: {},
          chapter_count: 1,
        },
      },
      stats: { video_count: 1, topic_count: 0, topic_family_count: 0 },
      revision: 1,
      content_hash: "0".repeat(64),
    }));
    writeFileSync(join(catalogRoot, "analysis", "fixture.analysis.json"), JSON.stringify({
      schema_version: 2,
      video: "fixture.mp4",
      title: "Native playback fixture",
      summary: "A generated video used by the native playback regression test.",
      topics: [],
      sections: [{
        start: "00:00:00",
        end: "00:00:02",
        title: "Playback",
        concepts: [],
        description: "The generated fixture plays.",
      }],
    }));
  }

  const prime = runDesktopPhase("prime selected-folder access", true);
  if (prime.status !== 0 || !prime.passed) throw new Error("Initial native playback failed");

  const restore = runDesktopPhase("verify playback after restart", false);
  if (restore.status !== 0 || !restore.passed) throw new Error("Native playback failed after restart");

  const metadataFolder = join(libraryRoot, "Video Catalog");
  const metadataGuard = runDesktopPhase(
    "play when the metadata folder is selected",
    true,
    metadataFolder,
  );
  if (metadataGuard.status !== 0 || !metadataGuard.passed) {
    throw new Error("Native playback failed when the metadata folder was selected");
  }

  process.stdout.write("\nWatchcraft playback smoke passed.\n");
  exitCode = 0;
} catch (error) {
  console.error(`\nWatchcraft playback smoke failed: ${error instanceof Error ? error.message : String(error)}`);
} finally {
  rmSync(temporaryRoot, { recursive: true, force: true });
  rmSync(appDataDirectory, { recursive: true, force: true });
}

process.exit(exitCode);
