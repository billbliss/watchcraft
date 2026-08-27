import { appendFileSync, readFileSync, writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const TAG_PATTERN = /^v(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)$/;
const BETA_CONFIG = JSON.parse(
  readFileSync(new URL("../apps/desktop/src-tauri/tauri.beta.conf.json", import.meta.url), "utf8"),
);

export function releaseMetadata({
  refType = "",
  refName = "",
  requestedChannel = "beta",
  baseVersion = "0.1.0",
} = {}) {
  if (refType === "tag") {
    const match = TAG_PATTERN.exec(refName);
    if (!match) {
      throw new Error(`Release tags must look like v1.2.3 or v1.2.3-beta.1; received ${refName}.`);
    }
    const version = match[1];
    return {
      channel: version.includes("-") ? "beta" : "release",
      prerelease: version.includes("-"),
      version,
    };
  }

  if (requestedChannel !== "beta" && requestedChannel !== "release") {
    throw new Error(`Unknown build channel: ${requestedChannel}.`);
  }
  return {
    channel: requestedChannel,
    prerelease: requestedChannel === "beta",
    version: baseVersion,
  };
}

export function tauriChannelConfig(metadata) {
  return metadata.channel === "beta"
    ? { ...BETA_CONFIG, version: metadata.version }
    : { version: metadata.version };
}

function run() {
  const outputPath = process.argv[2];
  if (!outputPath) {
    throw new Error("Usage: node scripts/release-metadata.mjs <tauri-config-output-path>");
  }
  const rootPackage = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"));
  const metadata = releaseMetadata({
    refType: process.env.GITHUB_REF_TYPE,
    refName: process.env.GITHUB_REF_NAME,
    requestedChannel: process.env.WATCHCRAFT_CHANNEL || "beta",
    baseVersion: rootPackage.version,
  });
  writeFileSync(outputPath, `${JSON.stringify(tauriChannelConfig(metadata), null, 2)}\n`);

  if (process.env.GITHUB_OUTPUT) {
    appendFileSync(
      process.env.GITHUB_OUTPUT,
      `channel=${metadata.channel}\nprerelease=${metadata.prerelease}\nversion=${metadata.version}\n`,
    );
  }
  process.stdout.write(
    `Prepared Watchcraft ${metadata.channel} ${metadata.version} configuration at ${outputPath}.\n`,
  );
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  run();
}
