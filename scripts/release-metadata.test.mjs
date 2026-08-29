import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  deepLinkSchemes,
  installerBundles,
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
  assert.equal(config.version, "0.2.0-beta.1");
  assert.deepEqual(config.plugins["deep-link"].desktop.schemes, [
    "watchcraft",
    "watchcraft-beta",
  ]);
});

test("release builds preserve the production identity", () => {
  assert.deepEqual(tauriChannelConfig({ channel: "release", version: "1.0.0" }), {
    version: "1.0.0",
  });
  assert.deepEqual(tauriConfig.plugins["deep-link"].desktop.schemes, ["watchcraft"]);
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
  const destination = "/usr/share/metainfo/app.watchcraft.reader.metainfo.xml";
  assert.equal(
    tauriConfig.bundle.linux.deb.files[destination],
    "linux/app.watchcraft.reader.metainfo.xml",
  );
  assert.equal(
    betaTauriConfig.bundle.linux.deb.files[destination],
    "linux/app.watchcraft.reader.beta.metainfo.xml",
  );
});
