import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  renameSync,
  rmSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { basename, join } from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

if (process.platform !== "darwin") process.exit(0);

const dmgDirectory = fileURLToPath(new URL(
  "../apps/desktop/src-tauri/target/release/bundle/dmg/",
  import.meta.url,
));

if (!existsSync(dmgDirectory)) process.exit(0);

const diskImages = readdirSync(dmgDirectory)
  .filter((name) => name.endsWith(".dmg"))
  .map((name) => join(dmgDirectory, name));

for (const source of diskImages) {
  const workDirectory = mkdtempSync(join(tmpdir(), "watchcraft-dmg-"));
  const mountPoint = join(workDirectory, "mount");
  const readWriteImage = join(workDirectory, "read-write.dmg");
  const cleanedImage = `${source}.cleaned.dmg`;
  let mounted = false;

  try {
    mkdirSync(mountPoint);
    rmSync(cleanedImage, { force: true });
    execFileSync("hdiutil", [
      "convert",
      source,
      "-format",
      "UDRW",
      "-o",
      readWriteImage,
    ], { stdio: "ignore" });
    execFileSync("hdiutil", [
      "attach",
      readWriteImage,
      "-readwrite",
      "-noverify",
      "-noautoopen",
      "-nobrowse",
      "-mountpoint",
      mountPoint,
    ], { stdio: "ignore" });
    mounted = true;

    rmSync(join(mountPoint, ".VolumeIcon.icns"), { force: true });
    execFileSync("/usr/bin/SetFile", ["-a", "c", mountPoint], { stdio: "ignore" });
    execFileSync("sync", [], { stdio: "ignore" });
    execFileSync("hdiutil", ["detach", mountPoint], { stdio: "ignore" });
    mounted = false;

    execFileSync("hdiutil", [
      "convert",
      readWriteImage,
      "-format",
      "UDZO",
      "-imagekey",
      "zlib-level=9",
      "-o",
      cleanedImage,
    ], { stdio: "ignore" });
    renameSync(cleanedImage, source);
    console.log(`Removed the DMG volume icon from ${basename(source)}`);
  } finally {
    if (mounted) {
      try {
        execFileSync("hdiutil", ["detach", mountPoint, "-force"], { stdio: "ignore" });
      } catch {
        // Preserve the original packaging error; cleanup is best effort.
      }
    }
    rmSync(cleanedImage, { force: true });
    rmSync(workDirectory, { recursive: true, force: true });
  }
}
