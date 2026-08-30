import { appendFileSync, readFileSync, writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const TAG_PATTERN = /^v(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)$/;
const BETA_CONFIG = JSON.parse(
  readFileSync(new URL("../apps/desktop/src-tauri/tauri.beta.conf.json", import.meta.url), "utf8"),
);
const LEGACY_BETA_PACKAGE = "watchcraft-beta (<= 0.2.0-beta.2)";

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

export function tauriChannelConfig(metadata, { developerIdSigning = false } = {}) {
  const macOsBundle = developerIdSigning
    ? {
        macOS: {
          signingIdentity: null,
        },
      }
    : {};
  return metadata.channel === "beta"
    ? {
        ...BETA_CONFIG,
        version: metadata.version,
        bundle: {
          ...BETA_CONFIG.bundle,
          ...macOsBundle,
        },
      }
    : {
        version: metadata.version,
        bundle: {
          ...macOsBundle,
          linux: {
            deb: {
              conflicts: [LEGACY_BETA_PACKAGE],
              replaces: [LEGACY_BETA_PACKAGE],
            },
          },
        },
      };
}

export function linuxPackageIdentity(channel) {
  if (channel === "beta") {
    return {
      packageName: "watchcraft-beta",
      binaryName: "watchcraft-beta",
      desktopName: "Watchcraft Beta.desktop",
      metainfoName: "app.watchcraft.reader.beta.metainfo.xml",
    };
  }
  if (channel === "release") {
    return {
      packageName: "watchcraft",
      binaryName: "watchcraft",
      desktopName: "Watchcraft.desktop",
      metainfoName: "app.watchcraft.reader.metainfo.xml",
    };
  }
  throw new Error(`Unknown build channel: ${channel || "unknown"}.`);
}

export function installerBundles({ runnerOs, channel }) {
  if (runnerOs === "Windows") {
    return channel === "beta" ? "nsis" : "nsis,msi";
  }
  if (runnerOs === "Linux") return "deb,appimage";
  if (runnerOs === "macOS") return "dmg";
  throw new Error(`Unsupported runner operating system: ${runnerOs || "unknown"}.`);
}

export function deepLinkSchemes(channel) {
  if (channel === "beta") return ["watchcraft", "watchcraft-beta"];
  if (channel === "release") return ["watchcraft"];
  throw new Error(`Unknown build channel: ${channel || "unknown"}.`);
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
  writeFileSync(
    outputPath,
    `${JSON.stringify(tauriChannelConfig(metadata, {
      developerIdSigning: process.env.WATCHCRAFT_DEVELOPER_ID_SIGNING === "true",
    }), null, 2)}\n`,
  );

  if (process.env.GITHUB_OUTPUT) {
    const bundles = installerBundles({
      runnerOs: process.env.RUNNER_OS,
      channel: metadata.channel,
    });
    const linuxIdentity = linuxPackageIdentity(metadata.channel);
    appendFileSync(
      process.env.GITHUB_OUTPUT,
      `channel=${metadata.channel}\nprerelease=${metadata.prerelease}\nversion=${metadata.version}\nbundles=${bundles}\nschemes=${deepLinkSchemes(metadata.channel).join(",")}\npackage_name=${linuxIdentity.packageName}\nbinary_name=${linuxIdentity.binaryName}\ndesktop_name=${linuxIdentity.desktopName}\nmetainfo_name=${linuxIdentity.metainfoName}\n`,
    );
  }
  process.stdout.write(
    `Prepared Watchcraft ${metadata.channel} ${metadata.version} configuration at ${outputPath}.\n`,
  );
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  run();
}
