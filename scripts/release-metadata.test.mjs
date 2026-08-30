import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  deepLinkSchemes,
  installerBundles,
  linuxPackageIdentity,
  releaseMetadata,
  tauriChannelConfig,
} from "./release-metadata.mjs";

const tauriConfig = JSON.parse(
  readFileSync(new URL("../apps/desktop/src-tauri/tauri.conf.json", import.meta.url), "utf8"),
);
const desktopCapabilities = JSON.parse(
  readFileSync(
    new URL("../apps/desktop/src-tauri/capabilities/default.json", import.meta.url),
    "utf8",
  ),
);
const betaTauriConfig = JSON.parse(
  readFileSync(new URL("../apps/desktop/src-tauri/tauri.beta.conf.json", import.meta.url), "utf8"),
);

test("prerelease tags produce beta builds", () => {
  assert.deepEqual(releaseMetadata({ refType: "tag", refName: "v0.2.0-beta.3" }), {
    channel: "beta",
    prerelease: true,
    version: "0.2.0-beta.3",
  });
});

test("stable tags produce release builds", () => {
  assert.deepEqual(releaseMetadata({ refType: "tag", refName: "v1.0.0" }), {
    channel: "release",
    prerelease: false,
    version: "1.0.0",
  });
});

test("manual builds default to the requested channel and package version", () => {
  assert.deepEqual(
    releaseMetadata({ requestedChannel: "beta", baseVersion: "0.1.0" }),
    { channel: "beta", prerelease: true, version: "0.1.0" },
  );
});

test("beta builds use a separate product and application identity", () => {
  const config = tauriChannelConfig({ channel: "beta", version: "0.2.0-beta.1" });
  assert.equal(config.productName, "Watchcraft Beta");
  assert.equal(config.identifier, "app.watchcraft.reader.beta");
  assert.equal(config.mainBinaryName, "watchcraft-beta");
  assert.equal(config.version, "0.2.0-beta.1");
  assert.deepEqual(config.plugins["deep-link"].desktop.schemes, [
    "watchcraft",
    "watchcraft-beta",
  ]);
});

test("release builds preserve the production identity", () => {
  const config = tauriChannelConfig({ channel: "release", version: "1.0.0" });
  assert.equal(config.version, "1.0.0");
  assert.deepEqual(config.bundle.linux.deb.conflicts, [
    "watchcraft-beta (<= 0.2.0-beta.2)",
  ]);
  assert.deepEqual(config.bundle.linux.deb.replaces, [
    "watchcraft-beta (<= 0.2.0-beta.2)",
  ]);
  assert.deepEqual(tauriConfig.plugins["deep-link"].desktop.schemes, ["watchcraft"]);
});

test("Developer ID builds allow Tauri to infer the imported certificate identity", () => {
  const betaConfig = tauriChannelConfig(
    { channel: "beta", version: "0.2.0-beta.1" },
    { developerIdSigning: true },
  );
  const releaseConfig = tauriChannelConfig(
    { channel: "release", version: "1.0.0" },
    { developerIdSigning: true },
  );
  assert.equal(betaConfig.bundle.macOS.signingIdentity, null);
  assert.equal(releaseConfig.bundle.macOS.signingIdentity, null);
  assert.equal(
    tauriChannelConfig({ channel: "beta", version: "0.2.0-beta.1" })
      .bundle.macOS,
    undefined,
  );
});

test("Linux beta and release packages install distinct executables", () => {
  assert.deepEqual(linuxPackageIdentity("beta"), {
    packageName: "watchcraft-beta",
    binaryName: "watchcraft-beta",
    desktopName: "Watchcraft Beta.desktop",
    metainfoName: "app.watchcraft.reader.beta.metainfo.xml",
  });
  assert.deepEqual(linuxPackageIdentity("release"), {
    packageName: "watchcraft",
    binaryName: "watchcraft",
    desktopName: "Watchcraft.desktop",
    metainfoName: "app.watchcraft.reader.metainfo.xml",
  });
});

test("beta accepts public links while retaining its channel-specific scheme", () => {
  assert.deepEqual(deepLinkSchemes("beta"), ["watchcraft", "watchcraft-beta"]);
  assert.deepEqual(deepLinkSchemes("release"), ["watchcraft"]);
});

test("desktop builds can display their packaged version", () => {
  assert.ok(desktopCapabilities.permissions.includes("core:app:allow-version"));
});

test("desktop builds can subscribe to forwarded deep-link events", () => {
  assert.ok(desktopCapabilities.permissions.includes("core:event:allow-listen"));
  assert.ok(desktopCapabilities.permissions.includes("core:event:allow-unlisten"));
});

test("desktop builds enable and permit the standard zoom shortcuts", () => {
  assert.equal(tauriConfig.app.windows[0].zoomHotkeysEnabled, true);
  assert.equal(betaTauriConfig.app.windows[0].zoomHotkeysEnabled, true);
  assert.ok(desktopCapabilities.permissions.includes("core:webview:allow-set-webview-zoom"));
});

test("Windows beta builds use NSIS without the MSI prerelease restriction", () => {
  assert.equal(installerBundles({ runnerOs: "Windows", channel: "beta" }), "nsis");
});

test("Windows stable builds retain both installer formats", () => {
  assert.equal(installerBundles({ runnerOs: "Windows", channel: "release" }), "nsis,msi");
});

test("Linux and macOS installer formats do not vary by channel", () => {
  assert.equal(installerBundles({ runnerOs: "Linux", channel: "beta" }), "deb,appimage");
  assert.equal(installerBundles({ runnerOs: "macOS", channel: "release" }), "dmg");
});

test("Linux packages retain the media runtime required for embedded playback", () => {
  assert.equal(tauriConfig.bundle.linux.appimage.bundleMediaFramework, true);
  assert.deepEqual(tauriConfig.bundle.linux.deb.depends, [
    "gstreamer1.0-plugins-good",
    "gstreamer1.0-plugins-bad",
    "gstreamer1.0-libav",
  ]);
});

test("Linux Debian packages include channel-specific AppStream metadata", () => {
  const stableDestination = "/usr/share/metainfo/app.watchcraft.reader.metainfo.xml";
  const betaDestination = "/usr/share/metainfo/app.watchcraft.reader.beta.metainfo.xml";
  assert.equal(
    tauriConfig.bundle.linux.deb.files[stableDestination],
    "linux/app.watchcraft.reader.metainfo.xml",
  );
  assert.equal(
    betaTauriConfig.bundle.linux.deb.files[stableDestination],
    null,
  );
  assert.equal(
    betaTauriConfig.bundle.linux.deb.files[betaDestination],
    "linux/app.watchcraft.reader.beta.metainfo.xml",
  );
});
